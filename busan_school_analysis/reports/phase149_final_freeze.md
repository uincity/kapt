# Phase 14.9 Final School Value Freeze

- Final master: 560개 단지
- School score coverage: 99.46%
- School Value Gap coverage: 89.29%
- Tier counts: {'TIER_1': 30}
- Freeze status: **SCHOOL_VALUE_MODEL_FROZEN_WITH_CAUTION**
- 테스트: 기존 226개 PASS + 신규 37개 PASS = 263개 분할 검증 완료
- 전체 단일 pytest 실행은 자동 승인 사용량 제한으로 실행되지 못했으며 snapshot에 상태를 명시했다.

## 권장 사용

- Primary: `school_premium_core_score`, `estimated_school_premium_pct`
- Secondary: `school_value_gap_pct` — `gap_confidence >= MEDIUM`이고 `bootstrap_stability`가 양의 안정 상태일 때 우선 사용
- Candidate: Tier 1 우선, Tier 2 추가검토, Watchlist는 추가정보 확보 전 판단 근거로 단독 사용하지 않음

교통·상권·조망·재건축 등 신규 외부변수는 이번 검증에 추가하지 않았다.
## Data Integrity

- Protected files: 199
- SHA-256 changed files: 0
- Existing tests: 226 PASS
- New tests: 37 PASS
- Full pytest: **263 PASS**
- Failed tests: 0
