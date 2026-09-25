"""
KB부동산 기반 아파트 평형별 세대수·면적·KB시세 수집 ETL 파이프라인 실행 스크립트.

실행 예시:
  파일럿:   python scripts/build_kb_area_master.py --pilot
  전체:     python scripts/build_kb_area_master.py
  특정단지:  python scripts/build_kb_area_master.py --kapt-code A10026094
  headed:   python scripts/build_kb_area_master.py --headed
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

# Windows 콘솔 UTF-8 재구성 (cp949 인코딩 에러 원천 방지)
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

# 프로젝트 루트를 sys.path에 추가
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.kb_area_master.config import (
    ensure_kb_directories, PILOT_KAPT_CODE, PILOT_COMPLEX_NAME,
    KB_REQUEST_DELAY_SEC, KB_MAX_RETRIES, LOG_FILE,
    AUTO_VERIFY_CONFIDENCES,
)
from src.kb_area_master.models import (
    AreaType, CollectionStatus, MatchConfidence, PendingReason,
    ComplexCandidate,
)
from src.kb_area_master.kapt import build_targets_with_kapt
from src.kb_area_master.kb_browser import KBBrowser
from src.kb_area_master.kb_search import generate_search_queries, search_kb_complex
from src.kb_area_master.kb_matcher import (
    calculate_match_score, determine_confidence, match_best_candidate,
    normalize_name_for_match, extract_dong_from_address,
)
from src.kb_area_master.kb_collector import KBCollector
from src.kb_area_master.area_normalizer import aggregate_area_types
from src.kb_area_master.validator import validate_complex, run_pilot_checks
from src.kb_area_master.exporter import (
    export_master_csv, export_kb_raw_csv, export_mapping_csv,
    export_pending_csv, load_mapping_csv,
    build_master_row, build_kb_raw_row,
)
from src.kb_area_master.state import StateManager
from src.kb_area_master.progress import ProgressTracker, console

# ── 로깅 설정 ──
def setup_logging() -> logging.Logger:
    """화면 + 파일 이중 로깅을 설정한다."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 파일 핸들러 (상세)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(fh)

    # 콘솔 핸들러 (간략)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    root_logger.addHandler(ch)

    return logging.getLogger("build_kb_area_master")


