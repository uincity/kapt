# Phase 15.3 Local Value Gap × School Signal Validation

## 1. Dataset
- Fair Price available: 502/560
- 6M/12M observed price: 499/503
- HIGH/MEDIUM official gap universe: 502개; LOW excluded: 58개
- Fair interval과 observed price는 모두 대표면적 총액으로 단위를 맞췄다.

## 2. Local Value Gap
- 12M official gap median/P25/P75: 2.92% / -4.74% / 12.54%
- Positive/Neutral/Negative: 249/100/153
- 양수는 확정 저평가가 아니라 Fair Price 대비 상대가치 방향 신호다.

## 3. Temporal Stability
- {'STABLE_POSITIVE': 273, 'STABLE_NEGATIVE': 185, 'MIXED': 40, 'INSUFFICIENT': 4}
- 6M/12M Gap Spearman: 0.9650

## 4. Interval-Aware Result
- {'POTENTIAL_UNDERVALUED_SIGNAL': 241, 'POTENTIAL_OVERVALUED_SIGNAL': 149, 'WITHIN_MODEL_RANGE': 100, 'STRONG_UNDERVALUED_SIGNAL': 8, 'STRONG_OVERVALUED_SIGNAL': 4}
- 95% prediction interval 전체가 observed price보다 높은 strong signal은 8개다.

## 5. Confidence
- Local gap confidence: {'HIGH': 285, 'MEDIUM': 134, 'LOW': 83}
- Interval width P25/Median/P75/P90: 57.55/67.95/98.04/98.04%

## 6. School vs Local Signal
- Pearson/Spearman: 0.6300/0.7502 (School gap confidence HIGH/MEDIUM)
- Agreement: {'DOUBLE_POSITIVE': 183, 'DOUBLE_NEGATIVE': 115, 'MIXED_OR_NEUTRAL': 83, 'LOCAL_ONLY_POSITIVE': 65, 'SCHOOL_ONLY_POSITIVE': 56}
- 두 Gap 모두 +3% 초과인 DOUBLE_POSITIVE: 183개
- Dual signal 판정: **DUAL_SIGNAL_COMPLEMENTARY**

## 7. Candidate Classes
- {'UNCERTAIN': 200, 'NEGATIVE_OR_FULLY_PRICED': 116, 'ROBUST_DUAL_POSITIVE': 94, 'LOCAL_VALUE_CANDIDATE': 61, 'SCHOOL_VALUE_CANDIDATE': 31}
- ROBUST_DUAL_POSITIVE Top10: 금곡화목타운; 금곡3단지주공; 삼익그린; 명지오션시티한신휴플러스; 협성피닉스타운; 도시화명그린(295); 금곡9단지주공; 센텀대림; 명지두산위브포세이돈; 협진태양·조성아파트

## 8. Legal Dong Bias
- Bias flag: 10개 법정동
- Positive median top5: 청룡동(30.9%); 기장읍청강리(23.9%); 반송동(21.4%); 우암동(20.5%); 부전동(17.5%)
- Negative median top5: 가야동(-13.6%); 당감동(-8.6%); 망미동(-6.4%); 남천동(-6.4%); 온천동(-5.7%)

## 9. Phase 15.4 Audit Candidates
- HIGH priority: 33개
- extreme gap은 omitted premium/discount 가능성을 조사할 대상으로만 해석한다.

## 10. Final Decision
1. 공식 Local Value Gap은 502개 단지에서 계산했다.
2. 6M/12M Spearman은 0.9650, stable 방향 비율은 91.2%다.
3. Strong undervalued signal은 8개다.
4. Potential undervalued signal은 241개다.
5. School Gap과 Local Gap의 Spearman은 0.7502다.
6. DOUBLE_POSITIVE는 183개다.
7. Class A는 94개다.
8. Bias flag는 10개 법정동으로 특정 지역 집중을 별도 audit해야 한다.
9. Phase 15.4 HIGH priority extreme 후보는 33개다.
10. Secondary screening 판정은 **LOCAL_VALUE_GAP_USABLE_WITH_CAUTION**이며 confidence filtering이 필수다.

Local Gap 판정: **LOCAL_VALUE_GAP_USABLE_WITH_CAUTION**
Dual Signal 판정: **DUAL_SIGNAL_COMPLEMENTARY**

## 11. Validation
- Phase 7~15.2 보호 파일: 292개, SHA-256 변경 0개
- 기존 테스트 340개 + Phase 15.3 신규 테스트 48개 = 전체 **388 PASS**
- 공식 gap·interval·총액 단위, 6M/12M 중앙값, School Gap 보존, 결측 미대체, ranking 제외 규칙을 검증했다.

Phase 15.4는 자동 실행하지 않는다.
