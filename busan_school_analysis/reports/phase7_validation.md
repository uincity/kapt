# Phase 7 학군점수 검증 보고서

## A. Phase 7 개요
공식 배정 근거와 Phase 3 점수를 연결한 규칙 기반 0~100 점수다. 머신러닝이나 임의 순위 보정은 사용하지 않았다.

## B. 데이터 연결 현황
입력 감사: `{
  "middle_school_scores_by_id.parquet": 183,
  "middle_school_scores.parquet": 183,
  "busan_apartment_elementary_match_2025.parquet": 4545,
  "busan_elementary_middle_relation_2025.parquet": 462,
  "busan_schoolzone_school_link_2025.parquet": 324,
  "busan_elementary_catchment_boundaries_2025.parquet": 309,
  "busan_apartment_coordinates_2025.parquet": 4521,
  "busan_apartment_elementary_relation_2025.parquet": 4537
}`

## C. middle school score 현황
Phase 3 점수 170개를 재계산 없이 사용했다.

## D. elementary feeder score 설계
가중 중학교 65%, 최저 15%, exclusivity 10%, 공식 배정자료 품질 10%다. 생성 54/297개다.

## E. assignment weight 설계
`{
  "EXACT": 1.0,
  "ELIGIBLE": 0.8,
  "CONDITIONAL": 0.5,
  "GROUP_MEMBERSHIP": 0.25,
  "UNRESOLVED": 0.0
}`. 가중치는 배정확률이 아니라 근거 신뢰도 proxy다. 관계 건수 `{
  "UNRESOLVED": 243,
  "ELIGIBLE": 182,
  "GROUP_MEMBERSHIP": 28,
  "CONDITIONAL": 9
}`.

## F. feeder uncertainty/exclusivity
중학교 점수 표준편차·범위·변동계수와 약한 관계 비중을 별도 저장했다. 최고점 하나만으로 feeder 점수를 만들지 않는다.

## G. apartment school zone score
BASE는 feeder 80%, 초등 직선거리 10%, 배정자료 품질 10%다. 893/4521개 단지에 생성했다.

## H. 500세대 이상 Ranking
79/560개에 점수와 부산·구군·법정동 순위를 생성했다.

## I. 센텀 validation
센텀초→센텀중은 기존 공식 근거의 `GROUP_MEMBERSHIP` 수준을 유지했다. 조건부·학교군 관계를 EXACT로 승격하지 않았다.

## J. 공동통학구역 현황
공동/복수 초등 관계 단지 4개. 평균·최고·최저 feeder를 모두 보존했다.

## K. REVIEW 제외 현황
좌표 REVIEW 단지는 공식 직접 확정 근거가 없는 한 점수에서 제외한다. REVIEW 상태 3개다.

## L. sensitivity analysis
상위 50개 BASE 대비 Spearman 상관(순위값 Pearson): `{
  "BASE_vs_QUALITY_FOCUSED": 0.965889198682617,
  "BASE_vs_STABILITY_FOCUSED": 0.9244883466681275
}`. 단지별 rank 범위와 민감도 플래그를 저장했다.

## M. 데이터 한계
초등학교별 중입 관계가 공식 원문에서 행 단위로 확인되지 않은 학교는 UNRESOLVED다. 직선거리는 실제 보행 통학거리와 다르다. 중학교 성과는 학교 효과나 배정 보장을 뜻하지 않는다. 품질 분포 `{
  "LOW": 3628,
  "HIGH": 827,
  "MEDIUM": 66
}`, 점수 분포 `{
  "count": 893.0,
  "mean": 57.86456899348593,
  "std": 6.140217069493215,
  "min": 38.078543417366944,
  "50%": 58.729019607843135,
  "80%": 63.67264705882354,
  "90%": 64.6635294117647,
  "95%": 65.17941176470589,
  "max": 66.24264705882354
}`.

## N. Phase 8 진행 가능 여부
**NOT_READY**. 현재 점수 보유 범위에서는 가격 결합 검증이 가능하지만, 미공개·미추출 초→중 관계는 결측으로 유지해야 한다.