# ── 개별 단지 처리 ──
async def process_single_complex(
    row: dict[str, Any],
    browser: KBBrowser,
    collector: KBCollector,
    state_mgr: StateManager,
    existing_mapping: dict[str, dict[str, str]],
    logger: logging.Logger,
) -> dict[str, Any]:
    """
    한 단지를 처리한다: KB 검색 → 매칭 → 수집 → 검증.

    Returns:
        {
            "kapt_code": str,
            "status": str,
            "match_confidence": str,
            "kb_complex_id": str,
            "area_types": list[AreaType],
            "aggregated_rows": list[dict],
            "details": dict[str, str],
            "elapsed": float,
        }
    """
    start = time.time()
    kapt_code = str(row.get("kapt_code", "")).strip()
    complex_name = str(row.get("complex_name", "")).strip()
    dong = str(row.get("dong", "")).strip()
    gu = str(row.get("sigungu", "") or row.get("sigungu_name", "") or "").strip()
    kapt_name = str(row.get("kapt_name", "") or complex_name).strip()
    kapt_hh = int(row.get("total_households", 0) or row.get("households", 0) or 0)
    sale_type = str(row.get("sale_type", "") or "").strip()
    approval_date = str(row.get("approval_date", "") or "").strip()
    road_address = str(row.get("road_address", "") or "").strip()
    legal_address = str(row.get("legal_address", "") or "").strip()

    details: dict[str, str] = {}
    result: dict[str, Any] = {
        "kapt_code": kapt_code,
        "status": "FAILED",
        "match_confidence": "unmatched",
        "kb_complex_id": "",
        "kb_name": "",
        "kb_url": "",
        "area_types": [],
        "aggregated_rows": [],
        "details": details,
        "elapsed": 0,
    }

    # ── STEP 1: K-apt 정보 확인 ──
    details["K-apt"] = f"OK ({kapt_name}, {kapt_hh}세대)" if kapt_name else "MISSING"

    # ── STEP 2: 임대/혼합 사전 판정 ──
    if "혼합" in sale_type:
        result["status"] = "PENDING"
        result["reason_code"] = PendingReason.MIXED_RENTAL_COMPLEX.value
        result["reason"] = f"혼합 단지 (sale_type={sale_type})"
        details["SaleType"] = f"PENDING - {sale_type}"
        result["elapsed"] = time.time() - start
        return result

    if "임대" in sale_type:
        result["status"] = "PENDING"
        result["reason_code"] = PendingReason.RENTAL_COMPLEX.value
        result["reason"] = f"임대 단지 (sale_type={sale_type})"
        details["SaleType"] = f"PENDING - {sale_type}"
        result["elapsed"] = time.time() - start
        return result

    # ── STEP 3: 기존 매핑 캐시 확인 ──
    kb_complex_id = ""
    kb_name = ""
    kb_url = ""
    kb_households = 0
    match_confidence = MatchConfidence.UNMATCHED

    if kapt_code in existing_mapping:
        cached = existing_mapping[kapt_code]
        cached_conf = cached.get("match_confidence", "")
        if cached_conf in ("exact", "high"):
            kb_complex_id = cached.get("kb_complex_id", "")
            kb_name = cached.get("kb_name", "")
            kb_url = cached.get("kb_url", "")
            kb_households = int(cached.get("kb_households", 0) or 0)
            match_confidence = MatchConfidence(cached_conf)
            details["KB Search"] = f"CACHED (id={kb_complex_id})"

    # ── STEP 4: KB 검색 (캐시 없을 때) ──
    if not kb_complex_id:
        queries = generate_search_queries(dong, complex_name, gu)
        all_candidates: list[ComplexCandidate] = []

        for query in queries:
            details["KB Search"] = f"검색 중: {query}"
            try:
                raw_results = await search_kb_complex(browser.page, query)
                for raw in raw_results:
                    # 점수 계산
                    score, reasons = calculate_match_score(
                        kapt_name=kapt_name,
                        kapt_dong=dong,
                        kapt_address=legal_address,
                        kapt_road_address=road_address,
                        kapt_households=kapt_hh,
                        kapt_approval_date=approval_date,
                        kb_name=raw.get("kb_name", ""),
                        kb_address=raw.get("kb_address", ""),
                        kb_dong=raw.get("kb_dong", ""),
                        kb_households=raw.get("kb_households", 0),
                        kb_approval_year=raw.get("kb_approval_year", ""),
                    )
                    candidate = ComplexCandidate(
                        kb_complex_id=raw.get("kb_complex_id", ""),
                        kb_name=raw.get("kb_name", ""),
                        kb_address=raw.get("kb_address", ""),
                        kb_dong=raw.get("kb_dong", ""),
                        kb_households=raw.get("kb_households", 0),
                        kb_url=raw.get("kb_url", ""),
                        match_score=score,
                        match_confidence=determine_confidence(score),
                        match_reasons=reasons,
                    )
                    all_candidates.append(candidate)

                # 충분한 후보가 있으면 추가 검색 생략
                if any(c.match_confidence in (MatchConfidence.EXACT, MatchConfidence.HIGH) for c in all_candidates):
                    break

            except Exception as e:
                logger.warning("KB 검색 실패 (query=%s): %s", query, e)

            await asyncio.sleep(1)

        # 최적 후보 선택
        best = match_best_candidate(all_candidates, kapt_name, dong, kapt_hh)
        if best and best.match_confidence != MatchConfidence.UNMATCHED:
            kb_complex_id = best.kb_complex_id
            kb_name = best.kb_name
            kb_url = best.kb_url
            kb_households = best.kb_households
            match_confidence = best.match_confidence
            details["KB Search"] = f"OK ({len(all_candidates)}후보)"
            details["KB Match"] = f"OK score={best.match_score} confidence={match_confidence.value}"
        else:
            details["KB Search"] = f"후보 {len(all_candidates)}개, 매칭 실패"
            result["status"] = "PENDING"
            result["reason_code"] = PendingReason.KB_COMPLEX_NOT_FOUND.value if not all_candidates else PendingReason.KB_COMPLEX_AMBIGUOUS.value
            result["reason"] = f"KB 단지 매칭 실패 (후보 {len(all_candidates)}개)"
            result["elapsed"] = time.time() - start
            return result

    # ── STEP 5: confidence 미달 → pending ──
    if match_confidence not in AUTO_VERIFY_CONFIDENCES:
        result["status"] = "PENDING"
        result["match_confidence"] = match_confidence.value
        result["kb_complex_id"] = kb_complex_id
        result["kb_name"] = kb_name
        result["reason_code"] = PendingReason.LOW_MATCH_CONFIDENCE.value
        result["reason"] = f"KB 매칭 confidence 부족 ({match_confidence.value})"
        details["KB Match"] = f"PENDING confidence={match_confidence.value}"
        result["elapsed"] = time.time() - start
        return result

    result["kb_complex_id"] = kb_complex_id
    result["kb_name"] = kb_name
    result["kb_url"] = kb_url
    result["match_confidence"] = match_confidence.value

    # ── STEP 6: KB 평형/시세 수집 ──
    area_types: list[AreaType] = []
    for attempt in range(1, KB_MAX_RETRIES + 1):
        try:
            details["KB Types"] = f"수집 중 (시도 {attempt}/{KB_MAX_RETRIES})"
            area_types = await collector.collect_area_types(
                browser.page, kb_complex_id, kb_url
            )
            if area_types:
                break
        except Exception as e:
            logger.warning("평형 수집 실패 (시도 %d/%d, 단지=%s): %s", attempt, KB_MAX_RETRIES, complex_name, e)
            if attempt < KB_MAX_RETRIES:
                await asyncio.sleep(2)

    result["area_types"] = area_types

    if not area_types:
        result["status"] = "PENDING"
        result["reason_code"] = PendingReason.AREA_NOT_AVAILABLE.value
        result["reason"] = "KB 평형 데이터 수집 실패"
        details["KB Types"] = "FAILED"
        result["elapsed"] = time.time() - start
        return result

    collected_hh = sum(at.households for at in area_types)
    has_price = any(at.kb_sale_general for at in area_types)
    details["KB Types"] = f"{len(area_types)} types"
    details["Households"] = f"{collected_hh} / K-apt {kapt_hh}  {'MATCH' if collected_hh == kapt_hh else 'MISMATCH'}"
    details["KB Prices"] = "OK" if has_price else "미확보"

    # ── STEP 7: 면적 집계 ──
    aggregated = aggregate_area_types(kapt_code, area_types)
    result["aggregated_rows"] = aggregated

    # ── STEP 8: 검증 ──
    val = validate_complex(
        kapt_code=kapt_code,
        kapt_name=kapt_name,
        kapt_households=kapt_hh,
        sale_type=sale_type,
        match_confidence=match_confidence,
        area_types=area_types,
        aggregated_rows=aggregated,
    )

    result["status"] = val.status.value
    if val.reason:
        result["reason"] = val.reason
    if val.reason_codes:
        result["reason_code"] = val.reason_codes[0].value

    result["elapsed"] = time.time() - start
    return result


