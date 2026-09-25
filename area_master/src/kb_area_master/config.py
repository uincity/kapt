"""
KB부동산 ETL 파이프라인 환경 설정 및 경로·상수 모듈.

왜 별도 config인가:
- 기존 area_master/config.py는 건축HUB 전용 경로가 중심이므로,
  KB 수집 전용 경로와 매칭 임계치를 분리하여 관리한다.
- MASTER_COLUMNS는 기존과 동일하게 유지 (임의 변경 금지).
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# ── 프로젝트 루트 (area_master 폴더) ──
ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

# ── 디렉터리 경로 ──
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"

# KB 브라우저 프로필 (persistent context)
BROWSER_PROFILE_DIR = DATA_DIR / "browser" / "kb_profile"

# KB 매핑 캐시
MAPPING_DIR = DATA_DIR / "mapping"
KB_MAPPING_CSV = MAPPING_DIR / "kb_complex_mapping.csv"

# KB 원본 데이터
RAW_KB_DIR = DATA_DIR / "raw" / "kb"
KB_AREA_TYPES_CSV = RAW_KB_DIR / "kb_area_types.csv"

# 검토 대상
REVIEW_DIR = DATA_DIR / "review"
PENDING_CSV = REVIEW_DIR / "area_master_pending.csv"

# Checkpoint 상태
STATE_DIR = DATA_DIR / "state"
COLLECTION_STATE_FILE = STATE_DIR / "kb_collection_state.json"

# K-apt 원천 데이터 (기존 재사용)
RAW_KAPT_DIR = DATA_DIR / "raw" / "kapt"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"

# 로그
LOG_DIR = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR / "kb_area_collection.log"

# ── 최종 마스터 CSV 컬럼 (기존 규격 절대 유지) ──
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

# ── 매칭 점수 가중치 (실데이터 기반으로 조정 가능) ──
MATCH_WEIGHTS = {
    "legal_dong_exact": 30,       # 법정동 정확히 일치
    "road_address_exact": 40,     # 도로명 주소 정확히 일치
    "jibun_core_match": 40,       # 지번 핵심값 일치
    "households_exact": 25,       # 총세대수 정확히 일치
    "normalized_name_exact": 20,  # 정규화 단지명 정확히 일치
    "name_high_similarity": 18,   # 단지명 높은 유사도 (0.8+)
    "name_medium_similarity": 10, # 단지명 중간 유사도 (0.6+)
    "approval_year_match": 10,    # 사용승인 연도 일치
}

# ── 매칭 confidence 임계치 ──
CONFIDENCE_THRESHOLDS = {
    "exact": 90,    # 주소+세대수+이름 모두 일치
    "high": 65,     # 동+이름+세대수 일치
    "medium": 45,   # 동+이름 유사
    "low": 25,      # 부분 일치
}

# 자동 확정 가능한 최소 confidence
AUTO_VERIFY_CONFIDENCES = {"exact", "high"}

# ── KB 수집 속도 제어 ──
KB_REQUEST_DELAY_SEC = 2.0       # 단지 간 최소 대기
KB_PAGE_LOAD_TIMEOUT_MS = 30000  # 페이지 로드 타임아웃
KB_MAX_RETRIES = 3               # 최대 재시도 횟수

# ── 파일럿 단지 ──
PILOT_COMPLEX_NAME = "대연sk뷰힐스아파트"
PILOT_KAPT_CODE = "A10026094"

# ── 세대수 검증 허용 오차 ──
HOUSEHOLD_TOLERANCE_RATIO = 0.0  # 정확히 일치해야 verified (0% 오차)


def ensure_kb_directories() -> None:
    """KB 수집에 필요한 모든 디렉터리를 생성한다."""
    for path in [
        CONFIG_DIR,
        BROWSER_PROFILE_DIR,
        MAPPING_DIR,
        RAW_KB_DIR,
        REVIEW_DIR,
        STATE_DIR,
        INTERMEDIATE_DIR,
        RAW_KAPT_DIR,
        LOG_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
