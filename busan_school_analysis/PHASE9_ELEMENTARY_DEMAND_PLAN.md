# Phase 9 Elementary Demand Score 구현 계획

작성일: 2026-09-10  
원칙: Phase 6·6.5·7·8 산출물과 점수공식은 변경하거나 덮어쓰지 않는다.

## 1. 기존 자산 확인

| 확인 항목 | 확정 결과 |
|---|---|
| Phase 7 구현 | `src/phase7_scoring.py`, `src/phase7_assignment_2026.py` |
| Phase 7 최종 점수 | `data/processed/busan_apartment_school_scores_2026.parquet`의 `school_zone_score` |
| Phase 7 고정본 | `data/snapshots/school_scores_2026_phase7_final.parquet` |
| 공식 초등학교 ID | `schools.parquet.school_id`; 부산 초등학교 319개, 결측 0, 중복 0 |
| 학교알리미 공개 ID | `schools.parquet.school_public_id`; 초등학교 319개, 결측 0, 중복 0 |
| 아파트→초등학교 | `busan_apartment_elementary_relation_2025.parquet.elementary_school_id` |
| Phase 7→아파트 키 | `internal_complex_id`; Phase 7은 4,521개 단지 1행씩 유일 |
| Phase 8 가격 패널 | 581,334행, 4,409개 단지; 키는 `internal_complex_id, year_month, area_group` |
| Phase 8 가격 열 | `median_price_per_sqm`, `price_per_m2`, 거래량·회전율·전세가율·통제변수 포함 |

`school_id`, `school_public_id`, 학교알리미 응답의 `SCHUL_CODE`가 같은 공식
학교 식별자를 나타내는지 수집 후 전수 검증한다. 이름만으로 결합하지 않는다.

## 2. Phase 8 benchmark 동결

현재 결과를 `data/snapshots/phase8_baseline_benchmark.json`에 별도 저장한다.
기존 Phase 8 CSV·Parquet·보고서는 수정하지 않는다. 동결 값은 다음과 같다.

- 전체 아파트 4,521, Phase 7 점수 4,288
- 500세대 이상 560, 점수 생성 546, coverage 97.5%
- 실거래 223,932건, 월별 패널 581,334행, Primary sample 487
- Pearson 0.398, Spearman 0.375
- 구·군 내 Spearman 0.190, 법정동 demeaned Spearman 0.005
- 법정동 FE 10점 연관 +3.10%, p-value 0.1887
- 판정 `USEFUL_FEATURE`

## 3. 공식 학교알리미 입력

공식 `https://www.schoolinfo.go.kr/openApi.do`를 사용한다.

| API | apiType | 사용 필드 |
|---|---:|---|
| 학년별·학급별 학생수 | 09 | `SCHUL_CODE`, `COL_S1`~`COL_S6`, `COL_C1`~`COL_C6`, `COL_S_SUM`, `COL_C_SUM`, `COL_SUM` |
| 전·출입 학생수 | 10 | `SCHUL_CODE`, `COL_211`~`COL_261`, `COL_212`~`COL_262`, `MVIN_SUM`, `MVT_SUM`, `STDNT_SUM` |

`pbanYr`로 연도를 명시한다. 2026-09-10 실제 확인 결과 공식 API가 제공하는
범위는 2024~2026이다. 2022·2023은 기존 snapshot이 없으며 API가 최근 3년
제한 오류를 반환하므로 생성하거나 추정하지 않는다. 매 응답과 요청 메타데이터,
SHA256을 `data/raw/phase9_schoolinfo/{year}/`에 보존한다. 인증키는 저장하지 않는다.

## 4. 정제 및 품질검사

학교×연도 1행의 longitudinal 파일을 만든다.

- 공식 ID 유일성, 부산 초등학교 여부, 제외·분교 상태 검사
- 학년 합계와 전체 학생수 차이 기록
- 전입·전출 합계와 학년별 합계 차이 기록
- 음수, 비수치, 중복, 연도 누락을 검수 파일로 분리
- 폐교·공시제외 행은 원문에 보존하고 점수에서는 제외

산출물:

- `data/processed/phase9_elementary_student_longitudinal.parquet`
- `reports/phase9_collection_status.csv`
- `reports/phase9_data_quality.csv`

## 5. 독립 feature engineering

