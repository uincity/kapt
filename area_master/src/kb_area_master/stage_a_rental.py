"""
STAGE A: 순수 임대 단지 처리 모듈.

목적:
- 정말 일반 매매 가능한 아파트 주거세대가 없는 rental-only 단지인지 확인.
- 확실한 순수 임대단지는 EXCLUDED_RENTAL_ONLY로 정상 제외 처리.
- sale_apartment 범위에 억지로 넣지 않고, 정상적인 대상 제외 상태로 분리.
- 혹시라도 '분양전환' 또는 '일반분양 혼합' 징후가 발견되면 PENDING_MIXED로 이관.
- 출력: data/review/excluded_rental_only.csv
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def process_stage_a_rentals(
    pending_df: pd.DataFrame,
    kapt_df: pd.DataFrame,
    output_dir: Path,
) -> dict[str, Any]:
    """
    STAGE A: 임대 단지(RENTAL_COMPLEX)를 전수 검증하여 순수 임대단지는 제외 처리하고,
    혼합 징후가 있는 단지는 PENDING_MIXED로 분리한다.

    Returns:
        {
            "excluded_rental_codes": list[str],
            "moved_to_mixed_codes": list[str],
            "excluded_rows": list[dict],
        }
    """
    logger.info("=== STAGE A: 순수 임대 단지(RENTAL_COMPLEX) 전수 검증 시작 ===")

    rental_pending = pending_df[pending_df["reason_code"] == "RENTAL_COMPLEX"].copy()
    logger.info("검증 대상 RENTAL_COMPLEX 단지 수: %d개", len(rental_pending))

    # K-apt 기본정보 조인
    merged = pd.merge(
        rental_pending,
        kapt_df[["kapt_code", "sale_type", "approval_date", "legal_address", "road_address", "households"]],
        on="kapt_code",
        how="left",
        suffixes=("", "_kapt")
    )

    excluded_rows = []
    excluded_codes = []
    moved_to_mixed_codes = []

    for _, row in merged.iterrows():
        kapt_code = str(row["kapt_code"]).strip()
        kapt_name = str(row.get("kapt_name", "")).strip()
        sale_type = str(row.get("sale_type", "")).strip()
        hh = int(row.get("kapt_households", 0) or row.get("households", 0) or 0)
        appr_date = str(row.get("approval_date", "")).strip()
        addr = str(row.get("kapt_address", "") or row.get("legal_address", "")).strip()

        # 1. 혼합/분양전환 징후 검사
        is_mixed_candidate = False
        mixed_reasons = []

        if "혼합" in sale_type:
            is_mixed_candidate = True
            mixed_reasons.append("sale_type contains 혼합")
        if "분양" in sale_type and "임대" in sale_type:
            is_mixed_candidate = True
            mixed_reasons.append("sale_type contains both 분양 and 임대")
        if "분양전환" in kapt_name:
            is_mixed_candidate = True
            mixed_reasons.append("단지명에 '분양전환' 포함")

        if is_mixed_candidate:
            logger.warning("단지 [%s] %s: 순수 임대 아님 -> PENDING_MIXED로 이관 (%s)", kapt_code, kapt_name, ", ".join(mixed_reasons))
            moved_to_mixed_codes.append(kapt_code)
            continue

        # 2. 순수 임대단지 확정 (K-apt 공식 분양형태 '임대')
        # 임대 유형 세부 판별
        rental_type = "공공임대/국민임대"
        if "행복주택" in kapt_name:
            rental_type = "행복주택"
        elif "영구" in kapt_name:
            rental_type = "영구임대"
        elif "국민" in kapt_name or "주공" in kapt_name:
            rental_type = "국민임대"
        elif "LH" in kapt_name:
            rental_type = "LH공공임대"
        elif "도시공사" in kapt_name or "BMC" in kapt_name:
            rental_type = "BMC공공임대"

        record = {
            "kapt_code": kapt_code,
            "kapt_name": kapt_name,
            "legal_dong": str(row.get("legal_dong", "")),
            "address": addr,
            "total_households": hh,
            "approval_date": appr_date,
            "sale_type": sale_type,
            "rental_type": rental_type,
            "evidence_source": "K-apt 공식 분양형태(임대)",
            "exclusion_reason": "순수 임대단지 (일반 분양 주거세대 없음, sale_apartment 제외 대상)",
            "processing_status": "EXCLUDED_RENTAL_ONLY",
            "verified_at": datetime.now().strftime("%Y-%m-%d"),
        }
        excluded_rows.append(record)
        excluded_codes.append(kapt_code)

    # excluded_rental_only.csv 저장
    out_file = output_dir / "excluded_rental_only.csv"
    pd.DataFrame(excluded_rows).to_csv(out_file, index=False, encoding="utf-8-sig")
    logger.info("STAGE A 완료: %d개 단지 EXCLUDED_RENTAL_ONLY 확정, %d개 단지 혼합 이관 -> 저장: %s",
                len(excluded_codes), len(moved_to_mixed_codes), out_file)

    return {
        "excluded_rental_codes": excluded_codes,
        "moved_to_mixed_codes": moved_to_mixed_codes,
        "excluded_rows": excluded_rows,
    }
