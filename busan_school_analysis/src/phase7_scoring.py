"""Phase 7 explainable school-zone scoring from preserved official evidence."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .config import ROOT, now, write_csv, write_json, write_parquet, atomic_bytes

RELATION_MAP = {
    "exact": "EXACT", "guaranteed": "EXACT",
    "eligible": "ELIGIBLE", "official_eligibility": "ELIGIBLE",
    "conditional": "CONDITIONAL", "conditional_not_guaranteed": "CONDITIONAL",
    "general_priority": "CONDITIONAL", "preference": "CONDITIONAL",
    "group_only": "GROUP_MEMBERSHIP", "group_membership": "GROUP_MEMBERSHIP",
    "unresolved": "UNRESOLVED",
}


def load_score_config(root=ROOT):
    return yaml.safe_load((Path(root) / "config/school_score.yaml").read_text(encoding="utf-8"))


def normalize_relation_type(value):
    key = str(value or "").strip().lower()
    return RELATION_MAP.get(key, key.upper() if key.upper() in set(RELATION_MAP.values()) else "UNRESOLVED")


def assignment_is_guaranteed(relation_type):
    return normalize_relation_type(relation_type) == "EXACT"


def calculate_feeder_exclusivity(relations, config):
    valid = relations[relations["assignment_reliability_weight"].gt(0)]
    if valid.empty:
        return 0.0
    n = valid["middle_school_id"].nunique()
    total = valid["assignment_reliability_weight"].sum()
    exact = valid.loc[valid.relation_type.eq("EXACT"), "assignment_reliability_weight"].sum() / total
    strong = valid.loc[valid.relation_type.isin(["EXACT", "ELIGIBLE"]), "assignment_reliability_weight"].sum() / total
    concentration = 1.0 / max(n, 1)
    w = config["feeder_exclusivity"]
    return float(np.clip(w["exact_share"] * exact + w["candidate_concentration"] * concentration +
                         w["strong_relation_share"] * strong, 0, 1))


def accessibility_score(distance_m, config):
    if pd.isna(distance_m):
        return np.nan
    for band in config["accessibility_bands"]:
        if band["max_distance_m"] is None or distance_m <= band["max_distance_m"]:
            return float(band["score"])
    return 25.0


def _school_key(value):
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value)).replace("등학교", "").replace("학교", "").replace("여자", "여")


def _names(text, suffix):
    return list(dict.fromkeys(re.findall(rf"[가-힣]+{suffix}", str(text))))


def _parse_seobu_relations(root=ROOT):
    """Parse only rows where the official fixed-layout feeder table exposes both sides."""
    from .parsers.pdf_parser import parse_pdf
    base = Path(root) / "data/raw/education_office/seobu/2025/middle_assignment"
    path = next(iter(base.glob("*초등학교 기준 배정 중학교*.pdf")), None)
    if path is None:
        return pd.DataFrame()
    lines = parse_pdf(path).text.splitlines()
    records = []
    current_group = None
    pending_elementaries = []
    last_elementaries = []
    for line_no, line in enumerate(lines):
        match = re.search(r"(\d+)학교군", line)
        if match:
            current_group = f"{match.group(1)}학교군"
        left, male, female = line[:24], line[24:46], line[46:]
        elementary = [x for x in _names(left, "초") if x not in {"국립초", "사립초"}]
        # The official table omits the suffix in its elementary column.
        if not elementary and line_no >= 5:
            clean = re.sub(r"\d+학교군|\([^)]*\)|\*.*", "", left)
            elementary = [x.strip() + "초" for x in re.split(r"[,，]", clean) if re.fullmatch(r"[가-힣]{2,6}", x.strip())]
        middles = _names(male + " " + female, "중")
        if elementary:
            pending_elementaries.extend(elementary)
            last_elementaries = elementary
        targets = pending_elementaries if middles and pending_elementaries else last_elementaries
        if middles and targets:
            for elementary_name in targets:
                for middle_name in middles:
                    records.append({"data_year": 2025, "education_office": "seobu",
                                    "elementary_school_name": elementary_name,
                                    "middle_school_name": middle_name, "school_group": current_group,
                                    "relation_type": "ELIGIBLE", "source_document": str(path.relative_to(root)),
                                    "source_page_or_section": f"layout line {line_no + 1}",
                                    "source_text": line.strip(), "manual_review": False})
            pending_elementaries = []
    return pd.DataFrame(records).drop_duplicates(["elementary_school_name", "middle_school_name"])


def build_elementary_middle_relations(root=ROOT):
    root = Path(root)
    frames = []
    phase5 = root / "data/interim/haeundae_elementary_middle_validation_2025.parquet"
    if phase5.exists():
        h = pd.read_parquet(phase5)
        if "evidence_source" in h:
            h["source_document"] = h.get("source_document", pd.Series(index=h.index, dtype="object")).fillna(h.evidence_source)
        if "evidence_text" in h:
            h["source_text"] = h.get("source_text", pd.Series(index=h.index, dtype="object")).fillna(h.evidence_text)
        h["relation_type"] = h["assignment_certainty"].map(normalize_relation_type)
        frames.append(h)
    seobu = _parse_seobu_relations(root)
    if not seobu.empty:
        frames.append(seobu)
    relations = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    links = pd.read_parquet(root / "data/processed/busan_schoolzone_school_link_2025.parquet")
    elementary = (links[["school_id", "school_name_current", "education_office_name"]]
                  .dropna(subset=["school_id"]).drop_duplicates("school_id")
                  .rename(columns={"school_id": "elementary_school_id", "school_name_current": "elementary_school_name"}))
    schools = pd.read_parquet(root / "data/processed/schools.parquet")
    middles = schools[schools.school_level.astype(str).str.lower().isin(["중학교", "middle"])].copy()
    middles["_key"] = middles.school_name.map(_school_key)
    relations["_key"] = relations.middle_school_name.map(_school_key)
    middle_lookup = middles[["_key", "school_id"]].drop_duplicates("_key").rename(columns={"school_id": "_matched_middle_id"})
    relations = relations.merge(middle_lookup, on="_key", how="left")
    if "middle_school_id" in relations:
        relations["middle_school_id"] = relations.middle_school_id.fillna(relations._matched_middle_id)
    else:
        relations["middle_school_id"] = relations._matched_middle_id
    relations = relations.drop(columns=["_key", "_matched_middle_id"])
    relations["_elementary_key"] = relations.elementary_school_name.map(_school_key)
    elementary["_elementary_key"] = elementary.elementary_school_name.map(_school_key)
    relations = relations.merge(elementary[["_elementary_key", "elementary_school_id"]], on="_elementary_key", how="left")
    relations = relations.loc[:, ~relations.columns.duplicated()]
    known = set(relations.elementary_school_id.dropna())
    missing = elementary[~elementary.elementary_school_id.isin(known)]
    unresolved = missing.assign(middle_school_id=pd.NA, middle_school_name=pd.NA,
                                relation_type="UNRESOLVED", data_year=2025,
                                source_document=pd.NA, source_text="공식 초등학교별 중학교 관계 미확보",
                                manual_review=True)
    relations = pd.concat([relations, unresolved], ignore_index=True, sort=False)
    config = load_score_config(root)
    relations["relation_type"] = relations.relation_type.map(normalize_relation_type)
    relations["assignment_reliability_weight"] = relations.relation_type.map(config["middle_relation_weights"]).astype(float)
    relations["guaranteed_assignment"] = relations.relation_type.map(assignment_is_guaranteed)
    relations["assignment_data_quality"] = relations.relation_type.map(config["assignment_quality"]).astype(float)
    relations["data_year"] = 2025
    relations["parser_version"] = "phase7-1.0"
    keep = ["data_year", "education_office", "education_office_name", "elementary_school_id",
            "elementary_school_name", "middle_school_id", "middle_school_name", "school_group",
            "relation_type", "assignment_reliability_weight", "guaranteed_assignment",
            "assignment_data_quality", "source_document", "source_page_or_section", "source_text",
            "manual_review", "parser_version"]
    for col in keep:
        if col not in relations:
            relations[col] = pd.NA
    relations = relations[keep].drop_duplicates(["elementary_school_id", "middle_school_id", "relation_type"])
    write_parquet(root / "data/processed/busan_elementary_middle_relation_2025.parquet", relations)
    return relations


def build_feeder_scores(relations, middle_scores, config):
    detail = relations.merge(middle_scores, on="middle_school_id", how="left", suffixes=("", "_score"))
    rows = []
    for elementary_id, group in detail.groupby("elementary_school_id", dropna=False):
        scored = group[group.assignment_reliability_weight.gt(0) & group.middle_school_score.notna()].copy()
        base = group.iloc[0]
        row = {"elementary_school_id": elementary_id, "elementary_school_name": base.elementary_school_name,
               "data_year": 2025, "eligible_middle_count": int(scored.middle_school_id.nunique())}
        for rel, col in [("EXACT", "exact_middle_count"), ("ELIGIBLE", "eligible_count"),
                         ("CONDITIONAL", "conditional_count"), ("GROUP_MEMBERSHIP", "group_only_count")]:
            row[col] = int(group.loc[group.relation_type.eq(rel), "middle_school_id"].nunique())
        if scored.empty:
            row.update({k: np.nan for k in ["best_middle_score", "mean_middle_score", "median_middle_score",
                                             "worst_middle_score", "weighted_middle_score", "feeder_score_std",
                                             "feeder_score_range", "feeder_score_cv", "feeder_uncertainty",
                                             "feeder_exclusivity", "assignment_data_quality", "middle_score_reliability",
                                             "feeder_stability", "elementary_feeder_score"]})
            row.update(feeder_stability_label="UNAVAILABLE", feeder_score_status="UNRESOLVED")
        else:
            scores = scored.middle_school_score.astype(float)
            weights = scored.assignment_reliability_weight.astype(float)
            weighted = float(np.average(scores, weights=weights))
            std = float(scores.std(ddof=0))
            exclusivity = calculate_feeder_exclusivity(scored, config)
            quality = float(np.average(scored.assignment_data_quality, weights=weights))
            warning = scored.sample_warning.astype("boolean").fillna(False).to_numpy(dtype=bool)
            reliability = float(np.average(np.where(warning, .7, 1.0), weights=weights))
            stability = scored.score_stability.dropna()
            stability_value = float(stability.mean() * 100) if len(stability) else np.nan
            stability_label = "UNAVAILABLE" if pd.isna(stability_value) else ("HIGH" if stability_value >= 80 else "MEDIUM" if stability_value >= 60 else "LOW")
            parts = config["elementary_feeder_score"]
            feeder = (parts["weighted_middle_score"] * weighted + parts["worst_middle_score"] * scores.min() +
                      parts["feeder_exclusivity"] * exclusivity * 100 + parts["assignment_data_quality"] * quality)
            row.update(best_middle_score=float(scores.max()), mean_middle_score=float(scores.mean()),
                       median_middle_score=float(scores.median()), worst_middle_score=float(scores.min()),
                       weighted_middle_score=weighted, feeder_score_std=std,
                       feeder_score_range=float(scores.max() - scores.min()),
                       feeder_score_cv=float(std / scores.mean()) if scores.mean() else np.nan,
                       feeder_uncertainty=float(np.clip(std * 2 + (1 - weights.mean()) * 25, 0, 100)),
                       feeder_exclusivity=exclusivity, assignment_data_quality=quality,
                       middle_score_reliability=reliability, feeder_stability=stability_value,
                       feeder_stability_label=stability_label,
                       elementary_feeder_score=float(np.clip(feeder, 0, 100)), feeder_score_status="SCORED")
        rows.append(row)
    return pd.DataFrame(rows), detail


def _haversine(lat1, lon1, lat2, lon2):
    values = [lat1, lon1, lat2, lon2]
    if any(pd.isna(x) for x in values):
        return np.nan
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _grade(percentile, config):
    if pd.isna(percentile): return pd.NA
    for grade, threshold in config["percentile_grades"].items():
        if percentile >= threshold: return grade
    return "E"


def build_apartment_scores(apartment_relations, feeders, schools, detail, config):
    elementary = schools[schools.school_level.astype(str).str.lower().isin(["초등학교", "elementary"])][["school_id", "latitude", "longitude"]].rename(
        columns={"school_id": "elementary_school_id", "latitude": "school_latitude", "longitude": "school_longitude"})
    feeder_columns = [c for c in feeders.columns if c != "elementary_school_name"]
    rel = apartment_relations.merge(feeders[feeder_columns], on="elementary_school_id", how="left")
    rel = rel.merge(elementary, on="elementary_school_id", how="left")
    rel["elementary_distance_m"] = rel.apply(lambda x: _haversine(x.latitude, x.longitude, x.school_latitude, x.school_longitude), axis=1)
    review_coordinate = rel.coordinate_status.eq("REVIEW")
    direct = rel.evidence_types.astype(str).str.contains("OFFICIAL_DIRECT") & rel.direct_match_status.astype(str).eq("CONFIRMED")
    rel["eligible_for_school_score"] = ~review_coordinate | direct
    rows = []
    for apartment_id, group in rel.groupby("internal_complex_id", sort=False):
        base = group.iloc[0]
        group_review = group.coordinate_status.eq("REVIEW")
        valid = group[group.eligible_for_school_score & group.elementary_feeder_score.notna()].drop_duplicates("elementary_school_id")
        row = {c: base.get(c) for c in ["internal_complex_id", "kapt_code", "complex_name", "households", "sigungu", "legal_dong", "is_500plus"]}
        row["manual_review"] = bool(group_review.any() or group.manual_review_link.astype("boolean").fillna(False).any())
        if valid.empty:
            row.update(elementary_school_ids=[], elementary_school_names=[], elementary_school_count=0,
                       nearest_elementary_distance_m=np.nan, mean_elementary_feeder_score=np.nan,
                       best_elementary_feeder_score=np.nan, worst_elementary_feeder_score=np.nan,
                       middle_school_count=0, best_middle_score=np.nan, mean_middle_score=np.nan,
                       worst_middle_score=np.nan, feeder_exclusivity=np.nan, assignment_data_quality=np.nan,
                       elementary_accessibility_score=np.nan, shared_catchment=False, school_zone_score=np.nan,
                       score_quality_focused=np.nan, score_stability_focused=np.nan,
                       school_score_status="REVIEW" if group_review.any() else "UNRESOLVED",
                       school_score_quality="LOW")
        else:
            ids = valid.elementary_school_id.dropna().unique().tolist()
            names = valid.elementary_school_name.dropna().unique().tolist()
            f = valid.elementary_feeder_score.astype(float)
            distance = valid.elementary_distance_m.min()
            access = accessibility_score(distance, config)
            confidence = valid.assignment_data_quality.mean()
            scenarios = {}
            for scenario, weights in config["apartment_scenarios"].items():
                feeder_value = f.mean()
                if scenario == "STABILITY_FOCUSED":
                    feeder_value = (weights["feeder_mean"] * f.mean() + weights["feeder_worst"] * f.min() +
                                    weights["exclusivity"] * valid.feeder_exclusivity.mean() * 100)
                scenarios[scenario] = float(np.clip(weights["feeder"] * feeder_value +
                                                     weights["accessibility"] * access +
                                                     weights["confidence"] * confidence, 0, 100))
            m = detail[detail.elementary_school_id.isin(ids) & detail.middle_school_score.notna()]
            weak = valid.group_only_count.sum() + valid.conditional_count.sum() > 0
            shared = len(ids) > 1 or valid.school_zone_type.astype(str).str.contains("공동|JOINT|SHARED", case=False).any()
            quality = "LOW" if row["manual_review"] else "MEDIUM" if (weak or shared) else "HIGH"
            row.update(elementary_school_ids=ids, elementary_school_names=names, elementary_school_count=len(ids),
                       nearest_elementary_distance_m=float(distance), mean_elementary_feeder_score=float(f.mean()),
                       best_elementary_feeder_score=float(f.max()), worst_elementary_feeder_score=float(f.min()),
                       middle_school_count=int(m.middle_school_id.nunique()),
                       best_middle_score=float(m.middle_school_score.max()) if len(m) else np.nan,
                       mean_middle_score=float(m.middle_school_score.mean()) if len(m) else np.nan,
                       worst_middle_score=float(m.middle_school_score.min()) if len(m) else np.nan,
                       feeder_exclusivity=float(valid.feeder_exclusivity.mean()),
                       assignment_data_quality=float(confidence), elementary_accessibility_score=access,
                       shared_catchment=bool(shared), school_zone_score=scenarios["BASE"],
                       score_quality_focused=scenarios["QUALITY_FOCUSED"],
                       score_stability_focused=scenarios["STABILITY_FOCUSED"],
                       school_score_status="SCORED", school_score_quality=quality)
        rows.append(row)
    out = pd.DataFrame(rows)
    scored = out.school_zone_score.notna()
    out.loc[scored, "busan_school_rank"] = out.loc[scored, "school_zone_score"].rank(method="min", ascending=False)
    n = int(scored.sum())
    out.loc[scored, "school_zone_percentile"] = (n - out.loc[scored, "busan_school_rank"]) / max(n - 1, 1) * 100
    out["school_zone_grade"] = out.school_zone_percentile.map(lambda x: _grade(x, config))
    return out, rel


def _rank_sensitivity(apartments, config):
    out = apartments[["internal_complex_id", "complex_name", "school_zone_score", "score_quality_focused", "score_stability_focused"]].copy()
    for score, rank in [("school_zone_score", "rank_base"), ("score_quality_focused", "rank_quality"),
                        ("score_stability_focused", "rank_stability")]:
        out[rank] = out[score].rank(method="min", ascending=False)
    ranks = out[["rank_base", "rank_quality", "rank_stability"]]
    out["rank_min"] = ranks.min(axis=1); out["rank_max"] = ranks.max(axis=1)
    out["rank_range"] = out.rank_max - out.rank_min
    out["ranking_sensitive"] = out.rank_range.gt(config["ranking_sensitive_range"])
    top_ids = set(out.nsmallest(50, "rank_base").internal_complex_id)
    top = out[out.internal_complex_id.isin(top_ids)]
    correlations = {"BASE_vs_QUALITY_FOCUSED": top.rank_base.corr(top.rank_quality),
                    "BASE_vs_STABILITY_FOCUSED": top.rank_base.corr(top.rank_stability)}
    return out, correlations


def phase7_audit(root=ROOT):
    root = Path(root)
    files = ["middle_school_scores_by_id.parquet", "middle_school_scores.parquet",
             "busan_apartment_elementary_match_2025.parquet", "busan_elementary_middle_relation_2025.parquet",
             "busan_schoolzone_school_link_2025.parquet", "busan_elementary_catchment_boundaries_2025.parquet",
             "busan_apartment_coordinates_2025.parquet", "busan_apartment_elementary_relation_2025.parquet"]
    rows = []
    for name in files:
        path = root / "data/processed" / name
        frame = pd.read_parquet(path) if path.exists() else None
        rows.append({"file": name, "exists": path.exists(), "rows": len(frame) if frame is not None else None,
                     "columns": json.dumps(list(frame.columns), ensure_ascii=False) if frame is not None else None})
    write_csv(root / "reports/phase7_schema_audit.csv", pd.DataFrame(rows))
    return rows


def phase7_build(root=ROOT):
    root = Path(root); config = load_score_config(root)
    audit = phase7_audit(root)
    relations = build_elementary_middle_relations(root)
    scores = pd.read_parquet(root / "data/processed/middle_school_scores.parquet")
    score_cols = ["middle_school_id", "middle_school_score", "busan_rank", "sample_warning", "score_stability", "score_reference_year"]
    feeders, detail = build_feeder_scores(relations, scores[score_cols], config)
    write_parquet(root / "data/processed/elementary_feeder_scores_2025.parquet", feeders)
    apartment_rel = pd.read_parquet(root / "data/processed/busan_apartment_elementary_relation_2025.parquet")
    coordinate_master = pd.read_parquet(root / "data/processed/busan_apartment_coordinates_2025.parquet")
    missing_ids = coordinate_master.loc[~coordinate_master.internal_complex_id.isin(apartment_rel.internal_complex_id)]
    if len(missing_ids):
        placeholders = missing_ids.copy()
        for column in apartment_rel.columns:
            if column not in placeholders:
                placeholders[column] = pd.NA
        apartment_rel = pd.concat([apartment_rel, placeholders[apartment_rel.columns]], ignore_index=True)
    schools = pd.read_parquet(root / "data/processed/schools.parquet")
    apartments, apartment_detail = build_apartment_scores(apartment_rel, feeders, schools, detail, config)
    write_parquet(root / "data/processed/busan_apartment_school_scores_2025.parquet", apartments)
    large = apartments[apartments.households.ge(500)].copy()
    valid = large.school_zone_score.notna()
    large.loc[valid, "busan_500plus_rank"] = large.loc[valid, "school_zone_score"].rank(method="min", ascending=False)
    large.loc[valid, "sigungu_500plus_rank"] = large.loc[valid].groupby("sigungu").school_zone_score.rank(method="min", ascending=False)
    large.loc[valid, "legal_dong_500plus_rank"] = large.loc[valid].groupby(["sigungu", "legal_dong"]).school_zone_score.rank(method="min", ascending=False)
    write_parquet(root / "data/processed/busan_apartment_school_scores_500plus_2025.parquet", large)
    sensitivity, correlations = _rank_sensitivity(apartments, config)
    write_parquet(root / "data/processed/busan_school_score_sensitivity_2025.parquet", sensitivity)
    metrics = {"middle_school_scores": scores.middle_school_score.notna().sum(),
               "elementary_relations": len(relations),
               "scored_elementaries": feeders.elementary_feeder_score.notna().sum(),
               "scored_apartments": apartments.school_zone_score.notna().sum(),
               "apartment_total": len(apartments), "scored_500plus": large.school_zone_score.notna().sum(),
               "apartment_500plus_total": len(large),
               "review_coordinates_excluded": int(apartments.school_score_status.eq("REVIEW").sum()),
               "shared_catchment_apartments": int(apartments.shared_catchment.sum())}
    metrics.update({f"relation_{key}": value for key, value in relations.relation_type.value_counts().items()})
    metrics.update({f"status_{key}": value for key, value in apartments.school_score_status.value_counts().items()})
    metrics.update({f"quality_{key}": value for key, value in apartments.school_score_quality.value_counts().items()})
    quality = pd.DataFrame([{"metric": key, "value": value} for key, value in metrics.items()])
    write_csv(root / "reports/phase7_school_score_quality.csv", quality)
    top = apartments.dropna(subset=["school_zone_score"]).nsmallest(30, "busan_school_rank").copy()
    if len(top):
        top["explanation"] = top.apply(lambda x: f"{', '.join(x.elementary_school_names)} 통학구역; 중학교 {x.middle_school_count}개; 평균 {x.mean_middle_score:.1f}, 최저 {x.worst_middle_score:.1f}; 초등 직선거리 {x.nearest_elementary_distance_m:.0f}m; 부산 상위 {100-x.school_zone_percentile:.1f}%", axis=1)
    else:
        top["explanation"] = pd.Series(dtype="object")
    write_csv(root / "reports/phase7_top_school_zones.csv", top)
    sigungu_top = (apartments.dropna(subset=["school_zone_score"]).sort_values(
        ["sigungu", "school_zone_score", "complex_name"], ascending=[True, False, True]).groupby("sigungu").head(10))
    write_csv(root / "reports/phase7_sigungu_top10.csv", sigungu_top)
    distribution = apartments.school_zone_score.describe(percentiles=[.8, .9, .95]).to_dict()
    relation_counts = relations.relation_type.value_counts().to_dict()
    coverage_500plus = float(valid.mean()) if len(large) else 0.0
    thresholds = config["readiness_500plus_coverage"]
    readiness = ("READY" if coverage_500plus >= thresholds["ready"] else
                 "READY_WITH_REVIEW" if coverage_500plus >= thresholds["ready_with_review"] else "NOT_READY")
    report = _validation_report(audit, relations, feeders, apartments, large, correlations, distribution, readiness)
    atomic_bytes(root / "reports/phase7_validation.md", report.encode("utf-8"))
    write_parquet(root / "data/processed/busan_apartment_school_score_detail_2025.parquet", apartment_detail)
    write_parquet(root / "data/processed/elementary_middle_score_detail_2025.parquet", detail)
    return {"middle_school_scores": int(scores.middle_school_score.notna().sum()),
            "relation_counts": relation_counts, "scored_elementaries": int(feeders.elementary_feeder_score.notna().sum()),
            "scored_apartments": int(apartments.school_zone_score.notna().sum()), "apartments_total": len(apartments),
            "scored_500plus": int(large.school_zone_score.notna().sum()), "apartments_500plus": len(large),
            "coverage_500plus": coverage_500plus,
            "score_distribution": distribution, "sensitivity": correlations, "readiness": readiness}


def _validation_report(audit, relations, feeders, apartments, large, correlations, distribution, readiness):
    counts = relations.relation_type.value_counts().to_dict()
    quality = apartments.school_score_quality.value_counts().to_dict()
    shared = int(apartments.shared_catchment.sum())
    review = int(apartments.school_score_status.eq("REVIEW").sum())
    def js(x): return json.dumps(x, ensure_ascii=False, indent=2, default=str)
    return f"""# Phase 7 학군점수 검증 보고서

