"""Import the user-supplied official 2026 Bukbu and Seobu assignment tables."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from .config import ROOT, atomic_bytes, write_csv, write_parquet
from .parsers.pdf_parser import parse_pdf
from .phase7_scoring import (_school_key, _names, build_apartment_scores,
                             build_feeder_scores, load_score_config, _rank_sensitivity)

OFFICIAL_ABBREVIATION_ALIASES = {
    "영선중": "부산영선중학교",
    "대신중": "부산대신중학교",
    "중앙여중": "부산중앙여자중학교",
    "이사벨여중": "이사벨중학교",
    "내성중": "부산내성중학교",
}

DISTRICT_OFFICES = {
    "서구": "seobu", "영도구": "seobu", "사하구": "seobu",
    "남구": "nambu", "동구": "nambu", "부산진구": "nambu",
    "북구": "bukbu", "사상구": "bukbu", "강서구": "bukbu",
    "동래구": "dongnae", "금정구": "dongnae", "연제구": "dongnae",
    "해운대구": "haeundae", "수영구": "haeundae", "기장군": "haeundae",
}


def _relation_records(elementary, male_text, female_text, *, office, group, path, line_no, year=2026):
    gender_by_school = {}
    for gender, text in (("male", male_text), ("female", female_text)):
        for middle in _names(text, "중"):
            gender_by_school.setdefault(middle, set()).add(gender)
    records = []
    for middle, genders in gender_by_school.items():
        records.append({"data_year": year, "assignment_year": year, "education_office": office,
                        "elementary_school_name": elementary, "middle_school_name": middle,
                        "school_group": group, "relation_type": "ELIGIBLE",
                        "gender_condition": "all" if len(genders) == 2 else next(iter(genders)),
                        "source_document": str(path), "source_page_or_section": f"layout line {line_no + 1}",
                        "source_text": f"남학생 중입={male_text}; 여학생 중입={female_text}",
                        "manual_review": False, "parser_version": "phase7-assignment-2026-1.0"})
    return records


def parse_bukbu_2026(path):
    path = Path(path); lines = parse_pdf(path).text.splitlines()
    if not lines or "2026학년도 중입배정 및 전학배정표" not in lines[0]:
        raise ValueError("북부 2026 중입배정표 제목 또는 연도가 일치하지 않습니다.")
    records = []; group = None
    for line_no, line in enumerate(lines[2:], 2):
        group_match = re.search(r"(\d+)학교군|중학구", line)
        if group_match:
            group = f"{group_match.group(1)}학교군" if group_match.group(1) else "중학구"
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) > 1 and not re.fullmatch(r"\d+", parts[0]) and re.fullmatch(r"\d+", parts[1]):
            parts = parts[1:]
        if len(parts) < 4 or not re.fullmatch(r"\d+", parts[0]) or not re.fullmatch(r"[가-힣]+초", parts[1]):
            continue
        male_intake = parts[2]
        # Six fields contain all four assignment columns. When a transfer cell wraps,
        # pdftotext omits that empty/wrapped cell; the next visible cell is female intake.
        female_intake = parts[4] if len(parts) >= 6 else parts[3]
        parsed = _relation_records(parts[1], male_intake, female_intake, office="bukbu",
                                   group=group, path=path, line_no=line_no)
        if parsed:
            records.extend(parsed)
        elif "교육지원청 배정" in male_intake + female_intake:
            records.append({"data_year": 2026, "assignment_year": 2026, "education_office": "bukbu",
                            "elementary_school_name": parts[1], "middle_school_name": pd.NA,
                            "school_group": group, "relation_type": "UNRESOLVED", "gender_condition": "all",
                            "source_document": str(path), "source_page_or_section": f"layout line {line_no + 1}",
                            "source_text": f"외부 교육지원청 배정: {male_intake}", "manual_review": True,
                            "parser_version": "phase7-assignment-2026-1.0"})
    out = pd.DataFrame(records)
    if out.elementary_school_name.nunique() < 65:
        raise ValueError("북부 2026 표 행 추출률이 예상보다 낮습니다.")
    return out.drop_duplicates(["elementary_school_name", "middle_school_name"])


def parse_seobu_2026(path):
    path = Path(path); lines = parse_pdf(path).text.splitlines()
    if not lines or "2026학년도 초등학교 기준 배정 중학교" not in lines[0]:
        raise ValueError("서부 2026 입학배정표 제목 또는 연도가 일치하지 않습니다.")
    records = []; group = None; pending = []; last = []
    for line_no, line in enumerate(lines[5:], 5):
        match = re.search(r"(\d+)학교군", line)
        if match:
            group = f"{match.group(1)}학교군"
        parts = re.split(r"\s{2,}", line.strip())
        middle_index = next((i for i, cell in enumerate(parts) if _names(cell, "중")), len(parts))
        left = ",".join(parts[:middle_index])
        left = re.sub(r"\d+학교군|\([^)]*\)|\*.*", "", left)
        elementaries = [x.strip() + "초" for x in re.split(r"[,，]", left)
                        if re.fullmatch(r"[가-힣]{2,6}", x.strip()) and not x.strip().endswith("중")]
        cells_with_middle = [cell for cell in parts[middle_index:] if _names(cell, "중")]
        male = cells_with_middle[0] if cells_with_middle else ""
        female = cells_with_middle[1] if len(cells_with_middle) > 1 else ""
        if elementaries:
            pending.extend(elementaries); last = elementaries
        targets = pending if (male or female) and pending else last
        if targets and (male or female):
            for elementary in targets:
                records.extend(_relation_records(elementary, male, female, office="seobu",
                                                 group=group, path=path, line_no=line_no))
            pending = []
    out = pd.DataFrame(records)
    if out.elementary_school_name.nunique() < 45:
        raise ValueError("서부 2026 표 행 추출률이 예상보다 낮습니다.")
    return out.drop_duplicates(["elementary_school_name", "middle_school_name"])


def parse_manual_assignment_2026(path):
    """Parse user-curated elementary-to-middle candidates with row provenance."""
    path = Path(path)
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    required = ["구", "초등학교", "배정가능 중학교"]
    if list(frame.columns) != required:
        raise ValueError(f"수작업 배정 CSV 열이 일치하지 않습니다: {list(frame.columns)}")
    frame = frame.apply(lambda column: column.str.strip())
    if frame[required].eq("").any().any():
        raise ValueError("수작업 배정 CSV에 빈 구·학교명이 있습니다.")
    unknown = sorted(set(frame["구"]) - set(DISTRICT_OFFICES))
    if unknown:
        raise ValueError(f"교육지원청을 판정할 수 없는 구·군입니다: {unknown}")

    rows = []
    for index, item in frame.drop_duplicates(required).iterrows():
        rows.append({
            "data_year": 2026,
            "assignment_year": 2026,
            "education_office": DISTRICT_OFFICES[item["구"]],
            "elementary_school_name": item["초등학교"],
            "middle_school_name": item["배정가능 중학교"],
            "school_group": pd.NA,
            "relation_type": "ELIGIBLE",
            "gender_condition": "all",
            "source_document": str(path),
            "source_page_or_section": f"CSV row {index + 2}",
            "source_text": f"{item['구']},{item['초등학교']},{item['배정가능 중학교']}",
            "manual_review": True,
            "parser_version": "phase7-manual-assignment-2026-1.0",
        })
    return pd.DataFrame(rows)


def build_assignment_2026(root=ROOT):
    root = Path(root); base = root / "em_school"
    bukbu_path = base / "01.북부교육지청_2026학년도 중입배정 및 전학배정표.pdf"
    seobu_path = base / "02.서부교육지청_2026학년도 입학배정.pdf"
    manual_path = base / "수작업 초_중배정내역(260908).csv"
    official_relations = pd.concat(
        [parse_bukbu_2026(bukbu_path), parse_seobu_2026(seobu_path)], ignore_index=True
    )
    manual_relations = parse_manual_assignment_2026(manual_path)
    relations = pd.concat([official_relations, manual_relations], ignore_index=True)
    schools = pd.read_parquet(root / "data/processed/schools.parquet")
    elementary = schools[schools.school_level.astype(str).str.lower().isin(["elementary", "초등학교"])].copy()
    middle = schools[schools.school_level.astype(str).str.lower().isin(["middle", "중학교"])].copy()
    elementary["_key"] = elementary.school_name.map(_school_key); middle["_key"] = middle.school_name.map(_school_key)
    relations["_elementary_key"] = relations.elementary_school_name.map(_school_key)
    relations["middle_school_name_current"] = relations.middle_school_name.map(
        lambda value: OFFICIAL_ABBREVIATION_ALIASES.get(value, value) if not pd.isna(value) else value)
    relations["_middle_key"] = relations.middle_school_name_current.map(_school_key)
    relations = relations.merge(elementary[["_key", "school_id"]].drop_duplicates("_key").rename(
        columns={"_key": "_elementary_key", "school_id": "elementary_school_id"}), on="_elementary_key", how="left")
    relations = relations.merge(middle[["_key", "school_id"]].drop_duplicates("_key").rename(
        columns={"_key": "_middle_key", "school_id": "middle_school_id"}), on="_middle_key", how="left")
    relations = relations.drop_duplicates(
        ["elementary_school_id", "middle_school_id", "relation_type", "gender_condition"], keep="first"
    )
    config = load_score_config(root)
    relations["assignment_reliability_weight"] = relations.relation_type.map(config["middle_relation_weights"]).astype(float)
    relations["assignment_data_quality"] = relations.relation_type.map(config["assignment_quality"]).astype(float)
    relations["guaranteed_assignment"] = False
    relations["source_sha256"] = relations.source_document.map(
        lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest())
    relations = relations.drop(columns=["_elementary_key", "_middle_key"])
    write_parquet(root / "data/processed/busan_elementary_middle_relation_2026.parquet", relations)

    middle_scores = pd.read_parquet(root / "data/processed/middle_school_scores.parquet")
    cols = ["middle_school_id", "middle_school_score", "busan_rank", "sample_warning", "score_stability", "score_reference_year"]
    feeders, detail = build_feeder_scores(relations, middle_scores[cols], config)
    feeders["assignment_year"] = 2026
    write_parquet(root / "data/processed/elementary_feeder_scores_2026.parquet", feeders)
    write_parquet(root / "data/processed/elementary_middle_score_detail_2026.parquet", detail)

    apartment_rel = pd.read_parquet(root / "data/processed/busan_apartment_elementary_relation_2025.parquet")
    coordinate_master = pd.read_parquet(root / "data/processed/busan_apartment_coordinates_2025.parquet")
    missing = coordinate_master[~coordinate_master.internal_complex_id.isin(apartment_rel.internal_complex_id)].copy()
    for column in apartment_rel.columns:
        if column not in missing:
            missing[column] = pd.NA
    if len(missing):
        # Omit synthetic columns that are entirely empty. ``concat`` adds them back
        # from apartment_rel and avoids pandas' deprecated all-NA dtype inference.
        populated = missing[apartment_rel.columns].dropna(axis="columns", how="all")
        apartment_rel = pd.concat([apartment_rel, populated], ignore_index=True)
    apartments, apartment_detail = build_apartment_scores(apartment_rel, feeders, schools, detail, config)
    apartments["assignment_year"] = 2026; apartments["catchment_boundary_year"] = 2025
    write_parquet(root / "data/processed/busan_apartment_school_scores_2026.parquet", apartments)
    write_parquet(root / "data/processed/busan_apartment_school_score_detail_2026.parquet", apartment_detail)
    large = apartments[apartments.households.ge(500)].copy(); valid = large.school_zone_score.notna()
    large.loc[valid, "busan_500plus_rank"] = large.loc[valid, "school_zone_score"].rank(method="min", ascending=False)
    large.loc[valid, "sigungu_500plus_rank"] = large.loc[valid].groupby("sigungu").school_zone_score.rank(method="min", ascending=False)
    large.loc[valid, "legal_dong_500plus_rank"] = large.loc[valid].groupby(["sigungu", "legal_dong"]).school_zone_score.rank(method="min", ascending=False)
    write_parquet(root / "data/processed/busan_apartment_school_scores_500plus_2026.parquet", large)
    sensitivity, correlations = _rank_sensitivity(apartments, config)
    write_parquet(root / "data/processed/busan_school_score_sensitivity_2026.parquet", sensitivity)
    quality = pd.DataFrame([{"metric": "bukbu_elementaries", "value": relations.loc[relations.education_office.eq("bukbu"), "elementary_school_id"].nunique()},
                            {"metric": "seobu_elementaries", "value": relations.loc[relations.education_office.eq("seobu"), "elementary_school_id"].nunique()},
                            {"metric": "manual_source_rows", "value": len(manual_relations)},
                            {"metric": "manual_source_elementaries", "value": manual_relations.elementary_school_name.nunique()},
                            {"metric": "relation_rows", "value": len(relations)},
                            {"metric": "unmatched_elementary_ids", "value": relations.elementary_school_id.isna().sum()},
                            {"metric": "unresolved_external_office_rows", "value": relations.relation_type.eq("UNRESOLVED").sum()},
                            {"metric": "unmatched_named_middle_ids", "value": (relations.middle_school_id.isna() & relations.middle_school_name.notna()).sum()},
                            {"metric": "scored_apartments", "value": apartments.school_zone_score.notna().sum()},
                            {"metric": "scored_500plus", "value": large.school_zone_score.notna().sum()}])
    write_csv(root / "reports/phase7_assignment_2026_quality.csv", quality)
    report = f"""# 2026 중입배정 반영 보고서