# ── 파일럿 실행 ──
async def run_pilot(browser: KBBrowser, logger: logging.Logger, targets_df: Any) -> bool:
    """
    대연SK뷰힐스 파일럿을 실행하고 12개 체크포인트를 검증한다.

    Returns:
        True = PASS (전체 수집 진행), False = FAIL (중단)
    """
    console.print()
    console.print("=" * 50)
    console.print("[bold cyan]PILOT: 대연SK뷰힐스 파일럿 실행[/bold cyan]")
    console.print("=" * 50)

    # 파일럿 대상 찾기
    pilot_row = None
    for _, row in targets_df.iterrows():
        if str(row.get("kapt_code", "")).strip() == PILOT_KAPT_CODE:
            pilot_row = row.to_dict()
            break

    kapt_found = pilot_row is not None
    if not kapt_found:
        console.print("[red]PILOT FAILED: supplement에서 대연SK뷰힐스를 찾을 수 없습니다.[/red]")
        return False

    # K-apt 정보 확인
    kapt_name = str(pilot_row.get("kapt_name", "") or pilot_row.get("complex_name", "")).strip()
    kapt_hh = int(pilot_row.get("total_households", 0) or pilot_row.get("households", 0) or 0)
    kapt_info_available = bool(kapt_name and kapt_hh > 0)
    console.print(f"  K-apt: {kapt_name}, {kapt_hh}세대")

    # KB 검색/매칭/수집
    collector = KBCollector()
    state_mgr = StateManager()

    result = await process_single_complex(
        row=pilot_row,
        browser=browser,
        collector=collector,
        state_mgr=state_mgr,
        existing_mapping={},
        logger=logger,
    )

    # 파일럿 체크포인트 검증
    area_types = result.get("area_types", [])
    kb_raw_saved = False
    master_conversion_ok = False

    # KB 원본 저장 테스트
    if area_types:
        try:
            raw_rows = [
                build_kb_raw_row(
                    PILOT_KAPT_CODE, kapt_name,
                    result.get("kb_complex_id", ""), result.get("kb_name", ""),
                    result.get("kb_url", ""), at,
                    datetime.now().isoformat(),
                )
                for at in area_types
            ]
            export_kb_raw_csv(raw_rows)
            kb_raw_saved = True
        except Exception as e:
            logger.error("KB 원본 저장 실패: %s", e)

    # market_cap_area_master 변환 테스트
    aggregated = result.get("aggregated_rows", [])
    if aggregated:
        try:
            master_rows = [
                build_master_row(
                    PILOT_KAPT_CODE, ar,
                    result.get("kb_url", ""),
                    result.get("kb_name", ""),
                )
                for ar in aggregated
            ]
            if master_rows:
                master_conversion_ok = True
        except Exception as e:
            logger.error("마스터 변환 실패: %s", e)

    # 12개 체크포인트 출력
    checks_result = run_pilot_checks(
        kapt_code=PILOT_KAPT_CODE,
        kapt_name=kapt_name,
        kapt_found=kapt_found,
        kapt_info_available=kapt_info_available,
        kb_candidates_found=1 if result.get("kb_complex_id") else 0,
        kb_complex_id=result.get("kb_complex_id", ""),
        match_confidence=MatchConfidence(result.get("match_confidence", "unmatched")),
        area_types=area_types,
        kapt_households=kapt_hh,
        kb_raw_saved=kb_raw_saved,
        master_conversion_ok=master_conversion_ok,
    )

    console.print()
    console.print("[bold]파일럿 체크포인트 결과:[/bold]")
    for check in checks_result["checks"]:
        icon = "[green]PASS[/green]" if check["pass"] else "[red]FAIL[/red]"
        console.print(f"  {icon}  {check['name']}")
        console.print(f"         {check['detail']}")

    console.print()

    if checks_result["all_pass"]:
        console.print("=" * 50)
        console.print("[bold green]PILOT SUCCESS[/bold green]")
        console.print("대연SK뷰힐스 수집 및 검증 완료")
        console.print("전체 단지 수집을 시작합니다.")
        console.print("=" * 50)
        return True
    else:
        console.print("=" * 50)
        console.print("[bold red]PILOT FAILED[/bold red]")
        console.print("전체 단지 처리를 시작하지 않습니다.")
        console.print("=" * 50)

        # 실패 상세 정보
        failed_checks = [c for c in checks_result["checks"] if not c["pass"]]
        console.print()
        console.print("[bold]실패 원인:[/bold]")
        for fc in failed_checks:
            console.print(f"  • {fc['name']}: {fc['detail']}")

        return False


