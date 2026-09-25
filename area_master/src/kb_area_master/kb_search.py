"""
KB부동산 단지 검색 모듈.

왜 여러 검색어 후보인가:
- K-apt 단지명과 KB 단지명은 정확히 일치하지 않을 수 있다.
- "대연sk뷰힐스아파트" → KB에서는 "대연SK뷰힐스"로 등록되어 있을 수 있다.
- 법정동명 + 단지명 조합으로 검색 정확도를 높인다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from playwright.async_api import Page

from .models import ComplexCandidate

logger = logging.getLogger(__name__)


def normalize_for_search(name: str) -> str:
    """
    검색용 단지명 정규화.
    
    차수(1차/2차), 단지 구분(A단지/B단지), 브랜드명 등은 절대 제거하지 않는다.
    """
    if not name:
        return ""
    text = name.strip()
    # 괄호 내용 제거
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    # 연속 공백 정리
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_core_name(name: str) -> str:
    """
    단지명에서 '아파트', 'APT' 등 일반 접미사만 제거한 핵심 이름.
    차수·브랜드·구분어는 보존한다.
    """
    text = normalize_for_search(name)
    # 일반 접미사 제거 (끝에 있는 경우만)
    for suffix in ["아파트", "APT", "apt", "주상복합", "맨션"]:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[:-len(suffix)].strip()
            break
    return text


def generate_search_queries(dong: str, complex_name: str, gu: str = "") -> list[str]:
    """
    검색어 후보를 우선순위 순으로 생성한다.

    QUERY 1: {동명} {원본 단지명}
    QUERY 2: {동명} {정규화 단지명}
    QUERY 3: {구명} {동명} {정규화 단지명}
    QUERY 4: {동명} {핵심 단지명}
    """
    dong_clean = dong.strip() if dong else ""
    norm_name = normalize_for_search(complex_name)
    core_name = extract_core_name(complex_name)

    queries = []

    # QUERY 1: 동명 + 핵심 단지명 ('아파트' 등 접미사 제거된 핵심 이름 - KB 검색 최적)
    if dong_clean and core_name:
        q1 = f"{dong_clean} {core_name}"
        queries.append(q1)

    # QUERY 2: 핵심 단지명만 (동명이 KB 주소와 불일치할 경우 대비)
    if core_name and core_name not in queries:
        queries.append(core_name)

    # QUERY 3: 동명 + 정규화 단지명
    if dong_clean and norm_name and norm_name != core_name:
        q3 = f"{dong_clean} {norm_name}"
        if q3 not in queries:
            queries.append(q3)

    # QUERY 4: 구명 + 동명 + 핵심 단지명
    if gu and dong_clean and core_name:
        q4 = f"{gu} {dong_clean} {core_name}"
        if q4 not in queries:
            queries.append(q4)

    # QUERY 5: 동명 + 원본 단지명
    if dong_clean and complex_name.strip():
        q5 = f"{dong_clean} {complex_name.strip()}"
        if q5 not in queries:
            queries.append(q5)

    return queries


async def search_kb_complex(page: Page, query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """
    KB부동산에서 단지를 검색하고 결과 후보를 수집한다.

    1순위 원칙에 따라 브라우저 세션의 page.request를 통해
    KB Land 공식 통합검색 API(intgraSerch)를 직접 호출한다.
    절대 첫 번째 항목을 자동 선택하지 않고, 상위 후보 전체를 수집하여 반환한다.
    """
    import urllib.parse
    results: list[dict[str, Any]] = []

    try:
        # API URL 생성
        params = {
            "검색설정명": "SRC_NTOTAL",
            "검색키워드": query,
            "출력갯수": str(max_results),
            "페이지설정값": "1",
        }
        api_url = f"https://api.kbland.kr/land-complex/serch/intgraSerch?{urllib.parse.urlencode(params)}"

        # 브라우저 세션의 request context 사용 (쿠키/헤더 유지)
        resp = await page.request.get(
            api_url,
            headers={
                "Referer": "https://kbland.kr/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            },
            timeout=10000
        )

        if resp.status == 200:
            data = await resp.json()
            hscm_list = (
                data.get("dataBody", {})
                .get("data", {})
                .get("data", {})
                .get("HSCM", {})
                .get("data", [])
            )

            for item in hscm_list[:max_results]:
                cid = str(item.get("COMPLEX_NO", "")).strip()
                name = str(item.get("HSCM_NM", "")).strip()
                addr = str(item.get("BUBADDR", "")).strip()
                road = str(item.get("NEWADDRESS", "")).strip()
                ths_str = str(item.get("THS_NUM", "0")).strip()
                try:
                    households = int(ths_str)
                except ValueError:
                    households = 0

                mvi = str(item.get("MVIHS_DATE", "")).strip()
                year = mvi[:4] if len(mvi) >= 4 else ""

                candidate = {
                    "kb_complex_id": cid,
                    "kb_name": name,
                    "kb_address": addr,
                    "kb_dong": addr.split()[-1] if addr else "",
                    "kb_road_address": road,
                    "kb_households": households,
                    "kb_approval_year": year,
                    "kb_url": f"https://kbland.kr/map?complex={cid}",
                    "property_type": str(item.get("SLND_PERTY_NM", "")).strip(),
                    "obj_idnfr": str(item.get("OBJ_IDNFR", "")).strip(),
                    "raw_text": f"{name} {addr} {road} {households}세대",
                }
                results.append(candidate)

            logger.info("KB 검색 API '%s' -> %d개 단지 후보 발견", query, len(results))
            return results

        logger.warning("KB 검색 API 비정상 응답: status=%d", resp.status)

    except Exception as e:
        logger.warning("KB 검색 중 오류 (query=%s): %s", query, e)

    return results
