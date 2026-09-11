import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from src.config import ROOT
from src.phase135_145_school_value import (
    MIN_COMPARABLES,
    RANDOM_SEED,
    SCORE_REFERENCE,
    comparable_match,
    school_basis,
    verify_manifest,
)


def _phase13():
    return pd.read_csv(ROOT / "data/processed/phase13_school_premium_index.csv", encoding="utf-8-sig")


def _phase14():
    return pd.read_csv(ROOT / "data/processed/phase14_apartment_school_premium_value.csv", encoding="utf-8-sig")


def _gap():
    return pd.read_csv(ROOT / "data/processed/phase145_school_value_gap.csv", encoding="utf-8-sig")


def test_protected_phase7_to_phase13_manifest_is_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase135_protected_manifest.csv", encoding="utf-8-sig")
    assert len(manifest) > 0
    assert manifest.unchanged.all()
    for row in manifest.itertuples():
        digest = hashlib.sha256((ROOT / row.path).read_bytes()).hexdigest()
        assert digest == row.sha256_before == row.sha256_after


def test_phase13_frozen_snapshot_matches_source():
    snapshot = json.loads((ROOT / "data/snapshots/phase135_school_premium_freeze.json").read_text(encoding="utf-8"))
    source = ROOT / snapshot["source_path"]
    assert snapshot["status"] == "SCHOOL_PREMIUM_INDEX_FROZEN"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == snapshot["source_sha256"]


def test_phase13_frozen_row_count_is_unchanged():
    assert len(_phase13()) == 560


def test_phase13_frozen_apartment_ids_are_unique():
    assert _phase13().apartment_id.is_unique


def test_phase13_score_range_and_missing_are_preserved():
    data = _phase13()
    assert data.school_premium_core_score.dropna().between(0, 100).all()
    assert data.school_premium_core_score.isna().sum() == 3


def test_phase14_all_models_use_one_common_sample():
    comparison = pd.read_csv(ROOT / "reports/phase14_model_comparison.csv", encoding="utf-8-sig")
    assert comparison.n_transactions.nunique() == 1
    assert comparison.n_apartments.nunique() == 1
    assert comparison.train_transactions.nunique() == 1
    assert comparison.test_transactions.nunique() == 1
    assert comparison.n_transactions.iloc[0] == comparison.train_transactions.iloc[0] + comparison.test_transactions.iloc[0]


def test_temporal_split_has_no_future_leakage():
    comparison = pd.read_csv(ROOT / "reports/phase14_model_comparison.csv", encoding="utf-8-sig")
    assert not comparison.future_leakage.any()
    sample = pd.read_parquet(ROOT / "data/processed/phase135_transaction_sample.parquet")
    cutoff = pd.Timestamp(comparison.train_end.iloc[0])
    assert sample.loc[sample.transaction_date <= cutoff, "transaction_date"].max() < sample.loc[sample.transaction_date > cutoff, "transaction_date"].min()


def test_phase14_selected_model_obeys_prespecified_rule():
    comparison = pd.read_csv(ROOT / "reports/phase14_model_comparison.csv", encoding="utf-8-sig").set_index("model")
    result = json.loads((ROOT / "data/processed/phase14_result.json").read_text(encoding="utf-8"))
    linear = comparison.loc["MODEL_LINEAR"]
    eligible = comparison.loc[["MODEL_QUADRATIC", "MODEL_BINNED", "MODEL_SPLINE"]]
    eligible = eligible[
        eligible.monotonic & eligible.rmse_oos.le(linear.rmse_oos * .995)
        & eligible.mae_oos.le(linear.mae_oos * .995)
    ]
    expected = "LINEAR" if eligible.empty else eligible.sort_values(["rmse_oos", "mae_oos", "parameter_count"]).index[0].removeprefix("MODEL_")
    assert result["selected_model"] == expected


def test_premium_curve_is_complete_and_referenced_to_50():
    curve = pd.read_csv(ROOT / "reports/phase14_school_score_price_effect_curve.csv", encoding="utf-8-sig")
    assert curve.school_score.tolist() == list(range(101))
    reference = curve[curve.school_score.eq(SCORE_REFERENCE)].iloc[0]
    assert np.isclose(reference.relative_price_effect_pct, 0)
    assert np.isclose(reference.lower_ci_pct, 0)
    assert np.isclose(reference.upper_ci_pct, 0)


def test_premium_curve_is_deterministic():
    scores = np.arange(101, dtype=float)
    first, names_first = school_basis(scores, "SPLINE")
    second, names_second = school_basis(scores, "SPLINE")
    assert names_first == names_second
    pd.testing.assert_frame_equal(first, second)


def test_selected_linear_curve_is_monotonic():
    result = json.loads((ROOT / "data/processed/phase14_result.json").read_text(encoding="utf-8"))
    curve = pd.read_csv(ROOT / "reports/phase14_school_score_price_effect_curve.csv", encoding="utf-8-sig")
    assert result["selected_model"] == "LINEAR"
    assert curve.relative_price_effect_pct.is_monotonic_increasing


def test_phase14_premium_amount_identity():
    data = _phase14().dropna(subset=["estimated_school_premium_amount"])
    expected = data.school_adjusted_expected_price - data.baseline_expected_price
    assert np.allclose(data.estimated_school_premium_amount, expected)


def test_phase14_premium_percentage_identity():
    data = _phase14().dropna(subset=["estimated_school_premium_pct"])
    expected = (data.school_adjusted_expected_price / data.baseline_expected_price - 1) * 100
    assert np.allclose(data.estimated_school_premium_pct, expected)


