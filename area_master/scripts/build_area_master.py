"""
부산 지역 아파트 전용면적별 세대수 수집·검증 ETL 파이프라인 실행 스크립트.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.area_master.config import ensure_directories
from src.area_master.load_targets import load_targets
from src.area_master.kapt_client import build_kapt_complexes_intermediate
from src.area_master.bldrgst_client import BuildingLedgerClient, QuotaExceededError
from src.area_master.matcher import match_complex
from src.area_master.aggregate import aggregate_exclusive_areas
from src.area_master.validator import validate_complex_and_areas
from src.area_master.exporter import (
    export_master_csv,
    export_pending_csv,
    export_intermediate_artifacts,
)


def setup_logger() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("build_area_master")


def run_pipeline(
    limit: int | None = None,
    kapt_code: str | None = None,
    refresh: bool = False,
    only_pending: bool = False,
) -> dict[str, Any]:
    logger = setup_logger()
    logger.info("=== 아파트 전용면적별 세대수 ETL 파이프라인 시작 ===")
    ensure_directories()

    targets_df = load_targets()
    if kapt_code:
        targets_df = targets_df[targets_df["kapt_code"] == kapt_code].copy()
        if targets_df.empty:
            raise ValueError(f"지정된 kapt_code({kapt_code})가 supplement 대상에 없습니다.")
    elif limit and limit > 0:
        targets_df = targets_df.head(limit).copy()

    total_targets = len(targets_df)
    logger.info("처리 대상 단지 수: %d개", total_targets)

    kapt_merged = build_kapt_complexes_intermediate(targets_df)
    client = BuildingLedgerClient()

    matches_list: list[dict[str, Any]] = []
    all_area_rows: list[dict[str, Any]] = []
    validation_results: list[dict[str, Any]] = []

    verified_area_rows: list[dict[str, Any]] = []
    pending_complex_records: list[dict[str, Any]] = []

    quota_exhausted = False

    for idx, (_, row) in enumerate(kapt_merged.iterrows(), start=1):
        cur_code = str(row["kapt_code"]).strip()
        cur_name = str(row.get("kapt_name") or row.get("complex_name", "")).strip()
        sale_type = str(row.get("sale_type", "") or "").strip()
        kapt_hh = int(row.get("total_households", 0) or 0)

        # 1. 단지 매칭
        try:
            match_info = match_complex(row, client)
        except Exception as exc:
            logger.warning("단지 매칭 중 예외 발생 (단지=%s, 코드=%s): %s", cur_name, cur_code, exc)
            match_info = {
                "sigungu_cd": "",
                "bjdong_cd": "",
                "bun": "",
                "ji": "",
                "match_score": 0,
                "match_confidence": "none",
                "matched_title": None,
                "reason": f"매칭 예외 발생: {exc}",
            }
        matches_list.append(match_info)

        sigungu = match_info["sigungu_cd"]
        bjdong = match_info["bjdong_cd"]
        bun = match_info["bun"]
        ji = match_info["ji"]

        # 2. 혼합 / 임대 단지 판정
        if "혼합" in sale_type:
            pending_complex_records.append({
                "kapt_code": cur_code,
                "kapt_name": cur_name,
                "reason": f"혼합 단지 (분양+임대 혼합, sale_type={sale_type}) - 분양 세대 분리 필요",
                "match_confidence": match_info["match_confidence"],
                "kapt_households": kapt_hh,
                "collected_households": 0,
                "sale_households": None,
                "source": "K-apt 및 국토교통부 건축물대장 2026-09",
                "recommended_next_source": "LH/BMC 공급자료 또는 입주자모집공고",
            })
            continue

        if "임대" in sale_type:
            pending_complex_records.append({
                "kapt_code": cur_code,
                "kapt_name": cur_name,
                "reason": f"임대 단지 (sale_type={sale_type}) - 매매 가능 세대(sale_apartment) 부재 또는 미확인",
                "match_confidence": match_info["match_confidence"],
                "kapt_households": kapt_hh,
                "collected_households": 0,
                "sale_households": 0,
                "source": "K-apt 및 국토교통부 건축물대장 2026-09",
                "recommended_next_source": "임대주택 공고문 및 분양전환 여부 확인",
            })
            continue

        # 3. 매칭 신뢰도 미달 단지
        if match_info["match_score"] < 50:
            pending_complex_records.append({
                "kapt_code": cur_code,
                "kapt_name": cur_name,
                "reason": f"단지 매칭 신뢰도 부족 (score={match_info['match_score']}, confidence={match_info['match_confidence']})",
                "match_confidence": match_info["match_confidence"],
                "kapt_households": kapt_hh,
                "collected_households": 0,
                "sale_households": None,
                "source": "국토교통부 건축물대장 BldRgstHubService 2026-09",
                "recommended_next_source": "공식 지번 재확인 및 건축물대장 수기 대조",
            })
            continue

        # 4. 전유부 수집 (캐시 확인 및 쿼터 처리)
        exclusive_units: list[dict[str, Any]] = []
        is_cached = (client.cache_dir / f"exclusive_{sigungu}_{bjdong}_{bun}_{ji}.json").exists()

        if sigungu and bjdong and bun:
            if is_cached or not quota_exhausted:
                try:
                    exclusive_units = client.get_exclusive_units(sigungu, bjdong, bun, ji, refresh=refresh)
                except QuotaExceededError:
                    quota_exhausted = True
                    logger.warning("일일 쿼터 초과 상태로 전환. 남은 미캐시 단지는 pending 기록합니다.")
                except Exception as e:
                    logger.warning("전유부 수집 실패 (단지=%s): %s", cur_name, e)

        # 5. 전용면적 정밀 집계
        area_rows, collected_hh, non_res_cnt = aggregate_exclusive_areas(cur_code, exclusive_units)
        all_area_rows.extend(area_rows)

        # 6. 정합성 검증 및 판정
        val_res = validate_complex_and_areas(row.to_dict(), match_info, area_rows, collected_hh)
        
        # 쿼터 초과로 수집 못한 경우 사유 명시
        if quota_exhausted and not is_cached and collected_hh == 0:
            val_res["status"] = "pending"
            val_res["reason"] = "공공데이터포털 일일 API 호출 한도 초과(429 Quota Exceeded) - 전유부 미수집"
            val_res["recommended_next_source"] = "자정 이후 API 쿼터 리셋 시 재실행 (python scripts/build_area_master.py)"

        val_record = {
            "kapt_code": cur_code,
            "kapt_name": cur_name,
            **val_res,
            "match_score": match_info["match_score"],
            "match_confidence": match_info["match_confidence"],
        }
        validation_results.append(val_record)

        # 7. verified / pending 분류
        if val_res["status"] == "verified":
            for ar in area_rows:
                verified_area_rows.append({
                    **ar,
                    "source": "국토교통부 건축물대장 전유공용면적 BldRgstHubService 2026-09",
                    "notes": f"호별전유부({collected_hh}세대) K-apt 총세대수 일치",
                })
        else:
            pending_complex_records.append({
                "kapt_code": cur_code,
                "kapt_name": cur_name,
                "reason": val_res["reason"],
                "match_confidence": match_info["match_confidence"],
                "kapt_households": val_res["kapt_households"],
                "collected_households": val_res["collected_households"],
                "sale_households": val_res["sale_households"],
                "source": "국토교통부 건축물대장 BldRgstHubService 2026-09",
                "recommended_next_source": val_res["recommended_next_source"],
            })

        if idx % 20 == 0 or idx == total_targets:
            logger.info(
                "진행 상황: [%d/%d] 완료 (Verified: %d단지, Pending: %d단지)",
                idx, total_targets,
                len({r["kapt_code"] for r in verified_area_rows}),
                len(pending_complex_records),
            )

    # 8. 산출물 저장
    export_intermediate_artifacts(matches_list, all_area_rows, validation_results)
    master_df = export_master_csv(verified_area_rows)
    pending_df = export_pending_csv(pending_complex_records)

    # 9. 통계 분석 및 출력
    verified_complex_cnt = len({r["kapt_code"] for r in verified_area_rows})
    pending_complex_cnt = len(pending_complex_records)

    logger.info("==========================================")
    logger.info("파이프라인 실행 결과 요약 통계")
    logger.info("==========================================")
    logger.info("전체 대상 단지 수: %d", total_targets)
    logger.info("자동 Verified 단지 수: %d", verified_complex_cnt)
    logger.info("Pending (검토 필요) 단지 수: %d", pending_complex_cnt)
    logger.info("최종 생성된 평형 row 수: %d", len(master_df))

    if not pending_df.empty:
        logger.info("\n--- Pending 사유별 분포 ---")
        reason_counts = pending_df["reason"].value_counts()
        for reason, count in reason_counts.items():
            logger.info(" - %s: %d건", reason, count)
    logger.info("==========================================")

    return {
        "total_targets": total_targets,
        "verified_complexes": verified_complex_cnt,
        "pending_complexes": pending_complex_cnt,
        "master_rows": len(master_df),
        "pending_df": pending_df,
        "master_df": master_df,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="부산 아파트 전용면적별 세대수 ETL 파이프라인")
    parser.add_argument("--limit", type=int, default=None, help="처리할 단지 수 제한")
    parser.add_argument("--kapt-code", type=str, default=None, help="특정 kapt_code 단지만 처리")
    parser.add_argument("--refresh", action="store_true", help="API 캐시 무시 및 재수집")
    parser.add_argument("--only-pending", action="store_true", help="보완 대상 중 pending 건만 재처리")
    args = parser.parse_args()

    run_pipeline(
        limit=args.limit,
        kapt_code=args.kapt_code,
        refresh=args.refresh,
        only_pending=args.only_pending,
    )


if __name__ == "__main__":
    main()
