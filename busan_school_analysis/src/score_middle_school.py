"""Explainable multi-year empirical shrinkage and Busan percentile scoring."""

import numpy as np
import pandas as pd

from .config import ROOT, settings, write_csv, write_json, write_parquet

RATES = ['science_rate', 'foreign_international_rate', 'autonomous_private_rate']


def shrink_rate(rate, n, mean, k=100):
    if k < 0:
        raise ValueError('shrinkage_k must be nonnegative')
    return (n * rate + k * mean) / (n + k)


def year_weighted(values, years, latest_year, weights):
    offsets = latest_year - np.asarray(years, dtype=int)
    valid = (offsets >= 0) & (offsets < len(weights)) & pd.notna(values)
    if not valid.any():
        return float('nan')
    w = np.asarray(weights)[offsets[valid]]
    return float(np.average(np.asarray(values, dtype=float)[valid], weights=w))


def score_middle_schools(advancement, schools, cfg):
    weights = np.asarray(cfg['year_weights'], dtype=float)
    component = np.asarray([cfg['middle_weights'][k] for k in ['science', 'foreign_international', 'autonomous_private']], dtype=float)
    if len(weights) != 3 or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError('Three positive finite year weights are required.')
    if not np.isfinite(component).all() or (component < 0).any() or not np.isclose(component.sum(), 1):
        raise ValueError('Middle-school weights must be nonnegative and sum to one.')
    if advancement.duplicated(['middle_school_id', 'year']).any():
        raise ValueError('Duplicate school-year observations cannot be scored.')
    eligible = advancement.loc[advancement.eligible_for_scoring & advancement.graduates.gt(0)].copy()
    if eligible.empty:
        raise ValueError('No validated advancement observations are available.')
    latest = int(eligible.year.max())
    eligible = eligible.loc[eligible.year.between(latest - 2, latest)]
    baselines = []
    for year, group in eligible.groupby('year'):
        for rate in RATES + ['academic_selective_rate']:
            mean = float((group[rate] * group.graduates).sum() / group.graduates.sum())
            eligible.loc[group.index, rate + '_adjusted'] = shrink_rate(group[rate], group.graduates, mean, cfg['shrinkage_k'])
            baselines.append(dict(year=int(year), metric=rate, busan_mean_rate=mean,
                                  observed_school_count=len(group), graduates=int(group.graduates.sum())))
    annual_pct = eligible.groupby('year')[[c + '_adjusted' for c in RATES]].rank(method='average', pct=True)
    eligible['annual_score'] = annual_pct.to_numpy().dot(component) * 100
    rows = []
    for school_id, group in eligible.groupby('middle_school_id'):
        most_recent = group.sort_values('year').iloc[-1]
        record = most_recent.to_dict()
        record.update(data_year=latest, year=latest, latest_observation_year=int(group.year.max()),
                      available_year_count=len(group), observation_years=','.join(map(str, sorted(group.year))),
                      graduates_total=int(group.graduates.sum()),
                      weighted_graduates=year_weighted(group.graduates, group.year, latest, weights),
                      score_stability=float(np.clip(1 - group.annual_score.std(ddof=0) / 50, 0, 1)) if len(group) > 1 else np.nan,
                      source_document=';'.join(sorted(set(group.source_document))),
                      collected_at=max(group.collected_at), parser_version='middle-score-1.0',
                      source_name='학교알리미 공시 13-다',
                      sample_warning=bool(len(group) == 1 or group.graduates.min() < cfg.get('small_sample_threshold', 30)),
                      score_reference_year=latest)
        for rate in RATES + ['academic_selective_rate']:
            record['weighted_' + rate] = year_weighted(group[rate], group.year, latest, weights)
            record['weighted_' + rate + '_adjusted'] = year_weighted(group[rate + '_adjusted'], group.year, latest, weights)
        record['manual_review'] = bool(record['sample_warning'] or len(group) < 3 or group.year.max() < latest)
        record['review_reason'] = 'small_sample_or_missing_years' if record['manual_review'] else ''
        record['confidence'] = float(len(group) / 3)
        rows.append(record)
    scores = pd.DataFrame(rows)
    middle = schools.loc[schools.school_level.eq('middle'), ['school_id', 'school_name', 'sigungu', 'closed', 'suspended']].copy()
    middle = middle.rename(columns={'school_id': 'middle_school_id', 'school_name': 'middle_school_name'})
    scores = middle.merge(scores.drop(columns=['middle_school_name', 'sigungu']), on='middle_school_id', how='left', validate='one_to_one')
    active = ~scores.closed.eq('Y') & ~scores.suspended.eq('Y')
    scored = active & scores.weighted_science_rate_adjusted.notna()
    columns = ['weighted_' + c + '_adjusted' for c in RATES]
    ranks = scores.loc[scored, columns].rank(method='average', pct=True)
    for c in RATES:
        scores.loc[scored, c + '_percentile'] = ranks['weighted_' + c + '_adjusted'] * 100
    scores.loc[scored, 'middle_school_score'] = ranks.to_numpy().dot(component) * 100
    scores['busan_rank'] = scores.middle_school_score.rank(method='min', ascending=False).astype('Int64')
    scores['sigungu_rank'] = scores.groupby('sigungu').middle_school_score.rank(method='min', ascending=False).astype('Int64')
    scores['score_percentile'] = scores.middle_school_score.rank(method='average', pct=True) * 100
    scores['ranking_population'] = int(scored.sum())
    scores['population_middle_count'] = len(middle)
    scores['ranking_coverage'] = scored.sum() / active.sum() if active.sum() else np.nan
    scores['data_year'] = latest
    scores['score_status'] = np.where(scored, 'scored', np.where(active, 'no_valid_observations', 'closed_or_suspended'))
    scores['manual_review'] = scores.manual_review.astype('boolean').fillna(True).astype(bool) | ~scored
    scores['sample_warning'] = scores.sample_warning.astype('boolean').fillna(True).astype(bool)
    scores.loc[~scored, 'review_reason'] = scores.loc[~scored, 'score_status']
    scores['confidence'] = scores.confidence.fillna(0)
    scores['source_name'] = scores.source_name.fillna('학교알리미 공시 13-다')
    scores['source_url'] = scores.source_url.fillna('https://www.schoolinfo.go.kr/ei/pp/Pneipp_b06_s0p.do')
    scores['parser_version'] = 'middle-score-1.0'
    return scores.sort_values(['busan_rank', 'middle_school_id']), pd.DataFrame(baselines)


