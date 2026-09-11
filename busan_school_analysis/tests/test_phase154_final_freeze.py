from __future__ import annotations

import hashlib
import inspect
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.config import ROOT
from src.final_value_dashboard import (
    MASTER_PATH,
    currency_eok,
    download_frame,
    filter_master,
    health_check,
    load_frozen_data,
    percent_text,
    streamlit_uses_only_frozen_sources,
    korean_value,
)
from src.elementary_demand_dashboard import (
    _ranking_view,
    filter_elementary_demand,
    load_elementary_demand_data,
)
from src.middle_school_score_dashboard import (
    filter_middle_school_scores,
    load_middle_school_scores,
    middle_ranking_view,
)
from src.phase154_final_freeze import (
    CLASS_ORDER,
    FINAL_STATUS,
    final_review_class,
    limitation_flag,
    limitation_reasons,
    rank_candidates,
    unmodeled_discount_candidate,
    unmodeled_premium_candidate,
    verify_manifest,
)


MASTER = ROOT / MASTER_PATH


@pytest.fixture(scope="module")
def data():
    return pd.read_csv(MASTER, encoding="utf-8-sig")


@pytest.fixture(scope="module")
def source():
    return pd.read_csv(ROOT / "data/processed/phase153_local_value_gap.csv", encoding="utf-8-sig")


def _same(data, source, column):
    left = data.set_index("apartment_id")[column].sort_index()
    right = source.set_index("apartment_id")[column].sort_index().reindex(left.index)
    return np.allclose(left, right, equal_nan=True)


def test_01_phase7_to_phase153_protected_hash_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase154_protected_manifest.csv", encoding="utf-8-sig")
    assert len(manifest) >= 292 and manifest.unchanged.all()


def test_02_phase153_master_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase154_protected_manifest.csv", encoding="utf-8-sig")
    row = manifest[manifest.path.eq("data/processed/phase153_local_value_gap.csv")]
    assert len(row) == 1 and row.sha256_before.iloc[0] == row.sha256_after.iloc[0]


def test_03_phase152_fair_price_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase154_protected_manifest.csv", encoding="utf-8-sig")
    assert manifest.loc[manifest.path.eq("data/processed/phase152_local_fair_price.csv"), "unchanged"].all()


def test_04_phase149_school_master_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase154_protected_manifest.csv", encoding="utf-8-sig")
    assert manifest.loc[manifest.path.eq("data/processed/phase149_school_value_master.csv"), "unchanged"].all()


def test_05_final_master_row_count(data):
    assert len(data) == 560


def test_06_apartment_id_uniqueness(data):
    assert data.apartment_id.nunique() == len(data)


def test_07_classes_are_from_closed_set(data):
    assert set(data.final_review_class) <= set(CLASS_ORDER)


def test_08_every_row_has_exactly_one_class(data):
    assert data.final_review_class.notna().all() and sum(data.final_review_class.value_counts()) == 560


def test_09_core_candidate_rule(data):
    rows = data[data.final_review_class.eq("CORE_CANDIDATE")]
    assert len(rows) and rows.combined_candidate_class.eq("ROBUST_DUAL_POSITIVE").all()
    assert rows.model_confidence.isin(["HIGH", "MEDIUM"]).all()
    assert rows.local_gap_confidence.isin(["HIGH", "MEDIUM"]).all()
    assert rows.gap_confidence.isin(["HIGH", "MEDIUM"]).all()
    assert rows.local_gap_temporal_stability.eq("STABLE_POSITIVE").all()
    assert (~rows.dong_bias_flag & ~rows.extreme_gap_flag).all()


def test_10_local_value_rule(data):
    rows = data[data.final_review_class.eq("LOCAL_VALUE")]
    assert len(rows) and rows.combined_candidate_class.eq("LOCAL_VALUE_CANDIDATE").all()
    assert rows.local_gap_confidence.isin(["HIGH", "MEDIUM"]).all()


def test_11_school_value_rule(data):
    rows = data[data.final_review_class.eq("SCHOOL_VALUE")]
    assert len(rows) and rows.combined_candidate_class.eq("SCHOOL_VALUE_CANDIDATE").all()
    assert rows.gap_confidence.isin(["HIGH", "MEDIUM"]).all()


def test_12_watchlist_rule(data):
    rows = data[data.final_review_class.eq("WATCHLIST")]
    assert len(rows)
    assert rows.combined_candidate_class.isin(["UNCERTAIN", "ROBUST_DUAL_POSITIVE", "LOCAL_VALUE_CANDIDATE", "SCHOOL_VALUE_CANDIDATE"]).all()


def test_13_fully_priced_rule(data):
    rows = data[data.final_review_class.eq("FULLY_PRICED_OR_NEGATIVE")]
    assert len(rows) and rows.combined_candidate_class.eq("NEGATIVE_OR_FULLY_PRICED").all()


