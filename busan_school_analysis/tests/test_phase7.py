from pathlib import Path

import numpy as np
import pandas as pd

from src.phase7_scoring import (
    accessibility_score, assignment_is_guaranteed, build_feeder_scores,
    calculate_feeder_exclusivity, load_score_config, normalize_relation_type,
    _rank_sensitivity,
)

ROOT = Path(__file__).resolve().parents[1]


def config():
    return load_score_config(ROOT)


def relation_frame(types=("EXACT",), scores=(80.0,), warnings=None):
    warnings = warnings or [False] * len(types)
    weights = config()["middle_relation_weights"]
    quality = config()["assignment_quality"]
    relations = pd.DataFrame({
        "elementary_school_id": ["E1"] * len(types), "elementary_school_name": ["테스트초"] * len(types),
        "middle_school_id": [f"M{i}" for i in range(len(types))], "relation_type": list(types),
        "assignment_reliability_weight": [weights[x] for x in types],
        "assignment_data_quality": [quality[x] for x in types],
    })
    middle = pd.DataFrame({"middle_school_id": [f"M{i}" for i in range(len(types))],
                           "middle_school_score": list(scores), "busan_rank": range(1, len(types) + 1),
                           "sample_warning": warnings, "score_stability": [.9] * len(types),
                           "score_reference_year": [2025] * len(types)})
    return relations, middle


def feeder(types=("EXACT",), scores=(80.0,), warnings=None):
    r, m = relation_frame(types, scores, warnings)
    return build_feeder_scores(r, m, config())[0].iloc[0]


def test_assignment_weight_order():
    w = config()["middle_relation_weights"]
    assert w["EXACT"] > w["ELIGIBLE"] > w["CONDITIONAL"] > w["GROUP_MEMBERSHIP"] > w["UNRESOLVED"]


def test_exact_higher_than_group():
    exact, _ = relation_frame(("EXACT",), (80,)); group, _ = relation_frame(("GROUP_MEMBERSHIP",), (80,))
    assert calculate_feeder_exclusivity(exact, config()) > calculate_feeder_exclusivity(group, config())


def test_group_only_not_guaranteed():
    assert not assignment_is_guaranteed("group_only")


def test_weighted_middle_score():
    row = feeder(("EXACT", "CONDITIONAL"), (100, 40))
    assert np.isclose(row.weighted_middle_score, (100 + 20) / 1.5)


def test_worst_score_penalty():
    strong = feeder(("EXACT", "EXACT"), (90, 90))
    weak = feeder(("EXACT", "EXACT"), (90, 20))
    assert strong.elementary_feeder_score > weak.elementary_feeder_score


def test_feeder_exclusivity():
    row = feeder(("EXACT", "ELIGIBLE"), (80, 70))
    assert 0 <= row.feeder_exclusivity <= 1


def test_multiple_middle_uncertainty():
    stable = feeder(("ELIGIBLE", "ELIGIBLE"), (80, 80))
    spread = feeder(("ELIGIBLE", "ELIGIBLE"), (100, 20))
    assert spread.feeder_uncertainty > stable.feeder_uncertainty


def test_single_exact_feeder():
    row = feeder(("EXACT",), (82,))
    assert row.eligible_middle_count == 1 and row.exact_middle_count == 1


def test_best_score_bias_prevention():
    case_a = feeder(("EXACT",), (95,))
    case_b = feeder(("GROUP_MEMBERSHIP",) * 3, (95, 60, 40))
    assert case_a.elementary_feeder_score > case_b.elementary_feeder_score


def test_shared_catchment():
    scores = pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_2025.parquet")
    assert scores.loc[scores.elementary_school_count.gt(1), "shared_catchment"].all()


def test_elementary_accessibility():
    c = config()
    assert accessibility_score(200, c) == 100 and accessibility_score(1600, c) == 25


def test_apartment_school_score():
    scores = pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_2025.parquet")
    assert scores.school_zone_score.notna().any()


def test_score_range_0_100():
    scores = pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_2025.parquet").school_zone_score.dropna()
    assert scores.between(0, 100).all()


def test_school_score_percentile():
    scores = pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_2025.parquet").school_zone_percentile.dropna()
    assert scores.between(0, 100).all()


def test_500plus_ranking():
    large = pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_500plus_2025.parquet")
    assert len(large) == 560 and large.loc[large.school_zone_score.notna(), "busan_500plus_rank"].notna().all()


def test_manual_review_excluded():
    scores = pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_2025.parquet")
    assert scores.loc[scores.school_score_status.eq("REVIEW"), "school_zone_score"].isna().all()


def test_middle_sample_warning():
    normal = feeder(("EXACT",), (80,), [False]); warned = feeder(("EXACT",), (80,), [True])
    assert normal.elementary_feeder_score == warned.elementary_feeder_score
    assert warned.middle_score_reliability < normal.middle_score_reliability


def test_sensitivity_scenarios():
    frame = pd.DataFrame({"internal_complex_id": ["A", "B"], "complex_name": ["a", "b"],
                          "school_zone_score": [80, 70], "score_quality_focused": [70, 80],
                          "score_stability_focused": [75, 72]})
    result, corr = _rank_sensitivity(frame, config())
    assert {"rank_base", "rank_quality", "rank_stability"}.issubset(result.columns) and len(corr) == 2