def build_middle_scores(root=ROOT):
    advancement = pd.read_parquet(root / 'data/processed/middle_school_advancement.parquet')
    schools = pd.read_parquet(root / 'data/processed/schools.parquet')
    scores, baselines = score_middle_schools(advancement, schools, settings(root)['scoring'])
    # Provenance for unscored records points to their real failed/absent observations.
    for idx, row in scores.loc[scores.collected_at.isna()].iterrows():
        observed = advancement.loc[advancement.middle_school_id.eq(row.middle_school_id)]
        if not observed.empty:
            scores.loc[idx, 'collected_at'] = max(observed.collected_at)
            scores.loc[idx, 'source_document'] = ';'.join(sorted(set(observed.source_document)))
    write_parquet(root / 'data/processed/middle_school_scores.parquet', scores)
    write_csv(root / 'reports/middle_school_ranking.csv', scores)
    write_csv(root / 'reports/middle_school_scoring_baselines.csv', baselines)
    write_csv(root / 'reports/middle_school_manual_review.csv', scores.loc[scores.manual_review])
    centum = advancement.loc[advancement.middle_school_name.eq('센텀중학교')]
    write_csv(root / 'reports/centum_advancement_validation.csv', centum)
    quality = dict(reference_year=int(scores.data_year.iloc[0]), schools=len(scores),
                   scored_schools=int(scores.middle_school_score.notna().sum()),
                   sample_warning_count=int(scores.sample_warning.sum()),
                   available_years=sorted(advancement.loc[advancement.eligible_for_scoring, 'year'].unique().tolist()))
    write_json(root / 'reports/phase3_status.json', quality)
    return quality
