import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from src.config import ROOT
from src.phase146_149_stability import (
    BOOTSTRAP_ITERATIONS,
    RANDOM_SEED,
    bootstrap_gaps,
    classify_bootstrap,
    classify_candidate,
    classify_method,
    classify_temporal,
    leave_one_dong_out,
    verify_manifest,
)


def _stability():
    return pd.read_csv(ROOT / "data/processed/phase146_school_value_gap_stability.csv", encoding="utf-8-sig")


def _master():
    return pd.read_csv(ROOT / "data/processed/phase149_school_value_master.csv", encoding="utf-8-sig")


def test_phase7_to_phase145_protected_hashes_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase146_protected_manifest.csv", encoding="utf-8-sig")
    checked = verify_manifest(manifest, ROOT)
    assert len(checked) == 199 and checked.unchanged.all()


def test_phase13_core_score_is_unchanged_in_master():
    source = pd.read_csv(ROOT / "data/processed/phase13_school_premium_index.csv", encoding="utf-8-sig").set_index("apartment_id")
    master = _master().set_index("apartment_id")
    pd.testing.assert_series_equal(master.loc[source.index, "school_premium_core_score"], source.school_premium_core_score, check_names=False)


def test_phase14_selected_linear_specification_is_unchanged():
    result = json.loads((ROOT / "data/processed/phase14_result.json").read_text(encoding="utf-8"))
    assert result["selected_model"] == "LINEAR"
    assert np.isclose(result["ten_point_effect_at_50_pct"], 4.3336366222126514)


def test_phase145_gap_is_exactly_reproduced():
    stability = _stability()
    assert np.nanmax(np.abs(stability.phase145_reproduction_error)) == 0


@pytest.mark.parametrize("months", [6, 12, 24])
def test_price_window_transaction_counts_are_correct(months):
    tx = pd.read_parquet(ROOT / "data/processed/phase135_transaction_sample.parquet")
    end = tx.transaction_date.max()
    start = end - pd.DateOffset(months=months) + pd.offsets.Day(1)
    expected = tx[tx.transaction_date.between(start, end)].groupby("apartment_id").size()
    actual = _stability().set_index("apartment_id")[f"transaction_count_{months}m"].dropna().astype(int)
    pd.testing.assert_series_equal(actual.sort_index(), expected.loc[actual.index].sort_index(), check_names=False)


def test_no_forward_looking_transaction_leakage():
    comparison = pd.read_csv(ROOT / "reports/phase14_model_comparison.csv", encoding="utf-8-sig")
    assert not comparison.future_leakage.any()


def test_temporal_sign_pattern_function():
    assert classify_temporal([1, -2, np.nan])[0] == "+-NA"
    assert classify_temporal([np.nan, 1, 2])[0] == "NA++"


def test_temporal_stability_function():
    assert classify_temporal([1, 2, 3])[1] == "STABLE_POSITIVE"
    assert classify_temporal([-1, -2, np.nan])[1] == "STABLE_NEGATIVE"
    assert classify_temporal([1, -1, 2])[1] == "MIXED"
    assert classify_temporal([np.nan, 1, np.nan])[1] == "INSUFFICIENT"


def test_method_agreement_function():
    assert classify_method(2, 3) == "STRONG_POSITIVE"
    assert classify_method(-2, -3) == "STRONG_NEGATIVE"
    assert classify_method(2, -3) == "MIXED_POSITIVE_RESIDUAL"
    assert classify_method(-2, 3) == "MIXED_POSITIVE_COMPARABLE"
    assert classify_method(.2, 4) == "NEUTRAL_OR_ZERO"


def test_bootstrap_seed_is_fixed():
    assert RANDOM_SEED == 20260911


def test_bootstrap_is_deterministic_for_one_apartment():
    audit = pd.read_csv(ROOT / "reports/phase146_gap_stability_audit.csv", encoding="utf-8-sig")
    row = audit[audit.has_12m_price & audit.school_premium_core_score.notna()].head(1)
    tx = pd.read_parquet(ROOT / "data/processed/phase135_transaction_sample.parquet")
    predictions = pd.read_parquet(ROOT / "data/processed/phase14_transaction_predictions.parquet")
    first = bootstrap_gaps(row, tx, predictions)
    second = bootstrap_gaps(row, tx, predictions)
    pd.testing.assert_frame_equal(first, second)


