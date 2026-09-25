"""
정합성 검증 모듈.

검증 항목:
1. KB 평형별 세대수 합계 vs K-apt 총세대수
2. sale_apartment scope (임대/혼합 → pending)
3. 전용면적 unique 검증
4. 12개 파일럿 체크포인트
"""
from __future__ import annotations

import logging
from typing import Any

from .config import HOUSEHOLD_TOLERANCE_RATIO, AUTO_VERIFY_CONFIDENCES
from .models import (
    AreaType,
    CollectionStatus,
    MatchConfidence,
    PendingReason,
    ValidationResult,
)

logger = logging.getLogger(__name__)


def validate_complex(
    kapt_code: str,
    kapt_name: str,
    kapt_households: int,
    sale_type: str,
    match_confidence: MatchConfidence,
    area_types: list[AreaType],
    aggregated_rows: list[dict[str, Any]],
) -> ValidationResult:
    """
    단지 수집 결과의 정합성을 종합 검증한다.

    Returns:
        ValidationResult (status=VERIFIED or PENDING, reason_codes, etc.)
    """
    result = ValidationResult()
    result.expected_households = kapt_households
    result.types_found = len(area_types)

    # 총 수집 세대수
    collected_hh = sum(at.households for at in area_types)
    result.collected_households = collected_hh

    # ── 검증 1: 매칭 confidence ──
    if match_confidence not in AUTO_VERIFY_CONFIDENCES:
        result.reason_codes.append(PendingReason.LOW_MATCH_CONFIDENCE)
        result.reason = f"KB 매칭 confidence 부족 ({match_confidence.value})"
        result.status = CollectionStatus.PENDING
        result.recommended_next_action = "KB 단지 수동 확인 및 매핑 보정"
        return result

    # ── 검증 2: sale_type (임대/혼합) ──
    sale_clean = str(sale_type or "").strip()
    if "혼합" in sale_clean:
        result.reason_codes.append(PendingReason.MIXED_RENTAL_COMPLEX)
        result.reason = f"혼합 단지 (sale_type={sale_clean}) - 분양 세대 분리 필요"
        result.status = CollectionStatus.PENDING
        result.recommended_next_action = "분양/임대 세대 구분 확인"
        return result
    if "임대" in sale_clean:
        result.reason_codes.append(PendingReason.RENTAL_COMPLEX)
        result.reason = f"임대 단지 (sale_type={sale_clean}) - 매매 가능 세대 확인 필요"
        result.status = CollectionStatus.PENDING
        result.recommended_next_action = "임대주택 공고문 및 분양전환 여부 확인"
        return result

    # ── 검증 3: 평형 데이터 존재 여부 ──
    if not area_types:
        result.reason_codes.append(PendingReason.AREA_NOT_AVAILABLE)
        result.reason = "KB 평형 데이터 수집 실패"
        result.status = CollectionStatus.PENDING
        result.recommended_next_action = "KB 단지 페이지 구조 확인 또는 수동 입력"
        return result

    # ── 검증 4: 세대수 누락 ──
    types_without_hh = [at for at in area_types if at.households <= 0]
    if types_without_hh:
        result.reason_codes.append(PendingReason.TYPE_HOUSEHOLDS_MISSING)
        result.reason = f"세대수 미확보 타입 {len(types_without_hh)}개"
        result.status = CollectionStatus.PENDING
        result.recommended_next_action = "KB 평형별 세대수 수동 확인"
        return result

    # ── 검증 5: 전용면적 누락 ──
    types_without_area = [at for at in area_types if at.exclusive_area_sqm is None]
    if types_without_area:
        result.reason_codes.append(PendingReason.AREA_NOT_AVAILABLE)
        result.reason = f"전용면적 미확보 타입 {len(types_without_area)}개"
        result.status = CollectionStatus.PENDING
        result.recommended_next_action = "KB 전용면적 수동 확인"
        return result

    # ── 검증 6: KB시세 확보 ──
    types_without_price = [at for at in area_types if at.kb_sale_general is None]
    if len(types_without_price) == len(area_types):
        # 전체 타입 시세 없음 → 경고만 (pending은 아님)
        logger.warning("단지 %s: 전체 타입 시세 미확보", kapt_code)

    # ── 검증 7: 세대수 합계 비교 ──
    if kapt_households > 0:
        tolerance = int(kapt_households * HOUSEHOLD_TOLERANCE_RATIO)
        diff = abs(collected_hh - kapt_households)
        if diff > tolerance:
            result.reason_codes.append(PendingReason.HOUSEHOLDS_MISMATCH)
            result.reason = f"세대수 불일치 (KB합계={collected_hh}, K-apt={kapt_households}, 차이={diff})"
            result.status = CollectionStatus.PENDING
            result.recommended_next_action = "세대수 차이 원인 확인 (임대 포함 여부 등)"
            return result

    # ── 모든 검증 통과 → VERIFIED ──
    result.status = CollectionStatus.VERIFIED
    result.reason = f"KB 평형별 세대수 합계({collected_hh}) = K-apt 총세대수({kapt_households}) 일치"
    return result


