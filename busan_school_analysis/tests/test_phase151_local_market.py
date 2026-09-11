from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import adjusted_rand_score

from src.config import ROOT
from src.phase151_local_market import (
    BOOTSTRAP_ITERATIONS,
    CORE_CLUSTER_FEATURES,
    FORBIDDEN_CLUSTER_FEATURES,
    K_CANDIDATES,
    MIN_CLUSTER_APARTMENTS,
    MIN_CLUSTER_TRANSACTIONS,
    RANDOM_SEED,
    _window,
    align_labels,
    bootstrap_stability,
    discover_protected,
    fit_scaler,
    haversine_matrix,
    hybrid_markets,
    spatial_profile,
    time_window_stability,
    transform_scaler,
    verify_manifest,
)


FEATURE_PATH = ROOT / "data/processed/phase151_apartment_market_features.csv"
MAPPING_PATH = ROOT / "data/processed/phase151_local_market_mapping.csv"
SUMMARY_PATH = ROOT / "reports/phase151_local_market_summary.csv"
CROSSWALK_PATH = ROOT / "reports/phase151_legal_dong_market_crosswalk.csv"
RESULT_PATH = ROOT / "data/processed/phase151_result.json"


@pytest.fixture(scope="module")
def features():
    return pd.read_csv(FEATURE_PATH, encoding="utf-8-sig")


@pytest.fixture(scope="module")
def mapping():
    return pd.read_csv(MAPPING_PATH, encoding="utf-8-sig")


@pytest.fixture(scope="module")
def eligible(features):
    return features[features.clustering_eligible].reset_index(drop=True)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_01_phase7_to_phase149_protected_hashes_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase151_protected_manifest.csv", encoding="utf-8-sig")
    assert len(manifest) >= 199
    assert manifest.unchanged.all()


def test_02_phase149_master_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase151_protected_manifest.csv", encoding="utf-8-sig")
    row = manifest[manifest.path.eq("data/processed/phase149_school_value_master.csv")]
    assert len(row) == 1 and bool(row.unchanged.iloc[0])
    assert _sha(ROOT / row.iloc[0].path) == row.iloc[0].sha256_before


def test_03_phase149_snapshot_unchanged():
    manifest = pd.read_csv(ROOT / "reports/phase151_protected_manifest.csv", encoding="utf-8-sig")
    row = manifest[manifest.path.eq("data/snapshots/phase149_school_value_final_freeze.json")]
    assert len(row) == 1 and bool(row.unchanged.iloc[0])
    assert _sha(ROOT / row.iloc[0].path) == row.iloc[0].sha256_before
    snapshot = json.loads((ROOT / "data/snapshots/phase149_school_value_final_freeze.json").read_text(encoding="utf-8"))
    assert snapshot["freeze_status"] == "SCHOOL_VALUE_MODEL_FROZEN_WITH_CAUTION"
    assert snapshot["pytest_count"] == 263


def test_04_apartment_feature_id_unique(features):
    assert len(features) == features.apartment_id.nunique() == 560


def test_05_school_value_gap_not_core_feature():
    assert "school_value_gap_pct" not in CORE_CLUSTER_FEATURES


def test_06_estimated_school_premium_not_core_feature():
    assert "estimated_school_premium_pct" not in CORE_CLUSTER_FEATURES
    assert not set(FORBIDDEN_CLUSTER_FEATURES) & set(CORE_CLUSTER_FEATURES)


@pytest.mark.parametrize("months", [6, 12, 24])
def test_07_09_price_aggregation_correct(months, features):
    tx = pd.read_parquet(ROOT / "data/processed/phase135_transaction_sample.parquet")
    expected = _window(tx, tx.transaction_date.max(), months).groupby("apartment_id").price_per_sqm.median()
    actual = features.set_index("apartment_id")[f"recent_{months}m_price_per_m2"].dropna()
    common = expected.index.intersection(actual.index)
    assert np.allclose(actual.loc[common], expected.loc[common])


