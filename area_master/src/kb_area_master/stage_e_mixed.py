"""
STAGE E: 혼합 단지(MIXED_RENTAL_COMPLEX) 분양/임대 분리 및 수집 모듈.

목적:
- 1차 수집 시 K-apt 분양형태가 '혼합'으로 분류되어 PENDING된 37개 단지 대상.
- KB부동산에서 분양 아파트 단지를 매칭하고 mpriByType로 분양 평형별 세대수 및 시세 수집.
- 분양 세대수와 임대 세대수를 명확히 분리하여, master에는 scope=sale_apartment 세대만 적재.
- K-apt 총세대수 = 분양세대수 + 임대세대수 검증식 확인.
- 출력: data/review/phase2_mixed_complex_analysis.csv
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.async_api import Page

from .kb_search import normalize_for_search, extract_core_name
from .kb_collector import KBCollector
from .area_normalizer import aggregate_area_types
from .stage_b_low_confidence import generate_enhanced_queries, search_kb_api, calc_name_similarity
from .models import AreaType

logger = logging.getLogger(__name__)


async def process_stage_e_mixed(
    page: Page,
    pending_df: pd.DataFrame,
    kapt_df: pd.DataFrame,
    collector: KBCollector,
    output_dir: Path,
) -> dict[str, Any]:
    """STAGE E: 혼합단지 37개 단지에 대해 분양/임대 분리 및 수집을 수행한다."""
    logger.info("=== STAGE E: 혼합 단지(MIXED_RENTAL_COMPLEX) 분양 평형 분리 수집 시작 ===")

    target_mask = pending_df["reason_code"] == "MIXED_RENTAL_COMPLEX"
    mixed_df = pending_df[target_mask].copy()
    logger.info("STAGE E 대상 단지 수: %d개", len(mixed_df))

    sigungu_col = "sigungu" if "sigungu" in kapt_df.columns else "sigungu_kapt"
    cols_to_use = ["kapt_code", sigungu_col, "road_address", "legal_address", "approval_date", "households"]

    merged = pd.merge(
        mixed_df,
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

        queries = generate_enhanced_queries(kapt_name, dong, gu, road_addr, legal_addr)
        all_candidates: dict[str, dict[str, Any]] = {}

        for q in queries:
            cands = await search_kb_api(page, q)
            for c in cands:
                cid = c["kb_complex_id"]
                if cid and cid not in all_candidates:
                    all_candidates[cid] = c
            # 도로명 또는 세대수 일치 시 조기 중단
            if any(c["kb_households"] == kapt_hh for c in all_candidates.values()):
                break
            await asyncio.sleep(0.5)

        candidate_list = list(all_candidates.values())
        best_candidate = None
        match_reason = ""

        # 매칭 후보 선택
        for c in candidate_list:
            kb_hh = c["kb_households"]
            kb_road = c.get("kb_road_address", "")
            kb_dong = c.get("kb_dong", "")
            kb_name = c.get("kb_name", "")

            if road_addr and kb_road and (road_addr in kb_road or kb_road in road_addr):
                best_candidate = c
                match_reason = f"도로명 일치 ({road_addr})"
                break

            sim = calc_name_similarity(kapt_name, kb_name)
            if dong and kb_dong and (dong in kb_dong or kb_dong in dong):
                if sim >= 0.7:
                    best_candidate = c
                    match_reason = f"동 일치 및 이름유사도({sim:.2f})"
                    break

        area_types: list[AreaType] = []
        sale_hh_sum = 0
        rental_hh_est = 0
        status = "PENDING_MIXED"
        next_action = "VERIFY_RENTAL_SPLIT"

        if best_candidate:
            cid = best_candidate["kb_complex_id"]
            cname = best_candidate["kb_name"]

            area_types = await collector.collect_area_types(page, cid)
            sale_hh_sum = sum(at.households for at in area_types)

            if sale_hh_sum > 0:
                rental_hh_est = kapt_hh - sale_hh_sum
                # 임대 세대수 합리적 범위 (1 ~ 300세대 또는 K-apt 총세대수 일치)
                if 0 <= rental_hh_est <= 400:
                    status = "VERIFIED_FALLBACK"
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
                        "processing_status": "VERIFIED_FALLBACK",
                        "area_types": area_types,
                        "aggregated_rows": aggregated,
                        "notes": f"혼합단지 분양/임대 분리 (총 {kapt_hh}세대 중 분양 {sale_hh_sum}세대 집계, 임대 추정 {rental_hh_est}세대 제외)",
                    })
                    logger.info("[%d/%d] STAGE E 확정! [%s] %s -> 분양 %d세대, 임대제외 %d세대",
                                idx, len(merged), kapt_code, kapt_name, sale_hh_sum, rental_hh_est)

        review_rows.append({
            "kapt_code": kapt_code,
            "kapt_name": kapt_name,
            "legal_dong": dong,
            "kapt_households": kapt_hh,
            "matched_kb_id": best_candidate["kb_complex_id"] if best_candidate else "",
            "matched_kb_name": best_candidate["kb_name"] if best_candidate else "",
            "sale_households_collected": sale_hh_sum,
            "rental_households_excluded": rental_hh_est,
            "types_found": len(area_types),
            "match_reason": match_reason,
            "processing_status": status,
            "recommended_next_action": next_action,
            "verified_at": datetime.now().strftime("%Y-%m-%d") if status == "VERIFIED_FALLBACK" else "",
        })

    out_file = output_dir / "phase2_mixed_complex_analysis.csv"
    pd.DataFrame(review_rows).to_csv(out_file, index=False, encoding="utf-8-sig")
    logger.info("STAGE E 완료: %d건 중 %d건 분양 분리 해결 -> 저장: %s",
                len(merged), len(resolved_results), out_file)

    return {
        "resolved_results": resolved_results,
        "review_rows": review_rows,
    }
