"""
Checkpoint / Resume 상태 관리 모듈.

왜 필요한가:
- 560개 단지를 처리하다 중간에 종료되더라도 처음부터 재시작하지 않기 위해.
- 각 단지 처리 완료 시 상태를 JSON에 기록.
- 재실행 시 VERIFIED → skip, PENDING → skip/retry, FAILED → retry.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import COLLECTION_STATE_FILE, STATE_DIR
from .models import CollectionStatus, ComplexState, MatchConfidence

logger = logging.getLogger(__name__)


class StateManager:
    """단지별 수집 상태를 JSON 파일로 관리한다."""

    def __init__(self, state_file: Path | None = None):
        self._file = state_file or COLLECTION_STATE_FILE
        self._states: dict[str, ComplexState] = {}
        self._load()

    def _load(self) -> None:
        """기존 상태 파일을 로드한다."""
        if not self._file.exists():
            return

        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for kapt_code, state_dict in data.items():
                self._states[kapt_code] = ComplexState(
                    kapt_code=kapt_code,
                    status=CollectionStatus(state_dict.get("status", "WAITING")),
                    kb_complex_id=state_dict.get("kb_complex_id", ""),
                    match_confidence=MatchConfidence(state_dict.get("match_confidence", "unmatched")),
                    attempts=state_dict.get("attempts", 0),
                    last_error=state_dict.get("last_error", ""),
                    updated_at=state_dict.get("updated_at", ""),
                )
            logger.info("상태 파일 로드: %d건 (%s)", len(self._states), self._file.name)
        except Exception as e:
            logger.warning("상태 파일 로드 실패: %s", e)

    def save(self) -> None:
        """현재 상태를 JSON 파일에 저장한다."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)

        data = {}
        for kapt_code, state in self._states.items():
            data[kapt_code] = {
                "status": state.status.value,
                "kb_complex_id": state.kb_complex_id,
                "match_confidence": state.match_confidence.value,
                "attempts": state.attempts,
                "last_error": state.last_error,
                "updated_at": state.updated_at,
            }

        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get(self, kapt_code: str) -> ComplexState | None:
        """단지 상태를 조회한다."""
        return self._states.get(kapt_code)

    def update(
        self,
        kapt_code: str,
        status: CollectionStatus,
        kb_complex_id: str = "",
        confidence: MatchConfidence = MatchConfidence.UNMATCHED,
        error: str = "",
    ) -> None:
        """단지 상태를 갱신하고 즉시 저장한다."""
        if kapt_code not in self._states:
            self._states[kapt_code] = ComplexState(kapt_code=kapt_code)

        state = self._states[kapt_code]
        state.status = status
        if kb_complex_id:
            state.kb_complex_id = kb_complex_id
        if confidence != MatchConfidence.UNMATCHED:
            state.match_confidence = confidence
        state.attempts += 1
        state.last_error = error
        state.updated_at = datetime.now().isoformat()

        self.save()

    def should_process(
        self,
        kapt_code: str,
        retry_pending: bool = False,
        retry_failed: bool = False,
        refresh: bool = False,
    ) -> bool:
        """
        해당 단지를 처리해야 하는지 판단한다.

        - VERIFIED → skip (refresh=True이면 재처리)
        - PENDING → skip (retry_pending=True이면 재처리)
        - FAILED → skip (retry_failed=True이면 재처리)
        - WAITING/미등록 → 처리
        """
        if refresh:
            return True

        state = self._states.get(kapt_code)
        if state is None:
            return True

        if state.status == CollectionStatus.VERIFIED:
            return False  # 이미 확정됨

        if state.status == CollectionStatus.PENDING:
            return retry_pending

        if state.status == CollectionStatus.FAILED:
            return retry_failed

        # WAITING 등 나머지는 처리
        return True

    def get_summary(self) -> dict[str, int]:
        """상태별 통계를 반환한다."""
        summary: dict[str, int] = {}
        for state in self._states.values():
            key = state.status.value
            summary[key] = summary.get(key, 0) + 1
        return summary
