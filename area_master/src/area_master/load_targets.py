"""
보완 대상 단지 목록 로더 모듈.

supplement_2026-08.csv 파일에서 이번 파이프라인의 보완 대상 단지(560개)를
정확하게 읽어오고 유효성을 검증합니다.
"""
from __future__ import annotations

import logging
from pathlib import Path
import pandas as pd

from .config import ROOT_DIR

logger = logging.getLogger(__name__)


def load_targets(file_path: Path | None = None) -> pd.DataFrame:
    """
    보완 대상 CSV(supplement_2026-08.csv)를 로드하고 기본 정제를 수행합니다.

    Parameters
    ----------
    file_path : Path | None
        대상 파일 경로. 생략 시 프로젝트 루트의 supplement_2026-08.csv 사용.

    Returns
    -------
    pd.DataFrame
        보완 대상 단지 목록 DataFrame (kapt_code 기준 중복 없음)
    """
    path = file_path or (ROOT_DIR / "supplement_2026-08.csv")
    if not path.exists():
        raise FileNotFoundError(f"보완 대상 파일이 존재하지 않습니다: {path}")

    df = pd.read_csv(path, dtype=str)
    
    # 필수 식별자 컬럼 확인
    if "kapt_code" not in df.columns:
        raise ValueError("supplement 파일에 'kapt_code' 열이 누락되었습니다.")

    # 공백 제거 및 유효성 검증
    df["kapt_code"] = df["kapt_code"].str.strip()
    df = df[df["kapt_code"].notna() & (df["kapt_code"] != "")].copy()

    # 숫자형 세대수 변환
    if "households" in df.columns:
        df["households"] = pd.to_numeric(df["households"], errors="coerce")

    # 고유 단지 수 확인
    total_rows = len(df)
    unique_codes = df["kapt_code"].nunique()
    if total_rows != unique_codes:
        logger.warning(
            "보완 대상 목록에 중복 kapt_code가 존재합니다: 총 %d건 중 %d개 고유",
            total_rows, unique_codes
        )
        df = df.drop_duplicates(subset=["kapt_code"]).copy()

    logger.info("보완 대상 단지 %d개 로드 완료 (파일: %s)", len(df), path.name)
    return df
