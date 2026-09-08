"""Read-only coverage audit for unscored 500+ apartment complexes."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import ROOT, atomic_bytes, write_csv


OFFICE_KEYS = {
    "서부교육지원청": "seobu",
    "남부교육지원청": "nambu",
    "북부교육지원청": "bukbu",
    "동래교육지원청": "dongnae",
    "해운대교육지원청": "haeundae",
}

SIGUNGU_OFFICES = {
    "서구": "seobu", "영도구": "seobu", "사하구": "seobu",
    "남구": "nambu", "동구": "nambu", "부산진구": "nambu",
    "북구": "bukbu", "사상구": "bukbu", "강서구": "bukbu",
    "동래구": "dongnae", "금정구": "dongnae", "연제구": "dongnae",
    "해운대구": "haeundae", "수영구": "haeundae", "기장군": "haeundae",
}

AUDIT_COLUMNS = [
    "internal_complex_id", "complex_name", "households", "sigungu", "legal_dong",
    "elementary_school_id", "elementary_school_name", "education_office",
    "apartment_elementary_match_type", "middle_relation_exists", "middle_score_exists",
    "missing_reason",
]

MISSING_REASONS = [
    "MISSING_ELEMENTARY_MIDDLE_RELATION", "MISSING_MIDDLE_SCORE",
    "CROSS_OFFICE_ASSIGNMENT", "REVIEW", "OTHER",
]


def _office_key(value):
    if pd.isna(value):
        return pd.NA
    text = str(value)
    for label, key in OFFICE_KEYS.items():
        if label in text:
            return key
    return text


def _joined(values):
    cleaned = sorted({str(value) for value in values if not pd.isna(value) and str(value).strip()})
    return "|".join(cleaned)


def _markdown_table(frame):
    def cell(value):
        if pd.isna(value):
            return ""
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    lines.extend("| " + " | ".join(cell(value) for value in row) + " |"
                 for row in frame.itertuples(index=False, name=None))
    return "\n".join(lines)


def _reason(group, score_row):
    if str(score_row.get("school_score_status")) == "REVIEW" or bool(score_row.get("manual_review", False)):
        return "REVIEW"
    if group.empty:
        return "OTHER"
    if group["external_assignment"].any():
        return "CROSS_OFFICE_ASSIGNMENT"
    if not group["middle_relation_exists_school"].any():
        return "MISSING_ELEMENTARY_MIDDLE_RELATION"
    if not group["middle_score_exists_school"].any():
        return "MISSING_MIDDLE_SCORE"
    return "OTHER"


def build_phase7_coverage_audit(root=ROOT):
    root = Path(root)
    processed = root / "data/processed"
    reports = root / "reports"

    scores = pd.read_parquet(processed / "busan_apartment_school_scores_500plus_2026.parquet")
    apartment_relations = pd.read_parquet(processed / "busan_apartment_elementary_relation_2025.parquet")
    middle_relations = pd.read_parquet(processed / "busan_elementary_middle_relation_2026.parquet")
    middle_scores = pd.read_parquet(processed / "middle_school_scores.parquet")

    if len(scores) != 560:
        raise ValueError("Expected the audited population to contain 560 large complexes.")

    middle = middle_relations.merge(
        middle_scores[["middle_school_id", "middle_school_score"]], on="middle_school_id", how="left"
    )
    middle_by_elementary = (middle.groupby("elementary_school_id", dropna=False)
                            .agg(middle_relation_exists_school=("middle_school_name", lambda x: x.notna().any()),
                                 middle_score_exists_school=("middle_school_score", lambda x: x.notna().any()),
                                 external_assignment=("source_text", lambda x: x.astype(str).str.contains(
                                     "외부 교육지원청", regex=False).any()))
                            .reset_index())

    relation_columns = [
        "internal_complex_id", "elementary_school_id", "elementary_school_name",
        "education_office_name_link", "evidence_type",
    ]
    links = apartment_relations[relation_columns].drop_duplicates().merge(
        middle_by_elementary, on="elementary_school_id", how="left"
    )
    for column in ["middle_relation_exists_school", "middle_score_exists_school", "external_assignment"]:
        links[column] = links[column].map(lambda value: bool(value) if pd.notna(value) else False)
    links["education_office"] = links["education_office_name_link"].map(_office_key)

    missing = scores[scores["school_zone_score"].isna()].copy()
    audit_rows = []
    for _, score_row in missing.iterrows():
        group = links[links["internal_complex_id"].eq(score_row["internal_complex_id"])]
        office = (_joined(group["education_office"]) if not group.empty else "")
        if not office:
            office = SIGUNGU_OFFICES.get(score_row["sigungu"], "unknown")
        audit_rows.append({
            "internal_complex_id": score_row["internal_complex_id"],
            "complex_name": score_row["complex_name"],
            "households": score_row["households"],
            "sigungu": score_row["sigungu"],
            "legal_dong": score_row["legal_dong"],
            "elementary_school_id": _joined(group["elementary_school_id"]) if not group.empty else pd.NA,
            "elementary_school_name": _joined(group["elementary_school_name"]) if not group.empty else pd.NA,
            "education_office": office,
            "apartment_elementary_match_type": _joined(group["evidence_type"]) if not group.empty else "NO_ELEMENTARY_MATCH",
            "middle_relation_exists": bool(group["middle_relation_exists_school"].any()) if not group.empty else False,
            "middle_score_exists": bool(group["middle_score_exists_school"].any()) if not group.empty else False,
            "missing_reason": _reason(group, score_row),
        })
    audit = pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS).sort_values(
        ["education_office", "households", "internal_complex_id"], ascending=[True, False, True]
    )

    office_by_apartment = (links.groupby("internal_complex_id")["education_office"]
                           .agg(_joined).rename("education_office"))
    coverage = scores[["internal_complex_id", "sigungu", "school_zone_score"]].merge(
        office_by_apartment, on="internal_complex_id", how="left"
    )
    coverage["education_office"] = coverage.apply(
        lambda row: row["education_office"] if pd.notna(row["education_office"]) and row["education_office"]
        else SIGUNGU_OFFICES.get(row["sigungu"], "unknown"), axis=1
    )
    office_summary = (coverage.groupby("education_office")
                      .agg(total_500plus_apartments=("internal_complex_id", "nunique"),
                           scored_500plus_apartments=("school_zone_score", lambda x: x.notna().sum()))
                      .reset_index())
    office_summary["unscored_500plus_apartments"] = (
        office_summary["total_500plus_apartments"] - office_summary["scored_500plus_apartments"]
    )
    office_summary["score_coverage_pct"] = (
        office_summary["scored_500plus_apartments"] / office_summary["total_500plus_apartments"] * 100
    ).round(2)
    missing_school_counts = (links[links["internal_complex_id"].isin(missing["internal_complex_id"])]
                             .groupby("education_office")["elementary_school_id"].nunique())
    office_summary["unscored_unique_elementary_school_id_count"] = (
        office_summary["education_office"].map(missing_school_counts).fillna(0).astype(int)
    )

    target_links = links[
        links["internal_complex_id"].isin(missing["internal_complex_id"])
        & links["education_office"].isin(["haeundae", "dongnae"])
    ].drop_duplicates(["internal_complex_id", "elementary_school_id"])
    all_counts = (apartment_relations.groupby("elementary_school_id")["internal_complex_id"]
                  .nunique().rename("linked_all_apartment_count"))
    target_with_households = target_links.merge(
        missing[["internal_complex_id", "households"]], on="internal_complex_id", how="left"
    )
    priority = (target_with_households.groupby(
        ["education_office", "elementary_school_id", "elementary_school_name"], dropna=False)
        .agg(linked_500plus_apartment_count=("internal_complex_id", "nunique"),
             largest_complex_households=("households", "max"))
        .reset_index())
    priority = priority.merge(all_counts, on="elementary_school_id", how="left")
    priority = priority[["education_office", "elementary_school_id", "elementary_school_name",
                         "linked_500plus_apartment_count", "linked_all_apartment_count",
                         "largest_complex_households"]].sort_values(
        ["linked_500plus_apartment_count", "linked_all_apartment_count", "elementary_school_name"],
        ascending=[False, False, True]
    ).reset_index(drop=True)

    target_apartment_ids = set(target_links["internal_complex_id"])
    pareto_rows = []
    for top_n in [10, 20, 30, 40]:
        school_ids = set(priority.head(top_n)["elementary_school_id"])
        covered_ids = set(target_links.loc[target_links["elementary_school_id"].isin(school_ids), "internal_complex_id"])
        pareto_rows.append({
            "top_n": top_n,
            "covered_apartments": len(covered_ids),
            "target_apartments": len(target_apartment_ids),
            "potential_coverage_pct": round(len(covered_ids) / max(len(target_apartment_ids), 1) * 100, 2),
        })
    pareto = pd.DataFrame(pareto_rows)

    write_csv(reports / "phase7_missing_500plus_apartments.csv", audit)
    write_csv(reports / "phase7_missing_elementary_priority.csv", priority)

    coverage_md = _markdown_table(office_summary)
    reasons_md = (audit["missing_reason"].value_counts().reindex(MISSING_REASONS, fill_value=0)
                  .rename_axis("missing_reason").reset_index(name="apartment_count"))
    reasons_md = _markdown_table(reasons_md)
    priority_md = _markdown_table(priority.head(20))
    pareto_md = _markdown_table(pareto)
    statements = "\n".join(
        f'- 해운대·동래에서 상위 {int(row.top_n)}개 초등학교의 배정관계만 확보하면 '
        f'500세대 이상 미점수 단지의 {row.potential_coverage_pct:.2f}%({int(row.covered_apartments)}/{int(row.target_apartments)}개)를 '
        "추가로 점수화할 수 있음."
        for row in pareto.itertuples(index=False)
    )
    report = f"""# Phase 7 500세대 이상 미점수 coverage audit