Phase 9 feature 계산에는 학교알리미 학생 자료와 학교 기본 식별정보만 사용한다.
Phase 7 점수, 중학교 관계, 아파트, 가격은 읽지 않는다.

- 규모: `total_students`, `total_classes`, `students_per_class`
- 이동: `transfer_in`, `transfer_out`, `net_transfer_rate`
- 변화: `student_growth_3y`, `student_trend_slope`
- 학년구조: `upper_lower_ratio`
- 부산 학년구조 보정: `adjusted_upper_grade_index`
- 동일 cohort 연도 이동: `cohort_growth`
- 부산 동일 cohort 변화 보정: `adjusted_cohort_growth`

`adjusted_upper_grade_index`는 학교의 `(5·6학년)/(1·2학년)`을 같은 해 부산
전체 비율로 나눈 값이다. `adjusted_cohort_growth`는 예를 들어 2024년 4학년→
2025년 5학년→2026년 6학년처럼 동일 cohort를 추적한 변화율에서 같은 cohort의
부산 전체 변화율을 뺀 평균이다. 분모 0과 불완전 cohort는 결측으로 유지한다.

## 6. Elementary Demand Score

가격과 Phase 7 점수를 보지 않고 다음 네 축의 winsorized 부산 내 percentile로
0~100 점수를 만든다.

- 규모 20%: 전체 학생수, 학급당 학생수
- 순유입 25%: 순전입률
- 성장 25%: 3년 성장률, 추세 기울기
- 고학년·cohort 유입 30%: 보정 고학년 지수, 보정 cohort 성장

비율형 지표는 학생수 기반 신뢰도로 부산 중앙값 방향 shrinkage하고 원지표도
함께 보존한다. 구성요소·가중치·결측 재가중 여부를 설정파일에 명시한다.

산출물:

- `config/phase9_elementary_demand.yaml`
- `data/processed/phase9_elementary_demand_features.parquet`
- `data/processed/phase9_elementary_demand_scores.parquet`
- `reports/phase9_elementary_demand_ranking.csv`
- `reports/phase9_validation.md`

## 7. 수요 유형 cluster

점수 순위 생성과 분리해 표준화한 feature에 KMeans와 GMM을 각각 적용한다.
K=3~6을 비교하고 KMeans silhouette, GMM BIC 및 군집 최소 크기를 기록한다.
선택된 군집의 실제 평균 특성을 확인한 후에만 설명 이름을 부여한다.

- `reports/phase9_cluster_comparison.csv`
- `reports/phase9_cluster_profiles.csv`

## 8. Phase 9.5 결합

Phase 9 점수가 확정된 뒤에만 Phase 7 고정본과 결합한다. 아파트의 복수 초등학교는
기존 관계를 유지하고 평균·최저·최고 Elementary Demand를 별도 생성한다.

- E: `elementary_demand_score`
- M: 기존 `school_zone_score`
- I: 분석용 `E × M`; 통합점수로 사용하지 않음
- E/M 각각 부산 중앙값 기준 High/Low로 A~D 그룹 생성

신규 파일은 모두 `phase95_` 접두사를 사용한다.

## 9. Phase 10 가격 검증

Phase 8 benchmark와 동일한 표본·가격·통제변수로 Model A~D를 비교한다.
법정동 고정효과와 단지 군집 표준오차를 유지하고 train/test group split은
`internal_complex_id` 단위로 수행한다. 선형모형과 tree 모델 모두 동일 split을 쓴다.

비교표에는 Pearson, Spearman, 구·군 내 Spearman, 법정동 demeaned Spearman,
법정동 FE 계수·p-value, RMSE, MAE, R², Group Split RMSE를 기록한다. 특히 기존
법정동 demeaned Spearman 0.005와 직접 비교한다. 최종 통합 가중치는 만들지 않는다.

## 10. 실행 순서와 중단 조건

1. `phase9-collect --years 2024 2025 2026`
2. 원문·공식 ID·coverage 품질검사
3. `phase9-build`
4. cluster 해석 및 Phase 9 보고서
5. Phase 9.5 독립 결합
6. Phase 10 benchmark 비교

공식 ID 불일치, 연도별 대규모 누락, 합계 불일치가 확인되면 점수를 발행하지 않고
검수 보고서만 생성한다. Phase 7·8 파일은 어떤 단계에서도 쓰기 대상으로 열지 않는다.
