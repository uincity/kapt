# Phase 7 500세대 이상 미점수 coverage audit

## 범위와 판정 기준

- 기준 산출물: 2026학년도 점수 560개 중 미점수 222개
- 기존 관계·점수 파일은 읽기만 했으며 점수 로직과 점수 산출물을 변경하지 않았다.
- 공동학구 7개 단지는 감사 CSV에서 아파트당 1행을 유지하고 학교 ID와 이름을 `|`로 병합했다.
- `middle_relation_exists`와 `middle_score_exists`는 연결된 초등학교 중 하나 이상에 근거가 있으면 `True`다.
- `CROSS_OFFICE_ASSIGNMENT`는 PDF가 외부 교육지원청 배정을 명시한 경우다.
- `apartment_elementary_match_type`은 현재 공식 학구 연결의 `evidence_type`을 사용했다.
- Pareto 비율은 공동학구 단지의 중복을 제거한 아파트 합집합 기준이다. 실제 추가 점수화에는 확보될 중학교의 Phase 3 성과점수가 필요하다.

## 교육지원청별 coverage

| education_office | total_500plus_apartments | scored_500plus_apartments | unscored_500plus_apartments | score_coverage_pct | unscored_unique_elementary_school_id_count |
| --- | --- | --- | --- | --- | --- |
| bukbu | 144 | 130 | 14 | 90.28 | 4 |
| dongnae | 86 | 32 | 54 | 37.21 | 35 |
| haeundae | 150 | 108 | 42 | 72.00 | 23 |
| nambu | 111 | 0 | 111 | 0.00 | 50 |
| seobu | 69 | 68 | 1 | 98.55 | 0 |

## 미점수 사유

| missing_reason | apartment_count |
| --- | --- |
| MISSING_ELEMENTARY_MIDDLE_RELATION | 218 |
| MISSING_MIDDLE_SCORE | 0 |
| CROSS_OFFICE_ASSIGNMENT | 3 |
| REVIEW | 0 |
| OTHER | 1 |

- 미점수 단지가 연결된 전체 unique elementary_school_id: 111
- 초등학교 연결이 없는 단지: 1

## 해운대·동래 수기 확인 우선순위 상위 20개

| education_office | elementary_school_id | elementary_school_name | linked_500plus_apartment_count | linked_all_apartment_count | largest_complex_households |
| --- | --- | --- | --- | --- | --- |
| haeundae | S020001660 | 반안초등학교 | 3 | 3 | 1374.00 |
| haeundae | S020001664 | 상당초등학교 | 3 | 3 | 1848.00 |
| haeundae | S020001905 | 센텀초등학교 | 3 | 3 | 2752.00 |
| haeundae | S020001668 | 수영초등학교 | 2 | 69 | 1038.00 |
| haeundae | S020001695 | 호암초등학교 | 2 | 57 | 1233.00 |
| dongnae | S020000832 | 장서초등학교 | 2 | 49 | 809.00 |
| haeundae | S020001682 | 재송초등학교 | 2 | 39 | 703.00 |
| dongnae | S020000802 | 구서초등학교 | 2 | 37 | 1118.00 |
| dongnae | S020000807 | 금정초등학교 | 2 | 37 | 4043.00 |
| dongnae | S020000806 | 금양초등학교 | 2 | 35 | 1408.00 |
| dongnae | S020000808 | 낙민초등학교 | 2 | 31 | 732.00 |
| dongnae | S020000815 | 동현초등학교 | 2 | 26 | 885.00 |
| dongnae | S020001001 | 과정초등학교 | 2 | 25 | 560.00 |
| haeundae | S020001648 | 교리초등학교 | 2 | 23 | 875.00 |
| haeundae | S020001654 | 망미초등학교 | 2 | 22 | 684.00 |
| dongnae | S020000819 | 명장초등학교 | 2 | 22 | 793.00 |
| dongnae | S020001029 | 연천초등학교 | 2 | 21 | 2302.00 |
| dongnae | S020001034 | 창신초등학교 | 2 | 18 | 4470.00 |
| dongnae | S020001021 | 연동초등학교 | 2 | 17 | 1598.00 |
| dongnae | S020000833 | 장전초등학교 | 2 | 17 | 565.00 |

전체 우선순위는 `reports/phase7_missing_elementary_priority.csv`에 저장했다.

## Pareto 분석

| top_n | covered_apartments | target_apartments | potential_coverage_pct |
| --- | --- | --- | --- |
| 10 | 23 | 96 | 23.96 |
| 20 | 43 | 96 | 44.79 |
| 30 | 63 | 96 | 65.62 |
| 40 | 78 | 96 | 81.25 |

- 해운대·동래에서 상위 10개 초등학교의 배정관계만 확보하면 500세대 이상 미점수 단지의 23.96%(23/96개)를 추가로 점수화할 수 있음.
- 해운대·동래에서 상위 20개 초등학교의 배정관계만 확보하면 500세대 이상 미점수 단지의 44.79%(43/96개)를 추가로 점수화할 수 있음.
- 해운대·동래에서 상위 30개 초등학교의 배정관계만 확보하면 500세대 이상 미점수 단지의 65.62%(63/96개)를 추가로 점수화할 수 있음.
- 해운대·동래에서 상위 40개 초등학교의 배정관계만 확보하면 500세대 이상 미점수 단지의 81.25%(78/96개)를 추가로 점수화할 수 있음.
