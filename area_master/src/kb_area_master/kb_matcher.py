"""
kapt_code ↔ KB complex ID 매칭 모듈.

왜 다중 factor 점수인가:
- 이름만으로 매칭하면 LG메트로시티1차/2차 같은 차수 혼동이 발생한다.
- 법정동, 주소, 세대수, 단지명 유사도, 준공연도를 종합하여 정확한 매칭을 한다.
- HARD RULE을 적용하여 위험한 자동 확정을 방지한다.
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from .config import MATCH_WEIGHTS, CONFIDENCE_THRESHOLDS
from .models import ComplexCandidate, MatchConfidence

logger = logging.getLogger(__name__)


def normalize_name_for_match(name: str) -> str:
    """
    매칭용 단지명 정규화.
    차수/단지구분/브랜드는 보존하고, 접미사/공백/특수문자만 정리한다.
    """
    if not name:
        return ""
    text = name.strip()
    # 괄호 제거
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    # 특수문자 제거 (차수 숫자는 보존)
    text = re.sub(r"[-_.,·~#]", "", text)
    # 접미사 제거
    for suffix in ["아파트", "APT", "apt", "주상복합"]:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[:-len(suffix)]
            break
    # 공백 정리 및 소문자 변환
    text = re.sub(r"\s+", "", text).lower()
    return text


def calc_name_similarity(name_a: str, name_b: str) -> float:
    """
    두 단지명의 유사도를 0.0~1.0으로 반환한다.
    정규화된 이름으로 비교한다.
    """
    norm_a = normalize_name_for_match(name_a)
    norm_b = normalize_name_for_match(name_b)
    if not norm_a or not norm_b:
        return 0.0
    return SequenceMatcher(None, norm_a, norm_b).ratio()


def has_ordinal_conflict(kapt_name: str, kb_name: str) -> bool:
    """
    차수(1차/2차) 또는 단지번호(1단지/2단지)가 다르면 True.
    
    예:
    - LG메트로시티1차 vs LG메트로시티2차 → True (충돌)
    - LG메트로시티1차 vs LG메트로시티1차 → False
    - 대연SK뷰힐스 vs 대연SK뷰힐스 → False
    """
    # 차수 패턴: 1차, 2차, ...
    ordinal_pattern = re.compile(r"(\d+)\s*차")
    # 단지 패턴: 1단지, 2단지, A단지, ...
    danji_pattern = re.compile(r"([A-Za-z\d]+)\s*단지")

    kapt_ord = ordinal_pattern.findall(kapt_name)
    kb_ord = ordinal_pattern.findall(kb_name)

    kapt_danji = danji_pattern.findall(kapt_name)
    kb_danji = danji_pattern.findall(kb_name)

    # 둘 다 차수가 있는데 다르면 충돌
    if kapt_ord and kb_ord and kapt_ord != kb_ord:
        return True

    # 둘 다 단지번호가 있는데 다르면 충돌
    if kapt_danji and kb_danji and kapt_danji != kb_danji:
        return True

    return False


def normalize_dong(dong: str) -> str:
    """법정동명 정규화. '동' 접미사 보존."""
    if not dong:
        return ""
    return re.sub(r"\s+", "", dong.strip())


def extract_dong_from_address(address: str) -> str:
    """주소 문자열에서 법정동을 추출한다."""
    if not address:
        return ""
    # "부산광역시 남구 대연동 ..." 패턴
    match = re.search(r"([가-힣]+[동리])\s", address)
    return match.group(1) if match else ""


def calculate_match_score(
    kapt_name: str,
    kapt_dong: str,
    kapt_address: str,
    kapt_road_address: str,
    kapt_households: int,
    kapt_approval_date: str,
    kb_name: str,
    kb_address: str,
    kb_dong: str,
    kb_households: int,
    kb_approval_year: str = "",
) -> tuple[int, list[str]]:
    """
    kapt ↔ KB 단지 매칭 점수를 계산한다.

    반환: (total_score, reason_list)
    """
    score = 0
    reasons: list[str] = []

    # 1. 법정동 일치
    kapt_d = normalize_dong(kapt_dong)
    kb_d = normalize_dong(kb_dong) or extract_dong_from_address(kb_address)
    if kapt_d and kb_d and kapt_d == kb_d:
        score += MATCH_WEIGHTS["legal_dong_exact"]
        reasons.append(f"법정동 일치 ({kapt_d})")

    # 2. 도로명 주소 일치
    if kapt_road_address and kb_address:
        kapt_road_clean = re.sub(r"\s+", "", kapt_road_address)
        kb_addr_clean = re.sub(r"\s+", "", kb_address)
        if kapt_road_clean and kb_addr_clean:
            # 도로명 주소의 핵심 부분 비교
            if kapt_road_clean in kb_addr_clean or kb_addr_clean in kapt_road_clean:
                score += MATCH_WEIGHTS["road_address_exact"]
                reasons.append("도로명 주소 일치")

    # 3. 총세대수 일치
    if kapt_households > 0 and kb_households > 0:
        if kapt_households == kb_households:
            score += MATCH_WEIGHTS["households_exact"]
            reasons.append(f"총세대수 일치 ({kapt_households})")
        elif abs(kapt_households - kb_households) <= max(5, int(kapt_households * 0.02)):
            # 2% 이내 차이는 부분 점수
            score += MATCH_WEIGHTS["households_exact"] // 2
            reasons.append(f"세대수 유사 (K-apt:{kapt_households}, KB:{kb_households})")

    # 4. 단지명 유사도
    name_sim = calc_name_similarity(kapt_name, kb_name)
    norm_kapt = normalize_name_for_match(kapt_name)
    norm_kb = normalize_name_for_match(kb_name)

    if norm_kapt and norm_kb and norm_kapt == norm_kb:
        score += MATCH_WEIGHTS["normalized_name_exact"]
        reasons.append(f"단지명 정확 일치 ({norm_kapt})")
    elif name_sim >= 0.8:
        score += MATCH_WEIGHTS["name_high_similarity"]
        reasons.append(f"단지명 높은 유사도 ({name_sim:.2f})")
    elif name_sim >= 0.6:
        score += MATCH_WEIGHTS["name_medium_similarity"]
        reasons.append(f"단지명 중간 유사도 ({name_sim:.2f})")

    # 5. 사용승인 연도 일치
    if kapt_approval_date and kb_approval_year:
        kapt_year = str(kapt_approval_date)[:4]
        kb_year = str(kb_approval_year)[:4]
        if kapt_year.isdigit() and kb_year.isdigit() and kapt_year == kb_year:
            score += MATCH_WEIGHTS["approval_year_match"]
            reasons.append(f"준공연도 일치 ({kapt_year})")

    return score, reasons


def determine_confidence(score: int) -> MatchConfidence:
    """점수 기반으로 매칭 confidence를 결정한다."""
    if score >= CONFIDENCE_THRESHOLDS["exact"]:
        return MatchConfidence.EXACT
    elif score >= CONFIDENCE_THRESHOLDS["high"]:
        return MatchConfidence.HIGH
    elif score >= CONFIDENCE_THRESHOLDS["medium"]:
        return MatchConfidence.MEDIUM
    elif score >= CONFIDENCE_THRESHOLDS["low"]:
        return MatchConfidence.LOW
    else:
        return MatchConfidence.UNMATCHED


def apply_hard_rules(
    candidate: ComplexCandidate,
    kapt_name: str,
    kapt_dong: str,
    kapt_households: int,
    all_candidates: list[ComplexCandidate],
) -> ComplexCandidate:
    """
    HARD RULE을 적용하여 위험한 자동 확정을 방지한다.

    CASE C: 동 일치 + 이름만 비슷 + 세대수 불일치 → pending
    CASE D: 단지명 동일 + 동 불일치 → 자동 확정 금지
    CASE E: 동일 브랜드 여러 차수 → 차수 확인 전 자동 확정 금지
    CASE F: 상위 2개 거의 같은 score → 임의 선택 금지
    """
    # CASE E: 차수 충돌
    if has_ordinal_conflict(kapt_name, candidate.kb_name):
        candidate.match_confidence = MatchConfidence.LOW
        candidate.match_reasons.append("HARD_RULE: 차수/단지번호 불일치 → 자동확정 금지")
        logger.warning("차수 충돌 감지: K-apt='%s' vs KB='%s'", kapt_name, candidate.kb_name)
        return candidate

    # CASE D: 동 불일치
    kapt_d = normalize_dong(kapt_dong)
    kb_d = normalize_dong(candidate.kb_dong) or extract_dong_from_address(candidate.kb_address)
    if kapt_d and kb_d and kapt_d != kb_d:
        if candidate.match_confidence in (MatchConfidence.EXACT, MatchConfidence.HIGH):
            candidate.match_confidence = MatchConfidence.MEDIUM
            candidate.match_reasons.append(f"HARD_RULE: 법정동 불일치 (K-apt:{kapt_d} vs KB:{kb_d}) → confidence 하향")

    # CASE C: 동 일치 + 세대수 불일치
    if kapt_d and kb_d and kapt_d == kb_d:
        if kapt_households > 0 and candidate.kb_households > 0:
            if abs(kapt_households - candidate.kb_households) > max(10, int(kapt_households * 0.05)):
                if candidate.match_confidence in (MatchConfidence.EXACT, MatchConfidence.HIGH):
                    candidate.match_confidence = MatchConfidence.MEDIUM
                    candidate.match_reasons.append(
                        f"HARD_RULE: 세대수 불일치 (K-apt:{kapt_households} vs KB:{candidate.kb_households}) → confidence 하향"
                    )

    # CASE F: 상위 2개 거의 같은 score
    if len(all_candidates) >= 2:
        sorted_cands = sorted(all_candidates, key=lambda c: c.match_score, reverse=True)
        top_score = sorted_cands[0].match_score
        second_score = sorted_cands[1].match_score
        if top_score > 0 and second_score > 0:
            if (top_score - second_score) <= 10:
                # 거의 동점 → 자동 확정 금지
                if candidate.match_score == top_score:
                    candidate.match_confidence = MatchConfidence.MEDIUM
                    candidate.match_reasons.append(
                        f"HARD_RULE: 상위 2후보 점수 유사 (1위:{top_score}, 2위:{second_score}) → 임의선택 금지"
                    )

    return candidate


def match_best_candidate(
    candidates: list[ComplexCandidate],
    kapt_name: str,
    kapt_dong: str,
    kapt_households: int,
) -> ComplexCandidate | None:
    """
    후보 목록에서 최적의 매칭 후보를 선택한다.
    HARD RULE을 적용한 후 가장 높은 confidence/score를 반환한다.
    """
    if not candidates:
        return None

    # HARD RULE 적용
    for cand in candidates:
        apply_hard_rules(cand, kapt_name, kapt_dong, kapt_households, candidates)

    # 점수 순 정렬
    sorted_cands = sorted(
        candidates,
        key=lambda c: (
            # confidence 등급 순
            {"exact": 4, "high": 3, "medium": 2, "low": 1, "unmatched": 0}.get(c.match_confidence.value, 0),
            c.match_score,
        ),
        reverse=True,
    )

    return sorted_cands[0]