def test_10_no_future_leakage(features):
    tx = pd.read_parquet(ROOT / "data/processed/phase135_transaction_sample.parquet")
    assert set(features.feature_as_of_date) == {tx.transaction_date.max().date().isoformat()}


def test_11_scaling_deterministic(eligible):
    first, _ = fit_scaler(eligible)
    second, _ = fit_scaler(eligible)
    assert np.array_equal(first.to_numpy(), second.to_numpy())


def test_12_clustering_deterministic_seed(eligible):
    scaled, _ = fit_scaler(eligible)
    a = KMeans(n_clusters=3, random_state=RANDOM_SEED, n_init=10).fit_predict(scaled)
    b = KMeans(n_clusters=3, random_state=RANDOM_SEED, n_init=10).fit_predict(scaled)
    assert np.array_equal(a, b)


def test_13_cluster_size_rule():
    assert MIN_CLUSTER_APARTMENTS == 10 and MIN_CLUSTER_TRANSACTIONS == 500
    metrics = pd.read_csv(ROOT / "reports/phase151_cluster_selection.csv", encoding="utf-8-sig")
    selected = metrics[metrics.selected]
    assert len(selected) == 1 and selected.cluster_size_rule_pass.iloc[0]


def test_14_legal_dong_baseline_reproducible(eligible):
    ids = (eligible.gu.astype(str) + "|" + eligible.legal_dong.astype(str)).sort_values().unique()
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    assert len(ids) == result["final_market_count"] == 92


def test_15_kmeans_reproducible(eligible, mapping):
    scaled, _ = fit_scaler(eligible)
    labels = KMeans(n_clusters=3, random_state=RANDOM_SEED, n_init=30).fit_predict(scaled)
    actual = mapping.dropna(subset=["algorithm_cluster"]).set_index("apartment_id").loc[eligible.apartment_id, "algorithm_cluster"]
    assert adjusted_rand_score(labels, actual) == pytest.approx(1.0)


def test_16_hierarchical_reproducible(eligible, mapping):
    scaled, _ = fit_scaler(eligible)
    labels = AgglomerativeClustering(n_clusters=3, linkage="ward").fit_predict(scaled)
    actual = mapping.dropna(subset=["hierarchical_cluster"]).set_index("apartment_id").loc[eligible.apartment_id, "hierarchical_cluster"]
    assert adjusted_rand_score(labels, actual) == pytest.approx(1.0)


def test_17_time_window_stability_has_all_windows():
    table = pd.read_csv(ROOT / "reports/phase151_time_stability.csv", encoding="utf-8-sig")
    assert set(table.window) == {"12M", "24M", "FULL"}


@pytest.mark.parametrize("metric", ["ari_vs_12m", "nmi_vs_12m", "assignment_agreement_vs_12m"])
def test_18_20_time_metrics_in_unit_range(metric):
    table = pd.read_csv(ROOT / "reports/phase151_time_stability.csv", encoding="utf-8-sig")
    assert table[metric].between(0, 1).all()


def test_21_bootstrap_iteration_count():
    table = pd.read_csv(ROOT / "reports/phase151_bootstrap_stability.csv", encoding="utf-8-sig")
    assert set(table.bootstrap_iterations) == {BOOTSTRAP_ITERATIONS}


def test_22_bootstrap_assignment_probability_range():
    table = pd.read_csv(ROOT / "reports/phase151_bootstrap_stability.csv", encoding="utf-8-sig")
    assert table.assignment_stability.between(0, 1).all()


def test_23_cluster_label_alignment_correctness():
    reference = np.array([0, 0, 1, 1, 2, 2])
    candidate = np.array([2, 2, 0, 0, 1, 1])
    aligned, _ = align_labels(reference, candidate)
    assert np.array_equal(reference, aligned)


def test_24_spatial_fragmentation_rule():
    frame = pd.DataFrame({"latitude": [35.1, 35.1, 35.4], "longitude": [129.0, 129.01, 129.3],
                          "gu": ["A", "A", "B"], "legal_dong": ["a", "a", "b"]})
    profile = spatial_profile(frame, np.zeros(3, dtype=int)).iloc[0]
    assert profile.spatial_fragmentation_flag


