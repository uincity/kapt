# 부산 아파트 학군·상대가치 분석

부산 초등학교 통학구역과 중학교 배정관계, 학교알리미 학생·진학 데이터, 아파트 실거래를 연결하여 학군 프리미엄과 지역 상대가치를 분석하는 프로젝트입니다.

현재 분석 개발은 **Phase 15.4**에서 종료되었으며 최종 상태는 다음과 같습니다.

```text
BUSAN_APARTMENT_VALUE_MODEL_FINAL_FROZEN
```

이후에는 동결된 결과를 이용한 조회, 필터링과 후보 검토만 수행합니다. 기존 점수나 모델을 임의로 재계산하지 않습니다.

## 현재 핵심 결과

| 항목 | 결과 |
|---|---:|
| 부산 아파트 전체 | 4,521개 |
| 최종 가치분석 대상 | 500세대 이상 560개 |
| School Core Score | 557개 |
| School Value Gap | 500개 |
| Local Fair Price | 502개 |
| Local Value Gap | 502개 |
| CORE_CANDIDATE | 94개 |
| LOCAL_VALUE | 58개 |
| SCHOOL_VALUE | 30개 |
| WATCHLIST | 262개 |
| FULLY_PRICED_OR_NEGATIVE | 116개 |
| 전체 자동검증 | 448개 통과 |

최종 운영 파일은 다음 두 개입니다.

- `data/processed/phase154_final_apartment_value_master.csv`
- `data/snapshots/phase154_final_model_freeze.json`

상세 결과는 `reports/phase154_final_freeze_result_review.md`에서 확인할 수 있습니다.

## 분석 단계

### Phase 1~3: 기초자료와 중학교 점수

- 아파트 4,521개와 500세대 이상 560개 단지를 확인했습니다.
- 부산 초등학교와 중학교 기본정보를 학교알리미에서 수집했습니다.
- 중학교 183개교 중 170개교에 2023~2025년 고교 진학현황 기반 점수를 산출했습니다.
- 점수는 과학고, 외고·국제고, 자율형사립고 진학률을 최근 연도와 표본 크기로 보정한 부산 내 상대지표입니다.

중학교 점수는 학교 자체의 인과적 교육효과나 특정 학생의 진학을 보장하지 않습니다.

### Phase 4~5: 해운대 배정관계 PoC와 센텀 검증

- 해운대교육지원청의 통학구역 및 초등학교→중학교 배정관계 parser PoC를 구축했습니다.
- 센텀초·센텀중과 인근 아파트를 검증했습니다.
- 수작업 보정 자료는 원본 관계와 분리하여 출처와 검토 상태를 보존했습니다.

### Phase 6: 부산 5개 교육지원청 확대

- 서부·남부·북부·동래·해운대교육지원청으로 범위를 확대했습니다.
- 학구도안내서비스의 2025-09-22 공식 공간경계를 사용했습니다.
- 초등학교 통학구역과 중학교 배정관계의 출처, 기준연도와 원문을 보존했습니다.
- 북부·서부교육지원청의 2026학년도 중입배정 PDF와 수작업 검토 CSV를 반영했습니다.

### Phase 6.5: 아파트와 초등학교 공간매칭

- 4,521개 아파트와 공식 초등학교 통학구역을 연결했습니다.
- 공식경계, 보조매칭과 검토 필요 상태를 분리했습니다.
- 기존 `internal_complex_id`를 변경하지 않았습니다.

### Phase 7: Middle School Path 학군점수

- 초등학교→진학가능 중학교 관계와 중학교 성과점수를 결합했습니다.
- 평균·최저 중학교 점수, 배정 집중도, 자료 품질과 초등학교 접근성을 반영했습니다.
- 확정배정, 배정가능, 조건부, 학교군 포함, 제외와 미확정 관계를 구분했습니다.
- 교육지원청 PDF, 수작업 보정 CSV와 별도 override 파일을 지원합니다.
- 전체 4,521개 중 4,288개, 500세대 이상 560개 중 546개 단지에 점수를 생성했습니다.

Phase 7 원본 점수와 가중치는 이후 단계에서 변경하지 않았습니다.

### Phase 8: 학군점수와 아파트 가격 검증

