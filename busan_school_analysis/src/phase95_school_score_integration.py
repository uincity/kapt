"""Phase 9.5: join frozen Phase 7 school paths to frozen Phase 9 demand scores."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, write_csv, write_json, write_parquet

APARTMENT_ROOT = ROOT.parent / "busan_apartment_analysis"
PHASE7_SNAPSHOT = "data/snapshots/school_scores_2026_phase7_final.parquet"
PHASE8_SNAPSHOT = "data/snapshots/phase8_baseline_benchmark.json"
PHASE9_SCORES = "data/processed/phase9_elementary_demand_scores.parquet"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase95_input_hashes(root=ROOT) -> dict:
    root = Path(root)
    paths = [PHASE7_SNAPSHOT, PHASE8_SNAPSHOT, PHASE9_SCORES]
    return {path: file_sha256(root / path) for path in paths}


def _group(e, m, e_cutoff, m_cutoff):
    if pd.isna(e) or pd.isna(m):
        return "UNCLASSIFIED_MISSING"
    return ("HIGH_E_" if e >= e_cutoff else "LOW_E_") + ("HIGH_M" if m >= m_cutoff else "LOW_M")


def _primary_complex_ids(root: Path) -> set[str]:
    scores = pd.read_parquet(root / PHASE7_SNAPSHOT)
    trades = pd.read_parquet(APARTMENT_ROOT / "data/interim/trade_matched.parquet")
    end = pd.to_datetime(trades.deal_date).max()
    start = end - pd.DateOffset(months=12) + pd.Timedelta(days=1)
    traded = set(trades.loc[pd.to_datetime(trades.deal_date).between(start, end), "internal_complex_id"].dropna())
    mask = scores.households.ge(500) & scores.school_zone_score.notna() & scores.school_score_quality.eq("HIGH")
    return set(scores.loc[mask & scores.internal_complex_id.isin(traded), "internal_complex_id"])


def build_school_combined(root=ROOT):
    root = Path(root)
    master = pd.read_parquet(root / "data/processed/schools.parquet")
    master = master[master.school_level.eq("elementary")][["school_id", "school_name", "sigungu", "closed", "suspended"]].copy()
    master = master.rename(columns={"school_id": "school_id", "school_name": "school_name", "sigungu": "district"})
    e = pd.read_parquet(root / PHASE9_SCORES)[["elementary_school_id", "elementary_school_name", "elementary_demand_score", "elementary_demand_percentile", "elementary_demand_rank", "demand_cluster_name", "demand_score_quality"]]
    e = e.rename(columns={"elementary_school_id": "school_id", "elementary_school_name": "phase9_school_name", "demand_cluster_name": "elementary_cluster"})
    m = pd.read_parquet(root / "data/processed/elementary_feeder_scores_2026.parquet")[["elementary_school_id", "elementary_school_name", "elementary_feeder_score", "feeder_score_status"]]
    m = m.rename(columns={"elementary_school_id": "school_id", "elementary_school_name": "phase7_school_name", "elementary_feeder_score": "phase7_school_score"})
    if e.school_id.duplicated().any() or m.school_id.duplicated().any() or master.school_id.duplicated().any():
        raise ValueError("Phase 9.5 school ID must be unique")
    out = master.merge(e, on="school_id", how="outer", validate="one_to_one").merge(m, on="school_id", how="outer", validate="one_to_one")
    out["school_name"] = out.school_name.fillna(out.phase9_school_name).fillna(out.phase7_school_name)
    out["elementary_demand_score"] = pd.to_numeric(out.elementary_demand_score, errors="coerce")
    out["phase7_school_score"] = pd.to_numeric(out.phase7_school_score, errors="coerce")
    out["phase7_school_percentile"] = out.phase7_school_score.rank(pct=True, method="average") * 100
    out["E01"] = out.elementary_demand_score / 100
    out["M01"] = out.phase7_school_score / 100
    out["EM_interaction"] = out.E01 * out.M01
    out["phase9_data_status"] = np.where(out.elementary_demand_score.notna(), "AVAILABLE", "ELEMENTARY_DEMAND_MISSING_API")
    out["phase7_data_status"] = np.where(out.phase7_school_score.notna(), "AVAILABLE", "PHASE7_PATH_MISSING")
    out["combined_data_status"] = np.select(
        [out.elementary_demand_score.notna() & out.phase7_school_score.notna(), out.elementary_demand_score.notna(), out.phase7_school_score.notna()],
        ["BOTH", "E_ONLY", "M_ONLY"], default="BOTH_MISSING")
    both = out.combined_data_status.eq("BOTH")
    e_cutoff = out.loc[both, "elementary_demand_score"].quantile(.75)
    m_cutoff = out.loc[both, "phase7_school_score"].quantile(.75)
    out["school_path_group"] = [_group(a, b, e_cutoff, m_cutoff) for a, b in zip(out.elementary_demand_score, out.phase7_school_score)]
    for top in (10, 20, 30):
        q = 1 - top / 100
        ec, mc = out.loc[both, "elementary_demand_score"].quantile(q), out.loc[both, "phase7_school_score"].quantile(q)
        out[f"school_path_group_top{top}"] = [_group(a, b, ec, mc) for a, b in zip(out.elementary_demand_score, out.phase7_school_score)]
    columns = ["school_id", "school_name", "district", "elementary_demand_score", "elementary_demand_percentile", "elementary_cluster",
               "phase7_school_score", "phase7_school_percentile", "E01", "M01", "EM_interaction", "school_path_group",
               "phase9_data_status", "phase7_data_status", "combined_data_status", "elementary_demand_rank", "demand_score_quality",
               "feeder_score_status", "closed", "suspended", "school_path_group_top10", "school_path_group_top20", "school_path_group_top30"]
    return out[columns].sort_values(["combined_data_status", "school_id"]).reset_index(drop=True), {"e_cutoff": e_cutoff, "m_cutoff": m_cutoff}


def build_apartment_features(combined: pd.DataFrame, root=ROOT):
    root = Path(root)
    detail = pd.read_parquet(root / "data/processed/busan_apartment_school_score_detail_2026.parquet")
    mapped = detail[detail.elementary_school_id.notna() & detail.eligible_for_school_score.fillna(False)].drop_duplicates(["internal_complex_id", "elementary_school_id"]).copy()
    school = combined.rename(columns={"school_id": "elementary_school_id"})
    mapped = mapped.merge(school[["elementary_school_id", "elementary_demand_score", "elementary_cluster", "school_path_group", "phase9_data_status"]], on="elementary_school_id", how="left", validate="many_to_one")
    def values(series):
        return sorted(set(series.dropna().astype(str)))
    agg = mapped.groupby("internal_complex_id").agg(
        mapped_elementary_count=("elementary_school_id", "nunique"),
        E_available_count=("elementary_demand_score", "count"),
        E_mean=("elementary_demand_score", "mean"), E_max=("elementary_demand_score", "max"), E_min=("elementary_demand_score", "min"),
        elementary_clusters=("elementary_cluster", values), school_path_groups=("school_path_group", values),
        mapped_elementary_school_ids=("elementary_school_id", values)).reset_index()
    agg["phase9_coverage_status"] = np.select([agg.E_available_count.eq(0), agg.E_available_count.lt(agg.mapped_elementary_count)], ["MISSING", "PARTIAL"], default="COMPLETE")
    scores = pd.read_parquet(root / PHASE7_SNAPSHOT)
    out = scores.merge(agg, on="internal_complex_id", how="left", validate="one_to_one")
    out["phase7_school_score"] = out.school_zone_score
    out["elementary_demand_score"] = out.E_mean
    out["E01"] = out.elementary_demand_score / 100
    out["M01"] = out.phase7_school_score / 100
    out["EM_interaction"] = out.E01 * out.M01
    out["phase9_missing_flag"] = out.phase9_coverage_status.fillna("MISSING").ne("COMPLETE")
    return out


def _correlations(combined):
    rows = []
    both = combined.dropna(subset=["elementary_demand_score", "phase7_school_score"])
    for scope, groups in [("BUSAN", [("ALL", both)]), ("DISTRICT", list(both.groupby("district"))), ("CLUSTER", list(both.groupby("elementary_cluster")))]:
        for name, group in groups:
            rows.append({"scope": scope, "group": name, "schools": len(group),
                         "pearson": group.elementary_demand_score.corr(group.phase7_school_score),
                         "spearman": group.elementary_demand_score.corr(group.phase7_school_score, method="spearman")})
    return pd.DataFrame(rows)


def build_phase95(root=ROOT):
    root = Path(root); before = phase95_input_hashes(root)
    combined, cutoffs = build_school_combined(root)
    apartments = build_apartment_features(combined, root)
    primary_ids = _primary_complex_ids(root)
    valid_map = pd.read_parquet(root / "data/processed/busan_apartment_school_score_detail_2026.parquet")
    valid_map = valid_map[valid_map.elementary_school_id.notna() & valid_map.eligible_for_school_score.fillna(False)].drop_duplicates(["internal_complex_id", "elementary_school_id"])
    counts = valid_map.groupby("elementary_school_id").agg(linked_apartment_count=("internal_complex_id", "nunique"), linked_households=("households", "max")).reset_index()
    c500 = valid_map[valid_map.households.ge(500)].groupby("elementary_school_id").internal_complex_id.nunique().rename("500plus_apartment_count")
    cp = valid_map[valid_map.internal_complex_id.isin(primary_ids)].groupby("elementary_school_id").internal_complex_id.nunique().rename("primary_apartment_count")
    audit = combined.merge(counts.rename(columns={"elementary_school_id": "school_id"}), on="school_id", how="left").merge(c500.rename_axis("school_id").reset_index(), on="school_id", how="left").merge(cp.rename_axis("school_id").reset_index(), on="school_id", how="left")
    for col in ["linked_apartment_count", "500plus_apartment_count", "primary_apartment_count"]: audit[col] = audit[col].fillna(0).astype(int)
    audit["E"] = audit.elementary_demand_score; audit["M"] = audit.phase7_school_score
    audit["E_rank_busan"] = audit.E.rank(ascending=False, method="min"); audit["M_rank_busan"] = audit.M.rank(ascending=False, method="min")
    audit["E_rank_district"] = audit.groupby("district").E.rank(ascending=False, method="min"); audit["M_rank_district"] = audit.groupby("district").M.rank(ascending=False, method="min")
    ranking = audit[audit.school_path_group.eq("HIGH_E_HIGH_M")].copy()
    ranking = ranking.rename(columns={"elementary_cluster": "cluster"})
    cross = combined.dropna(subset=["elementary_cluster", "phase7_school_score"]).groupby("elementary_cluster").agg(school_count=("school_id", "size"), mean_M=("phase7_school_score", "mean"), median_M=("phase7_school_score", "median"), high_M_count=("school_path_group", lambda x: x.astype(str).str.endswith("HIGH_M").sum())).reset_index()
    representatives = combined.dropna(subset=["elementary_cluster", "phase7_school_score"]).sort_values(["elementary_cluster", "phase7_school_score"], ascending=[True, False]).groupby("elementary_cluster").head(10)
    cross = cross.merge(representatives.groupby("elementary_cluster").school_name.agg(lambda x: "; ".join(x)).rename("representative_high_M_schools"), on="elementary_cluster", how="left")
    write_parquet(root / "data/processed/phase95_elementary_middle_combined.parquet", combined)
    write_parquet(root / "data/processed/phase95_apartment_school_features.parquet", apartments)
    write_csv(root / "reports/phase95_school_score_linkage_audit.csv", audit)
    write_csv(root / "reports/phase95_high_e_high_m_schools.csv", ranking[["school_name", "district", "E", "E_rank_busan", "E_rank_district", "M", "M_rank_busan", "M_rank_district", "EM_interaction", "cluster", "linked_apartment_count", "500plus_apartment_count"]])
    write_csv(root / "reports/phase95_cluster_middle_cross_table.csv", cross)
    sensitivity=[]
    for top in (10,20,25,30):
        col="school_path_group" if top==25 else f"school_path_group_top{top}"
        counts=combined[col].value_counts()
        sensitivity.append({"high_threshold_top_pct":top,**{group:int(counts.get(group,0)) for group in ["HIGH_E_HIGH_M","HIGH_E_LOW_M","LOW_E_HIGH_M","LOW_E_LOW_M","UNCLASSIFIED_MISSING"]}})
    write_csv(root/"reports/phase95_threshold_sensitivity.csv",pd.DataFrame(sensitivity))
    coverage=[]
    for scope,mask in [("ALL_ELEMENTARY",pd.Series(True,index=audit.index)),("LINKED_500PLUS",audit["500plus_apartment_count"].gt(0)),("LINKED_PHASE8_PRIMARY",audit.primary_apartment_count.gt(0))]:
        counts=audit.loc[mask,"combined_data_status"].value_counts(); total=int(mask.sum())
        coverage.append({"scope":scope,"schools":total,"both":int(counts.get("BOTH",0)),"e_only":int(counts.get("E_ONLY",0)),"m_only":int(counts.get("M_ONLY",0)),"both_missing":int(counts.get("BOTH_MISSING",0)),"both_coverage_pct":int(counts.get("BOTH",0))/total*100 if total else np.nan})
    write_csv(root/"reports/phase95_linkage_coverage_summary.csv",pd.DataFrame(coverage))
    corr = _correlations(combined); write_csv(root / "reports/phase95_em_correlations.csv", corr)
    write_json(root / "data/snapshots/phase95_input_hashes.json", {"input_hashes": before, "cutoffs": cutoffs})
    if phase95_input_hashes(root) != before: raise ValueError("Phase 7/8/9 immutable input changed during Phase 9.5")
    status = combined.combined_data_status.value_counts().to_dict()
    return {"schools": len(combined), "both": int(status.get("BOTH", 0)), "e_only": int(status.get("E_ONLY", 0)), "m_only": int(status.get("M_ONLY", 0)), "both_missing": int(status.get("BOTH_MISSING", 0)), "high_e_high_m": len(ranking), "phase8_primary_complexes": len(primary_ids)}
