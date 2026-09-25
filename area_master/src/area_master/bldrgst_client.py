"""
국토교통부 건축물대장 오픈API (BldRgstHubService) 클라이언트.

재시도(Retry), 지수 백오프(Exponential Backoff), 타임아웃, 로컬 JSON 캐싱을 통해
안정적이고 재현 가능한 데이터 수집을 보장합니다.
일일 쿼터 초과(LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR) 시
QuotaExceededError를 발생시켜 파이프라인이 안전하게 pending 처리할 수 있도록 지원합니다.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
import requests
import xmltodict

from .config import RAW_BLDRGST_DIR, get_api_key

logger = logging.getLogger(__name__)

BASE_URL = "http://apis.data.go.kr/1613000/BldRgstHubService"


class QuotaExceededError(Exception):
    """공공데이터포털 일일 호출 쿼터 초과 예외."""
    pass


class BuildingLedgerClient:
    """건축물대장 정보 수집 클라이언트."""

    def __init__(
        self,
        service_key: str | None = None,
        cache_dir: Path | None = None,
        timeout: int = 15,
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        request_interval: float = 0.15,
    ):
        self.service_key = service_key or get_api_key("PUBLIC_DATA_API_KEY")
        if not self.service_key:
            raise ValueError("PUBLIC_DATA_API_KEY가 설정되지 않았습니다.")
        self.cache_dir = cache_dir or RAW_BLDRGST_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.request_interval = request_interval
        self.session = requests.Session()

    def _request_with_retry(self, url: str) -> dict[str, Any]:
        """네트워크 오류 및 일시적 서버 장애/429에 대해 안전한 백오프 재시도를 수행합니다."""
        for attempt in range(1, self.max_retries + 1):
            try:
                time.sleep(self.request_interval)
                response = self.session.get(url, timeout=self.timeout)
                if response.status_code == 200:
                    data = xmltodict.parse(response.text)
                    header = data.get("response", {}).get("header", {})
                    code = str(header.get("resultCode", "00"))
                    if code in ("00", "0"):
                        return data
                    msg = header.get("resultMsg", "")
                    logger.warning("API 결과코드 이상 (%s: %s) 시도 %d/%d", code, msg, attempt, self.max_retries)
                elif response.status_code == 429:
                    # 일일 쿼터 초과 확인
                    if "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR" in response.text or "22" in response.text:
                        logger.warning("공공데이터포털 일일 API 호출 한도 초과(429 Quota Exceeded) 감지!")
                        raise QuotaExceededError("공공데이터포털 일일 API 호출 한도 초과(429)")
                    
                    sleep_sec = 5.0 * attempt
                    logger.warning("HTTP 429 감지. %0.1f초 대기 후 재시도 (%d/%d)", sleep_sec, attempt, self.max_retries)
                    time.sleep(sleep_sec)
                    continue
                else:
                    logger.warning("HTTP %d 응답 발생 시도 %d/%d", response.status_code, attempt, self.max_retries)
            except QuotaExceededError:
                raise
            except Exception as exc:
                logger.warning("요청 실패 (%s) 시도 %d/%d", type(exc).__name__, attempt, self.max_retries)

            if attempt < self.max_retries:
                sleep_sec = self.backoff_factor * (2 ** (attempt - 1))
                time.sleep(sleep_sec)

        raise RuntimeError(f"API 요청이 {self.max_retries}회 연속 실패하였습니다: {url}")

    def get_title_info(
        self,
        sigungu_cd: str,
        bjdong_cd: str,
        bun: str,
        ji: str,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """
        표제부(getBrTitleInfo) 정보를 조회합니다.
        """
        cache_file = self.cache_dir / f"title_{sigungu_cd}_{bjdong_cd}_{bun}_{ji}.json"
        if not refresh and cache_file.exists():
            try:
                content = cache_file.read_text(encoding="utf-8")
                if content.strip() and len(content) > 5:
                    return json.loads(content)
            except Exception:
                pass

        url = (
            f"{BASE_URL}/getBrTitleInfo?"
            f"serviceKey={self.service_key}&"
            f"sigunguCd={sigungu_cd}&bjdongCd={bjdong_cd}&"
            f"bun={bun}&ji={ji}&numOfRows=100&pageNo=1"
        )
        data = self._request_with_retry(url)
        body = data.get("response", {}).get("body", {})
        items = body.get("items", {}).get("item", []) if body.get("items") else []
        if isinstance(items, dict):
            items = [items]

        cache_file.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return items

    def get_exclusive_units(
        self,
        sigungu_cd: str,
        bjdong_cd: str,
        bun: str,
        ji: str,
        refresh: bool = False,
        max_pages: int = 80,
    ) -> list[dict[str, Any]]:
        """
        전유공용면적(getBrExposPubuseAreaInfo)을 페이징 조회하여
        '전유(exposPubuseGbCd==1)'인 호별 정보를 모두 수집합니다.
        초대형 필지(수만 건)의 무한 페이징을 방지하기 위해 max_pages(기본 80페이지, 최대 8,000건) 상한을 둡니다.
        """
        cache_file = self.cache_dir / f"exclusive_{sigungu_cd}_{bjdong_cd}_{bun}_{ji}.json"
        if not refresh and cache_file.exists():
            try:
                content = cache_file.read_text(encoding="utf-8")
                if content.strip() and len(content) > 5:
                    return json.loads(content)
            except Exception:
                pass

        page = 1
        all_exclusive_units: list[dict[str, Any]] = []
        total_count = None

        while True:
            url = (
                f"{BASE_URL}/getBrExposPubuseAreaInfo?"
                f"serviceKey={self.service_key}&"
                f"sigunguCd={sigungu_cd}&bjdongCd={bjdong_cd}&"
                f"bun={bun}&ji={ji}&numOfRows=100&pageNo={page}"
            )
            data = self._request_with_retry(url)
            body = data.get("response", {}).get("body", {})
            if total_count is None:
                total_count = int(body.get("totalCount", 0) or 0)
                if total_count == 0:
                    break

            items_container = body.get("items")
            items = items_container.get("item", []) if items_container else []
            if isinstance(items, dict):
                items = [items]
            if not items:
                break

            for it in items:
                if it.get("exposPubuseGbCd") == "1":
                    all_exclusive_units.append({
                        "bldNm": it.get("bldNm"),
                        "dongNm": it.get("dongNm"),
                        "hoNm": it.get("hoNm"),
                        "flrNo": it.get("flrNo"),
                        "area": str(it.get("area", "")).strip(),
                        "mainPurpsCd": it.get("mainPurpsCd"),
                        "mainPurpsCdNm": it.get("mainPurpsCdNm"),
                        "etcPurps": it.get("etcPurps"),
                    })

            if page * 100 >= total_count or page >= max_pages:
                break
            page += 1

        cache_file.write_text(
            json.dumps(all_exclusive_units, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return all_exclusive_units