- 실거래 223,932건, 월별 panel 581,334행을 구축했습니다.
- Primary sample은 500세대 이상, 최근 거래와 높은 자료 품질을 충족한 487개 단지입니다.
- Pearson 0.398, Spearman 0.375, 구·군 내 Spearman 0.190을 기록했습니다.
- 법정동 내부 demeaned Spearman은 0.005였습니다.
- 법정동 고정효과에서 Phase 7 점수 10점 증가는 가격 3.10%와 연관됐으며 p-value는 0.1887이었습니다.
- 판정은 `USEFUL_FEATURE`이며 baseline snapshot을 보존합니다.

### Phase 9: Elementary Demand Score

- 학교알리미 공식 API의 학생·학급 및 전입·전출 자료를 사용했습니다.
- 공식 제공범위인 2024~2026년만 사용했으며 2022~2023년을 생성하거나 보간하지 않았습니다.
- 종단자료는 909개 학교·연도 행, 2026년 수요점수는 302개교입니다.
- 학생수 합계 오류와 공식 학교 ID 미연결은 0건입니다.
- 센텀초가 89.53점으로 현재 1위입니다.
- 학생수요 유형은 신축주거지 급성장형, 대규모 안정형, 학생감소형으로 분류했습니다.

Elementary Demand Score는 학교 교육의 질이 아니라 학생 자료에서 관측되는 통학구역의 주거·학군 수요 정도입니다.

### Phase 9.5~10: Elementary Demand 증분 설명력

- Elementary Demand와 기존 Phase 7 점수를 독립적으로 유지한 뒤 결합했습니다.
- 두 점수의 Spearman 상관은 0.283이며, 모두 상위 25%인 초등학교는 31개교였습니다.
- 공통표본은 486개 단지, 최근 12개월 거래는 22,181건입니다.
- 법정동 내부 Spearman은 M 단독 0.004에서 E+M 0.302로 증가했습니다.
- M 통제 후 E 10점 증가는 가격 6.01%와 연관됐고 p-value는 5.408e-09였습니다.
- E+M 모델의 out-of-sample RMSE는 M 단독보다 4.08% 개선됐습니다.
- E×M interaction은 지지되지 않아 `NOT_SUPPORTED`로 판정했습니다.
- Elementary Demand Layer 판정은 `INCREMENTAL_VALUE`입니다.

2024~2026 time-aligned 결과는 구조적 단면 결과보다 약하므로 장기 추세나 인과효과로 표현하지 않습니다.

### Phase 11~12.5: 중학교 통학권 수요와 Elementary-first 구조

- 중학교 183개교 중 점수 관측은 170개교입니다.
- 중학교 점수와 광의 통학권 Elementary Demand의 Spearman은 0.367이었습니다.
- 중학교 점수와 수요가 모두 상위 25%인 학교는 23개교입니다.
- 통학권 수요는 `MEANINGFUL`, 학생 이동 메커니즘은 `PARTIALLY_SUPPORTED`로 판정했습니다.
- Elementary Core는 `ELEMENTARY_CORE_SUPPORTED`로 판정했습니다.
- 중학교 증분가치는 `MIDDLE_INCREMENTAL_VALUE_PARTIALLY_SUPPORTED`로 판정했습니다.
- 최종 구조는 초등학교 수요를 Core로 두고 중학교 진학경로를 보조정보로 사용하는 방식입니다.

### Phase 13~14.9: School Premium과 School Value Gap 동결

- 500세대 이상 560개 중 557개 단지에 School Core Score를 생성했습니다.
- School Score 10점 증가의 가격 연관은 4.33%입니다.
- 법정동 내부 Spearman은 0.2982, residual 회귀 p-value는 1.73e-09였습니다.
- School Value Gap은 500개 단지에 존재하며 중앙값은 2.13%입니다.
- 최종 상태는 `SCHOOL_VALUE_MODEL_FROZEN_WITH_CAUTION`입니다.
- Phase 14.9 이후 School Core Score와 School Value Gap은 변경하지 않습니다.

### Phase 15.1~15.2: Local Fair Price

- 부산 Local Comparable의 기본 시장단위로 법정동을 선택했습니다.
- Phase 15.1 판정은 `LEGAL_DONG_BASELINE_PREFERRED`입니다.
- 충분한 표본의 법정동은 개별 회귀, 부족한 지역은 F3 partial pooling을 사용하는 Model F를 선택했습니다.
- Model F RMSE는 0.19574, MAE는 0.14880, R²는 0.8599입니다.
- Global 모델 대비 RMSE 48.78%, 법정동 고정효과 대비 20.48% 개선됐습니다.
- 학군 feature 추가 시 Model F RMSE가 5.74% 개선됐습니다.
- Fair Price는 502개 단지에서 산출됐습니다.
- 95% 예측구간 폭 중앙값은 67.95%로 불확실성이 크므로 개별 가격 확정값으로 사용하지 않습니다.

