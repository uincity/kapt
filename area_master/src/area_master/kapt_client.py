"""
K-apt 공식 메타데이터 관리 및 클라이언트 모듈.

K-apt의 단지 기본·상세 정보를 담고 있는 캐시(busan_complexes.parquet)에서
보완 대상 단지들의 법정동코드, 도로명/지번 주소, 분양형태, 총세대수, 사용승인일,
면적 구간별 세대수(검증 참고용)를 정확하게 추출합니다.
"""
from __future__ import annotations

import logging
from pathlib import Path
import pandas as pd

from .config import RAW_KAPT_DIR, INTERMEDIATE_DIR

logger = logging.getLogger(__name__)


def load_kapt_metadata(cache_path: Path | None = None) -> pd.DataFrame:
    """
    K-apt 부산 단지 메타데이터(busan_complexes.parquet)를 로드합니다.
    """
    path = cache_path or (RAW_KAPT_DIR / "busan_complexes.parquet")
    if not path.exists():
        fallback = Path(r"d:\90.invest\80.데이터수집\아파트정보수집\kapt\busan_apartment_analysis\data\raw\kapt\busan_complexes.parquet")
        if fallback.exists():
            path = fallback
        else:
            raise FileNotFoundError(f"K-apt 메타데이터 캐시 파일이 없습니다: {path}")

    df = pd.read_parquet(path)
    
    # 핵심 컬럼 매핑 및 정규화
    column_mapping = {
        "kaptCode": "kapt_code",
        "kaptName": "kapt_name",
        "bjdCode": "bjd_code",
        "as1": "sido",
        "as2": "sigungu",
        "as3": "eupmyeondong",
        "kaptAddr": "legal_address",
        "doroJuso": "road_address",
        "codeSaleNm": "sale_type",       # 분양, 임대, 혼합
        "kaptdaCnt": "total_households", # 총 세대수
        "hoCnt": "ho_households",
        "kaptUsedate": "approval_date",  # 사용승인일 (YYYYMMDD 등)
        "kaptMparea60": "kapt_mparea_60",   # 60㎡ 이하 세대수
        "kaptMparea85": "kapt_mparea_85",   # 60~85㎡ 세대수
        "kaptMparea135": "kapt_mparea_135", # 85~135㎡ 세대수
        "kaptMparea136": "kapt_mparea_136", # 135㎡ 초과 세대수
    }

    renamed = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

    # 공백 및 형식 정리
    renamed["kapt_code"] = renamed["kapt_code"].astype(str).str.strip()
    renamed["bjd_code"] = renamed["bjd_code"].astype(str).str.strip()
    renamed["total_households"] = pd.to_numeric(renamed["total_households"], errors="coerce")
    for bucket in ["kapt_mparea_60", "kapt_mparea_85", "kapt_mparea_135", "kapt_mparea_136"]:
        if bucket in renamed.columns:
            renamed[bucket] = pd.to_numeric(renamed[bucket], errors="coerce").fillna(0)

    return renamed


def build_kapt_complexes_intermediate(targets_df: pd.DataFrame) -> pd.DataFrame:
    """
    보완 대상 목록과 K-apt 메타데이터를 결합하여 중간 산출물(kapt_complexes.csv)을 생성합니다.
    """
    kapt_df = load_kapt_metadata()
    merged = targets_df.merge(
        kapt_df,
        on="kapt_code",
        how="left",
        suffixes=("", "_kapt")
    )

    # 중간 산출물 저장
    out_path = INTERMEDIATE_DIR / "kapt_complexes.csv"
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")
    logger.info("중간 산출물 생성 완료: %s (%d건)", out_path.name, len(merged))

    return merged
