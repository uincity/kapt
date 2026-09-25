"""
최종 master CSV 및 검토 대상 pending CSV 내보내기 모듈.

기존 13개 컬럼 규격을 100% 보존하며,
verified 데이터는 config/market_cap_area_master.csv에,
pending 예외 단지는 data/review/area_master_pending.csv에 분리하여 저장합니다.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any
import pandas as pd

from .config import (
    CONFIG_DIR,
    ROOT_DIR,
    REVIEW_DIR,
    INTERMEDIATE_DIR,
    MASTER_COLUMNS,
)

logger = logging.getLogger(__name__)


def export_master_csv(
    verified_area_rows: list[dict[str, Any]],
    output_path: Path | None = None,
    verified_date_str: str | None = None,
) -> pd.DataFrame:
    """
    검증 완료된 평형별 세대수 행들을 market_cap_area_master.csv 형식으로 내보냅니다.
    """
    today_str = verified_date_str or date.today().isoformat()
    dest_path = output_path or (CONFIG_DIR / "market_cap_area_master.csv")

    # 기존 마스터가 있는 경우 기존 검증 행 보존/충돌 확인
    existing_df = pd.DataFrame(columns=MASTER_COLUMNS)
    if dest_path.exists():
        try:
            existing_df = pd.read_csv(dest_path, dtype=str).fillna("")
        except Exception:
            pass

    records: list[dict[str, Any]] = []
    for r in verified_area_rows:
        records.append({
            "kapt_code": str(r["kapt_code"]).strip(),
            "area_group_id": str(r["area_group_id"]).strip(),
            "exclusive_area_sqm": str(r["exclusive_area_sqm"]).strip(),
            "supply_area_sqm": str(r.get("supply_area_sqm", "")).strip(),
            "type_name": str(r.get("type_name", "")).strip(),
            "households": int(r["households"]),
            "source": str(r.get("source", "국토교통부 건축물대장 전유공용면적 BldRgstHubService 2026-09")).strip(),
            "verified_at": today_str,
            "valid_from": "",  # 규칙: 명확한 세대구성 개정 시작 근거 없으면 빈칸 유지
            "valid_to": "",
            "verification_status": "verified",
            "scope": "sale_apartment",
            "notes": str(r.get("notes", "")).strip(),
        })

    new_df = pd.DataFrame(records, columns=MASTER_COLUMNS)

    # 기존 데이터와 결합 시 중복/충돌 처리
    if not existing_df.empty:
        # kapt_code + exclusive_area_sqm 기준 충돌 점검
        comb_key = ["kapt_code", "exclusive_area_sqm"]
        merged_map = {}
        for _, row in existing_df.iterrows():
            key = (row["kapt_code"], row["exclusive_area_sqm"])
            merged_map[key] = row.to_dict()

        for _, row in new_df.iterrows():
            key = (row["kapt_code"], row["exclusive_area_sqm"])
            merged_map[key] = row.to_dict()

        final_df = pd.DataFrame(list(merged_map.values()), columns=MASTER_COLUMNS)
    else:
        final_df = new_df

    # 정렬: kapt_code, exclusive_area_sqm
    final_df["households"] = pd.to_numeric(final_df["households"], errors="coerce")
    final_df = final_df.sort_values(by=["kapt_code", "exclusive_area_sqm"]).reset_index(drop=True)

    # 1. config/market_cap_area_master.csv에 저장
    final_df.to_csv(dest_path, index=False, encoding="utf-8-sig")
    logger.info("최종 master CSV 저장 완료: %s (%d행)", dest_path, len(final_df))

    # 2. 루트의 market_cap_area_master.csv에도 동기화
    root_master = ROOT_DIR / "market_cap_area_master.csv"
    final_df.to_csv(root_master, index=False, encoding="utf-8-sig")

    return final_df


def export_pending_csv(
    pending_records: list[dict[str, Any]],
    output_path: Path | None = None,
) -> pd.DataFrame:
    """
    미확인/검토 필요 단지 목록(area_master_pending.csv)을 내보냅니다.
    """
    dest_path = output_path or (REVIEW_DIR / "area_master_pending.csv")

    pending_cols = [
        "kapt_code",
        "kapt_name",
        "reason",
        "match_confidence",
        "kapt_households",
        "collected_households",
        "sale_households",
        "source",
        "recommended_next_source",
    ]

    df = pd.DataFrame(pending_records, columns=pending_cols)
    df.to_csv(dest_path, index=False, encoding="utf-8-sig")
    logger.info("검토 대상 pending CSV 저장 완료: %s (%d단지)", dest_path, len(df))
    return df


def export_intermediate_artifacts(
    matches: list[dict[str, Any]],
    area_rows: list[dict[str, Any]],
    val_results: list[dict[str, Any]],
) -> None:
    """
    디버깅 및 추적성을 위한 중간 산출물들을 CSV로 저장합니다.
    """
    if matches:
        pd.DataFrame(matches).to_csv(INTERMEDIATE_DIR / "complex_matches.csv", index=False, encoding="utf-8-sig")
    if area_rows:
        pd.DataFrame(area_rows).to_csv(INTERMEDIATE_DIR / "area_grouped.csv", index=False, encoding="utf-8-sig")
    if val_results:
        pd.DataFrame(val_results).to_csv(INTERMEDIATE_DIR / "validation_results.csv", index=False, encoding="utf-8-sig")