def test_14_school_gap_unchanged(data):
    original = pd.read_csv(ROOT / "data/processed/phase149_school_value_master.csv", encoding="utf-8-sig")
    assert _same(data, original, "school_value_gap_pct")


def test_15_local_gap_unchanged(data, source):
    assert _same(data, source, "local_value_gap_pct")


def test_16_fair_price_unchanged(data, source):
    assert _same(data, source, "local_fair_total_price")


@pytest.mark.parametrize("column", ["fair_price_lower", "fair_price_upper", "prediction_interval_width_pct"])
def test_17_prediction_interval_unchanged(data, source, column):
    assert _same(data, source, column)


def test_18_candidate_ranking_deterministic(data):
    first = rank_candidates(data)
    second = rank_candidates(data.sample(frac=1, random_state=154))
    pd.testing.assert_frame_equal(first, second)


def test_19_model_limitation_flag_deterministic(data):
    result = json.loads((ROOT / "data/processed/phase153_result.json").read_text(encoding="utf-8"))
    threshold = result["thresholds"]["interval_width_p75"]
    expected = [limitation_flag(limitation_reasons(row, threshold)) for row in data.itertuples()]
    assert expected == data.model_limitation_flag.tolist()


def test_20_high_audit_count_consistency(data):
    audit = pd.read_csv(ROOT / "reports/phase154_high_audit_review.csv", encoding="utf-8-sig")
    assert len(audit) == data.phase154_audit_priority.eq("HIGH").sum() == 33


def test_21_snapshot_metric_consistency(data):
    snapshot = json.loads((ROOT / "data/snapshots/phase154_final_model_freeze.json").read_text(encoding="utf-8"))
    assert snapshot["local_model"]["fair_price_coverage"] == data.local_fair_total_price.notna().sum()
    assert snapshot["final_classes"] == {name: int(data.final_review_class.eq(name).sum()) for name in CLASS_ORDER}


def test_22_freeze_status_correct():
    snapshot = json.loads((ROOT / "data/snapshots/phase154_final_model_freeze.json").read_text(encoding="utf-8"))
    assert snapshot["project_state"]["final_model_status"] == FINAL_STATUS
    assert snapshot["integrity"]["pytest_status"] == "FULL_PASS"


def test_23_no_new_analytical_model_instantiated():
    import src.phase154_final_freeze as module
    text = inspect.getsource(module)
    assert "sklearn" not in text and "statsmodels" not in text and ".fit(" not in text and ".predict(" not in text


def test_24_only_metadata_columns_added(data, source):
    added = set(data) - set(source)
    assert added == {"final_review_class", "model_limitation_flag", "model_limitation_detail", "unmodeled_premium_candidate", "unmodeled_discount_candidate"}


def test_25_streamlit_loads_only_frozen_master():
    assert streamlit_uses_only_frozen_sources()


def test_26_streamlit_does_not_call_model_functions():
    import src.final_value_dashboard as module
    text = inspect.getsource(module)
    assert ".fit(" not in text and ".predict(" not in text and "build_phase" not in text


def test_27_filter_output_correct(data):
    expected = data[(data.gu.eq(data.gu.iloc[0])) & data.final_review_class.eq("WATCHLIST") & data.household_count.ge(500)]
    actual = filter_master(data, gu=[data.gu.iloc[0]], review_class=["WATCHLIST"], households_min=500)
    assert set(actual.apartment_id) == set(expected.apartment_id)


def test_28_missing_values_not_converted_to_zero(data, source):
    for column in ["local_fair_total_price", "local_value_gap_pct", "school_value_gap_pct"]:
        assert data[column].isna().equals(source[column].isna()) if column in source else True
    assert data.loc[source.local_fair_total_price.isna(), "local_fair_total_price"].isna().all()


@pytest.mark.parametrize("value,expected", [(780_000_000, "7.80억"), (0, "0.00억"), (np.nan, "N/A")])
def test_29_currency_formatter(value, expected):
    assert currency_eok(value) == expected


@pytest.mark.parametrize("value,expected", [(7.234, "7.23%"), (0, "0.00%"), (np.nan, "N/A")])
def test_30_percentage_formatter(value, expected):
    assert percent_text(value) == expected


def test_31_streamlit_validation_health_check():
    ok, checks = health_check(ROOT)
    assert ok and checks.passed.all()


def test_32_download_dataframe_consistency(data):
    raw = download_frame(data.head(5))
    restored = pd.read_csv(pd.io.common.BytesIO(raw), encoding="utf-8-sig")
    assert restored.apartment_id.tolist() == data.head(5).apartment_id.tolist()


def test_33_protected_overwrite_prevention():
    with pytest.raises(RuntimeError, match="PROTECTED_ARTIFACT_MODIFIED"):
        verify_manifest(pd.DataFrame([{"path": "main.py", "sha256_before": "bad"}]), ROOT)


