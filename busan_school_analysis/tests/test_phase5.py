"""Offline snapshots and adversarial inputs protect against false school assignments."""
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from src.build_phase5 import build_middle_validation, resolve_phase4_reviews
from src.match_apartment_school import (normalize_complex_name, name_similarity, classify_match,
                                        apply_override, build_apartment_matches, haversine_m,
                                        spatial_outlier, filter_500plus)

FIX = Path(__file__).parent / 'fixtures/phase5'


@pytest.fixture(scope='module')
def frames():
    return {path.stem: pd.DataFrame(json.loads(path.read_text(encoding='utf-8')))
            for path in FIX.glob('*.json') if path.stem != 'provenance'}


@pytest.fixture(scope='module')
def output(frames):
    return build_apartment_matches(frames['catchments'], frames['apartments'], frames['schools'])


def classify(**kwargs):
    args = dict(raw_name='센텀파크1차', candidate_name='센텀파크1차', name_score=1,
                address_score=.8, viable_candidate_count=1)
    args.update(kwargs)
    return classify_match(**args)


def override(kind='confirmed', **kwargs):
    row = dict(data_year='2025', education_office='haeundae', elementary_school_name='센텀초',
               raw_apartment_name='센텀파크1차', internal_complex_id='A61271204', override_type=kind,
               evidence_source='tests/synthetic_official_address', evidence_text='synthetic reviewed address',
               reason='test-only official address confirmation', verified_at='2026-09-06')
    row.update(kwargs)
    return pd.DataFrame([row])


def test_complex_name_normalization():
    assert normalize_complex_name('㈜ 센텀파크 (1차) 아파트') == '센텀파크1차'
    assert normalize_complex_name('센텀파크1차 APT') == '센텀파크1차'


def test_complex_name_phase_variants():
    assert len({normalize_complex_name(x) for x in ['센텀파크1차', '센텀파크 1 차', '센텀파크 제1차']}) == 1
    assert normalize_complex_name('센텀파크Ⅱ차') == '센텀파크2차'
    assert name_similarity('센텀파크1차', '더샵센텀파크2차') == 0


def test_unique_name_address_match():
    assert classify(official_address_confirmed=True)[:2] == ('official_exact', 'CONFIRMED')


def test_same_name_multiple_candidates():
    assert classify(official_address_confirmed=True, viable_candidate_count=2)[1] == 'REVIEW'


def test_fuzzy_name_not_auto_confirmed():
    assert classify(candidate_name='더샵센텀파크1차', name_score=.99,
                    official_address_confirmed=True)[1] == 'REVIEW'


def test_contextual_match_requires_evidence():
    assert classify(contextual=True)[0] == 'contextual_candidate'
    assert classify(contextual=True, official_address_confirmed=True)[:2] == ('contextual_supported', 'REVIEW')


def test_manual_override_priority(output):
    _, frame = output
    auto = frame.iloc[0].to_dict()
    result = apply_override('센텀파크1차', '센텀초', auto, override())
    assert result['match_status'] == 'CONFIRMED' and result['official_catchment_match']
    rejected = apply_override('센텀파크1차', '센텀초', auto, override('rejected'))
    assert rejected['internal_complex_id'] is None and rejected['match_status'] == 'UNRESOLVED'
    assert rejected['complex_name'] is None


def test_address_support_required():
    assert classify(address_score=0, official_address_confirmed=True)[1] != 'CONFIRMED'
    assert classify(address_score=.8)[1] != 'CONFIRMED'  # legal-dong only


def test_distance_not_assignment_evidence(frames, output):
    apartments = frames['apartments'].copy()
    apartments[['latitude', 'longitude']] = [35.1813135114, 129.1218134018]
    _, altered = build_apartment_matches(frames['catchments'], apartments, frames['schools'])
    assert altered.match_status.tolist() == output[1].match_status.tolist()


def test_spatial_outlier(frames):
    assert spatial_outlier(5001) and not spatial_outlier(5000)
    assert not spatial_outlier(None)
    apartments = frames['apartments'].copy()
    apartments.loc[apartments.internal_complex_id.eq('A61271204'), ['latitude', 'longitude']] = [36.5, 128.0]
    _, matches = build_apartment_matches(frames['catchments'], apartments, frames['schools'], override())
    row = matches[matches.raw_apartment_name.eq('센텀파크1차')].iloc[0]
    assert row.spatial_outlier and row.manual_review and row.match_status == 'REVIEW'


def test_500_household_filter_only_view(output):
    _, matches = output
    view = filter_500plus(matches)
    assert view.households.ge(500).all()
    assert matches.households.lt(500).any() and len(view) < len(matches)
    assert matches[matches.raw_apartment_name.eq('센텀천일스카이원')].households.iloc[0] == 208


def test_group_only_not_exact(frames):
    result = build_middle_validation(frames['groups'], frames['assignment'], frames['scores'])
    assert not result[result.assignment_certainty.eq('group_only')].guaranteed_assignment.any()


def test_conditional_not_guaranteed_not_exact(frames):
    result = build_middle_validation(frames['groups'], frames['assignment'], frames['scores'])
    conditional = result[result.assignment_certainty.eq('conditional_not_guaranteed')]
    assert len(conditional) == 3 and not conditional.guaranteed_assignment.any()