### Phase 15.3: Local Value Gap과 Dual Signal

- Local Value Gap 공식값은 502개 단지에 생성됐고 중앙값은 2.92%입니다.
- 6개월·12개월 Gap Spearman은 0.9650입니다.
- 동일 방향 안정 비율은 91.2%입니다.
- Strong undervalued는 8개, Strong overvalued는 4개입니다.
- School Gap과 Local Gap의 HIGH/MEDIUM 표본 Spearman은 0.7502입니다.
- DOUBLE_POSITIVE는 183개, ROBUST_DUAL_POSITIVE는 94개입니다.
- Local Gap 판정은 `LOCAL_VALUE_GAP_USABLE_WITH_CAUTION`입니다.
- Dual Signal 판정은 `DUAL_SIGNAL_COMPLEMENTARY`입니다.

Local Value Gap은 수익을 보장하는 저평가 지표가 아니라 유사 단지 대비 상대가치 검토 신호입니다.

### Phase 15.4: Final Freeze

- Phase 7~15.3 보호 파일 320개의 SHA-256 변경이 0건임을 확인했습니다.
- 새로운 모델이나 가중 합산점수를 만들지 않았습니다.
- 560개 단지를 상호배타적인 최종 검토 분류로 정리했습니다.
- CORE_CANDIDATE 94개, LOCAL_VALUE 58개, SCHOOL_VALUE 30개, WATCHLIST 262개, FULLY_PRICED_OR_NEGATIVE 116개입니다.
- HIGH audit 후보 33개와 모델 한계 플래그를 제공합니다.
- 최종 상태는 `BUSAN_APARTMENT_VALUE_MODEL_FINAL_FROZEN`입니다.

## 부산아파트 학군분석 앱

Phase 15.4 동결 결과 조회 앱은 분석이나 모델 학습을 실행하지 않는 Viewer + Validator입니다.

```powershell
..\busan_apartment_analysis\.venv\Scripts\streamlit.exe run phase154_streamlit_app.py
```

앱 이름은 **부산아파트 학군분석**입니다. 메뉴 순서는 **초등학교수요분석 → 중학교 점수 → 학군프리미엄분석**이며, 선택 상자의 안내 문구는 **선택**으로 표시합니다.

### 초등학교수요분석

- 학교 순위 표에서 학교 행을 더블클릭하면 해당 학교의 학교 상세 탭으로 이동합니다. 열 제목으로 정렬하거나 학교를 검색할 수 있으며, 키보드 Enter로도 상세를 열 수 있습니다.
- 16개 구·군, 302개 초등학교 조회
- 부산 순위와 구·군 순위
- 학생수, 학급수, 학급당 학생수, 전입·전출과 순전입률
- 최근 3개 공시연도 학생수 변화
- 보정 고학년 지수와 보정 동일학년군 성장률
- 학생수요 유형, 자료 신뢰도와 학교별 연도 추이

### 중학교 점수

- 중학교 순위 표에서 학교 행을 더블클릭하면 해당 학교의 학교 상세 탭으로 이동합니다.
- 부산 중학교 183개교와 점수 산출 170개교 조회
- 부산 순위와 구·군 순위
- 과학고, 외고·국제고, 자율형사립고 진학률 구성
- 최근 관측연도, 관측연도 수, 누적 졸업자 수와 점수 안정성
- 표본 경고와 검토 사유

### 학군프리미엄분석

- 핵심 후보 표에서 단지 행을 클릭하면 해당 아파트의 단지 상세 탭으로 이동합니다. 선택 상자의 안내 문구는 `선택`으로 표시합니다.
- 구, 법정동, 최종 분류, 모델·Local·School 신뢰도 필터
- 학군점수, Local Gap, School Gap, 세대수, 법정동 편향과 감사 우선순위 필터
- 전체 현황, 핵심 후보, 단지 상세, 법정동 검증, 감사·추가 검토, 모델 검증
- 적정가격 예측구간과 최근 12개월 관측가격 비교
- 현재 필터, CORE_CANDIDATE, WATCHLIST와 HIGH audit CSV 내려받기

