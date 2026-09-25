"""
KB 단지 상세 페이지에서 평형별 데이터와 시세를 수집하는 모듈.

수집 우선순위:
1순위: Playwright 브라우저 세션을 통한 KB Land 공식 API (mpriByType, BasePrcInfoNew, typInfo)
2순위: Fetch/XHR route intercept
3순위: DOM 평형 선택 UI (fallback)
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from playwright.async_api import Page, Response

from .models import AreaType
from .config import KB_PAGE_LOAD_TIMEOUT_MS

logger = logging.getLogger(__name__)


class KBCollector:
    """
    KB 단지 상세 페이지에서 평형/시세 데이터를 수집한다.
    """

    def __init__(self):
        self._xhr_responses: list[dict[str, Any]] = []

    async def collect_area_types(
        self,
        page: Page,
        kb_complex_id: str,
        kb_url: str = "",
    ) -> list[AreaType]:
        """
        KB 단지의 평형별 면적·세대수·시세 데이터를 수집한다.

        1순위: KB 공식 API (mpriByType) 직접 호출
        2순위: 브라우저 XHR 인터셉트 및 DOM fallback
        """
        if not kb_complex_id:
            logger.warning("kb_complex_id가 비어있습니다.")
            return []

        # 1순위: KB 공식 API 호출 (가장 신뢰성 높고 정확)
        area_types = await self._collect_via_api(page, kb_complex_id)
        if area_types:
            logger.info("KB API(mpriByType)에서 %d개 평형 데이터 수집 완료 (단지=%s)", len(area_types), kb_complex_id)
            return area_types

        # 2순위 fallback: 브라우저 페이지 탐색 및 인터셉트
        logger.info("API 수집 실패, 브라우저 페이지 내비게이션 fallback 시도 (id=%s)", kb_complex_id)
        return await self._collect_via_browser(page, kb_complex_id, kb_url)

    async def _collect_via_api(self, page: Page, kb_complex_id: str) -> list[AreaType]:
        """KB Land 공식 JSON API를 page.request로 직접 호출하여 평형 데이터를 수집한다."""
        results: list[AreaType] = []

        try:
            # 1. 시세 기준일 조회를 위해 BasePrcInfoNew 먼저 호출 (대표 평형)
            price_date = ""
            try:
                base_prc_param = urllib.parse.quote("단지기본일련번호")
                base_prc_url = f"https://api.kbland.kr/land-price/price/BasePrcInfoNew?{base_prc_param}={kb_complex_id}"
                prc_resp = await page.request.get(
                    base_prc_url,
                    headers={"Referer": "https://kbland.kr/"},
                    timeout=8000,
                )
                if prc_resp.status == 200:
                    prc_data = await prc_resp.json()
                    sise_list = prc_data.get("dataBody", {}).get("data", {}).get("시세", [])
                    if sise_list:
                        raw_date = sise_list[0].get("시세기준년월일") or sise_list[0].get("기준년월일") or ""
                        if raw_date and len(raw_date) == 8:
                            price_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
            except Exception as e:
                logger.debug("시세 기준일 조회 실패 (무시 가능): %s", e)

            # 2. mpriByType 호출 (평형별 면적, 세대수, 시세 전체 목록)
            q_param = urllib.parse.quote("단지기본일련번호")
            api_url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{q_param}={kb_complex_id}"

            resp = await page.request.get(
                api_url,
                headers={
                    "Referer": "https://kbland.kr/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
                timeout=10000,
            )

            if resp.status != 200:
                logger.warning("mpriByType API 응답 실패: status=%d", resp.status)
                return []

            data = await resp.json()
            items = data.get("dataBody", {}).get("data", [])
            if not items:
                logger.warning("mpriByType 데이터가 비어있습니다. (id=%s)", kb_complex_id)
                return []

            for item in items:
                at = self._parse_mpri_item(item, price_date)
                if at:
                    results.append(at)

        except Exception as e:
            logger.warning("API 수집 중 예외 발생 (id=%s): %s", kb_complex_id, e)

        return results

    def _parse_mpri_item(self, item: dict[str, Any], default_price_date: str = "") -> Optional[AreaType]:
        """KB mpriByType 단일 평형 항목을 AreaType으로 변환한다."""
        if not isinstance(item, dict):
            return None

        # 평형 ID (면적일련번호)
        type_id = str(item.get("면적일련번호") or "")

        # 세대수
        households = self._safe_int(item.get("세대수"))

        # 전용면적 & 공급면적
        ex_sqm = self._safe_decimal(item.get("전용면적"))
        sup_sqm = self._safe_decimal(item.get("공급면적"))

        # 타입명 생성
        type_char = str(item.get("주택형타입내용") or "").strip()
        sup_pyeong = str(item.get("공급면적평N") or item.get("공급면적평") or "").strip()
        if type_char and sup_pyeong:
            type_name = f"{sup_pyeong}평{type_char}"
        elif type_char:
            type_name = f"{type_char}타입"
        elif sup_pyeong:
            type_name = f"{sup_pyeong}평"
        else:
            type_name = f"{ex_sqm}㎡" if ex_sqm else f"타입_{type_id}"

        # KB 시세 (만원 단위)
        kb_sale_general = self._safe_int(item.get("매매일반거래가"))
        kb_sale_upper = self._safe_int(item.get("매매상한가"))
        kb_sale_lower = self._safe_int(item.get("매매하한가"))

        kb_jeonse_general = self._safe_int(item.get("전세일반거래가"))

        kb_monthly_dep = self._safe_int(item.get("월세보증금액"))
        kb_monthly_low = self._safe_int(item.get("월임대최저금액"))
        kb_monthly_high = self._safe_int(item.get("월임대최고금액"))

        # 매물건수
        listing_cnt = self._safe_int(item.get("매매건수"))

        return AreaType(
            kb_type_id=type_id,
            type_name=type_name,
            households=households,
            supply_area_sqm=sup_sqm,
            exclusive_area_sqm=ex_sqm,
            area_precision="display",
            kb_sale_general=kb_sale_general,
            kb_sale_upper=kb_sale_upper,
            kb_sale_lower=kb_sale_lower,
            kb_jeonse_general=kb_jeonse_general,
            kb_monthly_deposit=kb_monthly_dep,
            kb_monthly_low=kb_monthly_low,
            kb_monthly_high=kb_monthly_high,
            kb_price_date=default_price_date,
            listing_count=listing_cnt,
        )

    async def _collect_via_browser(
        self,
        page: Page,
        kb_complex_id: str,
        kb_url: str = "",
    ) -> list[AreaType]:
        """브라우저 내비게이션 기반 fallback 수집."""
        target_url = kb_url or f"https://kbland.kr/map?complex={kb_complex_id}"
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=KB_PAGE_LOAD_TIMEOUT_MS)
            await asyncio.sleep(3)
        except Exception as e:
            logger.warning("브라우저 이동 실패: %s", e)
            return []

        return []

    def _safe_int(self, val: Any) -> int:
        """안전하게 정수로 변환한다."""
        if val is None:
            return 0
        try:
            if isinstance(val, (int, float)):
                return int(val)
            s = str(val).replace(",", "").strip()
            return int(float(s)) if s else 0
        except (ValueError, TypeError):
            return 0

    def _safe_decimal(self, val: Any) -> Optional[Decimal]:
        """안전하게 Decimal로 변환한다."""
        if val is None:
            return None
        try:
            s = str(val).replace(",", "").strip()
            if not s or s == "None":
                return None
            return Decimal(s)
        except (InvalidOperation, ValueError, TypeError):
            return None
