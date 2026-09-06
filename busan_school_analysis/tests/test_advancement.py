from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.clean_advancement import TITLES, add_rates, parse_advancement
from src.score_middle_school import shrink_rate, year_weighted, score_middle_schools

FIXTURES = Path(__file__).parent / 'fixtures'
SCHOOL = dict(school_id='S020001910', school_name='센텀중학교', sigungu='해운대구',
              school_public_id='bfc013ae-ea6d-4eb2-b2fb-f42899174b01')


def parse(year, content=None):
    return parse_advancement(content or (FIXTURES / f'centum_{year}.html').read_bytes(),
                             school=SCHOOL, year=year, document='official_public_html_fixture',
                             collected_at='2026-09-05T00:00:00+00:00')


def test_actual_2025_counts_and_rates():
    record = parse(2025)
    assert record['graduates'] == 370
    assert record['science_hs_count'] == 15
    assert record['foreign_international_hs_count'] == 26
    assert record['autonomous_private_hs_count'] == 36
    assert record['foreign_language_hs_count'] is None
    assert record['international_hs_count'] is None
    rate = add_rates(pd.DataFrame([record])).iloc[0]
    assert rate.academic_selective_count == 77
    assert rate.academic_selective_rate == pytest.approx(77 / 370)
    assert rate.arts_sports_rate == pytest.approx(28 / 370)


def test_actual_2026_redirect_cannot_become_2026_observation():
    record = parse(2026)
    assert record['observed_year'] == 2025
    assert record['availability'] == 'year_mismatch'
    assert not record['eligible_for_scoring'] and record['manual_review']
    assert record['graduates'] is None
    assert pd.isna(add_rates(pd.DataFrame([record])).iloc[0].academic_selective_rate)


def test_missing_table_is_not_zero():
    record = parse(2025, b'<html>Unavailable</html>')
    assert record['graduates'] is None and not record['eligible_for_scoring']


def test_official_no_data_message_is_not_a_transport_error():
    record = parse(2025, (FIXTURES / 'not_published.html').read_bytes())
    assert record['availability'] == 'not_published'
    assert record['graduates'] is None


def test_shrinkage_small_sample():
    assert shrink_rate(0.5, 10, 0.1, 100) == pytest.approx(15 / 110)
    assert abs(shrink_rate(0.5, 10, 0.1) - 0.1) < abs(shrink_rate(0.5, 1000, 0.1) - 0.1)


def test_weights_are_calendar_offsets_and_renormalize_missing():
    assert year_weighted([0.1, 0.2, 0.3], [2023, 2024, 2025], 2025, [0.5, 0.3, 0.2]) == pytest.approx(0.23)
    assert year_weighted([0.1, 0.3], [2023, 2025], 2025, [0.5, 0.3, 0.2]) == pytest.approx(0.17 / 0.7)
    assert np.isnan(year_weighted([0.9], [2022], 2025, [0.5, 0.3, 0.2]))


def ranking_inputs():
    base = parse(2025)
    records = []
    for school_id in ['a', 'b', 'c']:
        for year in [2023, 2024, 2025]:
            row = base | dict(middle_school_id=school_id, year=year, data_year=year)
            for field in TITLES:
                row[field] = 0
            row['graduates'] = 100
            for field in ['science_hs_count', 'foreign_international_hs_count', 'autonomous_private_hs_count']:
                row[field] = 10 if school_id != 'a' else 0
            records.append(row)
    frame = add_rates(pd.DataFrame(records))
    schools = pd.DataFrame([dict(school_id=s, school_name=s, school_level='middle', sigungu='구', closed='N', suspended='N') for s in ['a', 'b', 'c']])
    cfg = dict(year_weights=[0.5, 0.3, 0.2], shrinkage_k=100,
               middle_weights=dict(science=0.45, foreign_international=0.35, autonomous_private=0.20))
    return frame, schools, cfg


