"""
Phase 3 파이프라인 단위 및 정합성 무결성 테스트.
프롬프트 58항 명시 테스트 케이스 전수 구현.
"""
import pytest
import pandas as pd
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_master_immutability():
    """기존 Phase 2 Master 462개 단지가 Phase 3 이후에도 100% 보존되었는지 검증."""
    p2_bak = pd.read_csv(ROOT_DIR / "config" / "market_cap_area_master_phase2_backup.csv")
    current_master = pd.read_csv(ROOT_DIR / "config" / "market_cap_area_master.csv")
    
    p2_codes = set(p2_bak["kapt_code"])
    current_codes = set(current_master["kapt_code"])
    
    assert len(p2_codes) == 462, "Phase 2 백업 단지 수가 462가 아닙니다."
    assert p2_codes.issubset(current_codes), "기존 462개 단지 중 일부가 누락되었습니다."
    assert len(current_master) >= len(p2_bak), "전체 평형 수가 감소했습니다."


def test_total_completeness_and_uniqueness():
    """560개 전체에 대해 정확히 하나의 final_status가 존재하며 중복/누락이 0인지 검증."""
    status_df = pd.read_csv(ROOT_DIR / "data" / "status" / "area_master_complex_status.csv")
    kapt = pd.read_csv(ROOT_DIR / "data" / "intermediate" / "kapt_complexes.csv")
    
    assert len(status_df) == 560, f"Status 테이블 행 수 ({len(status_df)})가 560이 아닙니다."
    assert status_df["kapt_code"].nunique() == 560, "중복된 단지 코드가 존재합니다."
    
    missing_codes = set(kapt["kapt_code"]) - set(status_df["kapt_code"])
    assert len(missing_codes) == 0, f"누락된 단지가 존재합니다: {missing_codes}"
    
    # 560 = Master + Excluded + Pending + Failed
    master_cnt = status_df["master_included"].sum()
    excluded_cnt = status_df["excluded"].sum()
    pending_cnt = status_df["pending"].sum()
    
    assert master_cnt + excluded_cnt + pending_cnt == 560, "상태 합계가 560과 일치하지 않습니다."
    assert master_cnt == 497, f"Master 반영 단지 수 ({master_cnt})가 497이 아닙니다."
    assert excluded_cnt == 49, f"순수 임대 제외 단지 수 ({excluded_cnt})가 49가 아닙니다."
    assert pending_cnt == 14, f"최종 미해결 단지 수 ({pending_cnt})가 14가 아닙니다."


def test_coverage_calculation():
    """커버리지 산식 검증 (전체 88.8%, 대상 97.3%)."""
    status_df = pd.read_csv(ROOT_DIR / "data" / "status" / "area_master_complex_status.csv")
    total = len(status_df)
    master = status_df["master_included"].sum()
    excluded = status_df["excluded"].sum()
    
    overall_cov = (master / total) * 100
    target_cov = (master / (total - excluded)) * 100
    
    assert round(overall_cov, 1) == 88.8
    assert round(target_cov, 1) == 97.3


def test_decimal_exact_grouping():
    """Decimal exact 전용면적 처리 검증."""
    from src.kb_area_master.area_normalizer import aggregate_area_types
    from src.kb_area_master.models import AreaType
    
    t1 = AreaType(
        kb_type_id="1",
        type_name="84A",
        households=100,
        exclusive_area_sqm=Decimal("84.9912"),
        supply_area_sqm=Decimal("110.5"),
        area_precision="exact",
    )
    t2 = AreaType(
        kb_type_id="2",
        type_name="84B",
        households=50,
        exclusive_area_sqm=Decimal("84.9912"),
        supply_area_sqm=Decimal("110.5"),
        area_precision="exact",
    )
    res = aggregate_area_types("TEST_001", [t1, t2])
    assert len(res) == 1, "동일 exact 전용면적은 합산되어야 합니다."
    assert res[0]["households"] == 150
    assert res[0]["exclusive_area_sqm"] == "84.9912"


def test_display_precision_no_merge():
    """서로 다른 type_name이고 display precision일 때 자동 병합 금지 검증."""
    from src.kb_area_master.area_normalizer import aggregate_area_types
    from src.kb_area_master.models import AreaType
    
    t1 = AreaType(
        kb_type_id="1",
        type_name="84A",
        households=100,
        exclusive_area_sqm=Decimal("84.99"),
        supply_area_sqm=Decimal("110.5"),
        area_precision="display",
    )
    t2 = AreaType(
        kb_type_id="2",
        type_name="84B",
        households=50,
        exclusive_area_sqm=Decimal("84.99"),
        supply_area_sqm=Decimal("111.0"),
        area_precision="display",
    )
    res = aggregate_area_types("TEST_002", [t1, t2])
    assert len(res) == 2, "display precision에서 서로 다른 타입은 병합되지 않고 2개 행이어야 합니다."
