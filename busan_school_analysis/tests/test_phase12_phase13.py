import json

import numpy as np
import pandas as pd

from src.config import ROOT
from src.phase12_elementary_first import fit_clustered_ols, protected_hashes
from src.phase125_middle_incremental import build_apartment_middle_options


def _phase13():
    return pd.read_csv(
        ROOT / "data/processed/phase13_school_premium_index.csv",
        encoding="utf-8-sig",
    )


def test_phase12_protected_phase7_to_phase11_inputs_are_unchanged():
    snapshot = json.loads(
        (ROOT / "data/snapshots/phase12_input_hashes.json").read_text(encoding="utf-8")
    )["input_hashes"]
    assert protected_hashes(ROOT) == snapshot


def test_phase12_models_use_the_same_recent_common_sample():
    comparison = pd.read_csv(
        ROOT / "reports/phase12_elementary_vs_phase7_model_comparison.csv",
        encoding="utf-8-sig",
    )
    assert set(comparison.model) == {"MODEL_E", "MODEL_M"}
    assert comparison.n_transactions.nunique() == 1
    assert comparison.n_apartments.nunique() == 1
    assert comparison.n_schools.nunique() == 1
    assert comparison.train_transactions.nunique() == 1
    assert comparison.test_transactions.nunique() == 1


def test_phase125_nested_models_use_the_same_rows_and_split():
    comparison = pd.read_csv(
        ROOT / "reports/phase125_nested_model_comparison.csv",
        encoding="utf-8-sig",
    )
    assert set(comparison.model) == {"MODEL_E", "MODEL_E_PLUS_M"}
    for column in [
        "n_transactions", "n_apartments", "n_schools",
        "train_transactions", "test_transactions",
        "train_apartments", "test_apartments",
    ]:
        assert comparison[column].nunique() == 1


def test_middle_options_are_unweighted_and_unique_by_apartment():
    options = pd.read_parquet(
        ROOT / "data/processed/phase125_apartment_middle_options.parquet"
    )
    assert options.apartment_id.is_unique
    assert not options.assignment_probability_used.any()
    assert not any("probability" in c.lower() for c in options.columns if c != "assignment_probability_used")
    assert (options.guaranteed_middle_count <= options.eligible_middle_count).all()


def test_middle_option_build_is_deterministic():
    actual = pd.read_parquet(
        ROOT / "data/processed/phase125_apartment_middle_options.parquet"
    ).sort_values("apartment_id").reset_index(drop=True)
    rebuilt = build_apartment_middle_options(ROOT).sort_values("apartment_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(actual, rebuilt)


def test_exact_relationships_are_unique_per_elementary_school():
    relations = pd.read_parquet(
        ROOT / "data/processed/busan_elementary_middle_relation_2026.parquet"
    )
    exact = relations[
        relations.relation_status.eq("ACTIVE")
        & relations.guaranteed_assignment.fillna(False)
    ]
    assert len(exact) == exact.elementary_school_id.nunique() == 33
    assert not exact.duplicated(["elementary_school_id", "middle_school_id"]).any()


def test_yongso_remains_possible_with_two_active_options():
    relations = pd.read_parquet(
        ROOT / "data/processed/busan_elementary_middle_relation_2026.parquet"
    )
    yongso = relations[
        relations.elementary_school_id.eq("S020002045")
        & relations.relation_status.eq("ACTIVE")
    ]
    assert len(yongso) == 2
    assert set(yongso.relation_type) == {"ELIGIBLE"}
    assert not yongso.guaranteed_assignment.any()


def test_phase13_has_one_row_per_500plus_apartment_and_expected_coverage():
    final = _phase13()
    assert len(final) == final.apartment_id.nunique() == 560
    assert final.household_count.ge(500).all()
    assert final.school_premium_core_score.notna().sum() == 557
    assert np.isclose(final.school_premium_core_score.notna().mean() * 100, 99.46428571428572)


def test_phase13_missing_demand_is_explicit_and_never_imputed():
    final = _phase13()
    missing = final.elementary_demand_score.isna()
    assert missing.sum() == 3
    assert final.loc[missing, "final_school_premium_score"].isna().all()
    assert final.loc[missing, "data_quality_flag"].eq("ELEMENTARY_DEMAND_MISSING").all()
    assert final.loc[~missing, "final_school_premium_score"].notna().all()


def test_phase13_final_score_preserves_elementary_core():
    final = _phase13()
    pd.testing.assert_series_equal(
        final.final_school_premium_score,
        final.school_premium_core_score,
        check_names=False,
    )
    assert final.final_school_premium_score.dropna().between(0, 100).all()


def test_phase13_confidence_rules_are_consistent():
    final = _phase13()
    assert set(final.school_premium_confidence) == {"A", "B", "C"}
    assert final.school_premium_confidence.value_counts().to_dict() == {"B": 514, "A": 30, "C": 16}
    assert final.loc[final.school_premium_confidence.eq("A"), "has_guaranteed_assignment"].eq(1).all()
    assert final.loc[final.school_premium_confidence.eq("C") & final.elementary_demand_score.isna(), "data_quality_flag"].eq("ELEMENTARY_DEMAND_MISSING").all()


def test_phase13_ranking_is_stable_and_excludes_missing_scores():
    final = _phase13()
    expected = final.dropna(subset=["final_school_premium_score"]).sort_values(
        ["final_school_premium_score", "apartment_id"],
        ascending=[False, True], kind="mergesort",
    )
    ranking = pd.read_csv(
        ROOT / "reports/phase13_school_premium_ranking.csv",
        encoding="utf-8-sig",
    )
    ranking = ranking[ranking.ranking_type.eq("FINAL_SCHOOL_PREMIUM")]
    assert ranking["rank"].tolist() == list(range(1, 558))
    assert ranking.apartment_id.tolist() == expected.apartment_id.tolist()
    assert ranking.final_school_premium_score.notna().all()


def test_clustered_model_fit_is_deterministic():
    frame = pd.read_parquet(
        ROOT / "data/processed/phase12_elementary_first_dataset.parquet"
    )
    frame = frame[frame.is_phase10_recent_sample].dropna(
        subset=["elementary_demand_score"]
    ).head(1500)
    coef_a, metrics_a, pred_a, residual_a = fit_clustered_ols(
        frame, ["elementary_demand_score"], "MODEL_E"
    )
    coef_b, metrics_b, pred_b, residual_b = fit_clustered_ols(
        frame, ["elementary_demand_score"], "MODEL_E"
    )
    pd.testing.assert_frame_equal(coef_a, coef_b)
    assert metrics_a == metrics_b
    pd.testing.assert_series_equal(pred_a, pred_b)
    pd.testing.assert_series_equal(residual_a, residual_b)
