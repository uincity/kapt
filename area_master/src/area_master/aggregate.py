"""
전용면적별 세대수 집계 모듈.

건축물대장 호별 전유부 데이터를 바탕으로 상가/비주거 시설을 엄격히 분리하고,
오직 정확한 exclusive_area_sqm(Decimal) 기준으로 동일 면적의 세대수를 합산합니다.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
import pandas as pd

from .normalize import to_decimal, normalize_area_str, make_area_group_id


# 주거용 아파트 판정 키워드
RESIDENTIAL_KEYWORDS = ["아파트", "공동주택", "다세대", "연립주택"]
# 비주거 제외 키워드
EXCLUDE_KEYWORDS = [
    "근린생활시설", "상가", "소매점", "사무소", "식당", "카페", "학원",
    "미용", "세탁", "의원", "판매", "운동", "주차", "오피스텔", "노유자",
]


def is_residential_apartment(unit: dict[str, Any]) -> bool:
    """
    호별 전유부 레코드가 매매 가능한 아파트 주거 세대인지 검증합니다.
    """
    purps_nm = str(unit.get("mainPurpsCdNm", "") or "")
    etc_purps = str(unit.get("etcPurps", "") or "")
    combined = f"{purps_nm} {etc_purps}"

    # 명시적 비주거 키워드 포함 시 제외
    for kw in EXCLUDE_KEYWORDS:
        if kw in combined:
            return False

    # 주거 아파트 키워드 확인
    for kw in RESIDENTIAL_KEYWORDS:
        if kw in combined:
            return True

    # mainPurpsCd가 '02001'(아파트)인 경우 포함
    purps_cd = str(unit.get("mainPurpsCd", "") or "")
    if purps_cd == "02001":
        return True

    return False


def aggregate_exclusive_areas(
    kapt_code: str,
    units: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """
    전유부 목록에서 아파트 주거 세대를 필터링하고,
    동일한 정확한 전용면적(Decimal)을 가진 세대들을 하나의 행으로 합산합니다.

    Parameters
    ----------
    kapt_code : str
        단지 식별자
    units : list[dict[str, Any]]
        건축물대장 전유부 호별 목록

    Returns
    -------
    tuple[list[dict[str, Any]], int, int]
        (평형별 집계 행 목록, 주거 세대수 합계, 비주거 제외 호수)
    """
    if not units:
        return ([], 0, 0)

    residential_units: list[dict[str, Any]] = []
    non_residential_count = 0

    for u in units:
        area_str = str(u.get("area", "")).strip()
        if not area_str:
            continue
        try:
            area_dec = to_decimal(area_str)
            if area_dec <= Decimal("0"):
                continue
        except Exception:
            continue

        if is_residential_apartment(u):
            residential_units.append({**u, "area_dec": area_dec, "area_str": area_str})
        else:
            non_residential_count += 1

    total_residential = len(residential_units)
    if total_residential == 0:
        return ([], 0, non_residential_count)

    # 정확한 Decimal 기준으로 GROUP BY 및 카운트
    area_counts: dict[Decimal, int] = {}
    for ru in residential_units:
        dec = ru["area_dec"]
        area_counts[dec] = area_counts.get(dec, 0) + 1

    rows: list[dict[str, Any]] = []
    for area_dec, count in sorted(area_counts.items()):
        norm_str = normalize_area_str(area_dec)
        group_id = make_area_group_id(norm_str)

        rows.append({
            "kapt_code": kapt_code,
            "area_group_id": group_id,
            "exclusive_area_sqm": norm_str,
            "households": count,
            "exclusive_area_decimal": area_dec,
        })

    return (rows, total_residential, non_residential_count)
