"""
area_master 핵심 로직 단위 테스트 모듈.

사용자 요구사항 29번에 따른 6대 필수 검증 항목:
1. 동일 전용면적 합산
2. 서로 다른 전용면적 분리
3. float 반올림 왜곡 방지 및 정밀도 보존
4. area_group_id 포맷
5. valid_from 빈칸 유지
6. verification_status 보수적 판정 (조건 미충족 시 pending)
7. 기존 마스터 13개 컬럼 보존
"""
from __future__ import annotations

from decimal import Decimal
import pandas as pd
import pytest

from src.area_master.normalize import (
    to_decimal,
    normalize_area_str,
    make_area_group_id,
    normalize_complex_name,
)
from src.area_master.aggregate import aggregate_exclusive_areas
from src.area_master.validator import validate_complex_and_areas
from src.area_master.exporter import export_master_csv
from src.area_master.config import MASTER_COLUMNS


def test_area_group_id_generation():
    """area_group_id 생성 규칙 검증 (소수점은 '_'로 치환)"""
    assert make_area_group_id("59.9794") == "exclusive_59_9794"
    assert make_area_group_id(Decimal("84.9231")) == "exclusive_84_9231"
    assert make_area_group_id("59.98") == "exclusive_59_98"
    assert make_area_group_id(84.0) == "exclusive_84"


def test_float_precision_preservation():
    """float 반올림 때문에 서로 다른 면적이 같은 값으로 합쳐지지 않아야 함"""
    a1 = "59.9794"
    a2 = "59.9842"
    # 소수점 둘째자리 반올림 시 둘 다 59.98이 되지만, 시스템에서는 별도 식별되어야 함
    dec1 = to_decimal(a1)
    dec2 = to_decimal(a2)
    assert dec1 != dec2
    assert normalize_area_str(dec1) == "59.9794"
    assert normalize_area_str(dec2) == "59.9842"
    assert make_area_group_id(dec1) != make_area_group_id(dec2)


def test_aggregate_same_area_merging():
    """동일한 전용면적의 A/B 타입 세대수는 정확히 합산되어야 함"""
    # 59.9794 / 120세대, 59.9794 / 98세대 -> 59.9794 / 218세대
    units = []
    for _ in range(120):
        units.append({"area": "59.9794", "mainPurpsCdNm": "아파트"})
    for _ in range(98):
        units.append({"area": "59.9794", "mainPurpsCdNm": "아파트"})

    rows, total_hh, non_res = aggregate_exclusive_areas("A1001", units)
    assert len(rows) == 1
    assert rows[0]["exclusive_area_sqm"] == "59.9794"
    assert rows[0]["households"] == 218
    assert total_hh == 218
    assert non_res == 0


def test_aggregate_different_areas_separation():
    """서로 다른 전용면적은 59형이라는 이유 등으로 절대 합쳐지지 않고 분리되어야 함"""
    # 59.9794 / 120세대, 59.9842 / 98세대 -> 2개 행으로 분리
    units = []
    for _ in range(120):
        units.append({"area": "59.9794", "mainPurpsCdNm": "아파트"})
    for _ in range(98):
        units.append({"area": "59.9842", "mainPurpsCdNm": "아파트"})

    rows, total_hh, non_res = aggregate_exclusive_areas("A1001", units)
    assert len(rows) == 2
    assert total_hh == 218
    areas = [r["exclusive_area_sqm"] for r in rows]
    assert "59.9794" in areas
    assert "59.9842" in areas


def test_non_residential_filtering():
    """상가, 근린생활시설 등 비주거 호수는 주거 세대수 집계에서 제외되어야 함"""
    units = [
        {"area": "84.9", "mainPurpsCdNm": "아파트"},
        {"area": "84.9", "mainPurpsCdNm": "아파트"},
        {"area": "45.0", "mainPurpsCdNm": "근린생활시설", "etcPurps": "소매점"},
        {"area": "30.0", "mainPurpsCdNm": "부동산중개사무소"},
    ]
    rows, total_hh, non_res = aggregate_exclusive_areas("A1001", units)
    assert total_hh == 2
    assert non_res == 2
    assert rows[0]["households"] == 2


def test_validation_rules_conservative_pending():
    """불확실한 단지는 추측하지 않고 반드시 pending으로 분류되어야 함"""
    kapt_info_base = {
        "kapt_code": "A1001",
        "total_households": 500,
        "sale_type": "분양",
        "kapt_mparea_60": 200,
        "kapt_mparea_85": 300,
    }
    match_info_high = {"match_score": 85, "match_confidence": "high"}
    area_rows_matched = [
        {"area_group_id": "exclusive_59", "exclusive_area_sqm": "59.0", "households": 200, "exclusive_area_decimal": Decimal("59.0")},
        {"area_group_id": "exclusive_84", "exclusive_area_sqm": "84.0", "households": 300, "exclusive_area_decimal": Decimal("84.0")},
    ]

    # 1. 완벽 일치 단지 -> verified
    res_ok = validate_complex_and_areas(kapt_info_base, match_info_high, area_rows_matched, 500)
    assert res_ok["status"] == "verified"

    # 2. 총세대수 불일치 단지 -> pending
    res_hh_mismatch = validate_complex_and_areas(kapt_info_base, match_info_high, area_rows_matched, 480)
    assert res_hh_mismatch["status"] == "pending"
    assert "총세대수 불일치" in res_hh_mismatch["reason"]

    # 3. 혼합 단지 -> 자동 verified 절대 불가 (pending)
    kapt_info_mixed = {**kapt_info_base, "sale_type": "혼합(분양+임대)"}
    res_mixed = validate_complex_and_areas(kapt_info_mixed, match_info_high, area_rows_matched, 500)
    assert res_mixed["status"] == "pending"
    assert "혼합" in res_mixed["reason"]

    # 4. 임대 단지 -> 자동 verified 절대 불가 (pending)
    kapt_info_rental = {**kapt_info_base, "sale_type": "임대"}
    res_rental = validate_complex_and_areas(kapt_info_rental, match_info_high, area_rows_matched, 500)
    assert res_rental["status"] == "pending"
    assert "임대" in res_rental["reason"]

    # 5. 매칭 신뢰도 부족 단지 -> pending
    match_info_low = {"match_score": 40, "match_confidence": "low"}
    res_low_match = validate_complex_and_areas(kapt_info_base, match_info_low, area_rows_matched, 500)
    assert res_low_match["status"] == "pending"
    assert "매칭 신뢰도 부족" in res_low_match["reason"]


def test_export_master_schema_and_valid_from(tmp_path):
    """master CSV 스키마 13개 컬럼 유지 및 valid_from 빈칸 검증"""
    test_file = tmp_path / "test_market_cap_area_master.csv"
    verified_rows = [
        {
            "kapt_code": "A1001",
            "area_group_id": "exclusive_59_9794",
            "exclusive_area_sqm": "59.9794",
            "households": 218,
            "source": "국토교통부 건축물대장 전유공용면적 BldRgstHubService 2026-09",
        }
    ]
    df = export_master_csv(verified_rows, output_path=test_file, verified_date_str="2026-09-17")
    
    # 1. 컬럼 목록 일치 검증
    assert list(df.columns) == MASTER_COLUMNS
    
    # 2. valid_from 빈칸 유지 검증
    assert df.iloc[0]["valid_from"] == ""
    assert df.iloc[0]["verification_status"] == "verified"
    assert df.iloc[0]["scope"] == "sale_apartment"
    assert df.iloc[0]["verified_at"] == "2026-09-17"
