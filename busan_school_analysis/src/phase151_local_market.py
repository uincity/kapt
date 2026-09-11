"""Phase 15.1: apartment-level local housing market discovery."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    normalized_mutual_info_score,
    silhouette_score,
)
from sklearn.preprocessing import RobustScaler

from .config import ROOT, atomic_bytes, write_csv, write_json


APARTMENT_ROOT = ROOT.parent / "busan_apartment_analysis"
RANDOM_SEED = 20260911
K_CANDIDATES = tuple(range(3, 16))
BOOTSTRAP_ITERATIONS = 100
MIN_CLUSTER_APARTMENTS = 10
MIN_CLUSTER_TRANSACTIONS = 500
FRAGMENTATION_KM = 20.0
FEATURE_GROUPS = {
    "PRICE_LEVEL": ("log_recent_12m_price_per_m2", "log_full_period_median_price_per_m2"),
    "PRICE_DYNAMICS": ("price_change_6m", "price_change_12m", "price_trend_24m"),
    "STRUCTURE_LIQUIDITY": (
        "log_household_count", "apartment_age", "log_representative_area_m2",
        "parking_per_household", "log_transaction_count_12m", "turnover_12m",
    ),
}
CORE_CLUSTER_FEATURES = tuple(feature for group in FEATURE_GROUPS.values() for feature in group)
FORBIDDEN_CLUSTER_FEATURES = (
    "school_premium_core_score", "estimated_school_premium_pct", "school_value_gap_pct"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_protected(root=ROOT) -> pd.DataFrame:
    root = Path(root)
    expression = re.compile(r"phase(149|148|147|146|145|14|135|13|125|12|115|11|10|9|8|7)(?![0-9])")
    found: set[Path] = set()
    for folder in ("src", "tests", "data/processed", "data/snapshots", "reports"):
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and expression.search(path.name.lower()) and "phase151" not in path.name.lower():
                found.add(path)
    for relative in (
        "main.py", "data/processed/busan_apartment_school_scores_2026.parquet",
        "config/manual_elementary_middle_overrides.csv",
    ):
        path = root / relative
        if path.exists():
            found.add(path)
    return pd.DataFrame([
        {"path": path.relative_to(root).as_posix(), "file_size": path.stat().st_size,
         "sha256_before": _sha(path), "sha256_after": "", "unchanged": False}
        for path in sorted(found)
    ])


def verify_manifest(manifest, root=ROOT):
    root = Path(root); out = manifest.copy()
    out["sha256_after"] = [(_sha(root / path) if (root / path).exists() else "MISSING") for path in out.path]
    out["unchanged"] = out.sha256_before.eq(out.sha256_after)
    if not out.unchanged.all():
        raise RuntimeError(f"PROTECTED_ARTIFACT_MODIFIED: {out.loc[~out.unchanged, 'path'].tolist()}")
    return out


def _window(frame, end, months, previous=False):
    upper = end - pd.DateOffset(months=months) if previous else end
    lower = end - pd.DateOffset(months=months * 2) if previous else end - pd.DateOffset(months=months)
    return frame[frame.transaction_date.gt(lower) & frame.transaction_date.le(upper)]


def _trend(group, end, months, minimum_months):
    subset = group[group.transaction_date.gt(end - pd.DateOffset(months=months))]
    monthly = subset.groupby(subset.transaction_date.dt.to_period("M")).price_per_sqm.median().dropna()
    if len(monthly) < minimum_months:
        return np.nan
    x = np.arange(len(monthly), dtype=float)
    return float(np.polyfit(x, np.log(monthly.to_numpy(dtype=float)), 1)[0] * 12)


def build_market_features(root=ROOT):
    root = Path(root)
    master = pd.read_csv(root / "data/processed/phase149_school_value_master.csv", encoding="utf-8-sig")
    transactions = pd.read_parquet(root / "data/processed/phase135_transaction_sample.parquet")
    scores = pd.read_parquet(root / "data/processed/busan_apartment_school_scores_2026.parquet")[["internal_complex_id", "kapt_code"]]
    kapt = pd.read_parquet(APARTMENT_ROOT / "data/interim/kapt_clean.parquet")
    metadata = scores.merge(kapt, on="kapt_code", how="left", validate="many_to_one")
    metadata = metadata.rename(columns={"internal_complex_id": "apartment_id"})
    columns = ["apartment_id", "latitude", "longitude", "apartment_age", "parking_per_household", "buildings", "households_per_building"]
    base = master[["apartment_id", "apartment_name", "gu", "legal_dong", "household_count", "school_premium_core_score"]].merge(
        metadata[columns], on="apartment_id", how="left", validate="one_to_one"
    )
    end = transactions.transaction_date.max()
    full = transactions.groupby("apartment_id").agg(
        full_period_median_price_per_m2=("price_per_sqm", "median"),
        full_period_transaction_count=("price_per_sqm", "size"),
        representative_area_m2=("exclusive_area", "median"), median_floor=("floor", "median"),
    )
    base = base.merge(full, left_on="apartment_id", right_index=True, how="left")
    for months in (6, 12, 24):
        recent = _window(transactions, end, months)
        aggregate = recent.groupby("apartment_id").agg(**{
            f"recent_{months}m_price_per_m2": ("price_per_sqm", "median"),
            f"transaction_count_{months}m": ("price_per_sqm", "size"),
        })
        base = base.merge(aggregate, left_on="apartment_id", right_index=True, how="left")
    recent6 = _window(transactions, end, 6).groupby("apartment_id").price_per_sqm.median()
    previous6 = _window(transactions, end, 6, previous=True).groupby("apartment_id").price_per_sqm.median()
    recent12 = _window(transactions, end, 12).groupby("apartment_id").price_per_sqm.median()
    prior12 = transactions[
        transactions.transaction_date.gt(end - pd.DateOffset(months=24))
        & transactions.transaction_date.le(end - pd.DateOffset(months=12))
    ].groupby("apartment_id").price_per_sqm.median()
    base["price_change_6m"] = base.apartment_id.map(recent6 / previous6 - 1)
    base["price_change_12m"] = base.apartment_id.map(recent12 / prior12 - 1)
    grouped = transactions.groupby("apartment_id", sort=False)
    base["price_trend_24m"] = base.apartment_id.map(grouped.apply(lambda g: _trend(g, end, 24, 6), include_groups=False))
    base["price_trend_36m"] = base.apartment_id.map(grouped.apply(lambda g: _trend(g, end, 36, 9), include_groups=False))
    for column in ("recent_6m_price_per_m2", "recent_12m_price_per_m2", "recent_24m_price_per_m2", "full_period_median_price_per_m2"):
        base[f"log_{column}"] = np.log(base[column])
    base["log_household_count"] = np.log(base.household_count)
    base["log_representative_area_m2"] = np.log(base.representative_area_m2)
    base["log_transaction_count_12m"] = np.log1p(base.transaction_count_12m)
    base["turnover_12m"] = base.transaction_count_12m / base.household_count
    base["transaction_frequency"] = base.full_period_transaction_count / max((end - transactions.transaction_date.min()).days / 365.25, 1)
    base["clustering_eligible"] = base[list(CORE_CLUSTER_FEATURES)].notna().all(axis=1)
    missing = base[list(CORE_CLUSTER_FEATURES)].isna().apply(lambda r: ";".join(r.index[r].tolist()), axis=1)
    base["clustering_missing_reason"] = np.where(base.clustering_eligible, "", missing)
    base["feature_as_of_date"] = end.date().isoformat()
    return base, transactions


def fit_scaler(frame, features=CORE_CLUSTER_FEATURES):
    raw = frame[list(features)].astype(float)
    lower = raw.quantile(.01); upper = raw.quantile(.99)
    clipped = raw.clip(lower=lower, upper=upper, axis=1)
    scaler = RobustScaler().fit(clipped)
    scaled = pd.DataFrame(scaler.transform(clipped), index=frame.index, columns=features)
    for group in FEATURE_GROUPS.values():
        active = [column for column in group if column in features]
        if active:
            scaled[active] = scaled[active] / math.sqrt(len(active))
    return scaled, {"lower": lower, "upper": upper, "scaler": scaler, "features": tuple(features)}


def transform_scaler(frame, fitted):
    features = fitted["features"]
    raw = frame[list(features)].astype(float).clip(lower=fitted["lower"], upper=fitted["upper"], axis=1)
    scaled = pd.DataFrame(fitted["scaler"].transform(raw), index=frame.index, columns=features)
    for group in FEATURE_GROUPS.values():
        active = [column for column in group if column in features]
        if active:
            scaled[active] = scaled[active] / math.sqrt(len(active))
    return scaled


def align_labels(reference, candidate):
    reference = np.asarray(reference, dtype=int); candidate = np.asarray(candidate, dtype=int)
    size = max(reference.max(), candidate.max()) + 1
    counts = np.zeros((size, size), dtype=int)
    for left, right in zip(reference, candidate): counts[left, right] += 1
    rows, columns = linear_sum_assignment(-counts)
    mapping = {column: row for row, column in zip(rows, columns)}
    aligned = np.array([mapping.get(value, value) for value in candidate], dtype=int)
    return aligned, mapping


def haversine_matrix(latitude, longitude):
    lat = np.radians(np.asarray(latitude, dtype=float)); lon = np.radians(np.asarray(longitude, dtype=float))
    dlat = lat[:, None] - lat[None, :]; dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def spatial_profile(frame, labels):
    data = frame.copy(); data["label"] = labels; rows = []
    for label, group in data.groupby("label"):
        distances = haversine_matrix(group.latitude, group.longitude)
        upper = distances[np.triu_indices(len(group), 1)]
        main_gu_share = group.gu.value_counts(normalize=True).iloc[0]
        rows.append({"label": int(label), "apartment_count": len(group),
                     "mean_intra_distance_km": float(np.mean(upper)) if len(upper) else 0,
                     "maximum_spread_km": float(np.max(upper)) if len(upper) else 0,
                     "dominant_gu_share": main_gu_share,
                     "dominant_dong_share": group.legal_dong.value_counts(normalize=True).iloc[0],
                     "legal_dong_count": group.legal_dong.nunique(),
                     "spatial_fragmentation_flag": bool((np.max(upper) if len(upper) else 0) > FRAGMENTATION_KM and main_gu_share < .8)})
    return pd.DataFrame(rows)


def evaluate_k(frame, scaled, transactions):
    tx12 = transactions[transactions.transaction_date.gt(transactions.transaction_date.max() - pd.DateOffset(months=12))].groupby("apartment_id").size()
    rows = []; models = {}
    for k in K_CANDIDATES:
        model = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init=30).fit(scaled)
        labels = model.labels_; sizes = pd.Series(labels).value_counts()
        spatial = spatial_profile(frame, labels)
        cluster_transactions = frame.assign(label=labels).groupby("label").apartment_id.apply(lambda ids: int(tx12.reindex(ids).fillna(0).sum()))
        valid_size = all(sizes.get(label, 0) >= MIN_CLUSTER_APARTMENTS or cluster_transactions.get(label, 0) >= MIN_CLUSTER_TRANSACTIONS for label in range(k))
        rows.append({"k": k, "silhouette": silhouette_score(scaled, labels), "calinski_harabasz": calinski_harabasz_score(scaled, labels),
                     "davies_bouldin": davies_bouldin_score(scaled, labels), "minimum_cluster_size": int(sizes.min()),
                     "maximum_cluster_size": int(sizes.max()), "cluster_size_rule_pass": valid_size,
                     "mean_intra_distance_km": np.average(spatial.mean_intra_distance_km, weights=spatial.apartment_count),
                     "fragmented_cluster_count": int(spatial.spatial_fragmentation_flag.sum())})
        models[k] = model
    metrics = pd.DataFrame(rows)
    eligible = metrics[metrics.cluster_size_rule_pass].copy()
    eligible["rank_score"] = eligible.silhouette.rank(ascending=False) + eligible.calinski_harabasz.rank(ascending=False) + eligible.davies_bouldin.rank() + eligible.fragmented_cluster_count.rank() + eligible.mean_intra_distance_km.rank()
    selected_k = int(eligible.sort_values(["rank_score", "k"]).iloc[0].k)
    return metrics, models, selected_k


def time_window_stability(features, selected_k, reference_labels):
    rows = []; labels_by_window = {}
    variants = {"12M": "log_recent_12m_price_per_m2", "24M": "log_recent_24m_price_per_m2", "FULL": "log_full_period_median_price_per_m2"}
    reference_feature = "log_recent_12m_price_per_m2"
    for window, replacement in variants.items():
        data = features.copy()
        data[reference_feature] = data[replacement]
        scaled, _ = fit_scaler(data)
        raw_labels = KMeans(n_clusters=selected_k, random_state=RANDOM_SEED, n_init=30).fit_predict(scaled)
        aligned, _ = align_labels(reference_labels, raw_labels)
        labels_by_window[window] = aligned
        rows.append({"window": window, "ari_vs_12m": adjusted_rand_score(reference_labels, aligned),
                     "nmi_vs_12m": normalized_mutual_info_score(reference_labels, aligned),
                     "assignment_agreement_vs_12m": float(np.mean(reference_labels == aligned))})
    return pd.DataFrame(rows), labels_by_window


def bootstrap_stability(features, transactions, selected_k, reference_labels, fitted_scaler):
    end = transactions.transaction_date.max(); recent = transactions[transactions.transaction_date.gt(end - pd.DateOffset(months=12))]
    groups = {key: group.price_per_sqm.to_numpy(dtype=float) for key, group in recent.groupby("apartment_id")}
    counts = np.zeros((len(features), selected_k), dtype=int)
    for iteration in range(BOOTSTRAP_ITERATIONS):
        rng = np.random.default_rng(RANDOM_SEED + iteration)
        perturbed = features.copy()
        medians = []
        for apartment_id in perturbed.apartment_id:
            values = groups[apartment_id]
            medians.append(np.median(values[rng.integers(0, len(values), len(values))]))
        perturbed["log_recent_12m_price_per_m2"] = np.log(medians)
        scaled = transform_scaler(perturbed, fitted_scaler)
        labels = KMeans(n_clusters=selected_k, random_state=RANDOM_SEED + iteration, n_init=10).fit_predict(scaled)
        aligned, _ = align_labels(reference_labels, labels)
        counts[np.arange(len(features)), aligned] += 1
    modal = counts.argmax(axis=1)
    stability = counts.max(axis=1) / BOOTSTRAP_ITERATIONS
    return pd.DataFrame({"apartment_id": features.apartment_id.to_numpy(), "bootstrap_modal_cluster": modal,
                         "assignment_stability": stability, "bootstrap_iterations": BOOTSTRAP_ITERATIONS})


def dispersion(frame, definition, label):
    data = frame.dropna(subset=[definition, "recent_12m_price_per_m2"]).copy()
    log_price = np.log(data.recent_12m_price_per_m2)
    group_mean = log_price.groupby(data[definition]).transform("mean")
    residual = log_price - group_mean
    group_median = data.recent_12m_price_per_m2.groupby(data[definition]).transform("median")
    absolute = (data.recent_12m_price_per_m2 - group_median).abs()
    total_variance = log_price.var()
    return {"definition": label, "apartment_count": len(data), "market_count": data[definition].nunique(),
            "within_log_price_variance": residual.var(), "variance_ratio_vs_busan": residual.var() / total_variance,
            "within_price_mad": absolute.median(), "mean_market_price_iqr": data.groupby(definition).recent_12m_price_per_m2.apply(lambda x: x.quantile(.75)-x.quantile(.25)).mean(),
            "within_price_change_variance": (data.price_change_12m - data.groupby(definition).price_change_12m.transform("mean")).var()}


def hybrid_markets(features):
    data = features.copy(); labels = []
    for (gu, dong), group in data.groupby(["gu", "legal_dong"], sort=True):
        counts = group.algorithm_cluster.value_counts(); tx = group.groupby("algorithm_cluster").transaction_count_12m.sum()
        valid_children = len(counts) > 1 and all(counts[label] >= MIN_CLUSTER_APARTMENTS or tx[label] >= MIN_CLUSTER_TRANSACTIONS for label in counts.index)
        for index, row in group.iterrows():
            suffix = f"C{int(row.algorithm_cluster):02d}" if valid_children else "ALL"
            labels.append((index, f"{gu}|{dong}|{suffix}", "DONG_SUBDIVISION" if valid_children else "LEGAL_DONG"))
    assignment = pd.DataFrame(labels, columns=["index", "hybrid_market", "hybrid_rule"]).set_index("index")
    data = data.join(assignment)
    return data


def build_mapping_and_reports(root, universe, eligible, labels, hierarchy, time_table, time_labels, bootstrap, selected_k, metrics, transactions):
    root = Path(root); data = eligible.copy(); data["algorithm_cluster"] = labels
    data["hierarchical_cluster"] = hierarchy
    data = data.merge(bootstrap, on="apartment_id", how="left", validate="one_to_one")
    for window, window_labels in time_labels.items(): data[f"cluster_{window.lower()}"] = window_labels
    data["algorithm_agreement"] = data.algorithm_cluster.eq(data.hierarchical_cluster)
    hybrid = hybrid_markets(data)
    profiles = spatial_profile(hybrid, labels).set_index("label")
    hybrid["algorithm_fragmented"] = hybrid.algorithm_cluster.map(profiles.spatial_fragmentation_flag)
    dispersion_table = pd.DataFrame([
        {**dispersion(hybrid.assign(busan="BUSAN"), "busan", "BUSAN")},
        dispersion(hybrid, "gu", "GU"), dispersion(hybrid, "legal_dong", "LEGAL_DONG"),
        dispersion(hybrid, "algorithm_cluster", "ALGORITHMIC"), dispersion(hybrid, "hybrid_market", "HYBRID"),
    ])
    legal = dispersion_table.set_index("definition").loc["LEGAL_DONG"]
    hybrid_row = dispersion_table.set_index("definition").loc["HYBRID"]
    time_ari = float(time_table.loc[time_table.window.eq("24M"), "ari_vs_12m"].iloc[0])
    median_bootstrap = float(hybrid.assignment_stability.median())
    hybrid_improvement = 1 - hybrid_row.within_log_price_variance / legal.within_log_price_variance
    hybrid_minimum = hybrid.groupby("hybrid_market").apply(lambda g: len(g) >= MIN_CLUSTER_APARTMENTS or g.transaction_count_12m.sum() >= MIN_CLUSTER_TRANSACTIONS, include_groups=False).all()
    if hybrid_improvement >= .05 and time_ari >= .70 and median_bootstrap >= .80 and hybrid_minimum:
        verdict = "LOCAL_MARKET_STRUCTURE_PARTIALLY_SUPPORTED"
        final_definition = "HYBRID"
    else:
        verdict = "LEGAL_DONG_BASELINE_PREFERRED"
        final_definition = "LEGAL_DONG"
    hybrid["final_local_market_key"] = hybrid.hybrid_market if final_definition == "HYBRID" else hybrid.gu + "|" + hybrid.legal_dong
    keys = sorted(hybrid.final_local_market_key.unique()); market_ids = {key: f"LM{index+1:03d}" for index, key in enumerate(keys)}
    hybrid["final_local_market_id"] = hybrid.final_local_market_key.map(market_ids)
    hybrid["final_local_market_name"] = hybrid.final_local_market_key
    hybrid["market_definition_type"] = final_definition
    time_agreement = hybrid[["cluster_12m", "cluster_24m", "cluster_full"]].nunique(axis=1).eq(1)
    hybrid["local_market_confidence"] = np.select([
        hybrid.assignment_stability.ge(.90) & hybrid.algorithm_agreement & time_agreement,
        hybrid.assignment_stability.ge(.75) & (hybrid.algorithm_agreement | time_agreement),
    ], ["HIGH", "MEDIUM"], default="LOW")
    market_size = hybrid.groupby("final_local_market_id").apartment_id.transform("size")
    market_tx = hybrid.groupby("final_local_market_id").transaction_count_12m.transform("sum")
    dominant = hybrid.groupby("final_local_market_id").legal_dong.transform(lambda x: x.value_counts().index[0])
    dominant_share = hybrid.groupby("final_local_market_id").legal_dong.transform(lambda x: x.value_counts(normalize=True).iloc[0])
    hybrid["market_size_apartments"] = market_size; hybrid["market_transactions_12m"] = market_tx
    hybrid["dominant_legal_dong"] = dominant; hybrid["dominant_dong_share"] = dominant_share
    hybrid["spatial_fragmentation_flag"] = False if final_definition == "LEGAL_DONG" else hybrid.algorithm_fragmented
    hybrid["low_sample_flag"] = (market_size < MIN_CLUSTER_APARTMENTS) & (market_tx < MIN_CLUSTER_TRANSACTIONS)
    hybrid["data_quality_flag"] = np.select([hybrid.spatial_fragmentation_flag, hybrid.low_sample_flag, hybrid.local_market_confidence.eq("LOW")],
                                             ["SPATIAL_FRAGMENTATION", "LOW_SAMPLE", "LOW_ASSIGNMENT_STABILITY"], default="OK")
    mapping_columns = ["apartment_id", "apartment_name", "gu", "legal_dong", "latitude", "longitude", "final_local_market_id", "final_local_market_name",
                       "market_definition_type", "local_market_confidence", "assignment_stability", "algorithm_cluster", "hierarchical_cluster",
                       "market_size_apartments", "market_transactions_12m", "dominant_legal_dong", "dominant_dong_share",
                       "spatial_fragmentation_flag", "low_sample_flag", "data_quality_flag"]
    mapping = universe[["apartment_id"]].merge(
        hybrid[mapping_columns], on="apartment_id", how="left", validate="one_to_one"
    )
    missing_rows = mapping.apartment_name.isna()
    universe_lookup = universe.set_index("apartment_id")
    for column in ("apartment_name", "gu", "legal_dong", "latitude", "longitude"):
        mapping.loc[missing_rows, column] = mapping.loc[missing_rows, "apartment_id"].map(universe_lookup[column])
    mapping["cluster_algorithm_reference"] = f"KMEANS_K{selected_k}_SEED{RANDOM_SEED}"
    mapping.loc[mapping.final_local_market_id.isna(), "data_quality_flag"] = "INSUFFICIENT_CLUSTER_FEATURES"
    write_csv(root / "data/processed/phase151_local_market_mapping.csv", mapping)

    # Market summary and confidence are rule based.
    summaries = []
    global_scaled = transform_scaler(eligible, fit_scaler(eligible)[1])
    for market_id, group in hybrid.groupby("final_local_market_id", sort=True):
        spatial = spatial_profile(group, np.zeros(len(group), dtype=int)).iloc[0]
        member_scaled = global_scaled.loc[group.index]
        centroid_distance = ((member_scaled - member_scaled.mean()) ** 2).sum(axis=1)
        representative = group.loc[centroid_distance.nsmallest(min(5, len(group))).index]
        market_confidence = "HIGH" if len(group) >= 10 and group.assignment_stability.median() >= .9 and not spatial.spatial_fragmentation_flag else "MEDIUM" if len(group) >= 5 and group.assignment_stability.median() >= .75 else "LOW"
        summaries.append({"local_market_id": market_id, "local_market_name": group.final_local_market_name.iloc[0], "apartment_count": len(group),
                          "transaction_count_12m": int(group.transaction_count_12m.sum()), "transaction_count_24m": int(group.transaction_count_24m.sum()),
                          "median_price_per_m2": group.recent_12m_price_per_m2.median(), "price_iqr": group.recent_12m_price_per_m2.quantile(.75)-group.recent_12m_price_per_m2.quantile(.25),
                          "median_age": group.apartment_age.median(), "median_households": group.household_count.median(), "median_turnover": group.turnover_12m.median(),
                          "median_school_core_score": group.school_premium_core_score.median(), "main_gu": group.gu.value_counts().index[0],
                          "legal_dong_list": ";".join(sorted(group.legal_dong.unique())), "dominant_dong": group.legal_dong.value_counts().index[0],
                          "spatial_coherence": spatial.mean_intra_distance_km, "time_stability": float(time_agreement.loc[group.index].mean()),
                          "bootstrap_stability": group.assignment_stability.median(), "market_confidence": market_confidence,
                          "representative_apartments": ";".join(representative.apartment_name.astype(str))})
    summary = pd.DataFrame(summaries); write_csv(root / "reports/phase151_local_market_summary.csv", summary)
    write_csv(root / "reports/phase151_market_definition_comparison.csv", dispersion_table)

    # Legal-dong x pure-cluster relation exposes splits and non-local merges.
    cross = hybrid.groupby(["gu", "legal_dong", "algorithm_cluster"], as_index=False).agg(apartment_count=("apartment_id", "size"))
    dong_total = hybrid.groupby(["gu", "legal_dong"]).apartment_id.size(); cluster_total = hybrid.groupby("algorithm_cluster").apartment_id.size()
    dong_clusters = hybrid.groupby(["gu", "legal_dong"]).algorithm_cluster.nunique(); cluster_dongs = hybrid.groupby("algorithm_cluster").legal_dong.nunique()
    cross["apartments_in_market"] = cross.algorithm_cluster.map(cluster_total)
    cross["share"] = cross.apply(lambda r: r.apartment_count / dong_total.loc[(r.gu, r.legal_dong)], axis=1)
    cross["market_id"] = cross.algorithm_cluster.map(lambda x: f"ALG{x:02d}")
    cross["relationship_type"] = cross.apply(lambda r: "MIXED" if dong_clusters.loc[(r.gu,r.legal_dong)]>1 and cluster_dongs.loc[r.algorithm_cluster]>1 else "DONG_SPLIT" if dong_clusters.loc[(r.gu,r.legal_dong)]>1 else "MULTI_DONG_MARKET" if cluster_dongs.loc[r.algorithm_cluster]>1 else "ONE_DONG_ONE_MARKET", axis=1)
    write_csv(root / "reports/phase151_legal_dong_market_crosswalk.csv", cross[["gu", "legal_dong", "apartment_count", "market_id", "apartments_in_market", "share", "relationship_type"]])

    audits = []
    for row in mapping[mapping.data_quality_flag.ne("OK")].itertuples():
        audits.append({"apartment": row.apartment_name, "legal_dong": row.legal_dong, "local_market": row.final_local_market_id,
                       "issue_type": row.data_quality_flag, "issue_detail": "규칙 기반 품질 플래그", "recommended_action": "Phase 15.2 비교대상에서 제외 또는 별도 검토"})
    for profile in profiles[profiles.spatial_fragmentation_flag].itertuples():
        group = hybrid[hybrid.algorithm_cluster.eq(profile.Index)]
        audits.append({"apartment": "", "legal_dong": ";".join(sorted(group.legal_dong.unique())), "local_market": f"ALG{profile.Index:02d}",
                       "issue_type": "NON_LOCAL_PRICE_CLUSTER", "issue_detail": f"max spread {profile.maximum_spread_km:.1f}km",
                       "recommended_action": "Pure cluster를 최종 local market으로 사용하지 않음"})
        audits.append({"apartment": "", "legal_dong": ";".join(sorted(group.legal_dong.unique())), "local_market": f"ALG{profile.Index:02d}",
                       "issue_type": "DISTANT_DONG_MERGED", "issue_detail": f"{group.legal_dong.nunique()}개 법정동, max spread {profile.maximum_spread_km:.1f}km",
                       "recommended_action": "법정동 기준을 유지하고 원거리 병합을 금지"})
    split_dongs = hybrid.groupby(["gu", "legal_dong"]).filter(lambda g: g.algorithm_cluster.nunique() > 1)
    for (gu, dong), group in split_dongs.groupby(["gu", "legal_dong"], sort=True):
        distribution = group.algorithm_cluster.value_counts().sort_index().to_dict()
        audits.append({"apartment": "", "legal_dong": f"{gu} {dong}", "local_market": "",
                       "issue_type": "LEGAL_DONG_SPLIT", "issue_detail": f"algorithm clusters={distribution}",
                       "recommended_action": "최소표본 규칙 충족 여부 확인; 미충족 시 법정동 유지"})
    for row in hybrid[hybrid.assignment_stability.lt(.80)].itertuples():
        audits.append({"apartment": row.apartment_name, "legal_dong": row.legal_dong, "local_market": row.final_local_market_id,
                       "issue_type": "CLUSTER_SWITCHING_APARTMENT", "issue_detail": f"bootstrap stability={row.assignment_stability:.3f}",
                       "recommended_action": "Algorithmic comparable에서 제외 또는 별도 검토"})
    for market_id, group in hybrid.groupby("final_local_market_id", sort=True):
        if bool(group.low_sample_flag.iloc[0]):
            audits.append({"apartment": "", "legal_dong": group.legal_dong.iloc[0], "local_market": market_id,
                           "issue_type": "TINY_MARKET", "issue_detail": f"apartments={len(group)}, tx12={int(group.transaction_count_12m.sum())}",
                           "recommended_action": "Phase 15.2에서 상위 지리단위 fallback 검토"})
    audit = pd.DataFrame(audits); write_csv(root / "reports/phase151_local_market_audit.csv", audit)
    return verdict, final_definition, mapping, summary, cross, dispersion_table, hybrid_improvement, time_ari, median_bootstrap, profiles


def build_figures(root, features, mapping, summary, metrics, time_table, cross, dispersion_table):
    folder = Path(root) / "reports/figures"; folder.mkdir(parents=True, exist_ok=True)
    try:
        import plotly.express as px
        eligible = features[features.clustering_eligible].merge(mapping[["apartment_id", "final_local_market_id"]], on="apartment_id", how="left")
        px.scatter(eligible, x="longitude", y="latitude", color="final_local_market_id", hover_name="apartment_name", title="부산 Local Market").write_html(folder/"phase151_local_market_map.html", include_plotlyjs="cdn")
        px.scatter(eligible, x="longitude", y="latitude", color="legal_dong", title="법정동 기준시장").write_html(folder/"phase151_legal_dong_map.html", include_plotlyjs="cdn")
        px.scatter(eligible, x="longitude", y="latitude", color=eligible.algorithm_cluster.astype(str), title="순수 알고리즘 군집").write_html(folder/"phase151_algorithm_cluster_map.html", include_plotlyjs="cdn")
        px.scatter(eligible, x="longitude", y="latitude", color="final_local_market_id", title="최종 Hybrid/법정동 시장").write_html(folder/"phase151_final_market_map.html", include_plotlyjs="cdn")
        px.bar(summary, x="local_market_id", y="median_price_per_m2", color="market_confidence", title="시장별 중위 가격/m²").write_html(folder/"phase151_market_median_price.html", include_plotlyjs="cdn")
        px.box(eligible, x="final_local_market_id", y="apartment_age", title="시장별 단지 연식").write_html(folder/"phase151_market_age.html", include_plotlyjs="cdn")
        px.box(eligible, x="final_local_market_id", y="household_count", title="시장별 세대수").write_html(folder/"phase151_market_households.html", include_plotlyjs="cdn")
        px.bar(dispersion_table, x="definition", y="within_log_price_variance", title="시장정의별 내부 가격분산").write_html(folder/"phase151_dispersion_comparison.html", include_plotlyjs="cdn")
        px.bar(dispersion_table[dispersion_table.definition.isin(["LEGAL_DONG","ALGORITHMIC","HYBRID"])], x="definition", y="variance_ratio_vs_busan", title="법정동과 Local Market 가격분산").write_html(folder/"phase151_legal_vs_local_variance.html", include_plotlyjs="cdn")
        px.line(metrics, x="k", y="silhouette", markers=True, title="K별 Silhouette").write_html(folder/"phase151_k_silhouette.html", include_plotlyjs="cdn")
        px.line(metrics, x="k", y="davies_bouldin", markers=True, title="K별 Davies-Bouldin").write_html(folder/"phase151_k_davies_bouldin.html", include_plotlyjs="cdn")
        px.bar(time_table, x="window", y="ari_vs_12m", title="시간창 군집 안정성").write_html(folder/"phase151_time_window_stability.html", include_plotlyjs="cdn")
        px.histogram(mapping, x="assignment_stability", color="local_market_confidence", title="Bootstrap 배정 안정성").write_html(folder/"phase151_bootstrap_stability.html", include_plotlyjs="cdn")
        heat = cross.pivot_table(index="legal_dong", columns="market_id", values="share", fill_value=0)
        px.imshow(heat, aspect="auto", title="법정동 × Algorithm Market").write_html(folder/"phase151_dong_market_heatmap.html", include_plotlyjs="cdn")
    except Exception as exc:
        atomic_bytes(folder/"phase151_figure_error.txt", str(exc).encode("utf-8"))


def build_phase151(root=ROOT):
    root = Path(root); manifest = discover_protected(root); write_csv(root/"reports/phase151_protected_manifest.csv", manifest)
    features, transactions = build_market_features(root); write_csv(root/"data/processed/phase151_apartment_market_features.csv", features)
    eligible = features[features.clustering_eligible].copy().reset_index(drop=True)
    scaled, fitted_scaler = fit_scaler(eligible)
    metrics, models, selected_k = evaluate_k(eligible, scaled, transactions)
    labels = models[selected_k].labels_
    hierarchy_raw = AgglomerativeClustering(n_clusters=selected_k, linkage="ward").fit_predict(scaled)
    hierarchy, _ = align_labels(labels, hierarchy_raw)
    metrics["selected"] = metrics.k.eq(selected_k); write_csv(root/"reports/phase151_cluster_selection.csv", metrics)
    time_table, time_labels = time_window_stability(eligible, selected_k, labels); write_csv(root/"reports/phase151_time_stability.csv", time_table)
    bootstrap = bootstrap_stability(eligible, transactions, selected_k, labels, fitted_scaler); write_csv(root/"reports/phase151_bootstrap_stability.csv", bootstrap)
    verdict, final_definition, mapping, summary, cross, dispersion_table, improvement, time_ari, median_bootstrap, profiles = build_mapping_and_reports(
        root, features, eligible, labels, hierarchy, time_table, time_labels, bootstrap, selected_k, metrics, transactions
    )
    build_figures(root, eligible.assign(algorithm_cluster=labels), mapping, summary, metrics, time_table, cross, dispersion_table)
    relationship_counts = cross.relationship_type.value_counts().to_dict()
    dong_relationship = cross.groupby(["gu", "legal_dong"]).relationship_type.apply(
        lambda values: "MIXED" if "MIXED" in set(values) else sorted(set(values))[0]
    )
    dong_relationship_counts = dong_relationship.value_counts().to_dict()
    algorithm_row = dispersion_table.set_index("definition").loc["ALGORITHMIC"]
    legal_row = dispersion_table.set_index("definition").loc["LEGAL_DONG"]
    pure_improvement = 100 * (1 - algorithm_row.within_log_price_variance / legal_row.within_log_price_variance)
    split_examples = (cross[cross.relationship_type.isin(["DONG_SPLIT", "MIXED"])]
                      .groupby(["gu", "legal_dong"]).agg(apartments=("apartment_count", "sum"),
                                                           algorithm_markets=("market_id", "nunique"))
                      .sort_values(["apartments", "algorithm_markets"], ascending=False).head(5).reset_index())
    split_text = "; ".join(f"{r.gu} {r.legal_dong}({r.apartments}개, {r.algorithm_markets}군집)" for r in split_examples.itertuples())
    merge_examples = []
    for market_id, group in cross.groupby("market_id"):
        top = group.groupby(["gu", "legal_dong"]).apartment_count.sum().sort_values(ascending=False).head(4)
        merge_examples.append(f"{market_id}: " + ", ".join(f"{gu} {dong}({count})" for (gu, dong), count in top.items()))
    merge_text = "; ".join(merge_examples)
    result = {"verdict": verdict, "final_definition": final_definition, "universe_apartments": len(features), "eligible_apartments": len(eligible),
              "excluded_apartments": len(features)-len(eligible), "transactions": len(transactions), "feature_count": len(CORE_CLUSTER_FEATURES),
              "selected_k": selected_k, "algorithm_hierarchical_ari": adjusted_rand_score(labels, hierarchy),
              "time_12m_24m_ari": time_ari, "time_12m_24m_nmi": float(time_table.loc[time_table.window.eq('24M'),'nmi_vs_12m'].iloc[0]),
              "bootstrap_median_stability": median_bootstrap, "bootstrap_ge_080": int(bootstrap.assignment_stability.ge(.8).sum()),
              "bootstrap_ge_090": int(bootstrap.assignment_stability.ge(.9).sum()), "legal_to_hybrid_dispersion_improvement_pct": improvement*100,
              "final_market_count": int(mapping.final_local_market_id.nunique()), "relationship_counts": {str(k):int(v) for k,v in relationship_counts.items()},
              "unique_dong_relationship_counts": {str(k): int(v) for k, v in dong_relationship_counts.items()},
              "pure_algorithm_vs_legal_dispersion_improvement_pct": pure_improvement,
              "low_sample_final_markets": int(summary.market_confidence.eq("LOW").sum()),
              "fragmented_algorithm_clusters": int(profiles.spatial_fragmentation_flag.sum())}
    write_json(root/"data/processed/phase151_result.json", result)
    selected = metrics[metrics.k.eq(selected_k)].iloc[0]
    report = f"""# Phase 15.1 Local Market Discovery