def test_bootstrap_iteration_count():
    data = _stability()
    valid = data.bootstrap_iterations.gt(0)
    assert data.loc[valid, "bootstrap_iterations"].eq(BOOTSTRAP_ITERATIONS).all()


def test_bootstrap_probabilities_are_bounded():
    data = _stability()
    assert data.gap_positive_probability.dropna().between(0, 1).all()
    assert data.gap_negative_probability.dropna().between(0, 1).all()
    assert np.allclose(data.gap_positive_probability.dropna() + data.gap_negative_probability.dropna(), 1)


def test_bootstrap_percentiles_are_ordered():
    data = _stability().dropna(subset=["bootstrap_gap_p05"])
    values = data[["bootstrap_gap_p05", "bootstrap_gap_p25", "bootstrap_gap_median", "bootstrap_gap_p75", "bootstrap_gap_p95"]].to_numpy()
    assert (np.diff(values, axis=1) >= -1e-12).all()


def test_bootstrap_classification_thresholds():
    assert classify_bootstrap(.95) == "VERY_STABLE_POSITIVE"
    assert classify_bootstrap(.80) == "STABLE_POSITIVE"
    assert classify_bootstrap(.50) == "UNCERTAIN"
    assert classify_bootstrap(.20) == "STABLE_NEGATIVE"
    assert classify_bootstrap(.05) == "VERY_STABLE_NEGATIVE"


def test_original_sanity_flags_are_reproduced():
    sanity = pd.read_csv(ROOT / "reports/phase147_sanity_flag_classification.csv", encoding="utf-8-sig")
    assert sanity.original_sanity_flag.sum() == 95


def test_sanity_severity_major_rule():
    sanity = pd.read_csv(ROOT / "reports/phase147_sanity_flag_classification.csv", encoding="utf-8-sig")
    major_input = sanity[["flag_low_transaction", "flag_price_outlier", "flag_confidence_c", "flag_school_mapping", "flag_comparable_shortage", "flag_missing_control"]].any(axis=1)
    assert sanity.loc[major_input, "sanity_severity"].eq("MAJOR").all()


def test_sensitivity_samples_membership_is_nested_correctly():
    sensitivity = pd.read_csv(ROOT / "reports/phase147_sanity_flag_impact.csv", encoding="utf-8-sig").set_index("sample")
    assert sensitivity.loc["EXCLUDE_MAJOR_FLAG", "apartments"] <= sensitivity.loc["ALL", "apartments"]
    assert sensitivity.loc["GAP_CONFIDENCE_HIGH_ONLY", "apartments"] <= sensitivity.loc["GAP_CONFIDENCE_HIGH_MEDIUM", "apartments"] <= sensitivity.loc["ALL", "apartments"]


def test_gap_confidence_categories_are_disjoint():
    master = _master()
    sets = {name: set(master.loc[master.gap_confidence.eq(name), "apartment_id"]) for name in ["HIGH", "MEDIUM", "LOW"]}
    assert sets["HIGH"].isdisjoint(sets["MEDIUM"])
    assert sets["HIGH"].isdisjoint(sets["LOW"])
    assert sets["MEDIUM"].isdisjoint(sets["LOW"])


def test_lodo_train_excludes_holdout_dong():
    lodo = pd.read_csv(ROOT / "reports/phase147_leave_one_dong_out.csv", encoding="utf-8-sig")
    assert not lodo.train_contains_holdout.any()


def test_lodo_test_contains_only_holdout_dong():
    lodo = pd.read_csv(ROOT / "reports/phase147_leave_one_dong_out.csv", encoding="utf-8-sig")
    assert lodo.test_only_holdout.all()


def test_lodo_is_deterministic_on_small_frame():
    rows = []
    for dong in ["D1", "D2"]:
        for apartment in range(5):
            for transaction in range(20):
                score = 30 + apartment * 10
                rows.append({"apartment_id": f"{dong}_{apartment}", "legal_dong": dong, "school_premium_core_score": score,
                             "price_per_sqm": np.exp(15 + score / 100 + transaction / 1000), "transaction_date": pd.Timestamp("2025-01-01") + pd.offsets.Day(transaction),
                             "log_households": np.log(500 + apartment * 100), "floor": 5 + transaction % 3, "apartment_age": 10 + apartment,
                             "parking_per_household": 1.0, "transaction_month_index": 1.0, "area_group": "80_90"})
    frame = pd.DataFrame(rows)
    first = leave_one_dong_out(frame)
    second = leave_one_dong_out(frame)
    pd.testing.assert_frame_equal(first, second)


