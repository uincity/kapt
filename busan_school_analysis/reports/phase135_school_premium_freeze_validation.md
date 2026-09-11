# Phase 13.5 School Premium Freeze Validation

- 분석 거래/단지: 132,979건 / 500개
- 최근 12개월 거래/단지: 22,596건 / 500개
- 법정동 내부 Spearman: 0.2982
- 비학군 가격 residual에 대한 Core score 10점 계수: 0.04133 (p=1.735e-09)
- 거래량 구간별 양의 계수: 2/3
- Confidence A/B 계수 방향 일치: True
- 사람이 확인할 sanity flag: 95개
- 점수 미생성 단지: 3개(추정·대체하지 않음)
- 행정동은 현재 공식 연결키가 없어 `ADMIN_DONG_NOT_AVAILABLE`로 기록했다.
- 판정: **SCHOOL_PREMIUM_INDEX_FROZEN**

본 분석은 관측자료의 조건부 연관성 검증이며 인과효과를 뜻하지 않는다.
