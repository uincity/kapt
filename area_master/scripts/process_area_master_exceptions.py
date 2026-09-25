"""
2차 파이프라인: KB 평형 마스터 예외처리(PENDING 198건) 오케스트레이터.

실행 예시:
  python scripts/process_area_master_exceptions.py
  python scripts/process_area_master_exceptions.py --audit-only
  python scripts/process_area_master_exceptions.py --stage rental
  python scripts/process_area_master_exceptions.py --stage low-confidence
  python scripts/process_area_master_exceptions.py --stage mismatch
  python scripts/process_area_master_exceptions.py --stage not-found
  python scripts/process_area_master_exceptions.py --stage mixed
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Windows 콘솔 UTF-8 재구성
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
from rich.console import Console
from rich.table import Table

from src.kb_area_master.config import (
    CONFIG_DIR, DATA_DIR, REVIEW_DIR, RAW_KB_DIR, MAPPING_DIR,
    MASTER_COLUMNS,
)
from src.kb_area_master.kb_browser import KBBrowser
from src.kb_area_master.kb_collector import KBCollector
from src.kb_area_master.exporter import (
    build_master_row, build_kb_raw_row, export_master_csv, export_kb_raw_csv,
    export_mapping_csv, export_pending_csv,
)
from src.kb_area_master.stage_a_rental import process_stage_a_rentals
from src.kb_area_master.stage_b_low_confidence import process_stage_b_low_confidence
from src.kb_area_master.stage_c_mismatch import process_stage_c_mismatches
from src.kb_area_master.stage_d_not_found import process_stage_d_not_found
from src.kb_area_master.stage_e_mixed import process_stage_e_mixed

console = Console(highlight=False)
logger = logging.getLogger("process_area_master_exceptions")


def setup_logger() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("process_area_master_exceptions")


async def run_exception_pipeline(args: argparse.Namespace) -> None:
    start_time = time.time()
    log = setup_logger()

    console.print()
    console.print("=" * 50)
    console.print("[bold cyan]KB AREA MASTER PHASE 2 EXCEPTION PROCESSING[/bold cyan]")
    console.print("=" * 50)

    # 1. 파일 경로 확인 및 데이터 로드
    pending_file = REVIEW_DIR / "area_master_pending.csv"
    kapt_file = DATA_DIR / "intermediate" / "kapt_complexes.csv"
    master_file = CONFIG_DIR / "market_cap_area_master.csv"
    raw_file = RAW_KB_DIR / "kb_area_types.csv"
    mapping_file = MAPPING_DIR / "kb_complex_mapping.csv"

    if not pending_file.exists():
        console.print(f"[red]오류: {pending_file} 이 존재하지 않습니다.[/red]")
        return
    if not kapt_file.exists():
        console.print(f"[red]오류: {kapt_file} 이 존재하지 않습니다.[/red]")
        return

    df_pending = pd.read_csv(pending_file)
    df_kapt = pd.read_csv(kapt_file)
    total_pending = len(df_pending)

    console.print(f"Total Pending complexes: [bold]{total_pending}[/bold]")

    # Audit-only 모드
    if args.audit_only:
        console.print("[bold yellow]Audit mode completed. Exiting.[/bold yellow]")
        return

    # 기존 1차 VERIFIED 데이터 로드 및 보존
    df_existing_master = pd.read_csv(master_file) if master_file.exists() else pd.DataFrame(columns=MASTER_COLUMNS)
    initial_master_rows = len(df_existing_master)
    initial_master_complexes = df_existing_master["kapt_code"].nunique()
    console.print(f"Existing Master: [green]{initial_master_complexes} complexes[/green] ({initial_master_rows} rows) - [bold]보존됨[/bold]")

    # 브라우저 시작
    browser = KBBrowser(headless=True)
    await browser.launch()
    await browser.ensure_logged_in()
    collector = KBCollector()

    # 결과 보관 컨테이너
    all_resolved_results: list[dict[str, Any]] = []
    excluded_rental_codes: list[str] = []
    conflicts_rows: list[dict[str, Any]] = []

    # 단계별 실행
    stage_to_run = args.stage

    try:
        # ── STAGE A: 순수 임대 단지 처리 ──
        if not stage_to_run or stage_to_run == "rental":
            res_a = process_stage_a_rentals(df_pending, df_kapt, REVIEW_DIR)
            excluded_rental_codes.extend(res_a["excluded_rental_codes"])

        # ── STAGE B: 저신뢰 / 모호 단지 처리 ──
        if not stage_to_run or stage_to_run == "low-confidence":
            res_b = await process_stage_b_low_confidence(browser.page, df_pending, df_kapt, collector, REVIEW_DIR)
            all_resolved_results.extend(res_b["rematched_results"])

        # ── STAGE C: 세대수 불일치 분석 ──
        if not stage_to_run or stage_to_run == "mismatch":
            res_c = await process_stage_c_mismatches(browser.page, df_pending, df_kapt, collector, REVIEW_DIR)
            all_resolved_results.extend(res_c["resolved_results"])

        # ── STAGE D: KB 검색 미발견 처리 ──
        if not stage_to_run or stage_to_run == "not-found":
            res_d = await process_stage_d_not_found(browser.page, df_pending, df_kapt, collector, REVIEW_DIR)
            all_resolved_results.extend(res_d["resolved_results"])

        # ── STAGE E: 혼합 단지 분양/임대 분리 ──
        if not stage_to_run or stage_to_run == "mixed":
            res_e = await process_stage_e_mixed(browser.page, df_pending, df_kapt, collector, REVIEW_DIR)
            all_resolved_results.extend(res_e["resolved_results"])

    finally:
        await browser.close()

    # ── 마스터 파일 Merge (기존 361개 단지 데이터 보존) ──
    new_master_rows = []
    new_raw_rows = []
    new_mapping_rows = []

    existing_kapt_codes = set(df_existing_master["kapt_code"].astype(str).unique())

    for res in all_resolved_results:
        kcode = res["kapt_code"]
        kname = res["kapt_name"]
        kb_cid = res["kb_complex_id"]
        kb_name = res["kb_name"]
        kb_url = res["kb_url"]
        aggregated = res.get("aggregated_rows", [])
        area_types = res.get("area_types", [])
        notes = res.get("notes", "")

        # 충돌 검사 (기존 검증 단지와 중복 여부)
        if kcode in existing_kapt_codes:
            conflicts_rows.append({
                "kapt_code": kcode,
                "kapt_name": kname,
                "conflict_reason": "2차 수집 단지가 기존 1차 VERIFIED 마스터에 이미 존재함",
                "resolved_at": datetime.now().isoformat(),
            })
            continue

        # 마스터 행 생성
        for ar in aggregated:
            m_row = build_master_row(kcode, ar, kb_url, kb_name)
            if notes:
                m_row["notes"] = notes
            new_master_rows.append(m_row)

        # 원본 데이터 행 생성
        for at in area_types:
            new_raw_rows.append(build_kb_raw_row(
                kcode, kname, kb_cid, kb_name, kb_url, at, datetime.now().isoformat()
            ))

        # 매핑 캐시 행 생성
        new_mapping_rows.append({
            "kapt_code": kcode,
            "kapt_name": kname,
            "legal_dong": "",
            "kapt_address": "",
            "kapt_households": "",
            "kb_complex_id": kb_cid,
            "kb_name": kb_name,
            "kb_address": "",
            "kb_households": "",
            "kb_url": kb_url,
            "match_score": "",
            "match_confidence": res.get("match_confidence", "high"),
            "match_method": "phase2_exception_resolved",
            "verified_at": datetime.now().isoformat(),
        })

    # 파일 업데이트
    if new_master_rows:
        df_new_master = pd.DataFrame(new_master_rows)
        df_final_master = pd.concat([df_existing_master, df_new_master], ignore_index=True)
        df_final_master.to_csv(master_file, index=False, encoding="utf-8-sig")
        console.print(f"[green]Master updated: +{len(new_master_rows)} rows (+{len(all_resolved_results)} complexes)[/green]")

    if new_raw_rows and raw_file.exists():
        df_existing_raw = pd.read_csv(raw_file)
        df_final_raw = pd.concat([df_existing_raw, pd.DataFrame(new_raw_rows)], ignore_index=True)
        df_final_raw.to_csv(raw_file, index=False, encoding="utf-8-sig")

    if new_mapping_rows and mapping_file.exists():
        df_existing_map = pd.read_csv(mapping_file)
        df_final_map = pd.concat([df_existing_map, pd.DataFrame(new_mapping_rows)], ignore_index=True)
        df_final_map.to_csv(mapping_file, index=False, encoding="utf-8-sig")

    if conflicts_rows:
        pd.DataFrame(conflicts_rows).to_csv(REVIEW_DIR / "area_master_conflicts_phase2.csv", index=False, encoding="utf-8-sig")

    # ── Still Pending 산출물 작성 ──
    resolved_codes = set(r["kapt_code"] for r in all_resolved_results)
    excluded_codes_set = set(excluded_rental_codes)

    still_pending_rows = []
    for _, r in df_pending.iterrows():
        kc = str(r["kapt_code"]).strip()
        if kc not in resolved_codes and kc not in excluded_codes_set:
            # next action 결정
            rcode = r.get("reason_code", "")
            next_action = "CHECK_OFFICIAL_SALE_NOTICE"
            if rcode == "MIXED_RENTAL_COMPLEX":
                next_action = "VERIFY_RENTAL_SPLIT"
            elif rcode == "HOUSEHOLDS_MISMATCH":
                next_action = "VERIFY_OFFICIAL_HOUSEHOLDS"
            elif rcode in ["LOW_MATCH_CONFIDENCE", "KB_COMPLEX_AMBIGUOUS"]:
                next_action = "MANUAL_KB_COMPLEX_SELECTION"
            elif rcode == "KB_COMPLEX_NOT_FOUND":
                next_action = "CHECK_BUILDING_REGISTER"

            still_pending_rows.append({
                "kapt_code": kc,
                "kapt_name": r.get("kapt_name", ""),
                "legal_dong": r.get("legal_dong", ""),
                "kapt_households": r.get("kapt_households", ""),
                "original_reason_code": rcode,
                "recommended_next_action": next_action,
                "review_status": "STILL_PENDING",
            })

    pd.DataFrame(still_pending_rows).to_csv(REVIEW_DIR / "phase2_still_pending.csv", index=False, encoding="utf-8-sig")

    # ── 최종 정합성 검사 ──
    phase1_verified_cnt = initial_master_complexes
    phase2_new_verified_cnt = len(all_resolved_results)
    excluded_rental_cnt = len(excluded_rental_codes)
    still_pending_cnt = len(still_pending_rows)
    failed_cnt = 0

    total_accounted = (
        phase1_verified_cnt
        + phase2_new_verified_cnt
        + excluded_rental_cnt
        + still_pending_cnt
        + failed_cnt
    )

    elapsed_str = time.strftime("%H:%M:%S", time.gmtime(time.time() - start_time))

    # ── 최종 보고서 출력 ──
    console.print()
    console.print("=" * 50)
    console.print("[bold green]PHASE 2 COMPLETED[/bold green]")
    console.print("=" * 50)
    console.print(f"Original total complexes      : 560")
    console.print(f"Phase1 VERIFIED               : {phase1_verified_cnt}")
    console.print(f"Phase1 PENDING                : {total_pending}")
    console.print()
    console.print(f"Phase2 newly VERIFIED         : [green]{phase2_new_verified_cnt}[/green]")
    console.print(f"Excluded rental-only          : [cyan]{excluded_rental_cnt}[/cyan]")
    console.print(f"Still pending                 : [yellow]{still_pending_cnt}[/yellow]")
    console.print(f"Failed                        : [red]{failed_cnt}[/red]")
    console.print("-" * 50)
    console.print(f"Total accounted for           : [bold]{total_accounted}[/bold] / 560  "
                  f"({'[green]MATCH 560[/green]' if total_accounted == 560 else '[red]MISMATCH[/red]'})")
    console.print(f"Final Master Complexes        : [bold]{phase1_verified_cnt + phase2_new_verified_cnt}[/bold] 단지")
    console.print(f"Final Master Area Rows        : [bold]{len(pd.read_csv(master_file))}[/bold] 행")
    console.print(f"Total elapsed                 : {elapsed_str}")
    console.print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="KB Area Master Phase 2 Exception Processing")
    parser.add_argument("--audit-only", action="store_true", help="Run audit only and exit")
    parser.add_argument("--stage", choices=["rental", "low-confidence", "mismatch", "not-found", "mixed"],
                        help="Run specific stage only")
    args = parser.parse_args()
    asyncio.run(run_exception_pipeline(args))


if __name__ == "__main__":
    main()