def test_percentiles_ties_and_population_baseline():
    frame, schools, cfg = ranking_inputs()
    scores, baseline = score_middle_schools(frame, schools, cfg)
    scores = scores.set_index('middle_school_id')
    assert scores.loc['a', 'middle_school_score'] == pytest.approx(100 / 3)
    assert scores.loc['b', 'middle_school_score'] == scores.loc['c', 'middle_school_score']
    assert scores.loc['b', 'busan_rank'] == 1
    assert scores.score_stability.eq(1).all()
    assert baseline.loc[baseline.metric.eq('science_rate'), 'busan_mean_rate'].iloc[0] == pytest.approx(20 / 300)


def test_single_year_warning_and_closed_school_not_ranked():
    frame, schools, cfg = ranking_inputs()
    frame = frame.loc[~frame.middle_school_id.eq('a') | frame.year.eq(2025)]
    schools.loc[schools.school_id.eq('c'), 'closed'] = 'Y'
    scores, _ = score_middle_schools(frame, schools, cfg)
    scores = scores.set_index('middle_school_id')
    assert scores.loc['a', 'sample_warning']
    assert pd.isna(scores.loc['a', 'score_stability'])
    assert pd.isna(scores.loc['c', 'busan_rank'])


def test_duplicate_school_year_rejected():
    frame, schools, cfg = ranking_inputs()
    with pytest.raises(ValueError, match='Duplicate'):
        score_middle_schools(pd.concat([frame, frame.iloc[[0]]]), schools, cfg)


def test_reviewed_csv_rejects_inconsistent_counts_and_preserves_original(tmp_path):
    from src.import_advancement import REQUIRED, import_advancement
    row = parse(2025)
    row.update(reviewed_by='fixture-reviewer', reviewed_at='2026-09-05T00:00:00Z')
    csv = tmp_path / 'review.csv'
    pd.DataFrame([row])[REQUIRED].to_csv(csv, index=False)
    processed = tmp_path / 'data/processed'
    processed.mkdir(parents=True)
    pd.DataFrame([SCHOOL | dict(school_level='middle')]).to_parquet(processed / 'schools.parquet')
    result = import_advancement(csv, root=tmp_path)
    assert result['imported_rows'] == 1
    output = processed / 'middle_school_advancement.parquet'
    assert pd.read_parquet(output).iloc[0].academic_selective_count == 77
    original = output.read_bytes()
    row['graduates'] = 999
    pd.DataFrame([row])[REQUIRED].to_csv(csv, index=False)
    with pytest.raises(ValueError, match='totals'):
        import_advancement(csv, root=tmp_path)
    assert output.read_bytes() == original


def test_zero_graduates_does_not_produce_infinite_rate():
    row = parse(2025)
    row['graduates'] = 0
    row['eligible_for_scoring'] = False
    rates = add_rates(pd.DataFrame([row]))
    assert rates.academic_selective_rate.isna().all()


def test_failed_refresh_preserves_valid_and_reviewed_records(tmp_path, monkeypatch):
    from src.collect_advancement import collect_advancement
    processed = tmp_path / 'data/processed'
    processed.mkdir(parents=True)
    pd.DataFrame([SCHOOL | dict(school_level='middle')]).to_parquet(processed / 'schools.parquet')
    row = parse(2025)
    row['parser_version'] += '-reviewed-csv'
    row['reviewed_by'] = 'fixture-reviewer'
    output = processed / 'middle_school_advancement.parquet'
    add_rates(pd.DataFrame([row])).to_parquet(output, index=False)
    failed = parse(2025, b'<html>Unavailable</html>')
    monkeypatch.setattr('src.collect_advancement.collect_one', lambda *a, **k: failed)
    collect_advancement([2025], root=tmp_path)
    saved = pd.read_parquet(output).iloc[0]
    assert saved.eligible_for_scoring and saved.graduates == 370
    assert saved.reviewed_by == 'fixture-reviewer'
    # A successful automatic refresh also cannot replace explicit human corrections.
    monkeypatch.setattr('src.collect_advancement.collect_one', lambda *a, **k: parse(2025))
    collect_advancement([2025], root=tmp_path)
    assert pd.read_parquet(output).iloc[0].reviewed_by == 'fixture-reviewer'