def test_candidate_input_equals_original_phase145_set():
    source = pd.read_csv(ROOT / "reports/phase145_school_value_gap_rankings.csv", encoding="utf-8-sig")
    source_ids = set(source.loc[source.ranking_type.eq("POTENTIAL_SCHOOL_VALUE_CANDIDATES"), "apartment_id"])
    tiers = pd.read_csv(ROOT / "reports/phase148_candidate_tiering.csv", encoding="utf-8-sig")
    assert set(tiers.apartment_id) == source_ids and len(source_ids) == 30


def _candidate(**updates):
    row = {"school_value_gap_pct": 5, "gap_confidence": "HIGH", "residual_method_gap_pct": 4,
           "comparable_method_gap_pct": 6, "gap_method_agreement": "STRONG_POSITIVE",
           "temporal_stability": "STABLE_POSITIVE", "gap_positive_probability": .9, "sanity_severity": "NONE"}
    row.update(updates)
    return row


def test_tier1_rule():
    assert classify_candidate(_candidate())[0] == "TIER_1"


def test_tier2_rule():
    assert classify_candidate(_candidate(temporal_stability="MIXED"))[0] == "TIER_2"


def test_watchlist_rule():
    assert classify_candidate(_candidate(sanity_severity="MAJOR"))[0] == "WATCHLIST"


def test_no_arbitrary_school_score_imputation():
    master = _master()
    missing = master.school_premium_core_score.isna()
    assert master.loc[missing, "estimated_school_premium_pct"].isna().all()
    assert master.loc[missing, "school_value_gap_pct"].isna().all()


def test_three_missing_school_score_apartments_remain_missing():
    assert _master().school_premium_core_score.isna().sum() == 3


def test_phase149_apartment_ids_are_unique():
    master = _master()
    assert len(master) == master.apartment_id.nunique() == 560


def test_phase149_sort_is_deterministic():
    master = _master()
    assert master.apartment_id.tolist() == sorted(master.apartment_id.tolist())


def test_freeze_snapshot_consistency():
    snapshot = json.loads((ROOT / "data/snapshots/phase149_school_value_final_freeze.json").read_text(encoding="utf-8"))
    master = _master()
    assert snapshot["total_apartments"] == len(master)
    assert np.isclose(snapshot["score_coverage"], master.school_premium_core_score.notna().mean() * 100)
    assert np.isclose(snapshot["gap_coverage"], master.school_value_gap_pct.notna().mean() * 100)
    assert snapshot["model_specification"] == "LINEAR_CORE_SCORE_WITH_PHASE14_CONTROLS"
    assert snapshot["pytest_count"] == 263
    assert snapshot["pytest_status"] == "FULL_PASS"
    assert snapshot["pytest_count"] == 263
    assert snapshot["existing_pytest_count"] == 226 and snapshot["new_pytest_count"] == 37


def test_protected_overwrite_is_detected():
    manifest = pd.DataFrame([{"path": "main.py", "phase": "CORE", "file_size": 0,
                              "sha256_before": "wrong", "sha256_after": "", "unchanged": False}])
    with pytest.raises(RuntimeError, match="PROTECTED_ARTIFACT_MODIFIED"):
        verify_manifest(manifest, ROOT)


def test_final_master_contains_no_new_external_features():
    columns = set(_master().columns)
    forbidden = {"subway_distance", "commercial_score", "coast_distance", "park_distance", "bridge_view", "beach_distance", "reconstruction_score"}
    assert columns.isdisjoint(forbidden)


def test_final_freeze_status_reflects_lodo_caution():
    snapshot = json.loads((ROOT / "data/snapshots/phase149_school_value_final_freeze.json").read_text(encoding="utf-8"))
    assert snapshot["freeze_status"] == "SCHOOL_VALUE_MODEL_FROZEN_WITH_CAUTION"


def test_required_phase146_to_phase148_figures_exist():
    figures = list((ROOT / "reports/figures").glob("phase146_*.html")) + list((ROOT / "reports/figures").glob("phase147_*.html")) + list((ROOT / "reports/figures").glob("phase148_*.html"))
    assert len(figures) == 12 and all(path.stat().st_size > 0 for path in figures)
