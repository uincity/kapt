"""
자동 검증 및 verification_status 판정 모듈.

총세대수 일치 검증, 면적 구간별 검증, 혼합/임대 단지 분리, 매칭 신뢰도 평가를 통해
보수적으로 'verified' 또는 'pending'을 판정하고 예외 사유를 명시합니다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
import pandas as pd


def validate_complex_and_areas(
    kapt_info: dict[str, Any],
    match_info: dict[str, Any],
    area_rows: list[dict[str, Any]],
    collected_households: int,
) -> dict[str, Any]:
    """
    단지와 집계된 평형별 세대수 데이터의 정합성을 검증합니다.

    Returns
    -------
    dict[str, Any]
        {
            "status": "verified" | "pending",
            "scope": "sale_apartment" | "rental_apartment" | "unknown",
            "reason": str,
            "recommended_next_source": str,
            "kapt_households": int,
            "collected_households": int,
            "sale_households": int | None,
        }
    """
    kapt_code = kapt_info.get("kapt_code")
    sale_type = str(kapt_info.get("sale_type", "") or "").strip()
    kapt_hh = int(kapt_info.get("total_households", 0) or 0)
    match_score = match_info.get("match_score", 0)
    match_confidence = match_info.get("match_confidence", "low")

    # 1. 단지 매칭 신뢰도 검증
    if match_score < 60 or match_confidence == "low":
        return {
            "status": "pending",
            "scope": "sale_apartment",
            "reason": f"단지 매칭 신뢰도 부족 (score={match_score}, confidence={match_confidence})",
            "recommended_next_source": "공식 지번 재확인 및 건축물대장 수기 대조",
            "kapt_households": kapt_hh,
            "collected_households": collected_households,
            "sale_households": None,
        }

    # 2. 전용면적 데이터 수집 여부
    if not area_rows or collected_households == 0:
        return {
            "status": "pending",
            "scope": "sale_apartment",
            "reason": "건축물대장 전유부 전용면적 세대수 정보 부재",
            "recommended_next_source": "건축HUB 주택인허가 관리공동형별개요 또는 청약홈 입주자모집공고",
            "kapt_households": kapt_hh,
            "collected_households": collected_households,
            "sale_households": None,
        }

    # 3. 면적 그룹 ID 단지 내 고유성 검사
    group_ids = [r["area_group_id"] for r in area_rows]
    if len(group_ids) != len(set(group_ids)):
        return {
            "status": "pending",
            "scope": "sale_apartment",
            "reason": "단지 내 area_group_id 중복 발생",
            "recommended_next_source": "동일 전용면적 중복 행 병합 로직 검토",
            "kapt_households": kapt_hh,
            "collected_households": collected_households,
            "sale_households": None,
        }

    # 4. 임대 및 혼합 단지 판정 (자동 verified 절대 금지)
    if "혼합" in sale_type:
        return {
            "status": "pending",
            "scope": "sale_apartment",
            "reason": f"혼합 단지 (분양+임대 혼합, sale_type={sale_type}) - 분양 세대 분리 필요",
            "recommended_next_source": "LH/BMC 공급자료 또는 입주자모집공고",
            "kapt_households": kapt_hh,
            "collected_households": collected_households,
            "sale_households": None,
        }

    if "임대" in sale_type:
        return {
            "status": "pending",
            "scope": "rental_apartment",
            "reason": f"임대 단지 (sale_type={sale_type}) - 매매 가능 세대(sale_apartment) 부재 또는 미확인",
            "recommended_next_source": "임대주택 공고문 및 분양전환 여부 확인",
            "kapt_households": kapt_hh,
            "collected_households": collected_households,
            "sale_households": 0,
        }

    # 5. 일반 분양 단지의 세대수 합계 일치 검증
    if collected_households != kapt_hh:
        return {
            "status": "pending",
            "scope": "sale_apartment",
            "reason": f"총세대수 불일치 (건축물대장={collected_households}세대, K-apt={kapt_hh}세대)",
            "recommended_next_source": "건축물대장 동별 집계 확인 및 부속건물 확인",
            "kapt_households": kapt_hh,
            "collected_households": collected_households,
            "sale_households": None,
        }

    # 6. K-apt 면적 구간별 세대수 교차 검증
    # K-apt: 60㎡이하, 60~85㎡, 85~135㎡, 135㎡초과
    kapt_60 = float(kapt_info.get("kapt_mparea_60", 0) or 0)
    kapt_85 = float(kapt_info.get("kapt_mparea_85", 0) or 0)
    kapt_135 = float(kapt_info.get("kapt_mparea_135", 0) or 0)
    kapt_136 = float(kapt_info.get("kapt_mparea_136", 0) or 0)

    # 집계 데이터의 구간별 세대수 계산
    calc_60, calc_85, calc_135, calc_136 = 0, 0, 0, 0
    for r in area_rows:
        area_dec = r["exclusive_area_decimal"]
        cnt = r["households"]
        if area_dec <= Decimal("60"):
            calc_60 += cnt
        elif area_dec <= Decimal("85"):
            calc_85 += cnt
        elif area_dec <= Decimal("135"):
            calc_135 += cnt
        else:
            calc_136 += cnt

    # K-apt 구간 정보가 기재되어 있는 경우 교차 대조
    if (kapt_60 + kapt_85 + kapt_135 + kapt_136) > 0:
        bucket_mismatch = []
        if kapt_60 > 0 and calc_60 != kapt_60:
            bucket_mismatch.append(f"60㎡이하(K-apt={kapt_60}, 대장={calc_60})")
        if kapt_85 > 0 and calc_85 != kapt_85:
            bucket_mismatch.append(f"60~85㎡(K-apt={kapt_85}, 대장={calc_85})")
        if kapt_135 > 0 and calc_135 != kapt_135:
            bucket_mismatch.append(f"85~135㎡(K-apt={kapt_135}, 대장={calc_135})")
        if kapt_136 > 0 and calc_136 != kapt_136:
            bucket_mismatch.append(f"135㎡초과(K-apt={kapt_136}, 대장={calc_136})")

        if bucket_mismatch:
            return {
                "status": "pending",
                "scope": "sale_apartment",
                "reason": f"구간별 세대수 불일치: {', '.join(bucket_mismatch)}",
                "recommended_next_source": "공동주택관리정보시스템 단지 상세 및 공급계약서 확인",
                "kapt_households": kapt_hh,
                "collected_households": collected_households,
                "sale_households": None,
            }

    # 모든 조건 완벽 통과 -> verified 부여
    return {
        "status": "verified",
        "scope": "sale_apartment",
        "reason": "건축물대장 호별 전유부와 K-apt 총세대수 및 구간세대수 100% 일치",
        "recommended_next_source": "검증 완료 (공식자료 상호 교차일치)",
        "kapt_households": kapt_hh,
        "collected_households": collected_households,
        "sale_households": collected_households,
    }