def test_middle_score_join_does_not_imply_assignment(frames):
    result = build_middle_validation(frames['groups'], frames['assignment'], frames['scores'])
    assert result.middle_school_score.notna().all()
    assert not result.guaranteed_assignment.any()
    assert 'school_zone_score' not in result.columns


def test_centum_elementary_apartment_fixture(output):
    _, matches = output
    centum = matches[matches.elementary_school_name.eq('센텀초')]
    assert set(centum.internal_complex_id) == {'A61271204', 'A61271302', 'A61205003'}
    assert centum.manual_review.all() and centum.match_status.eq('REVIEW').all()
    assert centum.raw_catchment_text.str.contains('19～22통', regex=False).all()


def test_centum_middle_not_hardcoded(frames):
    result = build_middle_validation(frames['groups'], frames['assignment'], frames['scores'])
    target = result[result.middle_school_name.eq('센텀중')]
    assert len(target) == 1 and target.assignment_certainty.iloc[0] == 'group_only'
    changed = frames['groups'][frames['groups'].middle_school_name.ne('센텀중')]
    result = build_middle_validation(changed, frames['assignment'], frames['scores'])
    assert not result.middle_school_name.eq('센텀중').any()


def test_override_missing_evidence_rejected(output):
    with pytest.raises(ValueError, match='requires source'):
        apply_override('센텀파크1차', '센텀초', output[1].iloc[0].to_dict(), override(evidence_text=''))


def test_alias_is_not_confirmed(output):
    result = apply_override('센텀파크1차', '센텀초', output[1].iloc[0].to_dict(), override('alias'))
    assert result['match_status'] == 'REVIEW' and not result['official_catchment_match']


def test_override_missing_target_rejected(frames):
    with pytest.raises(ValueError, match='target ID'):
        build_apartment_matches(frames['catchments'], frames['apartments'], frames['schools'],
                                override(internal_complex_id='nonexistent'))


def test_all_seven_reviews_preserved(frames, output):
    reviews = frames['catchments'][frames['catchments'].manual_review]
    result = resolve_phase4_reviews(reviews, output[1])
    assert len(result) == 7 and result.review_id.is_unique and result.manual_review.all()
    assert result.resolution_method.eq('contextual_candidate').sum() == 2


def test_no_viable_candidate_has_no_selected_id(frames):
    apartments = frames['apartments'].copy()
    apartments['complex_name'] = '완전히다른이름'
    _, result = build_apartment_matches(frames['catchments'], apartments, frames['schools'])
    assert result.internal_complex_id.isna().all() and result.match_status.eq('UNRESOLVED').all()


def test_override_without_auto_candidate_and_refresh_fields(frames):
    apartments = frames['apartments'].copy()
    apartments['complex_name'] = '완전히다른이름'
    _, result = build_apartment_matches(frames['catchments'], apartments, frames['schools'], override())
    row = result[result.raw_apartment_name.eq('센텀파크1차')].iloc[0]
    assert row.internal_complex_id == 'A61271204' and row.households == 2752
    assert row.complex_name == '완전히다른이름' and row.match_status == 'CONFIRMED'
    assert row.evidence_type == 'manual_confirmed'


def test_conflicting_overrides_fail_closed(output):
    with pytest.raises(ValueError, match='Conflicting'):
        apply_override('센텀파크1차', '센텀초', output[1].iloc[0].to_dict(),
                       pd.concat([override(), override(internal_complex_id='A61271302')]))


def test_year_mismatch_rejected(frames):
    groups = frames['groups'].assign(data_year=2026)
    with pytest.raises(ValueError, match='data_year'):
        build_middle_validation(groups, frames['assignment'], frames['scores'])


def test_streamlit_validation_screen(tmp_path, frames, output):
    from streamlit.testing.v1 import AppTest
    candidates, matches = output
    middle = build_middle_validation(frames['groups'], frames['assignment'], frames['scores'],
                                     matches.elementary_school_name.unique())
    files = {
        'data/interim/haeundae_elementary_catchment_2025.parquet': frames['catchments'],
        'data/interim/haeundae_apartment_elementary_candidates_2025.parquet': candidates,
        'data/processed/haeundae_apartment_elementary_match_2025.parquet': matches,
        'data/interim/haeundae_elementary_middle_validation_2025.parquet': middle,
    }
    for relative, data in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data.to_parquet(path, index=False)
    (tmp_path / 'reports').mkdir()
    resolve_phase4_reviews(frames['catchments'][frames['catchments'].manual_review], matches).to_csv(
        tmp_path / 'reports/haeundae_phase4_review_resolution_2025.csv', index=False)
    shutil.copyfile(Path(__file__).parents[1] / 'streamlit_app.py', tmp_path / 'streamlit_app.py')
    app = AppTest.from_file(str(tmp_path / 'streamlit_app.py')).run(timeout=30)
    assert not app.exception and app.selectbox[0].value == '센텀초'
    app.selectbox[0].select('재송초').run()
    app.checkbox[0].check().run()
    assert not app.exception
