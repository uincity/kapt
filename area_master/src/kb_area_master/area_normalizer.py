"""
전용면적 정밀 집계 모듈.

핵심 규칙:
- 동일 전용면적(exact Decimal 기준)만 합산한다.
- round(area, 2) 후 GROUP BY 절대 금지.
- 다른 type_name + 동일 2자리 표시면적 + 고정밀 원본 없음 → 자동 merge 금지.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Any

from .models import AreaType

logger = logging.getLogger(__name__)


def normalize_area_str(val: Decimal) -> str:
    """
    Decimal 전용면적을 원자료 정밀도를 보존하는 문자열로 반환한다.
    예: Decimal('59.9794') → '59.9794'
    """
    s = f"{val:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def make_area_group_id(area: Decimal) -> str:
    """
    전용면적 기반 고유 면적 그룹 식별자를 생성한다.
    예: Decimal('59.9794') → 'exclusive_59_9794'
    """
    area_str = normalize_area_str(area)
    safe = area_str.replace(".", "_")
    return f"exclusive_{safe}"


def aggregate_area_types(
    kapt_code: str,
    area_types: list[AreaType],
) -> list[dict[str, Any]]:
    """
    KB에서 수집한 평형 데이터를 전용면적 기준으로 정밀 집계한다.

    규칙:
    1. 동일한 exact exclusive_area_sqm끼리만 합산.
    2. area_precision이 'display'이고 type_name이 다르면 자동 merge 금지 → 별도 행.
    3. Decimal 기반으로 처리하여 부동소수점 오차 방지.

    Returns:
        market_cap_area_master.csv에 들어갈 형태의 dict 리스트.
    """
    if not area_types:
        return []

    # 고정밀 면적이 있는 경우: exact Decimal 기준으로 GROUP BY
    # 고정밀 면적이 없는 경우: type_name별로 별도 행 유지 (자동 merge 금지)
    grouped: dict[str, dict[str, Any]] = {}
    ambiguous_types: list[AreaType] = []

    for at in area_types:
        if at.exclusive_area_sqm is None:
            # 전용면적 없는 타입은 pending 대상
            ambiguous_types.append(at)
            continue

        exact_area = at.exclusive_area_sqm
        area_key = normalize_area_str(exact_area)

        if at.area_precision == "exact":
            # 고정밀 면적: 안전하게 합산 가능
            if area_key in grouped:
                grouped[area_key]["households"] += at.households
                grouped[area_key]["type_names"].add(at.type_name)
            else:
                grouped[area_key] = {
                    "kapt_code": kapt_code,
                    "exclusive_area_sqm": exact_area,
                    "supply_area_sqm": at.supply_area_sqm,
                    "households": at.households,
                    "type_names": {at.type_name},
                    "area_precision": "exact",
                }
        else:
            # display 정밀도(2자리): type_name이 다르면 합산 금지
            display_key = f"{area_key}|{at.type_name}"
            if display_key in grouped:
                grouped[display_key]["households"] += at.households
            else:
                grouped[display_key] = {
                    "kapt_code": kapt_code,
                    "exclusive_area_sqm": exact_area,
                    "supply_area_sqm": at.supply_area_sqm,
                    "households": at.households,
                    "type_names": {at.type_name},
                    "area_precision": "display",
                }

    # 결과 변환
    result: list[dict[str, Any]] = []
    seen_area_group_ids: set[str] = set()

    for key, grp in grouped.items():
        area = grp["exclusive_area_sqm"]
        area_group_id = make_area_group_id(area)

        # unique area_group_id 검증 (동일 단지 내 중복 방지)
        if area_group_id in seen_area_group_ids:
            # 중복 시 type_name을 접미사로 추가
            type_suffix = "_".join(sorted(grp["type_names"]))
            area_group_id = f"{area_group_id}_{type_suffix.replace(' ', '')}"

        seen_area_group_ids.add(area_group_id)

        result.append({
            "kapt_code": kapt_code,
            "area_group_id": area_group_id,
            "exclusive_area_sqm": normalize_area_str(area),
            "supply_area_sqm": normalize_area_str(grp["supply_area_sqm"]) if grp["supply_area_sqm"] else "",
            "type_name": ", ".join(sorted(grp["type_names"])) if grp["type_names"] else "",
            "households": grp["households"],
            "area_precision": grp["area_precision"],
        })

    # 전용면적 없는 ambiguous 타입 경고
    if ambiguous_types:
        logger.warning(
            "단지 %s: 전용면적 없는 타입 %d개 → area_master에 포함하지 않음",
            kapt_code, len(ambiguous_types),
        )

    return result