def test_phase145_expected_fair_price_identity():
    data = _gap().dropna(subset=["expected_fair_price"])
    expected = data.baseline_non_school_price * (1 + data.expected_school_premium_pct / 100)
    assert np.allclose(data.expected_fair_price, expected)


def test_phase145_total_value_gap_identity():
    data = _gap().dropna(subset=["total_value_gap_pct"])
    expected = (data.expected_fair_price / data.recent_market_price - 1) * 100
    assert np.allclose(data.total_value_gap_pct, expected)


def test_phase145_school_gap_identity():
    data = _gap().dropna(subset=["school_value_gap_pct"])
    expected = data.expected_school_premium_pct - data.observed_market_premium_pct
    assert np.allclose(data.school_value_gap_pct, expected)


def test_comparable_minimum_rule_is_enforced():
    data = _gap()
    matched = data.comparable_rule.notna() & data.comparable_rule.ne("INSUFFICIENT_COMPARABLES")
    assert data.loc[matched, "comparable_count"].ge(MIN_COMPARABLES).all()
    insufficient = data.comparable_rule.eq("INSUFFICIENT_COMPARABLES")
    assert data.loc[insufficient, "comparable_count"].eq(0).all()


def test_comparable_relaxation_is_deterministic():
    candidates = pd.DataFrame({
        "apartment_id": ["A", "B", "C", "D", "E", "F"], "district": ["구"] * 6,
        "legal_dong": ["동"] * 6, "representative_area_m2": [84, 84, 85, 83, 84, 86],
        "apartment_age": [10, 11, 9, 10, 12, 8], "household_count": [1000, 900, 1100, 950, 1050, 1000],
        "recent_market_price_per_m2": [10, 9, 11, 10, 10.5, 9.5],
    })
    row = candidates.iloc[0]
    assert comparable_match(row, candidates) == comparable_match(row, candidates)
    assert comparable_match(row, candidates)["comparable_rule"] == "STRICT_SAME_DONG"


def test_gap_confidence_high_rule_is_enforced():
    data = _gap()
    high = data[data.gap_confidence.eq("HIGH")]
    assert high.school_premium_confidence.isin(["A", "B"]).all()
    assert high.transaction_count.ge(3).all() and high.comparable_count.ge(10).all()
    assert np.sign(high.residual_method_gap_pct).eq(np.sign(high.comparable_method_gap_pct)).all()


def test_gap_confidence_medium_rule_is_enforced():
    data = _gap()
    medium = data[data.gap_confidence.eq("MEDIUM")]
    assert medium.school_premium_confidence.isin(["A", "B"]).all()
    assert medium.transaction_count.ge(1).all() and medium.comparable_count.ge(5).all()
    assert np.sign(medium.residual_method_gap_pct).eq(np.sign(medium.comparable_method_gap_pct)).all()


def test_missing_score_apartments_are_never_estimated():
    phase13 = _phase13()
    phase14 = _phase14().set_index("apartment_id")
    gap = _gap().set_index("apartment_id")
    missing_ids = phase13.loc[phase13.school_premium_core_score.isna(), "apartment_id"]
    assert phase14.loc[missing_ids, "estimated_school_premium_pct"].isna().all()
    assert gap.loc[missing_ids, "school_value_gap_pct"].isna().all()
    assert gap.loc[missing_ids, "data_quality_flag"].eq("SCHOOL_SCORE_MISSING").all()


def test_phase14_and_phase145_outputs_have_unique_apartment_ids():
    assert len(_phase14()) == _phase14().apartment_id.nunique() == 560
    assert len(_gap()) == _gap().apartment_id.nunique() == 560


def test_recent_price_window_rules_are_valid():
    data = _phase14().dropna(subset=["price_window_used"])
    assert set(data.price_window_used).issubset({"6M", "12M", "24M"})
    assert data.loc[data.price_window_used.eq("6M"), "transaction_count"].ge(3).all()
    assert data.loc[data.price_window_used.eq("12M"), "transaction_count"].ge(3).all()
    assert data.loc[data.price_window_used.eq("24M"), "transaction_count"].ge(1).all()


def test_gap_ranking_order_is_reproducible():
    rankings = pd.read_csv(ROOT / "reports/phase145_school_value_gap_rankings.csv", encoding="utf-8-sig")
    for ranking_type, group in rankings.groupby("ranking_type"):
        ascending = ranking_type in {"HIGH_SCORE_FULLY_PRICED", "LOW_MEDIUM_SCORE_OVERPRICED"}
        expected = group.sort_values(["school_value_gap_pct", "apartment_id"], ascending=[ascending, True], kind="mergesort")
        assert group.apartment_id.tolist() == expected.apartment_id.tolist()
        assert group["rank"].tolist() == list(range(1, len(group) + 1))


def test_critical_gap_outputs_have_no_nan_or_infinity_when_available():
    data = _gap().dropna(subset=["school_value_gap_pct"])
    columns = [
        "recent_market_price", "baseline_non_school_price", "expected_school_premium_pct",
        "expected_school_premium_amount", "expected_fair_price", "observed_market_premium_pct",
        "school_value_gap_pct", "total_value_gap_pct", "residual_method_gap_pct",
    ]
    assert data[columns].notna().all().all()
    assert np.isfinite(data[columns].to_numpy(dtype=float)).all()


def test_protected_manifest_detects_overwrite():
    manifest = pd.DataFrame([{"path": "main.py", "phase": "13", "file_size": 0,
                              "sha256_before": "deliberately-wrong", "sha256_after": "", "unchanged": False}])
    with pytest.raises(RuntimeError, match="PROTECTED_ARTIFACT_MODIFIED"):
        verify_manifest(manifest, ROOT)


def test_model_seed_is_fixed():
    assert RANDOM_SEED == 20260911
