"""
Rich 기반 실시간 진행률 표시 모듈.

요구사항:
- 단지별 단계별 상태 코드 표시
- 전체 통계 (TOTAL/PROCESSED/VERIFIED/PENDING/FAILED)
- ETA 추정
- 터미널 화면에 실시간 출력
- Windows 콘솔 cp949 인코딩 안전성 보장
"""
from __future__ import annotations

import sys
import time
import logging
from typing import Any

# Windows 콘솔 UTF-8 재구성
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)

console = Console(highlight=False)


class ProgressTracker:
    """수집 진행 상황을 실시간으로 추적하고 표시한다."""

    def __init__(self, total: int):
        self.total = total
        self.processed = 0
        self.verified = 0
        self.pending = 0
        self.failed = 0
        self.start_time = time.time()
        self._last_print_time = 0

    def update(
        self,
        kapt_code: str,
        complex_name: str,
        result: str,
        details: dict[str, str] | None = None,
        elapsed_sec: float = 0,
    ) -> None:
        """단지 처리 완료 후 진행 상황을 갱신한다."""
        self.processed += 1

        if result == "VERIFIED":
            self.verified += 1
        elif result == "PENDING":
            self.pending += 1
        elif result == "FAILED":
            self.failed += 1

        self._print_progress(kapt_code, complex_name, result, details or {}, elapsed_sec)

    def _print_progress(
        self,
        kapt_code: str,
        complex_name: str,
        result: str,
        details: dict[str, str],
        elapsed_sec: float,
    ) -> None:
        """단지 처리 결과를 화면에 표시한다."""
        pct = (self.processed / self.total * 100) if self.total > 0 else 0

        # 결과에 따른 색상
        result_color = {
            "VERIFIED": "green",
            "PENDING": "yellow",
            "FAILED": "red",
            "SKIPPED": "dim",
        }.get(result, "white")

        # 단지 처리 상세 출력
        console.print()
        header = f"[{self.processed:>3}/{self.total} | {pct:5.1f}%] {complex_name}"
        console.print(f"[bold]{header}[/bold]")

        for key, value in details.items():
            # cp949 안전 문자열 사용 ([OK], [..])
            status_icon = "[OK]" if "OK" in value or "MATCH" in value else " ->"
            console.print(f"  {status_icon} {key:<15} {value}")

        console.print(f"   -> Result      [{result_color}]{result}[/{result_color}]")
        if elapsed_sec > 0:
            console.print(f"   -> elapsed     {elapsed_sec:.1f}s")

        # 전체 통계 (매 10건마다 또는 마지막)
        now = time.time()
        if self.processed % 10 == 0 or self.processed == self.total or now - self._last_print_time > 30:
            self._print_summary()
            self._last_print_time = now

    def _print_summary(self) -> None:
        """전체 통계를 표시한다."""
        elapsed_total = time.time() - self.start_time
        avg_per_complex = elapsed_total / self.processed if self.processed > 0 else 0
        remaining = self.total - self.processed
        eta_sec = avg_per_complex * remaining

        # 시간 포맷
        def fmt_time(sec: float) -> str:
            h, r = divmod(int(sec), 3600)
            m, s = divmod(r, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        console.print()
        console.print(f"[dim]{'-' * 50}[/dim]")
        console.print(f"  TOTAL [bold]{self.total}[/bold]  |  "
                      f"PROCESSED [bold]{self.processed}[/bold]  |  "
                      f"[green]VERIFIED {self.verified}[/green]  |  "
                      f"[yellow]PENDING {self.pending}[/yellow]  |  "
                      f"[red]FAILED {self.failed}[/red]  |  "
                      f"REMAINING {remaining}")
        console.print(f"  ELAPSED {fmt_time(elapsed_total)}  |  "
                      f"AVG/COMPLEX {avg_per_complex:.1f}s  |  "
                      f"ETA ~{fmt_time(eta_sec)}")
        console.print(f"[dim]{'-' * 50}[/dim]")

    def print_final_summary(
        self,
        exact_matches: int = 0,
        high_matches: int = 0,
        medium_low_matches: int = 0,
        total_area_rows: int = 0,
        hh_matched: int = 0,
        hh_mismatched: int = 0,
    ) -> None:
        """최종 결과 요약을 표시한다."""
        elapsed_total = time.time() - self.start_time

        def fmt_time(sec: float) -> str:
            h, r = divmod(int(sec), 3600)
            m, s = divmod(r, 60)
            return f"{h:02d}:{m:02d}:{s:02d}"

        console.print()
        console.print("=" * 50)
        console.print("[bold green]KB AREA MASTER COLLECTION COMPLETED[/bold green]")
        console.print("=" * 50)
        console.print()

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Label", style="bold")
        table.add_column("Value")

        table.add_row("Total complexes", str(self.total))
        table.add_row("Processed", str(self.processed))
        table.add_row("Verified", f"[green]{self.verified}[/green]")
        table.add_row("Pending", f"[yellow]{self.pending}[/yellow]")
        table.add_row("Failed", f"[red]{self.failed}[/red]")
        table.add_row("", "")
        table.add_row("KB exact matches", str(exact_matches))
        table.add_row("KB high matches", str(high_matches))
        table.add_row("KB medium/low matches", str(medium_low_matches))
        table.add_row("", "")
        table.add_row("Total area/type rows", str(total_area_rows))
        table.add_row("Household sum matched", str(hh_matched))
        table.add_row("Household sum mismatch", str(hh_mismatched))
        table.add_row("", "")
        table.add_row("Elapsed", fmt_time(elapsed_total))

        console.print(table)

        console.print()
        console.print("[bold]Output:[/bold]")
        console.print("  config/market_cap_area_master.csv")
        console.print("  data/raw/kb/kb_area_types.csv")
        console.print("  data/mapping/kb_complex_mapping.csv")
        console.print("  data/review/area_master_pending.csv")
        console.print()
        console.print("=" * 50)