def test_34_unmodeled_premium_rule_deterministic(data):
    assert [unmodeled_premium_candidate(row) for row in data.itertuples()] == data.unmodeled_premium_candidate.tolist()


def test_35_unmodeled_discount_rule_deterministic(data):
    assert [unmodeled_discount_candidate(row) for row in data.itertuples()] == data.unmodeled_discount_candidate.tolist()


def test_36_candidate_table_has_all_rows(data):
    candidates = pd.read_csv(ROOT / "reports/phase154_final_candidates.csv", encoding="utf-8-sig")
    assert len(candidates) == len(data) and candidates.apartment_id.nunique() == 560


def test_37_class_rank_is_contiguous():
    candidates = pd.read_csv(ROOT / "reports/phase154_final_candidates.csv", encoding="utf-8-sig")
    for _, group in candidates.groupby("final_review_class"):
        assert group.class_rank.tolist() == list(range(1, len(group) + 1))


def test_38_source_hash_matches_manifest():
    path = ROOT / "data/processed/phase153_local_value_gap.csv"
    manifest = pd.read_csv(ROOT / "reports/phase154_protected_manifest.csv", encoding="utf-8-sig")
    expected = manifest.loc[manifest.path.eq("data/processed/phase153_local_value_gap.csv"), "sha256_before"].iloc[0]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_39_frozen_loader_smoke():
    master, candidates, audit, snapshot = load_frozen_data(str(ROOT))
    assert len(master) == len(candidates) == 560 and len(audit) == 33
    assert snapshot["project_state"]["project_phase"] == "15.4"


def test_40_summary_counts_sum_to_universe(data):
    assert sum(data.final_review_class.value_counts()) == 560


def test_41_elementary_demand_frozen_sources_load():
    scores, history = load_elementary_demand_data(str(ROOT))
    assert len(scores) == 302 and len(history) == 909
    assert scores.sigungu_requested.nunique() == 16


def test_42_elementary_demand_district_filter():
    scores, _ = load_elementary_demand_data(str(ROOT))
    district = scores.sigungu_requested.dropna().iloc[0]
    filtered = filter_elementary_demand(scores, districts=[district])
    assert len(filtered) and filtered.sigungu_requested.eq(district).all()


def test_43_elementary_demand_display_columns_are_korean():
    scores, _ = load_elementary_demand_data(str(ROOT))
    view = _ranking_view(scores.head(5))
    assert {"부산 순위", "구·군 순위", "초등학교", "초등학교 수요점수", "자료 신뢰도"} <= set(view.columns)
    assert not ({"HIGH", "MEDIUM", "LOW"} & set(view["자료 신뢰도"]))


@pytest.mark.parametrize(
    "raw,translated",
    [
        ("CORE_CANDIDATE", "핵심 후보"),
        ("HIGH", "높음"),
        ("STRONG_UNDERVALUED_SIGNAL", "강한 저평가 신호"),
        ("DOUBLE_POSITIVE", "학군·지역 모두 양의 신호"),
        ("LOW_TRANSACTION;LEGAL_DONG_BIAS", "거래량 부족; 법정동 편향"),
    ],
)
def test_44_visible_status_values_translate_to_korean(raw, translated):
    assert korean_value(raw) == translated


def test_45_navigation_exposes_both_korean_menus():
    text = (ROOT / "phase154_streamlit_app.py").read_text(encoding="utf-8")
    assert "최종 가치분석" in text and "초등학교 수요 분석" in text


def test_46_middle_school_frozen_scores_load():
    scores = load_middle_school_scores(str(ROOT))
    assert len(scores) == 183 and scores.middle_school_score.notna().sum() == 170


def test_47_middle_school_district_filter():
    scores = load_middle_school_scores(str(ROOT))
    district = scores.sigungu.dropna().iloc[0]
    filtered = filter_middle_school_scores(scores, districts=[district])
    assert len(filtered) and filtered.sigungu.eq(district).all()


def test_48_middle_school_display_columns_are_korean():
    scores = load_middle_school_scores(str(ROOT))
    view = middle_ranking_view(scores.head(5))
    assert {"부산 순위", "구·군 순위", "중학교", "중학교 점수", "점수 상태"} <= set(view.columns)
    assert "scored" not in set(view["점수 상태"])


def test_49_navigation_exposes_middle_school_menu():
    text = (ROOT / "phase154_streamlit_app.py").read_text(encoding="utf-8")
    assert "중학교 점수" in text and "app_pages/middle_school_score.py" in text


def test_50_middle_dashboard_is_read_only():
    text = (ROOT / "src/middle_school_score_dashboard.py").read_text(encoding="utf-8")
    assert ".fit(" not in text and ".predict(" not in text and "build_middle_scores" not in text
