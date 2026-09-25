"""
단지 매칭 및 Match Confidence 계산 모듈.

K-apt 단지 식별 정보(법정동코드, 도로명주소, 지번, 사용승인일, 총세대수)와
건축물대장 표제부 정보를 다각도로 대조하여 신뢰도 점수를 산출합니다.
"""
from __future__ import annotations

import logging
from typing import Any
import pandas as pd

from .normalize import (
    normalize_complex_name,
    parse_bun_ji,
    resolve_address_via_kakao,
)
from .bldrgst_client import BuildingLedgerClient

logger = logging.getLogger(__name__)


def calculate_match_score(
    kapt_info: dict[str, Any],
    title_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    K-apt 단지 정보와 건축물대장 표제부 목록을 대조하여 매칭 신뢰도 점수를 계산합니다.

    점수 가중치 (100점 만점 기준 환산):
    - 법정동코드 일치: +30
    - 지번 일치: +30
    - 도로명 일치: +20
    - 정규화 단지명 일치/포함: +20
    - 총세대수 일치: +15
    - 사용승인일 일치: +10
    """
    if not title_items:
        return {
            "score": 0,
            "confidence": "none",
            "reason": "건축물대장 표제부 조회 결과 없음",
            "matched_title": None,
        }

    kapt_norm_name = normalize_complex_name(kapt_info.get("kapt_name", ""))
    kapt_hh = 0
    try:
        kapt_hh = int(kapt_info.get("total_households", 0) or 0)
    except Exception:
        pass
    kapt_use_date = str(kapt_info.get("approval_date", "")).replace("-", "")[:8]

    best_score = 0
    best_item = None
    best_reasons = []

    for item in title_items:
        score = 0
        reasons = []
        bld_norm_name = normalize_complex_name(item.get("bldNm", ""))

        # 1. 법정동코드 일치 (+30)
        item_bjd = str(item.get("sigunguCd", "")) + str(item.get("bjdongCd", ""))
        target_bjd = str(kapt_info.get("bjd_code", ""))
        if item_bjd and target_bjd and item_bjd == target_bjd:
            score += 30
            reasons.append("bjd_match")

        # 2. 지번 일치 (+30)
        item_bun = str(item.get("bun", "")).zfill(4)
        item_ji = str(item.get("ji", "")).zfill(4)
        target_bun = str(kapt_info.get("bun", "")).zfill(4)
        target_ji = str(kapt_info.get("ji", "")).zfill(4)
        if item_bun == target_bun and item_ji == target_ji:
            score += 30
            reasons.append("lot_match")

        # 3. 단지명 정규화 일치 또는 포함 (+20)
        if kapt_norm_name and bld_norm_name:
            if kapt_norm_name == bld_norm_name:
                score += 20
                reasons.append("exact_name_match")
            elif kapt_norm_name in bld_norm_name or bld_norm_name in kapt_norm_name:
                score += 15
                reasons.append("partial_name_match")

        # 4. 사용승인일 일치 (+10)
        item_use_date = str(item.get("useAprDay", "")).replace("-", "")[:8]
        if kapt_use_date and item_use_date and kapt_use_date == item_use_date:
            score += 10
            reasons.append("use_date_match")

        # 5. 세대수 비교 (+15)
        # 건축물대장 표제부의 hhldCnt (단지 전체 또는 동 단위)
        item_hh = 0
        try:
            item_hh = int(item.get("hhldCnt", 0) or 0)
        except Exception:
            pass
        if kapt_hh > 0 and item_hh == kapt_hh:
            score += 15
            reasons.append("exact_hh_match")
        elif kapt_hh > 0 and item_hh > 0:
            score += 5
            reasons.append("has_hh_info")

        if score > best_score:
            best_score = score
            best_item = item
            best_reasons = reasons

    confidence = "high" if best_score >= 70 else "medium" if best_score >= 50 else "low"
    return {
        "score": best_score,
        "confidence": confidence,
        "reason": "; ".join(best_reasons),
        "matched_title": best_item,
    }


def match_complex(
    kapt_row: pd.Series,
    client: BuildingLedgerClient,
) -> dict[str, Any]:
    """
    단일 K-apt 단지에 대해 건축물대장 대조 및 매칭을 수행합니다.
    """
    kapt_code = str(kapt_row.get("kapt_code", "")).strip()
    kapt_name = str(kapt_row.get("kapt_name", "")).strip()
    raw_bjd = str(kapt_row.get("bjd_code", "")).strip()
    road_addr = str(kapt_row.get("road_address", "")).strip()
    legal_addr = str(kapt_row.get("legal_address", "")).strip()

    # 지번 파싱
    raw_jibun = kapt_row.get("jibun") if "jibun" in kapt_row else None
    bun, ji = parse_bun_ji(str(raw_jibun) if pd.notna(raw_jibun) else legal_addr)

    sigungu_cd = raw_bjd[:5] if len(raw_bjd) >= 5 else ""
    bjdong_cd = raw_bjd[5:10] if len(raw_bjd) >= 10 else ""

    # 도로명주소 기반 카카오 정밀 지번 보완 (필요 시)
    if (not bun or bun == "0000") and road_addr:
        kakao_resolved = resolve_address_via_kakao(road_addr)
        if kakao_resolved:
            bun = kakao_resolved["bun"]
            ji = kakao_resolved["ji"]
            if kakao_resolved["bjd_code"]:
                sigungu_cd = kakao_resolved["bjd_code"][:5]
                bjdong_cd = kakao_resolved["bjd_code"][5:10]

    kapt_info = {
        "kapt_code": kapt_code,
        "kapt_name": kapt_name,
        "bjd_code": f"{sigungu_cd}{bjdong_cd}",
        "sigungu_cd": sigungu_cd,
        "bjdong_cd": bjdong_cd,
        "bun": bun,
        "ji": ji,
        "total_households": kapt_row.get("total_households"),
        "approval_date": kapt_row.get("approval_date"),
        "sale_type": kapt_row.get("sale_type"),
    }

    # 표제부 조회
    title_items = []
    if sigungu_cd and bjdong_cd and bun:
        try:
            title_items = client.get_title_info(sigungu_cd, bjdong_cd, bun, ji)
        except Exception as e:
            logger.warning("표제부 조회 중 오류 (kapt_code=%s): %s", kapt_code, e)

    # 매칭 점수 산출
    match_result = calculate_match_score(kapt_info, title_items)

    return {
        "kapt_code": kapt_code,
        "kapt_name": kapt_name,
        "sigungu_cd": sigungu_cd,
        "bjdong_cd": bjdong_cd,
        "bun": bun,
        "ji": ji,
        "match_score": match_result["score"],
        "match_confidence": match_result["confidence"],
        "match_reason": match_result["reason"],
        "matched_bld_name": match_result["matched_title"].get("bldNm") if match_result["matched_title"] else None,
        "kapt_households": kapt_row.get("total_households"),
        "sale_type": kapt_row.get("sale_type"),
    }