def test_25_low_sample_flag_rule(mapping):
    assigned = mapping.dropna(subset=["final_local_market_id"])
    expected = (assigned.market_size_apartments < MIN_CLUSTER_APARTMENTS) & (assigned.market_transactions_12m < MIN_CLUSTER_TRANSACTIONS)
    assert np.array_equal(expected, assigned.low_sample_flag)


def test_26_hybrid_rule_deterministic(eligible, mapping):
    labels = mapping.dropna(subset=["algorithm_cluster"]).set_index("apartment_id").loc[eligible.apartment_id, "algorithm_cluster"].to_numpy()
    source = eligible.assign(algorithm_cluster=labels)
    first = hybrid_markets(source).hybrid_market
    second = hybrid_markets(source).hybrid_market
    assert first.equals(second)


def test_27_missing_data_has_no_arbitrary_assignment(features, mapping):
    missing_ids = set(features.loc[~features.clustering_eligible, "apartment_id"])
    rows = mapping[mapping.apartment_id.isin(missing_ids)]
    assert rows.final_local_market_id.isna().all()
    assert rows.data_quality_flag.eq("INSUFFICIENT_CLUSTER_FEATURES").all()


def test_28_market_id_maps_to_one_name(mapping):
    assigned = mapping.dropna(subset=["final_local_market_id"])
    assert assigned.groupby("final_local_market_id").final_local_market_name.nunique().eq(1).all()


def test_29_every_assigned_apartment_exactly_one_market(mapping):
    assigned = mapping.dropna(subset=["final_local_market_id"])
    assert assigned.apartment_id.is_unique
    assert assigned.final_local_market_id.notna().all()


def test_30_local_market_confidence_rule(mapping):
    values = set(mapping.local_market_confidence.dropna())
    assert values <= {"HIGH", "MEDIUM", "LOW"} and values


def test_31_market_summary_consistency(mapping):
    summary = pd.read_csv(SUMMARY_PATH, encoding="utf-8-sig")
    assigned = mapping.dropna(subset=["final_local_market_id"])
    expected = assigned.groupby("final_local_market_id").size()
    actual = summary.set_index("local_market_id").apartment_count
    assert expected.equals(actual.loc[expected.index])


def test_32_legal_dong_crosswalk_consistency(mapping):
    cross = pd.read_csv(CROSSWALK_PATH, encoding="utf-8-sig")
    assert cross.apartment_count.sum() == mapping.final_local_market_id.notna().sum()
    assert cross.groupby(["gu", "legal_dong"]).share.sum().round(10).eq(1).all()


def test_33_final_mapping_row_count(mapping):
    assert len(mapping) == 560


def test_34_protected_overwrite_prevention():
    manifest = pd.DataFrame([{"path": "main.py", "sha256_before": "bad"}])
    with pytest.raises(RuntimeError, match="PROTECTED_ARTIFACT_MODIFIED"):
        verify_manifest(manifest, ROOT)


def test_35_core_feature_ranges_and_candidate_k():
    assert len(CORE_CLUSTER_FEATURES) == 11
    assert K_CANDIDATES == tuple(range(3, 16))


def test_36_mapping_required_columns(mapping):
    required = {"apartment_id", "apartment_name", "gu", "legal_dong", "latitude", "longitude",
                "final_local_market_id", "final_local_market_name", "market_definition_type",
                "local_market_confidence", "assignment_stability", "cluster_algorithm_reference",
                "market_size_apartments", "market_transactions_12m", "dominant_legal_dong",
                "dominant_dong_share", "spatial_fragmentation_flag", "low_sample_flag", "data_quality_flag"}
    assert required <= set(mapping.columns)


def test_37_protected_discovery_includes_phase149_assets():
    paths = set(discover_protected(ROOT).path)
    assert "data/processed/phase149_school_value_master.csv" in paths
    assert "data/snapshots/phase149_school_value_final_freeze.json" in paths