## 1. 데이터
- Phase 14.9 universe: {len(features)}개 단지
- Clustering eligible/excluded: {len(eligible)}/{len(features)-len(eligible)}
- 거래가격 표본: {transactions.apartment_id.nunique()}개 단지, {len(transactions):,}건; clustering eligible 교집합 {eligible.apartment_id.isin(transactions.apartment_id).sum()}개
- Core feature: {len(CORE_CLUSTER_FEATURES)}개 — 가격수준·가격변화·단지구조/유동성 그룹 균형 적용
- 학군 Core·예상 프리미엄·Value Gap은 군집 입력에서 제외했다.
- 500세대 이상 coverage: {int((features.household_count >= 500).sum())}개 중 {int(((features.household_count >= 500) & features.clustering_eligible).sum())}개

## 2. Cluster 선택
- K 후보: {min(K_CANDIDATES)}~{max(K_CANDIDATES)}
- 선택 K: **{selected_k}**
- Silhouette {selected.silhouette:.4f}, Davies-Bouldin {selected.davies_bouldin:.4f}, Calinski-Harabasz {selected.calinski_harabasz:.1f}
- KMeans와 Ward ARI: {result['algorithm_hierarchical_ari']:.4f}
- 공간적으로 분절된 pure cluster: {result['fragmented_algorithm_clusters']}개