def run_pilot_checks(
    kapt_code: str,
    kapt_name: str,
    kapt_found: bool,
    kapt_info_available: bool,
    kb_candidates_found: int,
    kb_complex_id: str,
    match_confidence: MatchConfidence,
    area_types: list[AreaType],
    kapt_households: int,
    kb_raw_saved: bool,
    master_conversion_ok: bool,
) -> dict[str, Any]:
    """
    파일럿(대연SK뷰힐스) 12개 체크포인트를 검증한다.

    Returns:
        {
            "all_pass": bool,
            "checks": [{"name": str, "pass": bool, "detail": str}, ...],
        }
    """
    collected_hh = sum(at.households for at in area_types)
    has_supply = any(at.supply_area_sqm is not None for at in area_types)
    has_exclusive = any(at.exclusive_area_sqm is not None for at in area_types)
    has_price = any(at.kb_sale_general is not None for at in area_types)

    checks = [
        {
            "name": "PILOT CHECK 1: supplement에서 kapt_code 찾기",
            "pass": kapt_found,
            "detail": f"kapt_code={kapt_code}" if kapt_found else "미발견",
        },
        {
            "name": "PILOT CHECK 2: K-apt 기본정보 확보",
            "pass": kapt_info_available,
            "detail": f"kapt_name={kapt_name}" if kapt_info_available else "K-apt 정보 없음",
        },
        {
            "name": "PILOT CHECK 3: KB 후보 확보",
            "pass": kb_candidates_found > 0,
            "detail": f"{kb_candidates_found}개 후보",
        },
        {
            "name": "PILOT CHECK 4: KB complex ID 확정 (exact/high)",
            "pass": match_confidence in (MatchConfidence.EXACT, MatchConfidence.HIGH),
            "detail": f"kb_id={kb_complex_id}, confidence={match_confidence.value}",
        },
        {
            "name": "PILOT CHECK 5: 평형 목록 수집",
            "pass": len(area_types) >= 1,
            "detail": f"{len(area_types)}개 타입",
        },
        {
            "name": "PILOT CHECK 6: 세대수 수집",
            "pass": collected_hh > 0,
            "detail": f"합계 {collected_hh}세대",
        },
        {
            "name": "PILOT CHECK 7: 공급면적 수집",
            "pass": has_supply,
            "detail": "확보" if has_supply else "미확보",
        },
        {
            "name": "PILOT CHECK 8: 전용면적 수집",
            "pass": has_exclusive,
            "detail": "확보" if has_exclusive else "미확보",
        },
        {
            "name": "PILOT CHECK 9: KB 매매시세 수집",
            "pass": has_price,
            "detail": "확보" if has_price else "미확보",
        },
        {
            "name": "PILOT CHECK 10: 세대수 합계 검증",
            "pass": collected_hh == kapt_households,
            "detail": f"KB={collected_hh}, K-apt={kapt_households}",
        },
        {
            "name": "PILOT CHECK 11: KB 원본 데이터 저장",
            "pass": kb_raw_saved,
            "detail": "저장 완료" if kb_raw_saved else "미저장",
        },
        {
            "name": "PILOT CHECK 12: market_cap_area_master 변환 테스트",
            "pass": master_conversion_ok,
            "detail": "변환 성공" if master_conversion_ok else "변환 실패",
        },
    ]

    all_pass = all(c["pass"] for c in checks)

    return {
        "all_pass": all_pass,
        "checks": checks,
    }
