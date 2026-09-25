"""
STAGE B: 매칭 신뢰도 미달(LOW_MATCH_CONFIDENCE & KB_COMPLEX_AMBIGUOUS) 처리 모듈.

목적:
- 1차 수집 시 점수 미달 또는 모호 판정된 28건 대상.
- 다각도 검색어(도로명주소, 지번, 정규화 단지명, 브랜드명 등)로 KB 단지를 재검색.
- 주소 exact + 세대수 exact, 또는 법정동 + 고유사도 + 세대수 일치 시 VERIFIED_KB_REMATCHED 자동 확정.
- 매칭 확정 단지는 mpriByType로 평형별 세대수·면적·시세 즉시 재수집.
- 출력: data/review/phase2_low_confidence_review.csv
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
from .kb_matcher import calculate_match_score, determine_confidence, calc_name_similarity
from .kb_collector import KBCollector
from .area_normalizer import aggregate_area_types
from .models import AreaType, MatchConfidence

logger = logging.getLogger(__name__)


def generate_enhanced_queries(
    kapt_name: str,
    dong: str,
    gu: str,
    road_address: str,
    legal_address: str,
) -> list[str]:
    """저신뢰 단지를 위한 6단계 다각도 검색 쿼리를 생성한다."""
    queries = []
    core_name = extract_core_name(kapt_name)
    norm_name = normalize_for_search(kapt_name)
    dong_clean = dong.strip() if dong else ""

    # 1. 동명 + 핵심단지명
    if dong_clean and core_name:
        queries.append(f"{dong_clean} {core_name}")

    # 2. 도로명 주소 (도로명 + 번호)
    if road_address:
        parts = road_address.split()
        if len(parts) >= 3:
            # 예: "부산광역시 남구 분포로 145" -> "분포로 145"
            road_core = " ".join(parts[2:4]) if len(parts) >= 4 else parts[-1]
            queries.append(road_core)
            if core_name:
                queries.append(f"{road_core} {core_name}")

    # 3. 핵심 단지명 단독
    if core_name and core_name not in queries:
        queries.append(core_name)

    # 4. 동명 + 정규화단지명
    if dong_clean and norm_name and norm_name != core_name:
        q = f"{dong_clean} {norm_name}"
        if q not in queries:
            queries.append(q)

    # 5. 구명 + 동명 + 핵심단지명
    if gu and dong_clean and core_name:
        q = f"{gu} {dong_clean} {core_name}"
        if q not in queries:
            queries.append(q)

    # 6. 지번 번호 활용
    if legal_address:
        parts = legal_address.split()
        if parts:
            jibun = parts[-1]
            if any(char.isdigit() for char in jibun) and dong_clean:
                q = f"{dong_clean} {jibun}"
                if q not in queries:
                    queries.append(q)

    return queries


async def search_kb_api(page: Page, query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """KB Land 통합검색 API를 브라우저 page.request로 직접 호출한다."""
    import urllib.parse
    results = []
    params = {
        "검색설정명": "SRC_NTOTAL",
        "검색키워드": query,
        "출력갯수": str(max_results),
        "페이지설정값": "1",
    }
    api_url = f"https://api.kbland.kr/land-complex/serch/intgraSerch?{urllib.parse.urlencode(params)}"
    try:
        resp = await page.request.get(
            api_url,
            headers={
                "Referer": "https://kbland.kr/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            timeout=8000,
        )
        if resp.status == 200:
            data = await resp.json()
            hscm_list = (
                data.get("dataBody", {})
                .get("data", {})
                .get("data", {})
                .get("HSCM", {})
                .get("data", [])
            )
            for item in hscm_list:
                cid = str(item.get("COMPLEX_NO", "")).strip()
                name = str(item.get("HSCM_NM", "")).strip()
                addr = str(item.get("BUBADDR", "")).strip()
                road = str(item.get("NEWADDRESS", "")).strip()
                ths_str = str(item.get("THS_NUM", "0")).strip()
                try:
                    hh = int(ths_str)
                except ValueError:
                    hh = 0
                results.append({
                    "kb_complex_id": cid,
                    "kb_name": name,
                    "kb_address": addr,
                    "kb_dong": addr.split()[-1] if addr else "",
                    "kb_road_address": road,
                    "kb_households": hh,
                    "property_type": str(item.get("SLND_PERTY_NM", "")).strip(),
                    "kb_url": f"https://kbland.kr/map?complex={cid}",
                })
    except Exception as e:
        logger.debug("KB 검색 실패 (query=%s): %s", query, e)

    return results


async def process_stage_b_low_confidence(
    page: Page,
    pending_df: pd.DataFrame,
    kapt_df: pd.DataFrame,
    collector: KBCollector,
    output_dir: Path,
) -> dict[str, Any]:
    """
    STAGE B: 매칭 신뢰도 미달(LOW_MATCH_CONFIDENCE + KB_COMPLEX_AMBIGUOUS)을 재검색하고
    확정된 단지는 평형별 데이터를 수집한다.
    """
    logger.info("=== STAGE B: 저신뢰/모호 단지 재검색 및 재매칭 시작 ===")

    target_mask = pending_df["reason_code"].isin(["LOW_MATCH_CONFIDENCE", "KB_COMPLEX_AMBIGUOUS"])
    low_conf_df = pending_df[target_mask].copy()
    logger.info("STAGE B 대상 단지 수: %d개", len(low_conf_df))

    sigungu_col = "sigungu" if "sigungu" in kapt_df.columns else "sigungu_kapt"
    cols_to_use = ["kapt_code", sigungu_col, "road_address", "legal_address", "approval_date", "households"]
    
    # K-apt 상세 정보 조인
    merged = pd.merge(
        low_conf_df,
        kapt_df[cols_to_use],
        on="kapt_code",
        how="left",
        suffixes=("", "_kapt")
    )
    if sigungu_col != "sigungu_name":
        merged["sigungu_name"] = merged[sigungu_col]

    review_rows = []
    rematched_results = []

    for idx, (_, row) in enumerate(merged.iterrows(), start=1):
        kapt_code = str(row["kapt_code"]).strip()
        kapt_name = str(row.get("kapt_name", "")).strip()
        dong = str(row.get("legal_dong", "")).strip()
        gu = str(row.get("sigungu_name", "")).strip()
        road_addr = str(row.get("road_address", "")).strip()
        legal_addr = str(row.get("legal_address", "")).strip()
        kapt_hh = int(row.get("kapt_households", 0) or row.get("households", 0) or 0)
        appr_date = str(row.get("approval_date", "")).strip()

        logger.info("[%d/%d] 재검색: [%s] %s (%s, %d세대)", idx, len(merged), kapt_code, kapt_name, dong, kapt_hh)

        # 다각도 쿼리 생성
        queries = generate_enhanced_queries(kapt_name, dong, gu, road_addr, legal_addr)
        all_candidates: dict[str, dict[str, Any]] = {}

        for q in queries:
            cands = await search_kb_api(page, q)
            for c in cands:
                cid = c["kb_complex_id"]
                if cid and cid not in all_candidates:
                    all_candidates[cid] = c
            # 도로명이나 세대수 일치 후보가 나오면 조기 중단
            if any(c["kb_households"] == kapt_hh for c in all_candidates.values()):
                break
            await asyncio.sleep(0.5)

        candidate_list = list(all_candidates.values())
        best_candidate = None
        match_reason = ""
        is_rematched = False

        # 후보 판정 로직
        for c in candidate_list:
            kb_hh = c["kb_households"]
            kb_road = c.get("kb_road_address", "")
            kb_dong = c.get("kb_dong", "")
            kb_name = c.get("kb_name", "")

            # CASE 1: 도로명 일치 + 세대수 일치
            if road_addr and kb_road and road_addr in kb_road or kb_road in road_addr:
                if kb_hh == kapt_hh and kb_hh > 0:
                    best_candidate = c
                    match_reason = f"도로명 일치 및 세대수 정확 일치 ({kb_hh}세대)"
                    is_rematched = True
                    break

            # CASE 2: 법정동 일치 + 단지명 유사도 0.8+ + 세대수 일치
            sim = calc_name_similarity(kapt_name, kb_name)
            if dong and kb_dong and (dong in kb_dong or kb_dong in dong):
                if sim >= 0.75 and kb_hh == kapt_hh and kb_hh > 0:
                    best_candidate = c
                    match_reason = f"법정동 일치 및 이름유사도({sim:.2f}) + 세대수 일치 ({kb_hh}세대)"
                    is_rematched = True
                    break

        # 재매칭 성공 시 평형 데이터 수집
        area_types: list[AreaType] = []
        status = "PENDING_LOW_CONFIDENCE"
        if is_rematched and best_candidate:
            cid = best_candidate["kb_complex_id"]
            cname = best_candidate["kb_name"]
            logger.info("  -> 매칭 확정! KB ID=%s (%s): %s", cid, cname, match_reason)

            # 수집
            area_types = await collector.collect_area_types(page, cid)
            collected_hh = sum(at.households for at in area_types)

            if collected_hh == kapt_hh:
                status = "VERIFIED_KB_REMATCHED"
                aggregated = aggregate_area_types(kapt_code, area_types)
                rematched_results.append({
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
                logger.info("  -> 평형 수집 및 세대수 검증 PASS: %d개 평형 (%d세대)", len(area_types), collected_hh)
            else:
                status = "PENDING_HOUSEHOLD_MISMATCH"
                logger.warning("  -> 평형 수집 세대수 불일치: KB %d세대 vs K-apt %d세대", collected_hh, kapt_hh)

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
            "verified_at": datetime.now().strftime("%Y-%m-%d") if status == "VERIFIED_KB_REMATCHED" else "",
            "recommended_next_action": "MANUAL_KB_COMPLEX_SELECTION" if status != "VERIFIED_KB_REMATCHED" else "",
        })

    out_file = output_dir / "phase2_low_confidence_review.csv"
    pd.DataFrame(review_rows).to_csv(out_file, index=False, encoding="utf-8-sig")
    logger.info("STAGE B 완료: %d건 중 %d건 VERIFIED_KB_REMATCHED 해결 -> 저장: %s",
                len(merged), len(rematched_results), out_file)

    return {
        "rematched_results": rematched_results,
        "review_rows": review_rows,
    }