## 범위와 판정 기준

- 기준 산출물: 2026학년도 점수 {len(scores):,}개 중 미점수 {len(audit):,}개
- 기존 관계·점수 파일은 읽기만 했으며 점수 로직과 점수 산출물을 변경하지 않았다.
- 공동학구 7개 단지는 감사 CSV에서 아파트당 1행을 유지하고 학교 ID와 이름을 `|`로 병합했다.
- `middle_relation_exists`와 `middle_score_exists`는 연결된 초등학교 중 하나 이상에 근거가 있으면 `True`다.
- `CROSS_OFFICE_ASSIGNMENT`는 PDF가 외부 교육지원청 배정을 명시한 경우다.
- `apartment_elementary_match_type`은 현재 공식 학구 연결의 `evidence_type`을 사용했다.
- Pareto 비율은 공동학구 단지의 중복을 제거한 아파트 합집합 기준이다. 실제 추가 점수화에는 확보될 중학교의 Phase 3 성과점수가 필요하다.

## 교육지원청별 coverage

{coverage_md}

## 미점수 사유

{reasons_md}

- 미점수 단지가 연결된 전체 unique elementary_school_id: {links[links['internal_complex_id'].isin(missing['internal_complex_id'])]['elementary_school_id'].nunique()}
- 초등학교 연결이 없는 단지: {int(audit['elementary_school_id'].isna().sum())}

## 해운대·동래 수기 확인 우선순위 상위 20개

{priority_md}

전체 우선순위는 `reports/phase7_missing_elementary_priority.csv`에 저장했다.

## Pareto 분석

{pareto_md}

{statements}
"""
    atomic_bytes(reports / "phase7_assignment_coverage_audit.md", report.encode("utf-8"))

    return {
        "missing_500plus_apartments": len(audit),
        "priority_elementaries": len(priority),
        "haeundae_dongnae_target_apartments": len(target_apartment_ids),
        "pareto": pareto_rows,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(build_phase7_coverage_audit(), ensure_ascii=False, indent=2))
