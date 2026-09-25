"""
area_master 환경 설정 및 경로, 컬럼 상수 모듈.

이 모듈은 프로젝트 전반에서 사용되는 경로, 필수 CSV 컬럼 구조,
환경변수 API 키 및 매칭 신뢰도 임계치를 일관되게 관리합니다.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 경로 (area_master 폴더 기준)
ROOT_DIR = Path(__file__).resolve().parents[2]

# 환경변수 로드 (.env 우선 로드)
load_dotenv(ROOT_DIR / ".env")

# 주요 디렉터리 경로
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_KAPT_DIR = RAW_DIR / "kapt"
RAW_BLDRGST_DIR = RAW_DIR / "bldrgst"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
REVIEW_DIR = DATA_DIR / "review"

# 기존 규격에 따른 마스터 CSV 필수 13개 컬럼 (순서 및 컬럼명 절대 변경 불가)
MASTER_COLUMNS = [
    "kapt_code",
    "area_group_id",
    "exclusive_area_sqm",
    "supply_area_sqm",
    "type_name",
    "households",
    "source",
    "verified_at",
    "valid_from",
    "valid_to",
    "verification_status",
    "scope",
    "notes",
]

# API 인증키 조회 함수
def get_api_key(name: str) -> str | None:
    """환경변수 또는 .env에서 API 키를 안전하게 조회합니다."""
    return os.getenv(name) or None


def ensure_directories() -> None:
    """파이프라인 실행에 필요한 모든 중간 및 원천 데이터 디렉터리를 생성합니다."""
    for path in [
        CONFIG_DIR,
        RAW_KAPT_DIR,
        RAW_BLDRGST_DIR,
        INTERMEDIATE_DIR,
        REVIEW_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