## A. Phase 7 개요
공식 배정 근거와 Phase 3 점수를 연결한 규칙 기반 0~100 점수다. 머신러닝이나 임의 순위 보정은 사용하지 않았다.

## B. 데이터 연결 현황
입력 감사: `{js({x['file']: x['rows'] for x in audit})}`

## C. middle school score 현황
Phase 3 점수 {int(pd.read_parquet(ROOT/'data/processed/middle_school_scores.parquet').middle_school_score.notna().sum())}개를 재계산 없이 사용했다.

## D. elementary feeder score 설계
가중 중학교 65%, 최저 15%, exclusivity 10%, 공식 배정자료 품질 10%다. 생성 {int(feeders.elementary_feeder_score.notna().sum())}/{len(feeders)}개다.

## E. assignment weight 설계
`{js(load_score_config(ROOT)['middle_relation_weights'])}`. 가중치는 배정확률이 아니라 근거 신뢰도 proxy다. 관계 건수 `{js(counts)}`.

## F. feeder uncertainty/exclusivity
중학교 점수 표준편차·범위·변동계수와 약한 관계 비중을 별도 저장했다. 최고점 하나만으로 feeder 점수를 만들지 않는다.

## G. apartment school zone score
BASE는 feeder 80%, 초등 직선거리 10%, 배정자료 품질 10%다. {int(apartments.school_zone_score.notna().sum())}/{len(apartments)}개 단지에 생성했다.

