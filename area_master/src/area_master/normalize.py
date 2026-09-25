"""
단지명, 주소, 전용면적 정규화 및 파싱 모듈.

전용면적 부동소수점 오차 방지를 위해 Decimal 및 정규화 문자열을 사용하며,
단지 매칭을 위한 지번 및 명칭 정규화를 지원합니다.
"""
from __future__ import annotations

import re
from decimal import Decimal
import requests
from typing import Any

from .config import get_api_key


def normalize_complex_name(name: str | None) -> str:
    """
    단지명에서 공백, 괄호, 일반 접미어(아파트, APT 등)를 정리하여
    단지 매칭 시 신뢰성 높은 비교가 가능하도록 정규화합니다.
    """
    if not name or not isinstance(name, str):
        return ""

    text = name.strip()
    # 괄호 및 괄호 내용 제거 (예: 대신푸르지오(1단지) -> 대신푸르지오)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    
    # 특수문자 제거
    text = re.sub(r"[-_\.,·~#]", "", text)
    
    # 일반적인 공동주택 접미사 제거
    for suffix in ["아파트", "apt", "APT", "주상복합", "맨션", "타운"]:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[:-len(suffix)]
            break

    # 모든 공백 제거
    text = re.sub(r"\s+", "", text)
    return text.lower()


def to_decimal(val: Any) -> Decimal:
    """
    문자열 또는 숫자를 부동소수점 왜곡 없이 정확한 Decimal 객체로 변환합니다.
    절대 float() 변환을 먼저 거치지 않습니다.
    """
    if isinstance(val, Decimal):
        return val
    str_val = str(val).strip()
    return Decimal(str_val)


def normalize_area_str(val: Any) -> str:
    """
    전용면적을 원자료 정밀도를 온전히 보존하는 표준 문자열로 반환합니다.
    예: Decimal('59.9794') -> '59.9794'
    """
    dec = to_decimal(val)
    # 지수 표기법 방지 및 고유 문자열 반환
    return f"{dec:f}".rstrip("0").rstrip(".") if "." in f"{dec:f}" else f"{dec:f}"


def make_area_group_id(exact_area: Any) -> str:
    """
    전용면적 기반의 고유 단지 내 면적 그룹 식별자를 생성합니다.
    규칙: exclusive_ + 소수점을 '_'로 치환한 정밀 전용면적 문자열
    예: 59.9794 -> exclusive_59_9794
        84.9231 -> exclusive_84_9231
    """
    norm_area = normalize_area_str(exact_area)
    safe_area = norm_area.replace(".", "_")
    return f"exclusive_{safe_area}"


def parse_bun_ji(raw_jibun: str | None) -> tuple[str, str]:
    """
    지번 문자열(예: '420', '1-92', '산 24')에서 건축물대장 API 규격(4자리 0-padding)의
    본번(bun)과 부번(ji)을 분리 추출합니다.
    """
    if not raw_jibun:
        return ("0000", "0000")

    clean = str(raw_jibun).strip()
    # '산' 제거
    clean = re.sub(r"^[산\s]+", "", clean)
    # 지번 뒤의 번지, 호 등 제거
    clean = clean.split()[0].replace("번지", "")

    if "-" in clean:
        parts = clean.split("-")
        bun = parts[0].strip()
        ji = parts[1].strip()
    else:
        bun = clean
        ji = "0"

    # 숫자만 추출하여 4자리 zfill
    bun_digits = re.sub(r"\D", "", bun)
    ji_digits = re.sub(r"\D", "", ji)

    bun_str = bun_digits.zfill(4) if bun_digits else "0000"
    ji_str = ji_digits.zfill(4) if ji_digits else "0000"

    return (bun_str, ji_str)


def resolve_address_via_kakao(address_query: str) -> dict[str, str] | None:
    """
    카카오 로컬 주소검색 API를 활용하여 도로명주소/지번주소로부터
    정확한 10자리 법정동코드(b_code), 본번(bun), 부번(ji)을 보강합니다.
    """
    key = get_api_key("KAKAO_API_KEY")
    if not key:
        return None

    headers = {"Authorization": f"KakaoAK {key}"}
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    
    try:
        r = requests.get(url, params={"query": address_query}, headers=headers, timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        docs = data.get("documents", [])
        if not docs:
            return None

        doc = docs[0]
        addr = doc.get("address")
        if not addr:
            return None

        b_code = addr.get("b_code", "")
        main_bun = addr.get("main_address_no", "")
        sub_bun = addr.get("sub_address_no", "")

        bun_str = main_bun.zfill(4) if main_bun else "0000"
        ji_str = sub_bun.zfill(4) if sub_bun else "0000"

        return {
            "bjd_code": b_code,
            "bun": bun_str,
            "ji": ji_str,
            "address_name": addr.get("address_name", ""),
        }
    except Exception:
        return None
