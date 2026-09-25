"""
STAGE 3C: KB 미발견 단지 (14개 단지) 발굴 및 정밀 매칭 수집 모듈.

발굴 대상 14개 전수 매칭 맵:
1. A10024005 (동래3차 SK VIEW, 999세대): KB ID 41710 (동래3차에스케이뷰) 999세대 exact match (온천장로65번길 9).
2. A61776104 (주례반도보라매머드, 1206세대): KB ID 5680 (반도보라매머드) 1206세대 exact match (백양대로 372).
3. A60879704 (문현현대, 693세대): KB ID 5333 (현대) 693세대 exact match (진남로198번길 9).
4. A61203018 (해운대대림2차, 682세대): KB ID 6150 (대림(2차)) 682세대 exact match (대천로103번길 9).
5. A60482013 (다대몰운대, 2960세대): KB ID 5828 (도시몰운대) 2960세대 exact match (다대낙조2길 216).
6. A10028081 (정관이지더원3차, 1035세대): KB ID 28212 (이지더원3차) 1035세대 exact match (정관로 350).
7. A61996106 (EGthe12차, 756세대): KB ID 24841 (EG더원2차) 756세대 exact match (정관2로 9).
8. A10025154 (명지화전우방아이유쉘, 1515세대): KB ID 319970 (명지화전우방아이유쉘) 1515세대 exact match (화전산단4로 74).
9. A61990514 (기장한신그린코아, 1131세대): KB ID 478625 (한신) 1131세대 exact match (차성로344번길 13).
10. A61970311 (기장서부주공, 702세대): KB ID 6235 (주공) 702세대 exact match (차성서로 123).
11. A61990110 (정관신도시이지더원1차, 978세대): KB ID 23424 (EG더원) 978세대 exact match (정관1로 18).
12. A61990609 (기장2주공, 520세대): KB ID 6233 (주공(기장제2주공)) 520세대 exact match (청강로 6).
13. A61282215 (대우마리나1,2차, 1164세대): 복합 단지 = 1차(KB 6106, 714) + 2차(KB 6107, 450) = 1164세대 exact match.
14. A60701004 (명륜아이파크, 1409세대): 복합 단지 = 1단지(KB 25211, 1139) + 2단지(KB 25213, 270) = 1409세대 exact match.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pandas as pd
from playwright.async_api import Page

from .kb_collector import KBCollector
from .area_normalizer import aggregate_area_types
from .exporter import build_master_row

logger = logging.getLogger(__name__)

STAGE_3C_DISCOVERIES: dict[str, dict[str, Any]] = {
    "A10024005": {
        "complexes": [{"kb_id": "41710", "kb_name": "동래3차에스케이뷰", "households": 999}],
        "reason": "도로명(온천장로65번길 9) 및 아파트 999세대 정확 일치",
    },
    "A61776104": {
        "complexes": [{"kb_id": "5680", "kb_name": "반도보라매머드", "households": 1206}],
        "reason": "도로명(백양대로 372) 및 세대수 1206세대 정확 일치",
    },
    "A60879704": {
        "complexes": [{"kb_id": "5333", "kb_name": "현대", "households": 693}],
        "reason": "도로명(진남로198번길 9) 및 세대수 693세대 정확 일치",
    },
    "A61203018": {
        "complexes": [{"kb_id": "6150", "kb_name": "대림(2차)", "households": 682}],
        "reason": "해운대 좌동 대천로103번길 9 대림2차 682세대 정확 일치",
    },
    "A60482013": {
        "complexes": [{"kb_id": "5828", "kb_name": "도시몰운대", "households": 2960}],
        "reason": "사하구 다대낙조2길 216 도시몰운대 2960세대 정확 일치",
    },
    "A10028081": {
        "complexes": [{"kb_id": "28212", "kb_name": "이지더원3차", "households": 1035}],
        "reason": "기장군 정관읍 정관로 350 이지더원3차 1035세대 정확 일치",
    },
    "A61996106": {
        "complexes": [{"kb_id": "24841", "kb_name": "EG더원2차", "households": 756}],
        "reason": "기장군 정관읍 정관2로 9 EG더원2차 756세대 정확 일치",
    },
    "A10025154": {
        "complexes": [{"kb_id": "319970", "kb_name": "명지화전우방아이유쉘", "households": 1515}],
        "reason": "강서구 화전산단4로 74 우방아이유쉘 1515세대 정확 일치",
    },
    "A61990514": {
        "complexes": [{"kb_id": "478625", "kb_name": "한신", "households": 1131}],
        "reason": "기장군 기장읍 차성로344번길 13 한신 1131세대(통합) 정확 일치",
    },
    "A61970311": {
        "complexes": [{"kb_id": "6235", "kb_name": "주공", "households": 702}],
        "reason": "기장군 기장읍 차성서로 123 서부주공 702세대 정확 일치",
    },
    "A61990110": {
        "complexes": [{"kb_id": "23424", "kb_name": "EG더원", "households": 978}],
        "reason": "기장군 정관읍 정관1로 18 EG더원 978세대 정확 일치",
    },
    "A61990609": {
        "complexes": [{"kb_id": "6233", "kb_name": "주공(기장제2주공)", "households": 520}],
        "reason": "기장군 기장읍 청강로 6 기장제2주공 520세대 정확 일치",
    },
    "A61282215": {
        "complexes": [
            {"kb_id": "6106", "kb_name": "대우마리나(1차)", "households": 714},
            {"kb_id": "6107", "kb_name": "대우마리나(2차)", "households": 450},
        ],
        "reason": "대우마리나 1차(714) + 2차(450) 세대수 합계 1164세대 정확 일치",
    },
    "A60701004": {
        "complexes": [
            {"kb_id": "25211", "kb_name": "명륜IPARK1단지", "households": 1139},
            {"kb_id": "25213", "kb_name": "명륜IPARK2단지", "households": 270},
        ],
        "reason": "명륜아이파크 1단지(1139) + 2단지(270) 세대수 합계 1409세대 정확 일치",
    },
}


async def process_stage_3c(
    page: Page,
    stage_c_complexes: list[dict[str, Any]],
    collector: KBCollector,
    logger: logging.Logger,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    STAGE 3C 실행:
    반환: (verified_master_rows, still_pending_records, resolution_records, provenance_records)
    """
    logger.info("=== STAGE 3C: KB 미발견 단지 (%d개) 발굴 및 정밀 매칭 시작 ===", len(stage_c_complexes))
    verified_master_rows = []
    still_pending_records = []
    resolution_records = []
    provenance_records = []

    for idx, row in enumerate(stage_c_complexes, 1):
        kapt_code = str(row["kapt_code"])
        kapt_name = str(row["kapt_name"])
        dong = str(row.get("legal_dong", ""))
        road = str(row.get("road_address", ""))
        kapt_hh = int(row.get("total_households", 0))

        logger.info("[%d/%d] STAGE 3C 발굴 검토: [%s] %s (%s, %d세대)", idx, len(stage_c_complexes), kapt_code, kapt_name, dong, kapt_hh)

        if kapt_code in STAGE_3C_DISCOVERIES:
            disc = STAGE_3C_DISCOVERIES[kapt_code]
            c_list = disc["complexes"]
            match_reason = disc["reason"]

            all_types = []
            kb_ids = []
            kb_names = []
            for c in c_list:
                t_list = await collector.collect_area_types(page, c["kb_id"])
                all_types.extend(t_list)
                kb_ids.append(c["kb_id"])
                kb_names.append(c["kb_name"])

            sum_hh = sum(t.households for t in all_types)
            logger.info("  -> 발굴 평형 수집 완료: %d개 평형 (합계: %d세대, 목표: %d세대)", len(all_types), sum_hh, kapt_hh)

            if sum_hh == kapt_hh and all_types:
                aggregated = aggregate_area_types(kapt_code, all_types)
                master_rows = [build_master_row(kapt_code, ar) for ar in aggregated]
                verified_master_rows.extend(master_rows)

                resolution_records.append({
                    "kapt_code": kapt_code,
                    "kapt_name": kapt_name,
                    "legal_dong": dong,
                    "road_address": road,
                    "kapt_households": kapt_hh,
                    "matched_kb_id": "+".join(kb_ids),
                    "matched_kb_name": "+".join(kb_names),
                    "matched_kb_households": sum_hh,
                    "match_method": "phase3_kb_discovery_match",
                    "match_confidence": "HIGH",
                    "processing_status": "VERIFIED_KB_REMATCHED",
                    "match_reason": match_reason,
                    "recommended_next_action": "NONE",
                    "verified_at": "2026-09-18",
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
                        "source_name": f"KB부동산 ({'+'.join(kb_names)})",
                        "source_url": f"https://kbland.kr/map?complex={c_list[0]['kb_id']}",
                        "source_page": "",
                        "kb_complex_id": "+".join(kb_ids),
                        "kb_type_id": "",
                        "kapt_total_households": kapt_hh,
                        "collected_total_households": sum_hh,
                        "sale_households": ar["households"],
                        "rental_households": 0,
                        "match_method": "phase3_kb_discovery_match",
                        "match_confidence": "HIGH",
                        "verification_method": "exact_household_discovery",
                        "verified_at": "2026-09-18",
                        "notes": match_reason,
                    })
                continue

        # 미발견 잔여
        still_pending_records.append({
            "kapt_code": kapt_code,
            "kapt_name": kapt_name,
            "legal_dong": dong,
            "kapt_households": kapt_hh,
            "original_reason_code": "KB_COMPLEX_NOT_FOUND",
            "recommended_next_action": "CHECK_OFFICIAL_SALE_NOTICE",
            "review_status": "STILL_PENDING",
        })

    logger.info("STAGE 3C 완료: %d개 단지 전수 발굴 및 해결 완료 (보류: %d개)", len(resolution_records), len(still_pending_records))
    return verified_master_rows, still_pending_records, resolution_records, provenance_records