## H. 500세대 이상 Ranking
{int(large.school_zone_score.notna().sum())}/{len(large)}개에 점수와 부산·구군·법정동 순위를 생성했다.

## I. 센텀 validation
센텀초→센텀중은 기존 공식 근거의 `GROUP_MEMBERSHIP` 수준을 유지했다. 조건부·학교군 관계를 EXACT로 승격하지 않았다.

## J. 공동통학구역 현황
공동/복수 초등 관계 단지 {shared}개. 평균·최고·최저 feeder를 모두 보존했다.

## K. REVIEW 제외 현황
좌표 REVIEW 단지는 공식 직접 확정 근거가 없는 한 점수에서 제외한다. REVIEW 상태 {review}개다.

## L. sensitivity analysis
상위 50개 BASE 대비 Spearman 상관(순위값 Pearson): `{js(correlations)}`. 단지별 rank 범위와 민감도 플래그를 저장했다.

## M. 데이터 한계
초등학교별 중입 관계가 공식 원문에서 행 단위로 확인되지 않은 학교는 UNRESOLVED다. 직선거리는 실제 보행 통학거리와 다르다. 중학교 성과는 학교 효과나 배정 보장을 뜻하지 않는다. 품질 분포 `{js(quality)}`, 점수 분포 `{js(distribution)}`.

## N. Phase 8 진행 가능 여부
**{readiness}**. 현재 점수 보유 범위에서는 가격 결합 검증이 가능하지만, 미공개·미추출 초→중 관계는 결측으로 유지해야 한다.
"""
