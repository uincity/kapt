"""Phase 11: reverse-aggregate frozen elementary demand over assignment edges.

The aggregates are descriptions of connected school sets.  No edge is interpreted
as an assignment probability and no equal/proportional weights are manufactured.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, atomic_bytes, write_csv, write_json, write_parquet

RELATION_PATH = "data/processed/busan_elementary_middle_relation_2026.parquet"
DEMAND_PATH = "data/processed/phase9_elementary_demand_scores.parquet"
MIDDLE_SCORE_PATH = "data/processed/middle_school_scores.parquet"
SCHOOL_MASTER_PATH = "data/processed/schools.parquet"
IMMUTABLE_INPUTS = (
    "data/snapshots/school_scores_2026_phase7_final.parquet",
    "data/snapshots/phase8_baseline_benchmark.json",
    DEMAND_PATH,
    "data/processed/phase95_elementary_middle_combined.parquet",
    "data/processed/phase10_common_sample.parquet",
    "reports/phase10_incremental_value_summary.csv",
    RELATION_PATH,
    MIDDLE_SCORE_PATH,
)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase11_input_hashes(root=ROOT) -> dict[str, str]:
    root = Path(root)
    return {name: file_sha256(root / name) for name in IMMUTABLE_INPUTS}


def classify_assignment_edges(relations: pd.DataFrame) -> pd.DataFrame:
    """Keep all source rows and attach a conservative analytical edge class."""
    out = relations.copy()
    active = out["relation_status"].eq("ACTIVE") & out["middle_school_id"].notna()
    confirmed = active & (out["relation_type"].eq("EXACT") | out["guaranteed_assignment"].fillna(False))
    possible = active & ~confirmed
    ambiguous = ~active & out["relation_status"].astype(str).str.contains("AMBIGUOUS|UNRESOLVED", regex=True)
    out["phase11_edge_class"] = np.select(
        [confirmed, possible, ambiguous], ["CONFIRMED", "POSSIBLE", "AMBIGUOUS"], default="EXCLUDED"
    )
    out["used_in_confirmed_aggregate"] = out.phase11_edge_class.eq("CONFIRMED")
    out["used_in_broad_aggregate"] = out.phase11_edge_class.isin(["CONFIRMED", "POSSIBLE"])
    out["probability_used"] = False
    return out


def _set_stats(frame: pd.DataFrame, prefix: str) -> dict:
    values = frame.drop_duplicates("elementary_school_id")["elementary_demand_score"].dropna().astype(float)
    result = {f"{prefix}_E_{name}": np.nan for name in ("mean", "median", "max", "min", "top25_mean")}
    result[f"{prefix}_school_count"] = int(frame.elementary_school_id.nunique())
    result[f"{prefix}_scored_school_count"] = int(values.size)
    if values.empty:
        return result
    cutoff = values.quantile(.75)
    result.update({
        f"{prefix}_E_mean": values.mean(), f"{prefix}_E_median": values.median(),
        f"{prefix}_E_max": values.max(), f"{prefix}_E_min": values.min(),
        f"{prefix}_E_top25_mean": values[values.ge(cutoff)].mean(),
    })
    return result


def build_middle_catchment(relations: pd.DataFrame, demand: pd.DataFrame,
                           middle_scores: pd.DataFrame, master: pd.DataFrame):
    edges = classify_assignment_edges(relations)
    ecols = ["elementary_school_id", "elementary_school_name", "elementary_demand_score",
             "elementary_demand_percentile", "demand_cluster_name"]
    edges = edges.merge(demand[ecols], on="elementary_school_id", how="left", validate="many_to_one",
                        suffixes=("", "_phase9"))
    middle_master = master[master.school_level.eq("middle")][["school_id", "school_name", "sigungu", "education_office", "closed", "suspended"]].copy()
    middle_master = middle_master.rename(columns={"school_id": "middle_school_id", "school_name": "middle_school_name", "sigungu": "district"})
    qcols = ["middle_school_id", "middle_school_score", "score_reference_year", "graduates_total",
             "weighted_graduates", "available_year_count", "observation_years", "score_stability",
             "sample_warning", "ranking_coverage", "score_status"]
    middle = middle_master.merge(middle_scores[qcols], on="middle_school_id", how="left", validate="one_to_one")
    rows = []
    for row in middle.itertuples(index=False):
        group = edges[edges.middle_school_id.eq(row.middle_school_id)]
        confirmed = group[group.used_in_confirmed_aggregate]
        broad = group[group.used_in_broad_aggregate]
        record = row._asdict()
        record.update(_set_stats(confirmed, "confirmed"))
        record.update(_set_stats(broad, "broad"))
        record["possible_elementary_count"] = int(group.loc[group.phase11_edge_class.eq("POSSIBLE"), "elementary_school_id"].nunique())
        record["ambiguous_elementary_count"] = int(group.loc[group.phase11_edge_class.eq("AMBIGUOUS"), "elementary_school_id"].nunique())
        record["excluded_edge_count"] = int(group.phase11_edge_class.isin(["AMBIGUOUS", "EXCLUDED"]).sum())
        record["total_elementary_count"] = int(broad.elementary_school_id.nunique())
        record["connected_elementary_schools"] = "; ".join(sorted(set(broad.elementary_school_name.dropna().astype(str))))
        rows.append(record)
    out = pd.DataFrame(rows)
    out["catchment_uncertainty_gap"] = (out.broad_E_median - out.confirmed_E_median).abs()
    valid_gap = out.catchment_uncertainty_gap.dropna()
    low, high = (valid_gap.quantile(.33), valid_gap.quantile(.67)) if len(valid_gap) else (np.nan, np.nan)
    out["assignment_uncertainty_grade"] = np.select(
        [out.confirmed_school_count.eq(0), out.catchment_uncertainty_gap.ge(high), out.catchment_uncertainty_gap.ge(low)],
        ["HIGH_NO_CONFIRMED", "HIGH", "MEDIUM"], default="LOW")
    out["representative_catchment_demand"] = out.confirmed_E_median.combine_first(out.broad_E_median)
    out["representative_basis"] = np.where(out.confirmed_E_median.notna(), "CONFIRMED_MEDIAN", "BROAD_MEDIAN_FALLBACK")
    out["data_quality_status"] = np.select(
        [out.total_elementary_count.eq(0), out.broad_scored_school_count.lt(out.total_elementary_count), out.confirmed_school_count.eq(0)],
        ["NO_ACTIVE_EDGE", "PARTIAL_ELEMENTARY_DEMAND", "NO_CONFIRMED_EDGE"], default="COMPLETE")
    return out.sort_values("middle_school_id").reset_index(drop=True), edges, {"uncertainty_low": low, "uncertainty_high": high}


def _correlations(middle: pd.DataFrame) -> pd.DataFrame:
    rows = []
    features = ["confirmed_E_mean", "confirmed_E_median", "confirmed_E_max", "confirmed_E_top25_mean",
                "broad_E_mean", "broad_E_median", "broad_E_max", "broad_E_top25_mean"]
    scopes = [("BUSAN", "ALL", middle)]
    scopes += [("EDUCATION_OFFICE", str(name), g) for name, g in middle.groupby("education_office")]
    scopes += [("DISTRICT", str(name), g) for name, g in middle.groupby("district")]
    for scope, group_name, group in scopes:
        for feature in features:
            d = group[["middle_school_score", feature]].dropna()
            rows.append({"scope": scope, "group": group_name, "catchment_feature": feature, "n": len(d),
                         "pearson": d.middle_school_score.corr(d[feature]) if len(d) > 1 else np.nan,
                         "spearman": d.middle_school_score.corr(d[feature], method="spearman") if len(d) > 1 else np.nan})
    return pd.DataFrame(rows)


def _matrix_and_sensitivity(middle: pd.DataFrame):
    valid = middle.dropna(subset=["middle_school_score", "representative_catchment_demand"]).copy()
    sensitivities = []
    primary = None
    for top in (10, 20, 25, 30):
        q = 1 - top / 100
        q_cut, d_cut = valid.middle_school_score.quantile(q), valid.representative_catchment_demand.quantile(q)
        temp = valid.copy()
        temp["quality_high"] = temp.middle_school_score.ge(q_cut)
        temp["demand_high"] = temp.representative_catchment_demand.ge(d_cut)
        temp["quality_demand_group"] = np.select(
            [temp.quality_high & temp.demand_high, temp.quality_high, temp.demand_high],
            ["HIGH_QUALITY_HIGH_DEMAND", "HIGH_QUALITY_LOW_DEMAND", "LOW_QUALITY_HIGH_DEMAND"],
            default="LOW_QUALITY_LOW_DEMAND")
        for name, g in temp.groupby("quality_demand_group"):
            sensitivities.append({"top_threshold_pct": top, "quality_cutoff": q_cut, "demand_cutoff": d_cut,
                                  "quality_demand_group": name, "middle_school_count": len(g)})
        if top == 25:
            primary = temp
    matrix = primary.copy()
    broad_cut = middle.broad_E_median.dropna().quantile(.75)
    confirmed_cut = middle.confirmed_E_median.dropna().quantile(.75)
    matrix["catchment_robustness"] = np.select(
        [matrix.confirmed_E_median.notna() & matrix.confirmed_E_median.ge(confirmed_cut) & matrix.broad_E_median.ge(broad_cut),
         matrix.confirmed_E_median.isna() & matrix.broad_E_median.ge(broad_cut), matrix.confirmed_E_median.isna()],
        ["ROBUST_HIGH_DEMAND", "BROAD_ONLY_HIGH_DEMAND", "CONFIRMED_DATA_INSUFFICIENT"], default="NOT_HIGH_DEMAND")
    return matrix, pd.DataFrame(sensitivities)


def _network(edges: pd.DataFrame, middle: pd.DataFrame) -> pd.DataFrame:
    usable = edges[edges.used_in_broad_aggregate].drop_duplicates(["elementary_school_id", "middle_school_id"])
    # The graph table retains every source edge; inclusion flags determine which
    # edges contribute to degrees and catchment aggregates.
    edge_rows = edges.copy()
    edge_rows["record_type"] = "EDGE"
    edge_rows["node_id"] = pd.NA
    elementary_rows = []
    for school_id, g in usable.groupby("elementary_school_id"):
        quality = pd.to_numeric(g.merge(middle[["middle_school_id", "middle_school_score"]], on="middle_school_id", how="left").middle_school_score, errors="coerce")
        elementary_rows.append({"record_type": "ELEMENTARY_NODE", "node_id": school_id,
            "elementary_school_id": school_id, "elementary_school_name": g.elementary_school_name.iloc[0],
            "candidate_middle_count": g.middle_school_id.nunique(),
            "confirmed_middle_count": g.loc[g.phase11_edge_class.eq("CONFIRMED"), "middle_school_id"].nunique(),
            "possible_middle_count": g.loc[g.phase11_edge_class.eq("POSSIBLE"), "middle_school_id"].nunique(),
            "connected_middle_quality_mean": quality.mean(), "connected_middle_quality_median": quality.median(),
            "connected_middle_quality_max": quality.max(),
            "assignment_uncertainty": g.middle_school_id.nunique() - g.loc[g.phase11_edge_class.eq("CONFIRMED"), "middle_school_id"].nunique()})
    middle_rows = middle.copy()
    middle_rows["record_type"] = "MIDDLE_NODE"; middle_rows["node_id"] = middle_rows.middle_school_id
    middle_rows["degree"] = middle_rows.total_elementary_count
    middle_rows["confirmed_degree"] = middle_rows.confirmed_school_count
    middle_rows["possible_degree"] = middle_rows.possible_elementary_count
    middle_rows["connected_high_E_count"] = 0
    cutoff = edges.elementary_demand_score.dropna().quantile(.75)
    for idx, row in middle_rows.iterrows():
        g = usable[usable.middle_school_id.eq(row.middle_school_id)].drop_duplicates("elementary_school_id")
        middle_rows.loc[idx, "connected_high_E_count"] = int(g.elementary_demand_score.ge(cutoff).sum())
    keep = ["record_type", "node_id", "elementary_school_id", "elementary_school_name", "middle_school_id",
            "middle_school_name_current", "phase11_edge_class", "relation_type", "relation_status",
            "original_relation_type", "original_relation_status", "used_in_confirmed_aggregate", "used_in_broad_aggregate", "probability_used"]
    for col in keep:
        if col not in edge_rows: edge_rows[col] = pd.NA
    nodes = pd.concat([pd.DataFrame(elementary_rows), middle_rows], ignore_index=True, sort=False)
    return pd.concat([nodes, edge_rows[keep]], ignore_index=True, sort=False)


def _write_html_scatter(path: Path, frame: pd.DataFrame, x: str, y: str, title: str, color: str | None = None):
    try:
        import plotly.express as px
        fig = px.scatter(frame, x=x, y=y, color=color, hover_name="middle_school_name", title=title)
        fig.write_html(path, include_plotlyjs="cdn")
    except Exception:
        atomic_bytes(path, ("<html><meta charset='utf-8'><h1>" + title + "</h1>" + frame.to_html(index=False) + "</html>").encode("utf-8"))


def _visuals(root: Path, middle: pd.DataFrame, matrix: pd.DataFrame, network: pd.DataFrame):
    _write_html_scatter(root/"reports/phase11_quality_vs_confirmed_demand.html", middle, "confirmed_E_median", "middle_school_score", "중학교 품질 × 확정 연결 초등 수요", "education_office")
    _write_html_scatter(root/"reports/phase11_quality_vs_broad_demand.html", middle, "broad_E_median", "middle_school_score", "중학교 품질 × 광의 연결 초등 수요", "education_office")
    _write_html_scatter(root/"reports/phase11_uncertainty_scatter.html", middle, "total_elementary_count", "catchment_uncertainty_gap", "배정 연결 수 × 불확실성", "assignment_uncertainty_grade")
    _write_html_scatter(root/"reports/phase11_network_degree.html", middle, "total_elementary_count", "representative_catchment_demand", "중학교 연결 차수 × 통학권 수요", "education_office")
    try:
        import plotly.express as px
        counts = matrix.quality_demand_group.value_counts().rename_axis("group").reset_index(name="schools")
        px.bar(counts, x="group", y="schools", title="중학교 품질·통학권 수요 2×2").write_html(root/"reports/phase11_quality_demand_matrix.html", include_plotlyjs="cdn")
        edge_counts = network[network.record_type.eq("EDGE")].phase11_edge_class.value_counts().rename_axis("edge_class").reset_index(name="edges")
        px.bar(edge_counts, x="edge_class", y="edges", title="초등학교–중학교 이분 네트워크 관계 요약").write_html(root/"reports/phase11_bipartite_network_summary.html", include_plotlyjs="cdn")
    except Exception:
        pass


def build_phase11(root=ROOT):
    root = Path(root); before = phase11_input_hashes(root)
    relations = pd.read_parquet(root/RELATION_PATH)
    demand = pd.read_parquet(root/DEMAND_PATH)
    middle_scores = pd.read_parquet(root/MIDDLE_SCORE_PATH)
    master = pd.read_parquet(root/SCHOOL_MASTER_PATH)
    middle, edges, uncertainty = build_middle_catchment(relations, demand, middle_scores, master)
    correlations = _correlations(middle)
    matrix, sensitivity = _matrix_and_sensitivity(middle)
    network = _network(edges, middle)
    write_parquet(root/"data/processed/phase11_middle_catchment_demand.parquet", middle)
    write_parquet(root/"data/processed/phase11_school_network.parquet", network)
    write_parquet(root/"data/processed/phase11_assignment_edges_audit.parquet", edges)
    write_csv(root/"reports/phase11_middle_quality_demand_matrix.csv", matrix.sort_values(["quality_demand_group", "middle_school_score"], ascending=[True, False]))
    write_csv(root/"reports/phase11_assignment_uncertainty.csv", middle.sort_values(["assignment_uncertainty_grade", "catchment_uncertainty_gap"], ascending=[True, False]))
    write_csv(root/"reports/phase11_quality_demand_correlations.csv", correlations)
    write_csv(root/"reports/phase11_threshold_sensitivity.csv", sensitivity)
    ranking_rows = []
    specs = {"QUALITY_TOP30": "middle_school_score", "CONFIRMED_DEMAND_TOP30": "confirmed_E_median", "BROAD_DEMAND_TOP30": "broad_E_median"}
    for ranking_type, col in specs.items():
        g = middle.nlargest(30, col).copy(); g["ranking_type"] = ranking_type; g["rank"] = range(1, len(g)+1); ranking_rows.append(g)
    high_both = matrix[matrix.quality_demand_group.eq("HIGH_QUALITY_HIGH_DEMAND")].nlargest(30, "middle_school_score").copy()
    high_both["ranking_type"] = "HIGH_QUALITY_HIGH_DEMAND_TOP30"; high_both["rank"] = range(1, len(high_both)+1); ranking_rows.append(high_both)
    rankings = pd.concat(ranking_rows, ignore_index=True)
    ranking_cols=["ranking_type","rank","middle_school_id","middle_school_name","district","education_office","middle_school_score","confirmed_E_median","broad_E_median","confirmed_school_count","possible_elementary_count","total_elementary_count","assignment_uncertainty_grade","connected_elementary_schools"]
    write_csv(root/"reports/phase11_middle_catchment_ranking.csv", rankings[ranking_cols])
    write_csv(root/"reports/phase11_rankings.csv", rankings)
    write_csv(root/"reports/phase11_assignment_edge_class_audit.csv", edges[["elementary_school_id","elementary_school_name","middle_school_id","middle_school_name_current","relation_type","relation_status","original_relation_type","original_relation_status","phase11_edge_class","used_in_confirmed_aggregate","used_in_broad_aggregate","probability_used","override_applied","assignment_share"]])
    _visuals(root, middle, matrix, network)
    after = phase11_input_hashes(root)
    if before != after: raise RuntimeError("An immutable Phase 7-10 input changed during Phase 11")
    snapshot = {"input_hashes": before, "relation_rows": len(relations), "edge_class_counts": edges.phase11_edge_class.value_counts().to_dict(),
                "middle_school_rows": len(middle), "scored_middle_schools": int(middle.middle_school_score.notna().sum()),
                "no_probability_weighting": True, **uncertainty}
    write_json(root/"data/snapshots/phase11_input_hashes.json", snapshot)
    return snapshot