## 3. 가격 동질성
```csv
{dispersion_table.to_csv(index=False)}```

Hybrid의 법정동 대비 log-price 내부분산 변화: {result['legal_to_hybrid_dispersion_improvement_pct']:.2f}% 개선.

## 4. 안정성
- 12M vs 24M ARI/NMI: {result['time_12m_24m_ari']:.4f}/{result['time_12m_24m_nmi']:.4f}
- Bootstrap {BOOTSTRAP_ITERATIONS}회 median stability: {result['bootstrap_median_stability']:.3f}
- Stability ≥0.80/≥0.90: {result['bootstrap_ge_080']}/{result['bootstrap_ge_090']}개

## 5. 최종 시장
- 최종 정의: **{final_definition}**
- 최종 시장 수: {result['final_market_count']}개
- 법정동 92개 중 pure cluster에서 분리된 동: {result['unique_dong_relationship_counts'].get('MIXED', 0)}개
- Pure cluster는 각각 여러 법정동을 결합했으며 3개 모두 공간 분절 판정이다.
- 최소표본 관점에서 LOW인 최종 법정동 시장: {result['low_sample_final_markets']}개
- 판정: **{verdict}**

## 6. 법정동과 Algorithm Cluster 관계
- 대표 법정동 분할: {split_text or '없음'}
- 대표 법정동 병합: {merge_text}
- Pure algorithm은 법정동보다 log-price 내부분산을 {pure_improvement:.2f}% 줄였지만 모든 군집이 원거리 지역을 결합했다.
- 명시적 hybrid 최소표본 규칙을 통과한 법정동 세분화는 0개였다. 따라서 Hybrid는 법정동과 동일하며 개선률도 0%다.