def test_rank_robustness():
    sensitivity = pd.read_parquet(ROOT / "data/processed/busan_school_score_sensitivity_2025.parquet")
    scored = sensitivity.dropna(subset=["rank_range"])
    assert (scored.rank_range == scored.rank_max - scored.rank_min).all()


def test_centum_relation_not_upgraded():
    relations = pd.read_parquet(ROOT / "data/processed/busan_elementary_middle_relation_2025.parquet")
    target = relations[relations.elementary_school_name.astype(str).str.contains("센텀") &
                       relations.middle_school_name.astype(str).str.contains("센텀")]
    assert len(target) and target.relation_type.eq("GROUP_MEMBERSHIP").all() and not target.guaranteed_assignment.any()


def test_relation_normalization_closed_set():
    assert normalize_relation_type("something unknown") == "UNRESOLVED"


def test_output_preserves_apartment_interface():
    scores = pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_2025.parquet")
    assert len(scores) == 4521 and scores.internal_complex_id.is_unique


def test_original_middle_score_unchanged():
    original = pd.read_parquet(ROOT / "data/processed/middle_school_scores_by_id.parquet")
    detail = pd.read_parquet(ROOT / "data/processed/elementary_middle_score_detail_2025.parquet")
    check = detail.dropna(subset=["middle_school_id"]).merge(original[["middle_school_id", "middle_school_score"]], on="middle_school_id", suffixes=("_used", "_original"))
    assert np.allclose(check.middle_school_score_used, check.middle_school_score_original)


def test_phase7_dashboard_pages():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "streamlit_app.py")).run(timeout=30)
    assert not app.exception and app.radio[0].value == "Overview"
    for page in ["Middle ranking", "Feeder ranking", "Apartment ranking", "Centum validation",
                 "Score sensitivity", "Data quality"]:
        app.radio[0].set_value(page).run(timeout=30)
        assert not app.exception


def test_assignment_editor_filters_elementary_by_sigungu():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "streamlit_app.py")).run(timeout=30)
    app.radio[0].set_value("Centum validation").run(timeout=30)
    assert not app.exception
    assert app.selectbox[0].label == "구·군 선택"
    assert app.selectbox[1].label == "초등학교 선택"
    assert app.selectbox[0].value == "해운대구" and "센텀초" in app.selectbox[1].options
    app.selectbox[0].select("강서구").run(timeout=30)
    assert not app.exception and "센텀초" not in app.selectbox[1].options


def test_feeder_ranking_filters_by_sigungu():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "streamlit_app.py")).run(timeout=30)
    app.radio[0].set_value("Feeder ranking").run(timeout=30)
    assert not app.exception and app.selectbox[0].label == "진학권 순위 구·군"
    app.selectbox[0].select("해운대구").run(timeout=30)
    assert not app.exception
    visible = app.dataframe[0].value
    assert len(visible) and visible.sigungu.eq("해운대구").all()
    assert {"busan_feeder_rank", "sigungu_feeder_rank"}.issubset(visible.columns)


def test_bukbu_2026_intake_excludes_transfer_candidates():
    from src.phase7_assignment_2026 import parse_bukbu_2026
    path = ROOT / "em_school/01.북부교육지청_2026학년도 중입배정 및 전학배정표.pdf"
    frame = parse_bukbu_2026(path)
    gamjeon = frame[frame.elementary_school_name.eq("감전초")]
    assert set(gamjeon.middle_school_name) == {"주례중"}
    assert frame.elementary_school_name.nunique() == 69


def test_bukbu_2026_gender_union():
    from src.phase7_assignment_2026 import parse_bukbu_2026
    frame = parse_bukbu_2026(ROOT / "em_school/01.북부교육지청_2026학년도 중입배정 및 전학배정표.pdf")
    gwaebeop = frame[frame.elementary_school_name.eq("괘법초")]
    assert set(gwaebeop.middle_school_name) == {"동주중", "주례여중"}


def test_seobu_2026_known_relation():
    from src.phase7_assignment_2026 import parse_seobu_2026
    frame = parse_seobu_2026(ROOT / "em_school/02.서부교육지청_2026학년도 입학배정.pdf")
    guhak = frame[frame.elementary_school_name.eq("구학초")]
    assert {"경남중", "대신중", "초장중", "대신여중", "부산여중", "중앙여중"}.issubset(set(guhak.middle_school_name))


def test_assignment_2026_version_isolated():
    current = pd.read_parquet(ROOT / "data/processed/busan_elementary_middle_relation_2026.parquet")
    old = pd.read_parquet(ROOT / "data/processed/busan_elementary_middle_relation_2025.parquet")
    assert current.data_year.eq(2026).all() and old.data_year.eq(2025).all()


def test_assignment_2026_output_interface():
    scores = pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_2026.parquet")
    assert len(scores) == 4521 and scores.internal_complex_id.is_unique
    assert scores.assignment_year.eq(2026).all() and scores.catchment_boundary_year.eq(2025).all()


def test_assignment_2026_named_middle_ids_resolved():
    relations = pd.read_parquet(ROOT / "data/processed/busan_elementary_middle_relation_2026.parquet")
    named = relations[relations.middle_school_name.notna()]
    unmatched = named[named.middle_school_id.isna()]
    assert unmatched.parser_version.eq("phase7-manual-assignment-2026-1.0").all()
    assert unmatched.manual_review.astype(bool).all()
    assert named[~named.index.isin(unmatched.index)].middle_school_id.notna().all()