## 입력
- 북부: `{bukbu_path.name}`
- 서부: `{seobu_path.name}`
- 수작업 확보 관계: `{manual_path.name}`
- 모든 입력 파일의 SHA256을 관계 행에 저장했다.

## 파싱 원칙
중입 배정과 전학 배정을 분리했다. 점수에는 남학생·여학생 **중입 배정** 열만 합집합으로 사용했다.
관계는 배정 후보이므로 `ELIGIBLE`, `guaranteed_assignment=False`다.
수작업 CSV 관계는 `manual_review=True`와 원본 CSV 행 번호를 보존한다.

## 결과
- 관계 행: {len(relations):,}
- 북부 초등학교: {relations.loc[relations.education_office.eq('bukbu'), 'elementary_school_id'].nunique():,}
- 서부 초등학교: {relations.loc[relations.education_office.eq('seobu'), 'elementary_school_id'].nunique():,}
- 수작업 관계: {len(manual_relations):,}행 / {manual_relations.elementary_school_name.nunique():,}개 초등학교
- feeder 점수: {feeders.elementary_feeder_score.notna().sum():,}
- 아파트 점수: {apartments.school_zone_score.notna().sum():,}/{len(apartments):,}
- 500세대 이상: {large.school_zone_score.notna().sum():,}/{len(large):,}
- 민감도 상관: `{json.dumps(correlations, ensure_ascii=False)}`

## 시간 기준
중입 관계는 2026학년도, 중학교 성과는 Phase 3의 2025 기준 점수, 아파트 통학구역 공간경계는
2025-09-22 자료다. 2025 산출물에는 2026 관계를 덮어쓰지 않았다.
"""
    atomic_bytes(root / "reports/phase7_assignment_2026_validation.md", report.encode("utf-8"))
    return {"relations": len(relations), "elementaries": int(relations.elementary_school_id.nunique()),
            "manual_relations": len(manual_relations),
            "manual_elementaries": int(manual_relations.elementary_school_name.nunique()),
            "feeders": int(feeders.elementary_feeder_score.notna().sum()),
            "apartments_scored": int(apartments.school_zone_score.notna().sum()),
            "apartments_500plus_scored": int(large.school_zone_score.notna().sum()),
            "apartments_500plus_total": len(large), "sensitivity": correlations}