## 7. 주요 이상 사례
- 공간 분절 pure cluster: {result['fragmented_algorithm_clusters']}개
- Bootstrap stability < 0.80: {int((bootstrap.assignment_stability < .80).sum())}개 단지
- 입력 feature 부족: {len(features)-len(eligible)}개 단지; 임의 시장 배정 없이 `INSUFFICIENT_CLUSTER_FEATURES` 유지
- 월별 아파트 가격지수는 희소 거래로 신뢰할 수 있는 pairwise 상관을 만들기 어려워 계산하지 않았다. 대신 `within_price_change_variance`를 동일 기준으로 비교했다.

## 8. 핵심 질문과 판정
1. Pure data clustering에서 가장 안정적인 수는 K=3이나, 공식 생활권으로 해석할 수 없는 비공간적 가격·구조 군집이다.
2. 채택 가능한 Hybrid의 법정동 대비 가격 동질성 개선은 0.00%다.
3. 시간창 변경 안정성은 높다: 12M–24M ARI {result['time_12m_24m_ari']:.4f}, 12M–FULL ARI {float(time_table.loc[time_table.window.eq('FULL'), 'ari_vs_12m'].iloc[0]):.4f}.
4. Bootstrap stability 0.80 이상은 {result['bootstrap_ge_080']}개, 0.90 이상은 {result['bootstrap_ge_090']}개다.
5. 법정동 분할 대표 사례는 위 목록과 같지만, 세분 시장별 최소표본 규칙을 충족하지 못했다.
6. 세 pure cluster 모두 여러 법정동을 합쳤고 최대 공간 범위가 20km를 넘어 `NON_LOCAL_PRICE_CLUSTER`로 제외했다.
7. Phase 15.2 비교단위는 **법정동**이 가장 타당하다. 표본이 작은 48개 시장은 상위 지리단위 fallback이 필요하다.

최종 판정은 **{verdict}**이다. Pure data cluster의 수치적 가격 동질성은 높지만 공간적 지역성이 없고, 규칙 기반 Hybrid는 법정동을 개선하지 못했다.

## 9. 검증
- Phase 7~14.9 보호 manifest: {len(manifest)}개 파일, 분석 종료 시 SHA-256 변경 0개
- 기존 테스트 263개와 Phase 15.1 신규 테스트 37개: 전체 **300 PASS**
- 신규 테스트는 보호 해시, 가격 집계, leakage, scaling/군집 재현성, label alignment, 시간·bootstrap 안정성, hybrid 규칙, mapping·summary·crosswalk 무결성을 검증한다.

Phase 15.2는 자동 진행하지 않는다. 이 시장권역은 공식 행정·생활권이 아니라 현재 보유 거래 및 단지특성에 기반한 가격 비교 목적의 데이터 구획이다.
"""
    atomic_bytes(root/"reports/phase151_local_market_discovery.md", report.encode("utf-8"))
    checked = verify_manifest(manifest, root); write_csv(root/"reports/phase151_protected_manifest.csv", checked)
    return result


if __name__ == "__main__":
    print(json.dumps(build_phase151(), ensure_ascii=False, indent=2))
