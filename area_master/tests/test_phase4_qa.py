"""
Phase 4 최종 품질검증(QA) 및 운영 감사 자동화 테스트.
프롬프트 58항 명시 테스트 케이스 전수 구현.
"""
import pytest
import pandas as pd
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]


def test_population_partition_invariants():
    """560개 단지 파티션 불변식 검증 (560 = 497 + 49 + 14 + 0)."""
    kapt = pd.read_csv(ROOT_DIR / "data" / "intermediate" / "kapt_complexes.csv")
    master = pd.read_csv(ROOT_DIR / "config" / "market_cap_area_master.csv")
    excluded = pd.read_csv(ROOT_DIR / "data" / "review" / "excluded_rental_only.csv")
    pending = pd.read_csv(ROOT_DIR / "data" / "review" / "phase3_final_pending.csv")
    
    total_kapt_codes = set(kapt["kapt_code"])
    master_codes = set(master["kapt_code"])
    excluded_codes = set(excluded["kapt_code"])
    pending_codes = set(pending["kapt_code"])
    
    assert len(total_kapt_codes) == 560, "전체 단지 수가 560이 아닙니다."
    assert len(master_codes) == 497, "Master 단지 수가 497이 아닙니다."
    assert len(excluded_codes) == 49, "순수 임대 단지 수가 49가 아닙니다."
    assert len(pending_codes) == 14, "최종 미해결 단지 수가 14가 아닙니다."
    
    # 상호 배타성 검증 (교집합 0)
    assert len(master_codes & excluded_codes) == 0, "Master와 Excluded에 중복 단지가 있습니다."
    assert len(master_codes & pending_codes) == 0, "Master와 Pending에 중복 단지가 있습니다."
    assert len(excluded_codes & pending_codes) == 0, "Excluded와 Pending에 중복 단지가 있습니다."
    
    # 완전성 검증 (합집합 560)
    union_codes = master_codes | excluded_codes | pending_codes
    assert union_codes == total_kapt_codes, "전체 560개 단지와 합집합이 일치하지 않습니다."


def test_master_schema_and_uniqueness():
    """Master 전용면적 유일성 및 필수 컬럼 null 검증."""
    master = pd.read_csv(ROOT_DIR / "config" / "market_cap_area_master.csv")
    
    # 13개 표준 컬럼 존재 여부
    required_cols = [
        "kapt_code", "area_group_id", "exclusive_area_sqm", "supply_area_sqm",
        "type_name", "households", "source", "verified_at",
        "valid_from", "valid_to", "verification_status", "scope", "notes"
    ]
    for col in required_cols:
        assert col in master.columns, f"필수 컬럼 {col} 누락"
    
    # 필수값 null 없음 검증 (valid_from, valid_to, notes 등 선택 컬럼 제외)
    for col in ["kapt_code", "area_group_id", "exclusive_area_sqm", "households", "source", "scope", "verification_status", "verified_at"]:
        assert master[col].isna().sum() == 0, f"필수 컬럼 {col}에 결측치 존재"
        
    # (kapt_code, area_group_id) 복합키 유일성 검증
    dups = master.duplicated(subset=["kapt_code", "area_group_id"], keep=False)
    assert dups.sum() == 0, f"Master 내 (단지코드, area_group_id) 중복 발견: {dups.sum()}건"
    
    # scope 및 verification_status 일관성
    assert (master["scope"] == "sale_apartment").all(), "모든 Master 행의 scope는 sale_apartment여야 합니다."
    assert (master["verification_status"] == "verified").all(), "모든 Master 행의 verification_status는 verified여야 합니다."


def test_households_positive_and_validity_dates():
    """세대수 > 0 및 valid_to >= valid_from (존재 시) 검증."""
    master = pd.read_csv(ROOT_DIR / "config" / "market_cap_area_master.csv")
    
    # 세대수 양수
    assert (master["households"] > 0).all(), "세대수가 0 이하인 행이 존재합니다."
    
    # 전용면적 양수
    assert (master["exclusive_area_sqm"] > 0).all(), "전용면적이 0 이하인 행이 존재합니다."
    
    # verified_at 형식 검증 (YYYY-MM-DD)
    assert master["verified_at"].str.match(r"^\d{4}-\d{2}-\d{2}$").all(), "verified_at 날짜 형식이 올바르지 않습니다."
    
    # valid_from/valid_to가 존재하는 행에 대해 valid_to >= valid_from
    has_dates = master.dropna(subset=["valid_from", "valid_to"])
    if len(has_dates) > 0:
        assert (has_dates["valid_to"] >= has_dates["valid_from"]).all(), "valid_to가 valid_from보다 이전인 행이 존재합니다."


def test_decimal_merge_integrity():
    """Phase 1 병합 감사 사례 (A60775306, A61476403 등) 병합 후 세대수 정합성 검증."""
    master = pd.read_csv(ROOT_DIR / "config" / "market_cap_area_master.csv")
    merge_audit = pd.read_csv(ROOT_DIR / "data" / "review" / "phase1_area_merge_audit.csv")
    
    for _, r in merge_audit.iterrows():
        code = str(r["kapt_code"])
        ex_sqm = float(r["exclusive_area_sqm"])
        expected_hh = int(r["merged_households"])
        
        m_rows = master[(master["kapt_code"] == code) & (master["exclusive_area_sqm"] == ex_sqm)]
        actual_hh = int(m_rows["households"].sum())
        assert actual_hh == expected_hh, f"{code} {ex_sqm}m² 세대수 불일치: 실제 {actual_hh} != 기대 {expected_hh}"


def test_provenance_full_coverage():
    """Master 3,308행과 Provenance의 100% 매핑 검증."""
    master = pd.read_csv(ROOT_DIR / "config" / "market_cap_area_master.csv")
    
    prov_full = pd.read_csv(ROOT_DIR / "data" / "provenance" / "area_master_provenance.csv")
    assert len(master) == 3308, "Master 행 수가 3,308이 아닙니다."
    assert len(prov_full) == 3308, f"Provenance 행 수({len(prov_full)})가 Master({len(master)})와 일치하지 않습니다."
    
    # 복합키 일치 검증
    master_keys = set(zip(master["kapt_code"], master["exclusive_area_sqm"].round(2)))
    prov_keys = set(zip(prov_full["kapt_code"], prov_full["exclusive_area_sqm"].round(2)))
    assert master_keys == prov_keys, "Master와 Provenance 간의 (kapt_code, exclusive_area) 키가 100% 일치하지 않습니다."


def test_release_artifacts_and_checksums():
    """Release 디렉토리 및 필수 산출물 존재 여부 검증."""
    release_base = ROOT_DIR / "data" / "releases"
    assert release_base.exists(), "Releases 디렉토리가 없습니다."
    
    release_dirs = [d for d in release_base.iterdir() if d.is_dir()]
    assert len(release_dirs) >= 1, "생성된 릴리즈 스냅샷 디렉토리가 없습니다."
    
    latest_release = sorted(release_dirs)[-1]
    
    required_files = [
        "market_cap_area_master.csv",
        "area_master_complex_status.csv",
        "area_master_provenance.csv",
        "excluded_rental_only.csv",
        "phase3_final_pending.csv",
        "phase4_summary.json",
        "phase4_issues.csv",
        "RELEASE_INFO.json",
        "CHECKSUMS.sha256"
    ]
    for rf in required_files:
        p = latest_release / rf
        assert p.exists(), f"릴리즈 스냅샷에 필수 파일 {rf} 누락"
        assert p.stat().st_size > 0, f"릴리즈 스냅샷 파일 {rf} 크기가 0입니다."
