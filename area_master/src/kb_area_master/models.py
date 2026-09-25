"""
Pydantic 기반 데이터 모델.

왜 Pydantic인가:
- 타입 안전성 확보 (면적 precision 실수 방지)
- serialization/deserialization 편의
- 자동 validation
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class MatchConfidence(str, Enum):
    """KB 단지 매칭 신뢰도 등급."""
    EXACT = "exact"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNMATCHED = "unmatched"


class CollectionStatus(str, Enum):
    """단지별 수집 상태 코드."""
    WAITING = "WAITING"
    SEARCHING = "SEARCHING"
    MATCHING = "MATCHING"
    COLLECTING_TYPES = "COLLECTING_TYPES"
    COLLECTING_PRICES = "COLLECTING_PRICES"
    VALIDATING = "VALIDATING"
    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    FAILED = "FAILED"


class PendingReason(str, Enum):
    """pending 사유 코드."""
    KB_COMPLEX_NOT_FOUND = "KB_COMPLEX_NOT_FOUND"
    KB_COMPLEX_AMBIGUOUS = "KB_COMPLEX_AMBIGUOUS"
    ADDRESS_MISMATCH = "ADDRESS_MISMATCH"
    HOUSEHOLDS_MISMATCH = "HOUSEHOLDS_MISMATCH"
    AREA_NOT_AVAILABLE = "AREA_NOT_AVAILABLE"
    AREA_PRECISION_AMBIGUOUS = "AREA_PRECISION_AMBIGUOUS"
    TYPE_HOUSEHOLDS_MISSING = "TYPE_HOUSEHOLDS_MISSING"
    KB_PRICE_MISSING = "KB_PRICE_MISSING"
    MIXED_RENTAL_COMPLEX = "MIXED_RENTAL_COMPLEX"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    PAGE_STRUCTURE_CHANGED = "PAGE_STRUCTURE_CHANGED"
    SOURCE_VALIDATION_FAILED = "SOURCE_VALIDATION_FAILED"
    RENTAL_COMPLEX = "RENTAL_COMPLEX"
    LOW_MATCH_CONFIDENCE = "LOW_MATCH_CONFIDENCE"
    COLLECTION_ERROR = "COLLECTION_ERROR"


class ComplexCandidate(BaseModel):
    """KB 검색 결과 후보 단지."""
    kb_complex_id: str = ""
    kb_name: str = ""
    kb_address: str = ""
    kb_dong: str = ""            # 법정동
    kb_road_address: str = ""
    kb_households: int = 0
    kb_approval_year: Optional[str] = None
    kb_url: str = ""
    match_score: int = 0
    match_confidence: MatchConfidence = MatchConfidence.UNMATCHED
    match_reasons: list[str] = Field(default_factory=list)


class AreaType(BaseModel):
    """KB에서 수집한 하나의 평형 유형."""
    kb_type_id: str = ""
    type_name: str = ""          # 예: "24평", "33A"
    households: int = 0
    supply_area_sqm: Optional[Decimal] = None
    exclusive_area_sqm: Optional[Decimal] = None
    area_precision: str = "display"  # "display" (화면 2자리) 또는 "exact" (고정밀)

    # KB 시세 (만원 단위)
    kb_sale_general: Optional[int] = None     # KB 매매 일반가
    kb_sale_upper: Optional[int] = None       # KB 매매 상위평균가
    kb_sale_lower: Optional[int] = None       # KB 매매 하위평균가
    kb_jeonse_general: Optional[int] = None   # KB 전세 일반가
    kb_jeonse_upper: Optional[int] = None
    kb_jeonse_lower: Optional[int] = None
    kb_monthly_deposit: Optional[int] = None  # 월세 보증금
    kb_monthly_low: Optional[int] = None      # 월세 하한
    kb_monthly_high: Optional[int] = None     # 월세 상한
    kb_price_date: str = ""                   # KB 시세 기준일
    listing_count: Optional[int] = None       # 매물건수

    class Config:
        # Decimal을 JSON으로 직렬화할 때 문자열로
        json_encoders = {Decimal: str}


class ValidationResult(BaseModel):
    """단지 검증 결과."""
    status: CollectionStatus = CollectionStatus.WAITING
    reason_codes: list[PendingReason] = Field(default_factory=list)
    reason: str = ""
    expected_households: int = 0     # K-apt 총세대수
    collected_households: int = 0    # KB 평형별 세대수 합계
    types_found: int = 0
    recommended_next_action: str = ""


class ComplexState(BaseModel):
    """단지별 수집 상태 (checkpoint용)."""
    kapt_code: str
    status: CollectionStatus = CollectionStatus.WAITING
    kb_complex_id: str = ""
    match_confidence: MatchConfidence = MatchConfidence.UNMATCHED
    attempts: int = 0
    last_error: str = ""
    updated_at: str = ""

    def mark_done(self, status: CollectionStatus, kb_id: str = "", confidence: MatchConfidence = MatchConfidence.UNMATCHED) -> None:
        """상태를 갱신하고 타임스탬프를 기록한다."""
        self.status = status
        if kb_id:
            self.kb_complex_id = kb_id
        if confidence != MatchConfidence.UNMATCHED:
            self.match_confidence = confidence
        self.updated_at = datetime.now().isoformat()
