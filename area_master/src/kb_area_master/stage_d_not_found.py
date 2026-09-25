"""
STAGE D: KB 검색 미발견(KB_COMPLEX_NOT_FOUND) 강화 탐색 모듈.

목적:
- 1차 수집 시 단순 단지명 검색으로 발견되지 않은 70개 단지 대상.
- 도로명 주소(도로명+번호), 지번 번호, 영문/별칭 변환(SK VIEW->SK뷰, I-PARK->아이파크 등),
  구 명칭/신 명칭 다각도 검색으로 KB 단지 발굴.
- 발굴된 단지 중 도로명 exact + 세대수 exact, 또는 법정동 + 세대수 exact 시 VERIFIED_KB_REMATCHED 확정.
- 확정된 단지는 mpriByType로 평형별 세대수·면적·시세 즉시 수집.
- 완전 미발견 단지는 KB_NOT_AVAILABLE로 분류하고 data/review/phase2_kb_not_found.csv에 기록.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.async_api import Page

from .kb_search import normalize_for_search, extract_core_name
from .kb_collector import KBCollector
from .area_normalizer import aggregate_area_types
from .stage_b_low_confidence import search_kb_api, calc_name_similarity
from .models import AreaType

logger = logging.getLogger(__name__)


def generate_alias_and_road_queries(
    kapt_name: str,
    dong: str,
    gu: str,
    road_address: str,
    legal_address: str,
) -> list[str]:
    """영문 변환, 도로명, 지번을 활용한 강화 검색 쿼리 목록을 생성한다."""
    queries = []
    dong_clean = dong.strip() if dong else ""

    # 1. 영문 및 일반 브랜드 별칭 변환
    alias_name = kapt_name
    replacements = [
        (r"SK\s*VIEW", "SK뷰"),
        (r"I-PARK|IPARK", "아이파크"),
        (r"APT|apt", ""),
        (r"아파트", ""),
        (r"주상복합", ""),
        (r"맨션", ""),
    ]
    for pattern, repl in replacements:
        alias_name = re.sub(pattern, repl, alias_name, flags=re.IGNORECASE)
    alias_name = re.sub(r"\s+", " ", alias_name).strip()

    if dong_clean and alias_name:
        queries.append(f"{dong_clean} {alias_name}")

    # 2. 도로명 핵심 (도로명 + 번호)
    if road_address:
        # "부산광역시 남구 오륙도로 85" -> "오륙도로 85"
        parts = road_address.split()
        if len(parts) >= 3:
            road_core = " ".join(parts[2:4]) if len(parts) >= 4 else parts[-1]
            if any(char.isdigit() for char in road_core):
                queries.append(road_core)

    # 3. 별칭 단독
    if alias_name and alias_name not in queries:
        queries.append(alias_name)

    # 4. 동명 + 핵심 브랜드 (롯데캐슬, 푸르지오, 자이, 아이파크, e편한세상 등)
    brands = ["SK뷰", "아이파크", "푸르지오", "롯데캐슬", "자이", "e편한세상", "힐스테이트", "더샵", "포레나", "동원로얄듀크", "삼정그린코아", "쌍용예가"]
    for b in brands:
        if b in alias_name and dong_clean:
            q = f"{dong_clean} {b}"
            if q not in queries:
                queries.append(q)
            break

    # 5. 지번 (동명 + 지번)
    if legal_address and dong_clean:
        parts = legal_address.split()
        if parts:
            jibun = parts[-1]
            if any(char.isdigit() for char in jibun):
                queries.append(f"{dong_clean} {jibun}")

    return queries


async def process_stage_d_not_found(
    page: Page,
    pending_df: pd.DataFrame,
    kapt_df: pd.DataFrame,
    collector: KBCollector,
    output_dir: Path,
) -> dict[str, Any]:
    """STAGE D: KB 미발견 70개 단지에 대해 강화 검색을 수행하고 해결한다."""
    logger.info("=== STAGE D: KB 검색 미발견 단지 강화 탐색 시작 ===")

    target_mask = pending_df["reason_code"] == "KB_COMPLEX_NOT_FOUND"
    not_found_df = pending_df[target_mask].copy()
    logger.info("STAGE D 대상 단지 수: %d개", len(not_found_df))

    sigungu_col = "sigungu" if "sigungu" in kapt_df.columns else "sigungu_kapt"
    cols_to_use = ["kapt_code", sigungu_col, "road_address", "legal_address", "approval_date", "households"]

    merged = pd.merge(
        not_found_df,
        kapt_df[cols_to_use],
        on="kapt_code",
        how="left",
        suffixes=("", "_kapt")
    )
    if sigungu_col != "sigungu_name":
        merged["sigungu_name"] = merged[sigungu_col]

    review_rows = []
    resolved_results = []

    for idx, (_, row) in enumerate(merged.iterrows(), start=1):
        kapt_code = str(row["kapt_code"]).strip()
        kapt_name = str(row.get("kapt_name", "")).strip()
        dong = str(row.get("legal_dong", "")).strip()
        gu = str(row.get("sigungu_name", "")).strip()
        road_addr = str(row.get("road_address", "")).strip()
        legal_addr = str(row.get("legal_address", "")).strip()
        kapt_hh = int(row.get("kapt_households", 0) or row.get("households", 0) or 0)

        queries = generate_alias_and_road_queries(kapt_name, dong, gu, road_addr, legal_addr)
        all_candidates: dict[str, dict[str, Any]] = {}

        for q in queries:
            cands = await search_kb_api(page, q)
            for c in cands:
                cid = c["kb_complex_id"]
                if cid and cid not in all_candidates:
                    all_candidates[cid] = c
            if any(c["kb_households"] == kapt_hh for c in all_candidates.values()):
                break
            await asyncio.sleep(0.5)

        candidate_list = list(all_candidates.values())
        best_candidate = None
        match_reason = ""
        is_matched = False

        for c in candidate_list:
            kb_hh = c["kb_households"]
            kb_road = c.get("kb_road_address", "")
            kb_dong = c.get("kb_dong", "")
            kb_name = c.get("kb_name", "")

            # CASE 1: 도로명 일치 + 세대수 일치
            if road_addr and kb_road and (road_addr in kb_road or kb_road in road_addr):
                if kb_hh == kapt_hh and kb_hh > 0:
                    best_candidate = c
                    match_reason = f"도로명 일치 및 세대수 정확 일치 ({kb_hh}세대)"
                    is_matched = True
                    break

            # CASE 2: 법정동 일치 + 단지명 유사도 0.7+ + 세대수 일치
            sim = calc_name_similarity(kapt_name, kb_name)
            if dong and kb_dong and (dong in kb_dong or kb_dong in dong):
                if sim >= 0.65 and kb_hh == kapt_hh and kb_hh > 0:
                    best_candidate = c
                    match_reason = f"동 일치, 유사명칭({sim:.2f}) 및 세대수 일치 ({kb_hh}세대)"
                    is_matched = True
                    break

        area_types: list[AreaType] = []
        status = "PENDING_NOT_FOUND"
        next_action = "CHECK_OFFICIAL_SALE_NOTICE"

        if is_matched and best_candidate:
            cid = best_candidate["kb_complex_id"]
            cname = best_candidate["kb_name"]
            logger.info("[%d/%d] STAGE D 발견! [%s] %s -> KB ID=%s (%s): %s",
                        idx, len(merged), kapt_code, kapt_name, cid, cname, match_reason)

            area_types = await collector.collect_area_types(page, cid)
            collected_hh = sum(at.households for at in area_types)

            if collected_hh == kapt_hh:
                status = "VERIFIED_KB_REMATCHED"
                next_action = ""
                aggregated = aggregate_area_types(kapt_code, area_types)
                resolved_results.append({
                    "kapt_code": kapt_code,
                    "kapt_name": kapt_name,
                    "kb_complex_id": cid,
                    "kb_name": cname,
                    "kb_url": best_candidate["kb_url"],
                    "match_confidence": "high",
                    "status": "VERIFIED",
                    "processing_status": status,
                    "area_types": area_types,
                    "aggregated_rows": aggregated,
                    "notes": match_reason,
                })
            else:
                status = "PENDING_HOUSEHOLD_MISMATCH"
                next_action = "VERIFY_OFFICIAL_HOUSEHOLDS"

        review_rows.append({
            "kapt_code": kapt_code,
            "kapt_name": kapt_name,
            "legal_dong": dong,
            "kapt_households": kapt_hh,
            "candidates_found": len(candidate_list),
            "matched_kb_id": best_candidate["kb_complex_id"] if best_candidate else "",
            "matched_kb_name": best_candidate["kb_name"] if best_candidate else "",
            "matched_kb_households": best_candidate["kb_households"] if best_candidate else "",
            "match_reason": match_reason,
            "processing_status": status,
            "recommended_next_action": next_action,
            "verified_at": datetime.now().strftime("%Y-%m-%d") if status == "VERIFIED_KB_REMATCHED" else "",
        })

    out_file = output_dir / "phase2_kb_not_found.csv"
    pd.DataFrame(review_rows).to_csv(out_file, index=False, encoding="utf-8-sig")
    logger.info("STAGE D 완료: %d건 중 %d건 VERIFIED_KB_REMATCHED 해결 -> 저장: %s",
                len(merged), len(resolved_results), out_file)

    return {
        "resolved_results": resolved_results,
        "review_rows": review_rows,
    }