## 주요 데이터와 보고서

| 파일 | 설명 |
|---|---|
| `data/processed/schools.parquet` | 부산 초·중학교 기본정보 |
| `data/processed/middle_school_scores.parquet` | 중학교 성과점수 183개교 |
| `data/processed/busan_apartment_elementary_match_2025.parquet` | 아파트와 공식 초등학교 통학구역 매칭 |
| `data/processed/phase9_elementary_student_longitudinal.parquet` | 2024~2026 초등학교 학생 종단자료 909행 |
| `data/processed/phase9_elementary_demand_scores.parquet` | 2026 초등학교 수요점수 302개교 |
| `data/processed/phase149_school_value_master.csv` | 동결 School Core와 School Value Gap |
| `data/processed/phase152_local_fair_price.csv` | Model F Local Fair Price |
| `data/processed/phase153_local_value_gap.csv` | Local Gap과 Dual Signal |
| `data/processed/phase154_final_apartment_value_master.csv` | 최종 운영 Master 560개 단지 |
| `data/snapshots/phase154_final_model_freeze.json` | 최종 모델·무결성 snapshot |
| `reports/phase154_final_candidates.csv` | 최종 분류와 class 내부 순위 |
| `reports/phase154_high_audit_review.csv` | HIGH audit 33개 후보 |
| `reports/phase154_protected_manifest.csv` | 보호 파일 SHA-256 목록 |
| `reports/phase154_final_freeze_result_review.md` | 최종 동결 보고서 |

## 데이터 출처

- 학교알리미 기본정보 Open API
- 학교알리미 학생·학급 및 전입·전출 공시정보
- 학교알리미 고교 진학현황 공시정보
- 학구도안내서비스 2025-09-22 공식 초등학교 통학구역 공간경계
- 부산 5개 교육지원청의 통학구역·중입배정 자료
- 국토교통부 아파트 실거래 자료
- K-apt 아파트 기본정보

수집 원본은 `data/raw/`에 보존하며 출처 문서, 수집시각, 기준연도와 SHA-256을 기록합니다.

## 주요 명령

아래 명령은 데이터 갱신이나 재현이 필요한 경우에만 사용합니다. Phase 15.4 운영에서는 동결 Master를 우선 사용합니다.

```powershell
# 학교 기본정보
python main.py collect-schools --year 2026
python main.py geocode-schools

# 중학교 진학성과
python main.py collect-advancement --years 2023 2024 2025
python main.py score-middle-schools

# 공식 통학구역
python main.py collect-schoolzone --year 2025
python main.py build-schoolzone --year 2025

# 초등학교 수요
python main.py phase9-collect --years 2024 2025 2026
python main.py phase9-build

# 전체 자동검증
..\busan_apartment_analysis\.venv\Scripts\python.exe -m pytest -q
```

## 설치

Python 3.11 이상을 권장합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

필요한 환경변수는 `.env.example`을 참고합니다. 인증키를 코드나 보고서에 기록하지 않습니다.

## 해석상 한계

- 학교점수는 관측된 학생수요와 진학성과의 상대지표이며 학교의 인과적 교육효과가 아닙니다.
- 통학구역과 중학교 배정관계는 기준연도와 관계유형을 함께 확인해야 합니다.
- 2026 Elementary Demand를 과거 거래시점에 알려진 정보처럼 해석하지 않습니다.
- Fair Price와 Value Gap은 통계적 추정치이며 실제 개별 매물의 동·향, 층, 조망, 내부상태를 반영하지 못합니다.
- 재건축 기대, 브랜드, 해안·교량 조망과 소음 등 누락요인은 residual 또는 audit 한계로 남깁니다.
- 후보 분류는 매수 추천이나 수익 보장이 아닙니다.

## 검증과 보호 원칙

- Phase 7 점수, override와 공간매칭을 변경하지 않습니다.
- Phase 9 Elementary Demand Score를 가격 결과에 맞춰 조정하지 않습니다.
- Phase 14.9 School Value와 Phase 15.2 Fair Price를 덮어쓰지 않습니다.
- 결측 학교와 결측 가격을 0이나 평균으로 대체하지 않습니다.
- Streamlit은 동결 파일만 읽으며 학습 함수를 호출하지 않습니다.
- 최종 검증 결과는 **448개 테스트 통과, 실패 0개**입니다.
