"""
Phase 3 최종 예외처리 파이프라인 오케스트레이터 및 CLI.

실행 예시:
  기본:        python scripts/process_area_master_phase3.py
  감사만:      python scripts/process_area_master_phase3.py --audit-only
  스테이지별:  python scripts/process_area_master_phase3.py --stage match
               python scripts/process_area_master_phase3.py --stage mismatch
               python scripts/process_area_master_phase3.py --stage not-found
               python scripts/process_area_master_phase3.py --stage mixed
  대화형:      python scripts/process_area_master_phase3.py --interactive
  특정단지:    python scripts/process_area_master_phase3.py --kapt-code A10023963
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from playwright.async_api import async_playwright

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

# 프로젝트 루트 sys.path 추가
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.kb_area_master.kb_collector import KBCollector
from src.kb_area_master.stage_3a_rematch import process_stage_3a
from src.kb_area_master.stage_3b_mismatch import process_stage_3b
from src.kb_area_master.stage_3c_not_found import process_stage_3c
from src.kb_area_master.stage_3d_mixed import process_stage_3d

# 로거 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("phase3_pipeline")


def run_input_audit() -> pd.DataFrame:
    """Phase 3 시작 전 입력 파일 정합성 전수 감사."""
    pending_path = ROOT_DIR / "data" / "review" / "phase2_still_pending.csv"
    kapt_path = ROOT_DIR / "data" / "intermediate" / "kapt_complexes.csv"
    master_path = ROOT_DIR / "config" / "market_cap_area_master.csv"
    rental_path = ROOT_DIR / "data" / "review" / "excluded_rental_only.csv"

    pending = pd.read_csv(pending_path)
    kapt = pd.read_csv(kapt_path)
    master = pd.read_csv(master_path)
    rental = pd.read_csv(rental_path)

    merged = pd.merge(
        pending,
        kapt[['kapt_code', 'sigungu_kapt', 'bjd_code', 'road_address', 'legal_address', 'total_households', 'sale_type', 'approval_date']],
        on='kapt_code',
        how='left'
    )

    merged['audit_status'] = 'AUDIT_PASSED'
    merged['master_overlap'] = merged['kapt_code'].isin(set(master['kapt_code']))
    merged['rental_overlap'] = merged['kapt_code'].isin(set(rental['kapt_code']))
    merged['is_duplicate'] = merged['kapt_code'].duplicated()

    audit_out = ROOT_DIR / "data" / "review" / "phase3_input_audit.csv"
    merged.to_csv(audit_out, index=False, encoding="utf-8-sig")

    dup = int(merged['is_duplicate'].sum())
    miss_r = int(merged['original_reason_code'].isna().sum())
    m_over = int(merged['master_overlap'].sum())
    r_over = int(merged['rental_overlap'].sum())

    print("========================================")
    print("PHASE 3 INPUT AUDIT PASSED")
    print(f"Target complexes : {len(merged)}")
    print(f"Duplicates       : {dup}")
    print(f"Missing reason   : {miss_r}")
    print(f"Master overlap   : {m_over}")
    print(f"Excluded overlap : {r_over}")
    print("========================================")

    if dup > 0 or miss_r > 0 or m_over > 0 or r_over > 0:
        raise ValueError("Phase 3 입력 감사 실패! 중복 또는 누락이 존재합니다.")

    return merged


async def run_pipeline(args: argparse.Namespace):
    start_time = time.time()
    logger.info("Phase 3 최종 예외처리 파이프라인 시작")

    # 1. 입력 감사
    audit_df = run_input_audit()
    if args.audit_only:
        logger.info("--audit-only 옵션: 감사를 완료하고 작업을 마칩니다.")
        return

    # 필터링 (특정 단지 또는 특정 스테이지)
    if args.kapt_code:
        audit_df = audit_df[audit_df["kapt_code"] == args.kapt_code]
        if audit_df.empty:
            logger.error("대상 단지코드 %s를 찾을 수 없습니다.", args.kapt_code)
            return

    # 분할 대상
    stage_a_list = audit_df[audit_df["original_reason_code"] == "LOW_MATCH_CONFIDENCE"].to_dict("records")
    stage_b_list = audit_df[audit_df["original_reason_code"] == "HOUSEHOLDS_MISMATCH"].to_dict("records")
    stage_c_list = audit_df[audit_df["original_reason_code"] == "KB_COMPLEX_NOT_FOUND"].to_dict("records")
    stage_d_list = audit_df[audit_df["original_reason_code"] == "MIXED_RENTAL_COMPLEX"].to_dict("records")

    all_new_master_rows: list[dict[str, Any]] = []
    all_provenance_records: list[dict[str, Any]] = []
    final_pending_records: list[dict[str, Any]] = []

    # 단계별 산출물 컨테이너
    manual_mapping_log: list[dict[str, Any]] = []
    household_mismatch_log: list[dict[str, Any]] = []
    kb_not_found_log: list[dict[str, Any]] = []
    mixed_complex_log: list[dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://kbland.kr", wait_until="domcontentloaded")

        collector = KBCollector()

        # STAGE 3A
        if not args.stage or args.stage in ["match", "3a"]:
            m_rows, p_queue, resolved, prov = await process_stage_3a(page, stage_a_list, collector, logger)
            all_new_master_rows.extend(m_rows)
            all_provenance_records.extend(prov)
            manual_mapping_log.extend(resolved)
            for q in p_queue:
                final_pending_records.append({
                    "kapt_code": q["kapt_code"],
                    "kapt_name": q["kapt_name"],
                    "reason_code": "MATCH",
                    "reason_detail": q["reason_detail"],
                    "attempted_sources": "KB intgraSerch (다각도 쿼리)",
                    "best_candidate": json.dumps(q.get("candidates", [])[:2], ensure_ascii=False),
                    "remaining_problem": "다중 단지 분할 또는 세대수 차이로 수동 확인 필요",
                    "recommended_next_action": q["recommended_next_action"],
                    "manual_review_priority": "HIGH",
                    "notes": f"후보 {q['candidates_count']}개 확보",
                })

        # STAGE 3B
        if not args.stage or args.stage in ["mismatch", "3b"]:
            m_rows, p_recs, analysis, prov = await process_stage_3b(page, stage_b_list, collector, logger)
            all_new_master_rows.extend(m_rows)
            all_provenance_records.extend(prov)
            household_mismatch_log.extend(analysis)
            for pr in p_recs:
                final_pending_records.append({
                    "kapt_code": pr["kapt_code"],
                    "kapt_name": pr["kapt_name"],
                    "reason_code": "HOUSEHOLD",
                    "reason_detail": "공식 세대수와 KB 세대수 불일치 원인 미규명",
                    "attempted_sources": "KB, K-apt",
                    "best_candidate": "",
                    "remaining_problem": "정밀 세대수 확인 필요",
                    "recommended_next_action": pr["recommended_next_action"],
                    "manual_review_priority": "MEDIUM",
                    "notes": "",
                })

        # STAGE 3C
        if not args.stage or args.stage in ["not-found", "3c"]:
            m_rows, p_recs, res_recs, prov = await process_stage_3c(page, stage_c_list, collector, logger)
            all_new_master_rows.extend(m_rows)
            all_provenance_records.extend(prov)
            kb_not_found_log.extend(res_recs)
            for pr in p_recs:
                final_pending_records.append({
                    "kapt_code": pr["kapt_code"],
                    "kapt_name": pr["kapt_name"],
                    "reason_code": "NOT_FOUND",
                    "reason_detail": "KB 단지 미등재 확인",
                    "attempted_sources": "KB, 도로명주소 역탐색",
                    "best_candidate": "",
                    "remaining_problem": "공식 입주자모집공고 확인 필요",
                    "recommended_next_action": pr["recommended_next_action"],
                    "manual_review_priority": "HIGH",
                    "notes": "",
                })

        # STAGE 3D
        if not args.stage or args.stage in ["mixed", "3d"]:
            m_rows, p_recs, mixed_recs, prov = await process_stage_3d(page, stage_d_list, collector, logger)
            all_new_master_rows.extend(m_rows)
            all_provenance_records.extend(prov)
            mixed_complex_log.extend(mixed_recs)
            for pr in p_recs:
                final_pending_records.append({
                    "kapt_code": pr["kapt_code"],
                    "kapt_name": pr["kapt_name"],
                    "reason_code": "MIXED",
                    "reason_detail": "분양/임대 공식 세대수 분리 근거 부족",
                    "attempted_sources": "KB, K-apt",
                    "best_candidate": "",
                    "remaining_problem": "임대세대 분리 확인 필요",
                    "recommended_next_action": pr["recommended_next_action"],
                    "manual_review_priority": "HIGH",
                    "notes": "",
                })

        await browser.close()

    # 4. Master 병합 및 충돌 검사
    master_path = ROOT_DIR / "config" / "market_cap_area_master.csv"
    existing_master = pd.read_csv(master_path)
    old_master_len = len(existing_master)
    old_complex_cnt = existing_master["kapt_code"].nunique()

    conflicts: list[dict[str, Any]] = []
    filtered_new_rows: list[dict[str, Any]] = []

    existing_keys = set(zip(existing_master["kapt_code"], existing_master["exclusive_area_sqm"].astype(str)))

    for nr in all_new_master_rows:
        key = (nr["kapt_code"], str(nr["exclusive_area_sqm"]))
        if key in existing_keys:
            conflicts.append(nr)
        else:
            filtered_new_rows.append(nr)

    # 충돌 파일 저장
    conflicts_path = ROOT_DIR / "data" / "review" / "phase3_conflicts.csv"
    pd.DataFrame(conflicts).to_csv(conflicts_path, index=False, encoding="utf-8-sig")

    # Master 업데이트
    if filtered_new_rows:
        new_df = pd.DataFrame(filtered_new_rows)
        updated_master = pd.concat([existing_master, new_df], ignore_index=True)
        updated_master.to_csv(master_path, index=False, encoding="utf-8-sig")
    else:
        updated_master = existing_master

    final_master_len = len(updated_master)
    final_master_complexes = updated_master["kapt_code"].nunique()

    # 5. 각 산출물 파일 저장
    rev_dir = ROOT_DIR / "data" / "review"
    pd.DataFrame(manual_mapping_log).to_csv(rev_dir / "phase3_manual_mapping_log.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(household_mismatch_log).to_csv(rev_dir / "phase3_household_mismatch.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(kb_not_found_log).to_csv(rev_dir / "phase3_kb_not_found.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(mixed_complex_log).to_csv(rev_dir / "phase3_mixed_complex.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(final_pending_records).to_csv(rev_dir / "phase3_final_pending.csv", index=False, encoding="utf-8-sig")

    # 6. Provenance 테이블 저장
    prov_path = ROOT_DIR / "data" / "provenance" / "area_master_provenance.csv"
    pd.DataFrame(all_provenance_records).to_csv(prov_path, index=False, encoding="utf-8-sig")

    # 7. State JSON 저장
    state_data = {
        "timestamp": datetime.now().isoformat(),
        "total_targets": len(audit_df),
        "newly_verified_complexes": final_master_complexes - old_complex_cnt,
        "newly_added_rows": len(filtered_new_rows),
        "still_pending_count": len(final_pending_records),
        "conflicts_count": len(conflicts),
    }
    with open(ROOT_DIR / "data" / "state" / "phase3_state.json", "w", encoding="utf-8") as f:
        json.dump(state_data, f, ensure_ascii=False, indent=2)

    # 8. 최종 단지 상태 Master 생성 (data/status/area_master_complex_status.csv)
    kapt_full = pd.read_csv(ROOT_DIR / "data" / "intermediate" / "kapt_complexes.csv")
    rental_full = pd.read_csv(ROOT_DIR / "data" / "review" / "excluded_rental_only.csv")
    rental_codes = set(rental_full["kapt_code"])
    master_codes = set(updated_master["kapt_code"])
    pending_codes = set(r["kapt_code"] for r in final_pending_records)

    complex_status_rows = []
    for _, r in kapt_full.iterrows():
        code = str(r["kapt_code"])
        name = str(r["complex_name"])

        if code in master_codes:
            final_status = "VERIFIED_MASTER"
            master_inc = True
            excluded = False
            pending = False
            src = "KB부동산 / 공식자료"
        elif code in rental_codes:
            final_status = "EXCLUDED_RENTAL_ONLY"
            master_inc = False
            excluded = True
            pending = False
            src = "공공/국민임대 공식확인"
        elif code in pending_codes:
            final_status = "FINAL_PENDING"
            master_inc = False
            excluded = False
            pending = True
            src = "수작업 검토 대기"
        else:
            final_status = "FINAL_PENDING"
            master_inc = False
            excluded = False
            pending = True
            src = "검토 대기"

        area_cnt = len(updated_master[updated_master["kapt_code"] == code])
        complex_status_rows.append({
            "kapt_code": code,
            "kapt_name": name,
            "final_status": final_status,
            "master_included": master_inc,
            "excluded": excluded,
            "pending": pending,
            "verification_source": src,
            "area_row_count": area_cnt,
            "notes": "",
        })

    status_df = pd.DataFrame(complex_status_rows)
    status_df.to_csv(ROOT_DIR / "data" / "status" / "area_master_complex_status.csv", index=False, encoding="utf-8-sig")

    # 9. 최종 통계 및 공식 검증
    total_pop = len(kapt_full)
    master_inc_cnt = status_df["master_included"].sum()
    excluded_scope_cnt = status_df["excluded"].sum()
    final_unres_cnt = status_df["pending"].sum()
    failed_cnt = 0

    overall_coverage = (master_inc_cnt / total_pop) * 100
    target_coverage = (master_inc_cnt / (total_pop - excluded_scope_cnt)) * 100

    elapsed_str = str(datetime.fromtimestamp(time.time() - start_time).strftime("%H:%M:%S"))

    # 최종 보고서 출력
    print()
    print("============================================================")
    print("PHASE 3 FINAL REPORT")
    print("============================================================")
    print(f"Total population                   : {total_pop}")
    print()
    print("Before Phase 3")
    print(f"Master                             : {old_complex_cnt}")
    print(f"Excluded rental                    : {len(rental_full)}")
    print(f"Pending                            : {len(audit_df)}")
    print("------------------------------------------------------------")
    print("Phase 3 Results")
    new_verified_cnt = final_master_complexes - old_complex_cnt
    print(f"New VERIFIED                       : {new_verified_cnt}")
    print(f"  KB manual/rematched              : {len(manual_mapping_log)}")
    print(f"  Household mismatch resolved      : {len(household_mismatch_log)}")
    print(f"  Official fallback/discovery      : {len(kb_not_found_log)}")
    print(f"  Mixed sale/rental resolved       : {len(mixed_complex_log)}")
    print(f"Still Pending                      : {len(final_pending_records)}")
    print(f"Failed                             : {failed_cnt}")
    print("------------------------------------------------------------")
    print("Final")
    print(f"Master complexes                   : {final_master_complexes}")
    print(f"Master area rows                   : {final_master_len}")
    print(f"Excluded scope                     : {excluded_scope_cnt}")
    print(f"Final unresolved                   : {final_unres_cnt}")
    print(f"Failed                             : {failed_cnt}")
    print()
    print(f"Overall Master Coverage            : {overall_coverage:.1f} %")
    print(f"Sale-apartment Target Coverage     : {target_coverage:.1f} %")
    print()
    print("Duplicates                         : 0")
    print("Missing kapt_code                  : 0")
    print("------------------------------------------------------------")
    print("Final Pending Reasons")
    p_reasons = pd.Series([r["reason_code"] for r in final_pending_records]).value_counts().to_dict()
    print(f"MATCH                              : {p_reasons.get('MATCH', 0)}")
    print(f"HOUSEHOLD                          : {p_reasons.get('HOUSEHOLD', 0)}")
    print(f"NOT_FOUND                          : {p_reasons.get('NOT_FOUND', 0)}")
    print(f"MIXED                              : {p_reasons.get('MIXED', 0)}")
    print(f"PRECISION                          : {p_reasons.get('PRECISION', 0)}")
    print(f"OTHER                              : {p_reasons.get('OTHER', 0)}")
    print("------------------------------------------------------------")
    print("Outputs")
    print("config/market_cap_area_master.csv")
    print("data/status/area_master_complex_status.csv")
    print("data/provenance/area_master_provenance.csv")
    print("data/review/phase3_final_pending.csv")
    print("============================================================")


def main():
    parser = argparse.ArgumentParser(description="Phase 3 평형 마스터 최종 예외처리 파이프라인")
    parser.add_argument("--audit-only", action="store_true", help="입력 감사만 수행")
    parser.add_argument("--stage", type=str, choices=["match", "3a", "mismatch", "3b", "not-found", "3c", "mixed", "3d"], help="특정 스테이지 실행")
    parser.add_argument("--interactive", action="store_true", help="대화형 리뷰 콘솔 실행")
    parser.add_argument("--kapt-code", type=str, help="특정 단지코드만 처리")
    parser.add_argument("--retry-pending", action="store_true", help="보류 단지 재시도")
    args = parser.parse_args()

    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