# ── 전체 파이프라인 ──
async def run_pipeline(args: argparse.Namespace) -> None:
    """메인 파이프라인 오케스트레이션."""
    logger = setup_logging()
    logger.info("=== KB부동산 아파트 평형별 세대수·면적·시세 ETL 파이프라인 시작 ===")

    ensure_kb_directories()

    # 1. 대상 목록 로드
    targets_df = build_targets_with_kapt()

    if args.kapt_code:
        targets_df = targets_df[targets_df["kapt_code"] == args.kapt_code].copy()
        if targets_df.empty:
            logger.error("지정된 kapt_code(%s)가 대상에 없습니다.", args.kapt_code)
            return
    elif args.name:
        mask = targets_df["complex_name"].str.contains(args.name, na=False, case=False)
        targets_df = targets_df[mask].copy()
        if targets_df.empty:
            logger.error("지정된 단지명(%s)이 대상에 없습니다.", args.name)
            return

    total = len(targets_df)
    logger.info("처리 대상: %d개 단지", total)

    # 2. KB 브라우저 시작
    headless = not args.headed  # 기본은 headless, --headed 옵션 지정 시에만 브라우저 창 표시

    browser = KBBrowser(headless=headless)
    try:
        await browser.launch()

        # 3. 로그인 확인 (비로그인 세션에서도 공개 API 정상 동작)
        logged_in = await browser.ensure_logged_in()

        # 4. 파일럿 검증 (대연SK뷰힐스 1개 단지)
        # 파일럿이 성공해야만 전체 단지로 진행한다.
        pilot_passed = await run_pilot(browser, logger, targets_df)
        if not pilot_passed:
            logger.error("파일럿 검증 실패: 전체 수집으로 진행하지 않고 중단합니다.")
            return

        if args.pilot:
            logger.info("파일럿 전용 모드(--pilot): 파일럿 검증 성공 후 작업을 마칩니다.")
            return

        logger.info("파일럿 검증 PASS! 나머지 대상 단지 수집을 자동으로 계속 진행합니다.")

        # 5. 전체 수집
        state_mgr = StateManager()
        collector = KBCollector()
        progress = ProgressTracker(total)

        # 기존 매핑 캐시 로드
        mapping_df = load_mapping_csv()
        existing_mapping: dict[str, dict[str, str]] = {}
        if not mapping_df.empty:
            for _, mr in mapping_df.iterrows():
                existing_mapping[str(mr.get("kapt_code", ""))] = mr.to_dict()

        # 결과 수집용
        all_verified_rows: list[dict[str, Any]] = []
        all_raw_rows: list[dict[str, Any]] = []
        all_mapping_rows: list[dict[str, Any]] = []
        all_pending_rows: list[dict[str, Any]] = []
        stats = {"exact": 0, "high": 0, "medium_low": 0, "hh_matched": 0, "hh_mismatched": 0}

        for idx, (_, row) in enumerate(targets_df.iterrows(), start=1):
            kapt_code = str(row.get("kapt_code", "")).strip()
            complex_name = str(row.get("complex_name", "")).strip()

            # checkpoint 확인
            if not state_mgr.should_process(
                kapt_code,
                retry_pending=args.retry_pending,
                retry_failed=args.retry_failed,
                refresh=args.refresh,
            ):
                progress.update(kapt_code, complex_name, "SKIPPED", {"State": "이미 처리됨"})
                continue

            # 단지 처리
            try:
                result = await process_single_complex(
                    row=row.to_dict(),
                    browser=browser,
                    collector=collector,
                    state_mgr=state_mgr,
                    existing_mapping=existing_mapping,
                    logger=logger,
                )

                status = result["status"]
                details = result.get("details", {})
                elapsed = result.get("elapsed", 0)

                # 상태 저장
                state_mgr.update(
                    kapt_code,
                    CollectionStatus(status),
                    kb_complex_id=result.get("kb_complex_id", ""),
                    confidence=MatchConfidence(result.get("match_confidence", "unmatched")),
                    error=result.get("reason", ""),
                )

                # 매핑 캐시 기록
                if result.get("kb_complex_id"):
                    all_mapping_rows.append({
                        "kapt_code": kapt_code,
                        "kapt_name": str(row.get("kapt_name", "") or complex_name),
                        "legal_dong": str(row.get("dong", "")),
                        "kapt_address": str(row.get("legal_address", "")),
                        "kapt_households": int(row.get("total_households", 0) or row.get("households", 0) or 0),
                        "kb_complex_id": result["kb_complex_id"],
                        "kb_name": result.get("kb_name", ""),
                        "kb_address": "",
                        "kb_households": "",
                        "kb_url": result.get("kb_url", ""),
                        "match_score": "",
                        "match_confidence": result.get("match_confidence", ""),
                        "match_method": "playwright_search",
                        "verified_at": datetime.now().isoformat(),
                    })

                if status == "VERIFIED":
                    # KB 원본 저장
                    area_types = result.get("area_types", [])
                    collected_at = datetime.now().isoformat()
                    for at in area_types:
                        all_raw_rows.append(build_kb_raw_row(
                            kapt_code, complex_name,
                            result.get("kb_complex_id", ""),
                            result.get("kb_name", ""),
                            result.get("kb_url", ""),
                            at, collected_at,
                        ))

                    # 마스터 행 생성
                    for ar in result.get("aggregated_rows", []):
                        all_verified_rows.append(build_master_row(
                            kapt_code, ar,
                            result.get("kb_url", ""),
                            result.get("kb_name", ""),
                        ))

                    # 통계
                    conf = result.get("match_confidence", "")
                    if conf == "exact":
                        stats["exact"] += 1
                    elif conf == "high":
                        stats["high"] += 1
                    else:
                        stats["medium_low"] += 1

                    kapt_hh = int(row.get("total_households", 0) or row.get("households", 0) or 0)
                    collected_hh = sum(at.households for at in area_types)
                    if collected_hh == kapt_hh:
                        stats["hh_matched"] += 1
                    else:
                        stats["hh_mismatched"] += 1

                elif status in ("PENDING", "FAILED"):
                    all_pending_rows.append({
                        "kapt_code": kapt_code,
                        "kapt_name": complex_name,
                        "legal_dong": str(row.get("dong", "")),
                        "kb_complex_id": result.get("kb_complex_id", ""),
                        "kb_name": result.get("kb_name", ""),
                        "reason_code": result.get("reason_code", ""),
                        "reason": result.get("reason", ""),
                        "match_score": "",
                        "match_confidence": result.get("match_confidence", ""),
                        "kapt_households": int(row.get("total_households", 0) or row.get("households", 0) or 0),
                        "kb_households": "",
                        "types_found": len(result.get("area_types", [])),
                        "recommended_next_action": "",
                        "source_url": result.get("kb_url", ""),
                    })

                progress.update(kapt_code, complex_name, status, details, elapsed)

            except Exception as e:
                logger.error("단지 처리 중 예외 (kapt_code=%s): %s", kapt_code, e, exc_info=True)
                state_mgr.update(kapt_code, CollectionStatus.FAILED, error=str(e))
                progress.update(kapt_code, complex_name, "FAILED", {"Error": str(e)[:80]})

            # 요청 간 대기 (KB 서비스 부하 방지)
            await asyncio.sleep(KB_REQUEST_DELAY_SEC)

            # 주기적으로 산출물 저장 (50건마다)
            if idx % 50 == 0:
                export_master_csv(all_verified_rows)
                export_kb_raw_csv(all_raw_rows)
                export_mapping_csv(all_mapping_rows)
                export_pending_csv(all_pending_rows)

        # 6. 최종 산출물 저장
        export_master_csv(all_verified_rows)
        export_kb_raw_csv(all_raw_rows)
        export_mapping_csv(all_mapping_rows)
        export_pending_csv(all_pending_rows)

        # 7. 최종 요약
        progress.print_final_summary(
            exact_matches=stats["exact"],
            high_matches=stats["high"],
            medium_low_matches=stats["medium_low"],
            total_area_rows=len(all_verified_rows),
            hh_matched=stats["hh_matched"],
            hh_mismatched=stats["hh_mismatched"],
        )

    finally:
        await browser.close()


# ── CLI ──
def main() -> None:
    parser = argparse.ArgumentParser(
        description="KB부동산 기반 아파트 평형별 세대수·면적·KB시세 ETL 파이프라인"
    )
    parser.add_argument("--pilot", action="store_true", help="대연SK뷰힐스 파일럿만 실행")
    parser.add_argument("--kapt-code", type=str, default=None, help="특정 kapt_code 단지만 처리")
    parser.add_argument("--name", type=str, default=None, help="특정 단지명으로 검색")
    parser.add_argument("--retry-pending", action="store_true", help="pending 단지 재시도")
    parser.add_argument("--retry-failed", action="store_true", help="failed 단지 재시도")
    parser.add_argument("--mapping-only", action="store_true", help="KB complex ID 매핑만")
    parser.add_argument("--collect-only", action="store_true", help="평형 데이터만 수집")
    parser.add_argument("--refresh", action="store_true", help="캐시 무시 재수집")
    parser.add_argument("--headed", action="store_true", help="브라우저 화면 표시")

    args = parser.parse_args()
    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
