"""
K-apt 메타데이터 로딩 및 보완 대상 목록 병합 모듈.

기존 src/area_master/kapt_client.py의 로직을 재사용하되,
KB 파이프라인 전용 인터페이스를 제공한다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .config import ROOT_DIR, RAW_KAPT_DIR, INTERMEDIATE_DIR

logger = logging.getLogger(__name__)


def load_kapt_metadata(cache_path: Optional[Path] = None) -> pd.DataFrame:
    """
    K-apt 부산 단지 메타데이터(busan_complexes.parquet)를 로드한다.

    왜 parquet인가:
    - K-apt API에서 한 번 수집한 전체 부산 단지 정보를 캐시해 둔 파일.
    - 매번 API를 호출할 필요 없이 로컬에서 빠르게 조회 가능.
    """
    path = cache_path or (RAW_KAPT_DIR / "busan_complexes.parquet")
    if not path.exists():
        # fallback: 상위 프로젝트에서 생성한 parquet 파일 참조
        fallback = Path(
            r"d:\90.invest\80.데이터수집\아파트정보수집\kapt\busan_apartment_analysis\data\raw\kapt\busan_complexes.parquet"
        )
        if fallback.exists():
            path = fallback
        else:
            raise FileNotFoundError(f"K-apt 메타데이터 캐시 파일이 없습니다: {path}")

    df = pd.read_parquet(path)

    # 핵심 컬럼 매핑
    column_mapping = {
        "kaptCode": "kapt_code",
        "kaptName": "kapt_name",
        "bjdCode": "bjd_code",
        "as1": "sido",
        "as2": "sigungu_name",
        "as3": "eupmyeondong",
        "kaptAddr": "legal_address",
        "doroJuso": "road_address",
        "codeSaleNm": "sale_type",
        "kaptdaCnt": "total_households",
        "hoCnt": "ho_households",
        "kaptUsedate": "approval_date",
    }
    renamed = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
    renamed["kapt_code"] = renamed["kapt_code"].astype(str).str.strip()
    renamed["bjd_code"] = renamed["bjd_code"].astype(str).str.strip()
    renamed["total_households"] = pd.to_numeric(renamed["total_households"], errors="coerce")

    return renamed


def load_targets() -> pd.DataFrame:
    """
    보완 대상 목록(supplement_2026-08.csv)을 로드한다.
    """
    supp_path = ROOT_DIR / "supplement_2026-08.csv"
    if not supp_path.exists():
        raise FileNotFoundError(f"보완 대상 파일이 없습니다: {supp_path}")

    df = pd.read_csv(supp_path, encoding="utf-8-sig")
    df["kapt_code"] = df["kapt_code"].astype(str).str.strip()
    logger.info("보완 대상 %d건 로드 완료 (원본: %s)", len(df), supp_path.name)
    return df


def build_targets_with_kapt() -> pd.DataFrame:
    """
    보완 대상 목록과 K-apt 메타데이터를 병합하여
    KB 검색에 필요한 통합 정보를 생성한다.

    반환 DataFrame 주요 컬럼:
    - kapt_code, complex_name (supplement 원본)
    - kapt_name, legal_address, road_address, bjd_code (K-apt)
    - dong (supplement 원본 동명)
    - total_households (K-apt 총세대수)
    - sale_type (분양형태)
    - approval_date (사용승인일)
    """
    targets = load_targets()
    kapt = load_kapt_metadata()

    merged = targets.merge(
        kapt[["kapt_code", "kapt_name", "bjd_code", "sigungu_name",
              "eupmyeondong", "legal_address", "road_address",
              "sale_type", "total_households", "approval_date"]],
        on="kapt_code",
        how="left",
        suffixes=("", "_kapt"),
    )

    # 중간 산출물 저장
    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = INTERMEDIATE_DIR / "kb_targets.csv"
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("KB 대상 단지 정보 생성 완료: %s (%d건)", out_path.name, len(merged))

    return merged
