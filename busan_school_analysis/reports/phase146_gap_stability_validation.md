# Phase 14.6 Gap Stability Validation

- 유효 단지: 6M 499 / 12M 503 / 24M 503
- Gap Spearman: 6M-12M 0.9714, 12M-24M 0.9758, 6M-24M 0.9672
- Temporal stability: {'STABLE_POSITIVE': 239, 'STABLE_NEGATIVE': 209, 'INSUFFICIENT': 60, 'MIXED': 52}
- Method agreement: {'STRONG_POSITIVE': 177, 'STRONG_NEGATIVE': 139, 'INSUFFICIENT': 104, 'MIXED_POSITIVE_RESIDUAL': 65, 'MIXED_POSITIVE_COMPARABLE': 62, 'NEUTRAL_OR_ZERO': 13}
- 방법 간 절대차이 median/P75/P90: 17.11 / 33.02 / 58.04%p
- Bootstrap: 500회, positive probability 중앙값 0.638
- Positive probability ≥0.75: 224개, ≥0.90: 190개
- 기존 Phase 14.5 Gap 재현 최대오차: 0

기존 Phase 14.5는 순수 12개월 고정창이 아니라 6M→12M→24M 적응형 가격창이다. 원본은 정확히 재현했으며, 순수 12M Gap과의 Spearman은 0.9726이다.
Bootstrap probability는 거래 재표집에서 Gap 부호가 유지된 비율이며 투자 성공확률이 아니다.
