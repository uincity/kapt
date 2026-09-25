"""
산출물 CSV 생성 모듈.

생성 파일:
1. config/market_cap_area_master.csv (기존 13컬럼 유지)
2. data/raw/kb/kb_area_types.csv (KB 원본 데이터)
3. data/mapping/kb_complex_mapping.csv (매핑 캐시)
4. data/review/area_master_pending.csv (검토 대상)
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from .config import (
    CONFIG_DIR, RAW_KB_DIR, MAPPING_DIR, REVIEW_DIR, MASTER_COLUMNS,
)

logger = logging.getLogger(__name__)


def export_master_csv(verified_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """
    verified 단지의 평형별 세대수를 market_cap_area_master.csv로 저장한다.
    기존 13컬럼 규격을 절대 변경하지 않는다.
    """
    if not verified_rows:
        logger.warning("verified 단지가 없어 마스터 CSV를 생성하지 않습니다.")
        return pd.DataFrame(columns=MASTER_COLUMNS)

    df = pd.DataFrame(verified_rows)

    # 기존 규격에 맞게 컬럼 정리
    for col in MASTER_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[MASTER_COLUMNS]

    out_path = CONFIG_DIR / "market_cap_area_master.csv"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("마스터 CSV 저장: %s (%d rows, %d단지)", out_path, len(df), df["kapt_code"].nunique())

    return df


def export_kb_raw_csv(raw_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """
    KB에서 수집한 원본 평형/시세 데이터를 별도 CSV로 저장한다.
    market_cap_area_master로 바로 변환하지 않고 원자료를 보존하는 목적.
    """
    if not raw_rows:
        return pd.DataFrame()

    df = pd.DataFrame(raw_rows)

    RAW_KB_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_KB_DIR / "kb_area_types.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("KB 원본 데이터 저장: %s (%d rows)", out_path, len(df))

    return df


def export_mapping_csv(mapping_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """
    kapt_code ↔ KB complex ID 매핑 캐시를 CSV로 저장한다.
    다음 실행에서 재검색 없이 직접 이동할 수 있다.
    """
    if not mapping_rows:
        return pd.DataFrame()

    df = pd.DataFrame(mapping_rows)

    MAPPING_DIR.mkdir(parents=True, exist_ok=True)
    out_path = MAPPING_DIR / "kb_complex_mapping.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("KB 매핑 캐시 저장: %s (%d건)", out_path, len(df))

    return df


def load_mapping_csv() -> pd.DataFrame:
    """기존 KB 매핑 캐시를 로드한다."""
    path = MAPPING_DIR / "kb_complex_mapping.csv"
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path, encoding="utf-8-sig")
    df["kapt_code"] = df["kapt_code"].astype(str).str.strip()
    return df


def export_pending_csv(pending_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """
    검토 대상(pending/failed) 단지 목록을 CSV로 저장한다.
    """
    if not pending_rows:
        return pd.DataFrame()

    df = pd.DataFrame(pending_rows)

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REVIEW_DIR / "area_master_pending.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("Pending 목록 저장: %s (%d건)", out_path, len(df))

    return df


def build_master_row(
    kapt_code: str,
    area_row: dict[str, Any],
    kb_url: str = "",
    kb_name: str = "",
) -> dict[str, Any]:
    """
    집계된 면적 행을 market_cap_area_master.csv 규격으로 변환한다.

    valid_from은 근거 없이 채우지 않는다 (빈칸).
    verified_at은 실제 검증일.
    """
    today = date.today().isoformat()
    source = f"KB부동산 단지 시세/평형정보 | {kb_url}" if kb_url else f"KB부동산 단지 시세/평형정보 ({kb_name})"

    return {
        "kapt_code": kapt_code,
        "area_group_id": area_row.get("area_group_id", ""),
        "exclusive_area_sqm": area_row.get("exclusive_area_sqm", ""),
        "supply_area_sqm": area_row.get("supply_area_sqm", ""),
        "type_name": area_row.get("type_name", ""),
        "households": area_row.get("households", 0),
        "source": source,
        "verified_at": today,
        "valid_from": "",       # 근거 없이 채우지 않는다
        "valid_to": "",
        "verification_status": "verified",
        "scope": "sale_apartment",
        "notes": "",
    }


def build_kb_raw_row(
    kapt_code: str,
    kapt_name: str,
    kb_complex_id: str,
    kb_name: str,
    kb_url: str,
    area_type: Any,  # AreaType
    collected_at: str,
) -> dict[str, Any]:
    """KB 원본 데이터 행을 생성한다."""
    return {
        "kapt_code": kapt_code,
        "kapt_name": kapt_name,
        "kb_complex_id": kb_complex_id,
        "kb_complex_name": kb_name,
        "kb_url": kb_url,
        "kb_type_id": area_type.kb_type_id,
        "type_name": area_type.type_name,
        "households": area_type.households,
        "supply_area_sqm": str(area_type.supply_area_sqm) if area_type.supply_area_sqm else "",
        "exclusive_area_sqm": str(area_type.exclusive_area_sqm) if area_type.exclusive_area_sqm else "",
        "area_precision": area_type.area_precision,
        "kb_sale_general": area_type.kb_sale_general or "",
        "kb_sale_upper": area_type.kb_sale_upper or "",
        "kb_sale_lower": area_type.kb_sale_lower or "",
        "kb_jeonse_general": area_type.kb_jeonse_general or "",
        "kb_jeonse_upper": area_type.kb_jeonse_upper or "",
        "kb_jeonse_lower": area_type.kb_jeonse_lower or "",
        "kb_monthly_deposit": area_type.kb_monthly_deposit or "",
        "kb_monthly_low": area_type.kb_monthly_low or "",
        "kb_monthly_high": area_type.kb_monthly_high or "",
        "kb_price_date": area_type.kb_price_date,
        "listing_count": area_type.listing_count or "",
        "collected_at": collected_at,
        "source_method": "playwright_xhr" if area_type.area_precision == "exact" else "playwright_dom",
    }
