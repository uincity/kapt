# Phase 12.5 Middle Incremental Value 검증

- Middle은 활성 후보집합의 개수·평균·범위·최선·최악 및 확정관계로 표현했다. `assignment_share`와 ELIGIBLE weight는 확률로 사용하지 않았다.
- 공통표본: 22,176건, 485개 단지
- Δ조정 R²: +0.0044; ΔAIC -577.80; ΔBIC -537.77
- OOS RMSE: 0.23554 → 0.23357 (0.84% 개선)
- OOS MAE: 0.18044 → 0.17967 (0.43% 개선)
- 후보 중학교 평균점수 계수: 0.001200, p=0.4353
- Gold 표본: 45개 단지, 1,862건; 확정 중학교 점수 계수 -0.008114, p=0.0185
- Gold interaction 계수: 1.730700, p=0.2357
- 판정: **MIDDLE_INCREMENTAL_VALUE_PARTIALLY_SUPPORTED**

적합도와 RMSE는 소폭 개선됐지만 MAE 사전기준을 충족하지 않았고, 후보 평균점수는 유의하지 않으며 Gold 표본 방향이 반대다. 현재 자료로는 추가 신호를 guaranteed 또는 eligible quality 한쪽에 안정적으로 귀속할 수 없다.
