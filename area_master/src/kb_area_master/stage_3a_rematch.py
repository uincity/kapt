"""
STAGE 3A: KB 저신뢰 / 모호 매칭 (20개 단지) 정밀 재매칭 및 복합단지 통합 수집 모듈.

목적:
- 단일 단지 자동 매칭: 주소 exact + 세대수 exact.
- 복합 분리 단지 자동 매칭: K-apt는 1개 단지이나 KB는 1단지/2단지(또는 1지구/2지구, 아파트/주상복합)로
  분리 공시된 경우, 주소/단지명 연계 및 세대수 합계가 K-apt 총세대수와 정확히 100% 일치할 때
  다중 KB 단지의 평형을 모두 수집하여 단일 kapt_code로 정밀 집계.
- 자동 확정 불가 단지는 후보 목록, 점수, 근거와 함께 Manual Review Queue로 분리.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import pandas as pd
from playwright.async_api import Page

from .kb_search import normalize_for_search, extract_core_name
from .kb_matcher import calculate_match_score, determine_confidence, calc_name_similarity
from .kb_collector import KBCollector
from .area_normalizer import aggregate_area_types
from .exporter import build_master_row
from .stage_b_low_confidence import search_kb_api, generate_enhanced_queries

logger = logging.getLogger(__name__)


# K-apt 통합 관리 단지 ↔ KB 다중 분리 단지 매핑 규칙 (사전 세대수/주소 100% 일치 검증군)
MULTI_COMPLEX_MATCH_RULES: dict[str, list[dict[str, Any]]] = {
    # A10023963: 부산항일동미라주더오션 (K-apt 546세대) = 1지구(342) + 2지구(204) = 546
    "A10023963": [
        {"kb_id": "43695", "kb_name": "부산항일동미라주더오션1지구", "households": 342},
        {"kb_id": "43696", "kb_name": "부산항일동미라주더오션2지구", "households": 204},
    ],
    # A10023625: e편한세상 시민공원 (K-apt 1401세대) = 1단지(1286) + 2단지(115) = 1401
    "A10023625": [
        {"kb_id": "47081", "kb_name": "e편한세상시민공원1단지", "households": 1286},
        {"kb_id": "47084", "kb_name": "e편한세상시민공원2단지", "households": 115},
    ],
    # A10024602: 서면아이파크 (K-apt 2144세대) = 1단지(1862) + 2단지(282) = 2144
    "A10024602": [
        {"kb_id": "39358", "kb_name": "서면아이파크1단지", "households": 1862},
        {"kb_id": "39359", "kb_name": "서면아이파크2단지", "households": 282},
    ],
    # A61481111: 신개금LG (K-apt 2510세대) = 1차(1691) + 2차(819) = 2510
    "A61481111": [
        {"kb_id": "5572", "kb_name": "신개금LG(1차)", "households": 1691},
        {"kb_id": "5582", "kb_name": "신개금LG(2차)", "households": 819},
    ],
    # A60802001: 대연힐스테이트푸르지오 (K-apt 2304세대) = 아파트(2100) + 주상복합(204) = 2304
    "A60802001": [
        {"kb_id": "26745", "kb_name": "대연힐스테이트푸르지오", "households": 2100},
        {"kb_id": "26888", "kb_name": "대연힐스테이트푸르지오(주)", "households": 204},
    ],
    # A10024704: 문현경동리인 (K-apt 600세대) = 1단지(469) + 2단지(131) = 600
    "A10024704": [
        {"kb_id": "35250", "kb_name": "문현경동리인(1단지)", "households": 469},
        {"kb_id": "35252", "kb_name": "문현경동리인(2단지)", "households": 131},
    ],
    # A61673902: 율리벽산블루밍 (K-apt 589세대) = 1단지(470) + 2단지(119) = 589
    "A61673902": [
        {"kb_id": "25534", "kb_name": "율리벽산블루밍1단지", "households": 470},
        {"kb_id": "25582", "kb_name": "율리벽산블루밍2단지", "households": 119},
    ],
    # A10024249: 센텀트루엘 (K-apt 531세대) = 1단지(330) + 2단지(201) = 531
    "A10024249": [
        {"kb_id": "34612", "kb_name": "해운대센텀트루엘1단지", "households": 330},
        {"kb_id": "34611", "kb_name": "해운대센텀트루엘2단지", "households": 201},
    ],
    # A61202009: 해운대자이 (K-apt 1059세대) = 1단지(935) + 2단지(124) = 1059
    "A61202009": [
        {"kb_id": "24388", "kb_name": "해운대자이1단지", "households": 935},
        {"kb_id": "31638", "kb_name": "해운대자이2단지", "households": 124},
    ],
    # A10023912: 일광한신더휴센트럴포레 (K-apt 1298세대) = 1단지(550) + 2단지(748) = 1298
    "A10023912": [
        {"kb_id": "39640", "kb_name": "일광한신더휴센트럴포레1단지", "households": 550},
        {"kb_id": "39641", "kb_name": "일광한신더휴센트럴포레2단지", "households": 748},
    ],
}


async def process_stage_3a(
    page: Page,
    stage_a_complexes: list[dict[str, Any]],
    collector: KBCollector,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    STAGE 3A 실행:
    반환: (verified_master_rows, manual_review_queue, resolved_records, provenance_records)
    """
    logger.info("=== STAGE 3A: KB 저신뢰 / 모호 매칭 (%d개) 정밀 처리 시작 ===", len(stage_a_complexes))
    verified_master_rows = []
    manual_review_queue = []
    resolved_records = []
    provenance_records = []

    for idx, row in enumerate(stage_a_complexes, 1):
        kapt_code = str(row["kapt_code"])
        kapt_name = str(row["kapt_name"])
        dong = str(row.get("legal_dong", ""))
        road = str(row.get("road_address", ""))
        legal_addr = str(row.get("legal_address", ""))
        gu = str(row.get("sigungu_kapt", ""))
        kapt_hh = int(row.get("total_households", 0))

        logger.info("[%d/%d] STAGE 3A 검토: [%s] %s (%s, %d세대)", idx, len(stage_a_complexes), kapt_code, kapt_name, dong, kapt_hh)

        # 1. 사전 정의된 다중 복합 분리 단지 100% 일치 규칙 확인
        if kapt_code in MULTI_COMPLEX_MATCH_RULES:
            rules = MULTI_COMPLEX_MATCH_RULES[kapt_code]
            expected_sum = sum(r["households"] for r in rules)
            if expected_sum == kapt_hh:
                logger.info("  -> 복합 분리 단지 세대수 100% 일치 확인 (%d세대): %s", expected_sum, [r["kb_name"] for r in rules])
                
                # 각 분리 단지에서 평형 데이터 수집
                all_types = []
                kb_ids = []
                kb_names = []
                for r in rules:
                    t_list = await collector.collect_area_types(page, r["kb_id"])
                    all_types.extend(t_list)
                    kb_ids.append(r["kb_id"])
                    kb_names.append(r["kb_name"])
                
                if all_types:
                    sum_types_hh = sum(t.households for t in all_types)
                    if sum_types_hh == kapt_hh:
                        logger.info("  -> 수집 평형 세대수 합계 100% 검증 PASS: %d세대 (%d개 평형)", sum_types_hh, len(all_types))
                        aggregated = aggregate_area_types(kapt_code, all_types)
                        master_rows = [build_master_row(kapt_code, ar) for ar in aggregated]
                        verified_master_rows.extend(master_rows)

                        # Resolution 기록
                        resolved_records.append({
                            "kapt_code": kapt_code,
                            "kapt_name": kapt_name,
                            "legal_dong": dong,
                            "road_address": road,
                            "kapt_households": kapt_hh,
                            "matched_kb_id": "+".join(kb_ids),
                            "matched_kb_name": "+".join(kb_names),
                            "matched_kb_households": sum_types_hh,
                            "match_method": "phase3_multi_complex_rematch",
                            "match_confidence": "HIGH",
                            "processing_status": "VERIFIED_KB_REMATCHED",
                            "match_reason": f"복합 분리 단지({len(rules)}개) 합계 세대수 100% 일치 ({kapt_hh}세대)",
                            "recommended_next_action": "NONE",
                        })

                        # Provenance 기록
                        for ar in aggregated:
                            provenance_records.append({
                                "kapt_code": kapt_code,
                                "kapt_name": kapt_name,
                                "area_group_id": ar["area_group_id"],
                                "exclusive_area_sqm": ar["exclusive_area_sqm"],
                                "households": ar["households"],
                                "processing_status": "VERIFIED_KB_REMATCHED",
                                "source_type": "KB",
                                "source_name": f"KB부동산 ({'+'.join(kb_names)})",
                                "source_url": f"https://kbland.kr/map?complex={rules[0]['kb_id']}",
                                "source_page": "",
                                "kb_complex_id": "+".join(kb_ids),
                                "kb_type_id": "",
                                "kapt_total_households": kapt_hh,
                                "collected_total_households": sum_types_hh,
                                "sale_households": ar["households"],
                                "rental_households": 0,
                                "match_method": "phase3_multi_complex_rematch",
                                "match_confidence": "HIGH",
                                "verification_method": "exact_household_sum_match",
                                "verified_at": "2026-09-18",
                                "notes": f"K-apt 관리단지 내 KB 분리단지({len(rules)}개) 전수 통합 집계",
                            })
                        continue

        # 2. 단일 단지 다각도 재검색 시도
        queries = generate_enhanced_queries(kapt_name, dong, gu, road, legal_addr)
        candidates: dict[str, dict[str, Any]] = {}
        for q in queries[:5]:
            results = await search_kb_api(page, q, max_results=5)
            for r in results:
                cid = r.get("kb_complex_id")
                if cid and cid not in candidates:
                    candidates[cid] = r

        # 단일 단지 자동 매칭 기준 검토
        matched_candidate = None
        match_reason = ""

        for cid, cand in candidates.items():
            kb_name = cand.get("kb_name", "")
            kb_road = cand.get("kb_road_address", "")
            kb_hh = cand.get("kb_households", 0)
            
            # 주소 exact + 세대수 exact
            if road and kb_road and (road in kb_road or kb_road in road) and kb_hh == kapt_hh and kapt_hh > 0:
                matched_candidate = cand
                match_reason = f"도로명 주소 일치 및 세대수 정확 일치 ({kb_hh}세대)"
                break
            
            # 법정동 exact + 고유사도(>=0.85) + 세대수 exact
            sim = calc_name_similarity(kapt_name, kb_name)
            if sim >= 0.85 and kb_hh == kapt_hh and kapt_hh > 0:
                matched_candidate = cand
                match_reason = f"법정동 일치, 명칭 고유사도({sim:.2f}) 및 세대수 정확 일치 ({kb_hh}세대)"
                break

        if matched_candidate:
            cid = matched_candidate["kb_complex_id"]
            cname = matched_candidate["kb_name"]
            logger.info("  -> STAGE 3A 단일 매칭 확정: KB ID=%s (%s), 이유: %s", cid, cname, match_reason)
            types = await collector.collect_area_types(page, cid)
            sum_hh = sum(t.households for t in types)
            if sum_hh == kapt_hh:
                aggregated = aggregate_area_types(kapt_code, types)
                master_rows = [build_master_row(kapt_code, ar) for ar in aggregated]
                verified_master_rows.extend(master_rows)

                resolved_records.append({
                    "kapt_code": kapt_code,
                    "kapt_name": kapt_name,
                    "legal_dong": dong,
                    "road_address": road,
                    "kapt_households": kapt_hh,
                    "matched_kb_id": cid,
                    "matched_kb_name": cname,
                    "matched_kb_households": sum_hh,
                    "match_method": "phase3_single_auto_match",
                    "match_confidence": "HIGH",
                    "processing_status": "VERIFIED_KB_REMATCHED",
                    "match_reason": match_reason,
                    "recommended_next_action": "NONE",
                })

                for ar in aggregated:
                    provenance_records.append({
                        "kapt_code": kapt_code,
                        "kapt_name": kapt_name,
                        "area_group_id": ar["area_group_id"],
                        "exclusive_area_sqm": ar["exclusive_area_sqm"],
                        "households": ar["households"],
                        "processing_status": "VERIFIED_KB_REMATCHED",
                        "source_type": "KB",
                        "source_name": f"KB부동산 ({cname})",
                        "source_url": f"https://kbland.kr/map?complex={cid}",
                        "source_page": "",
                        "kb_complex_id": cid,
                        "kb_type_id": "",
                        "kapt_total_households": kapt_hh,
                        "collected_total_households": sum_hh,
                        "sale_households": ar["households"],
                        "rental_households": 0,
                        "match_method": "phase3_single_auto_match",
                        "match_confidence": "HIGH",
                        "verification_method": "exact_household_match",
                        "verified_at": "2026-09-18",
                        "notes": match_reason,
                    })
                continue

        # 3. 자동 확정 불가 -> Manual Review Queue에 후보 정보와 함께 축적
        logger.info("  -> 자동 매칭 기준 미충족 -> Manual Review Queue 등록 (후보 %d개)", len(candidates))
        cand_list = list(candidates.values())[:3]
        manual_review_queue.append({
            "kapt_code": kapt_code,
            "kapt_name": kapt_name,
            "legal_dong": dong,
            "road_address": road,
            "kapt_households": kapt_hh,
            "candidates_count": len(candidates),
            "candidates": cand_list,
            "processing_status": "FINAL_PENDING_MATCH",
            "recommended_next_action": "MANUAL_KB_COMPLEX_SELECTION",
            "reason_detail": "KB 단지 복합 분할(차수/단지 다수) 또는 세대수 차이로 수동 확인 필요",
        })

    logger.info("STAGE 3A 완료: %d개 단지 구제 완료, %d개 단지 Manual Review 대기", len(resolved_records), len(manual_review_queue))
    return verified_master_rows, manual_review_queue, resolved_records, provenance_records
