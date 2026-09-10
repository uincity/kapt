# 부산 학군 데이터 검증

`busan_apartment_analysis`의 단지 ID와 K-apt 정보를 재사용하는 독립 프로젝트다.
학교 데이터를 연 1~2회 갱신하고, 공식 배정관계를 검증한 뒤 단지별 학군 parquet를 만드는 것이 목표다.

## 현재 완료 범위

- **Phase 1 완료**: 기존 코드·파일 스키마를 직접 확인하고 단지 master 4,521개를 생성했다.
  500세대 이상은 560개다. [상세 분석](reports/phase1_findings.md)을 참고한다.
- **Phase 2 실수집 검증 완료**: 초등학교 319개, 중학교 183개, 총 502개.
  좌표는 500개에 존재한다. 운영 중인 학교는 초등학교 305개, 중학교 171개이며 폐교도 보존한다.
- **Phase 3**: 공식 졸업생 진로 공개 표 수집, 원본/연도 검증, 진학률·소표본 보정·중학교 순위,
  Plotly HTML 보고서를 구현했다. [실수집 결과와 해석](reports/phase3_findings.md)을 참고한다.
- **Phase 4 완료**: 2025학년도 해운대교육지원청 통학구역·중입 원문 보존, 정규화 및 검증 PoC.
- **Phase 5 완료**: 센텀/재송 통학구역의 K-apt 후보 검증, 중학교 관계별 성과 연결, 최소 Streamlit 검증 화면.
- **Phase 6 공식 공간경계 보완 완료**: 학구도안내서비스 2025-09-22 경계 309개와 학교 연계 324건을
  부산 5개 교육지원청에 적용했다. 좌표 보유 아파트 1,468개 중 1,466개를 경계에 연결했다.
- **Phase 7 완료**: 공식 초→중 관계의 신뢰도, 중학교 성과 분포, 초등 직선거리와 자료 품질을
  결합한 설명 가능한 아파트 학군점수를 구축했다. 미확보 관계는 `UNRESOLVED`로 유지한다.
- Phase 8–9의 가격 프리미엄 분석과 최종 품질보고서는 후속 단계다.

## Phase 4: 해운대교육지원청 학교구역 PoC

2025학년도만 지원한다. 수집기는 공식 게시판에서 제목으로 게시물을 찾고 게시물 ID와
첨부 API 응답에서 실제 다운로드 경로를 얻는다. 기본 실행은 검증된 캐시를 재사용하며
`--force`는 기존 원본을 `history`에 보존한다.

```powershell
python main.py collect-catchments --office haeundae --year 2025
python main.py collect-middle-assignment --office haeundae --year 2025
python main.py parse-catchments --office haeundae --year 2025
python main.py parse-middle-assignment --office haeundae --year 2025
python main.py validate-school-zone --office haeundae --year 2025
```

통학구역은 원문 `catchment_text`를 유지한 채 논리 구간으로 펼친다. 구간별 상태는
`PARSED`, `PARTIAL`, `REVIEW`이며 뒤의 두 상태는 `manual_review=True`다.
학교군 행은 `assignment_certainty=group_only`다. 시행계획 PDF 26~27쪽의 일반우선·희망지원
대상은 별도 조건부 관계로 보존하지만 정원과 추첨 조건이 있으므로
`conditional_not_guaranteed`로 표시한다. 공개자료에는 초등학교별 특정 중학교 확정 관계가 없다.

legacy HWP는 원본만 보존하고 자동 해석하지 않는다. 수동 보완은
`data/manual/haeundae_middle_assignment_2025_manual.csv`에 공식 원문에서 확인한 값만 작성한다.
`source_document`, `source_page_or_section`, `source_text`, `assignment_type`,
`assignment_certainty`를 모두 채우고 불명확한 행은 `manual_review=True`로 둔다.

| 경로 | 역할 |
|---|---|
| `data/raw/education_office/haeundae/2025/` | 통학구역 HTML과 메타데이터 |
| `data/raw/education_office/haeundae/2025/middle_assignment/` | 게시판·게시물·학교군 HTML, PDF/HWP 원본과 해시 |
| `data/interim/haeundae_elementary_catchment_2025.parquet` | 원문 보존 통학구역 논리 구간 |
| `data/interim/haeundae_middle_school_groups_2025.parquet` | 학교군×중학교×거주동 many-to-many |
| `data/interim/haeundae_middle_assignment_2025.parquet` | PDF에 명시된 조건부 관계 |
| `reports/haeundae_parse_review_2025.csv` | PARTIAL/REVIEW 검수 대상 |
| `reports/haeundae_phase4_validation.md` | 건수, 성공률, 연도 및 관계 수준 검증 |

## Phase 7: 설명 가능한 아파트 학군점수

```powershell
python main.py phase7-audit
python main.py phase7-build
python main.py phase7-build --assignment-year 2026
python -m streamlit run streamlit_app.py
```

가중치는 `config/school_score.yaml`에서 관리한다. 관계 가중치는 배정확률이 아니라 공식 근거의
신뢰도 proxy다. `EXACT`, `ELIGIBLE`, `CONDITIONAL`, `GROUP_MEMBERSHIP`, `UNRESOLVED`를 구분하며
학교군 포함을 배정 확정으로 해석하지 않는다. 최고점 편향을 막기 위해 가중평균과 최저점,
후보 분산, exclusivity를 함께 사용한다. Phase 3 원점수와 소표본 경고는 수정하지 않는다.

최종 단지 파일은 4,521개 `internal_complex_id`를 1행씩 보존하며 기존 아파트 프로젝트에서
왼쪽 결합할 수 있다. 직선거리는 실제 보행거리와 다르며, 좌표 REVIEW 단지는 공식 직접 근거가
없는 한 점수에서 제외한다. 상세 한계와 Phase 8 준비 판정은 `reports/phase7_validation.md`에 있다.

사용자가 제공한 북부·서부 2026학년도 공식 PDF는 `--assignment-year 2026`으로 별도 파싱한다.
남녀 중입 배정 열만 사용하며 전학 배정 열은 점수 후보에서 제외한다. 2026 관계를 2025 관계에
덮어쓰지 않는다. 2026 아파트 점수는 2025-09-22 공간경계와 Phase 3의 2025 성과점수를 함께
참고하므로 각 기준연도를 결과와 검증보고서에 명시한다.
수작업으로 확보한 `em_school/수작업 초_중배정내역(260908).csv`와
`em_school/수작업 초_중배정내역(260909).csv`의 진학 가능 관계도 같은 명령에서 병합한다.
이 관계는 `ELIGIBLE`, `manual_review=True`로 구분하고 CSV 행 번호와 SHA256을 보존한다.
현행 학교 마스터에서 단일 학교를 확정할 수 없는 표기는 검수 CSV에 남기고 점수에서 제외한다.

## 실행 환경

## Phase 5: Centum validation

```powershell
python main.py validate-centum --office haeundae --year 2025
python -m streamlit run streamlit_app.py
python -m pytest -p no:cacheprovider
```

프로젝트 `.venv`가 없으면 기존에 검증한 `..\busan_apartment_analysis\.venv\Scripts\python.exe`로
위 명령의 `python`을 대체한다. 기존 환경에 설치된 Streamlit 1.62.0으로 검증했다.
외부 프로젝트의 데이터와 환경은 읽기만 하며 새 파일은 이 프로젝트 안에 생성한다.

범위는 센텀초 공식 통학구역 전체, 재송1·2동에 명시된 공동주택, Phase 4 괄호 없는 두 단지명이다.
마지막 사례인 센텀미진이지비아만 기존 REVIEW 검증을 위해 우동까지 조회한다.
K-apt 후보는 해당 구·법정동으로 제한한다. 행정동 숫자 제거는 후보 탐색 휴리스틱이며 경계 확인이 아니다.
500세대 미만 단지는 전체 후보·매칭 파일에 유지하고 별도 view에서만 필터한다.

이름 정규화는 공백·괄호·법인표기·아파트/APT·차수 표기를 처리한다. 지역명과 브랜드는
정규화 때 임의 삭제하지 않고 유사도 후보로 비교한다. 차수가 명시적으로 다르면 후보에서 제외한다.
`name_score`와 `address_score`는 각각 보존한다. 주소점수 0.8은 실제 주소의 구·법정동 보조근거이며,
행정동·통·반의 확정 확인이 아니다. 공식 주소 확인이 없는 fuzzy/문맥 후보는 `REVIEW`다.
`internal_complex_id`가 있어도 `REVIEW`는 후보 연결만 의미한다. 후보가 없으면 ID를 채우지 않고
`UNRESOLVED`로 남긴다. 거리 5km 초과는 `spatial_outlier`로 검수한다.

현재 입력은 2025 통학구역과 유효연도 미상의 K-apt 스냅샷, 2026 학교 기본정보를 함께 참고한다.
이를 모두 2025 당시 현황으로 간주하지 않는다. 중학교 점수는 `score_reference_year`와
`observation_years`를 보존하며 관계의 확실성을 올리거나 아파트 점수로 집계하지 않는다.
학교군 HTML에 적용연도가 없어 `temporal_review=True`를 보존한다.

수동보정은 `config/manual_apartment_school_overrides.csv`에 기록한다. 열은 다음과 같다:
`data_year, education_office, elementary_school_name, raw_apartment_name, internal_complex_id,
kapt_code, complex_name, override_type, evidence_source, evidence_text, reason, verified_at`.
원문 이름·학교·연도·교육지원청으로 적용하며 evidence, reason, verified_at이 비면 거부한다.
`confirmed`만 확정 관계로 표시하고 `alias`/`split`은 검수 관계로 유지한다. `rejected`/`unresolved`는
선택된 ID를 비운다. 대상 ID를 실제 master에서 검증하고 주소·세대수·거리도 해당 ID로 다시 읽는다.
같은 원문에 복수 보정 행이 있으면 자동 게시를 거부한다. 복수 split 확정은 후속 다중 근거 지원이 필요하다.
현재 보정 CSV는 빈 템플릿이며 임의 확정 예외를 넣지 않았다.

| 파일 | 내용 |
|---|---|
| `reports/haeundae_phase5_schema_audit.json` | Phase 1~4와 외부 원본의 실제 스키마·SHA256 |
| `data/interim/haeundae_apartment_elementary_candidates_2025.parquet` | 전체 후보, 순위, 후보 수, 이름/주소 점수 |
| `data/processed/haeundae_apartment_elementary_match_2025.parquet` | 상태와 근거를 유지한 단지명별 검증 |
| `data/interim/haeundae_elementary_middle_validation_2025.parquet` | group_only·조건부 관계, 학교 ID·성과 |
| `data/processed/haeundae_school_apartments_500plus_2025.parquet` | 세대수 확인 후보 중 500세대 이상 view |
| `reports/haeundae_phase4_review_resolution_2025.csv` | 기존 검수 7건 각각의 처리 상태 |
| `reports/haeundae_centum_apartment_validation_2025.csv` | 센텀초 3개 단지 상세 결과 |
| `reports/haeundae_phase5_quality_2025.json` | 분모가 명시된 품질 지표 |
| `reports/haeundae_phase5_validation.md` | A~K 최종 검증보고서 |
| `reports/phase5_pytest.xml` | 전체 회귀 및 Streamlit AppTest 결과 |

테스트는 `tests/fixtures/phase5/`의 실제 로컬 스냅샷과 합성 반례를 사용한다. 네트워크 접속이나
API 키 없이 실행하며 원본 해시는 `provenance.json`에 기록했다. Streamlit 테스트는 임시 폴더에
검증 데이터를 만들어 앱의 학교 선택과 500세대 필터를 확인한다. 서버를 상시 실행하지 않는다.

## Phase 6: 2025 공식 학구도 공간경계

[학구도안내서비스 공공데이터 목록](https://schoolzone.emac.kr/publicData/publicDataList.do)의
`초등학교 통학구역 및 공동통학구역(2025.09.22.)` Shapefile과 같은 기준일의
`학교-학구도 연계정보` CSV를 사용한다. 수집기는 게시물·첨부 식별자를 고정하고 원본 ZIP의
SHA256, 기준일, 수집시각, 공식 목록 및 다운로드 URL을 메타데이터로 기록한다.

```powershell
python main.py collect-schoolzone --year 2025
python main.py build-schoolzone --year 2025
python main.py phase6-report
```

부산 코드(`SD_CD=26`)만 추출하고 원 좌표계 EPSG:5186을 GeoParquet에 보존한다. 일반 통학구역과
공동통학구역을 구분하며 공동통학구역의 여러 학교 관계를 한 학교로 축약하지 않는다. 공식 학구 ID와
외부 학교 ID를 주 근거로 보존하고, 내부 `school_id`는 활성 학교명과 교육지원청을 이용해 별도 연결한다.
2025 자료의 휴교 표기와 2026 학교 마스터 상태가 다른 1건은 수동검토로 유지한다.

아파트 좌표는 WGS84에서 경계 좌표계로 변환한 후 `intersects`로 판정한다. 현재 K-apt 스냅샷을
2025 주소로 간주하지 않으며 `address_temporal_match=False`로 기록한다. 좌표 누락 3,053개는
`COORDINATE_MISSING`, 경계에서 약 18m와 22m 벗어난 2개는 `OUTSIDE_OFFICIAL_BOUNDARY`로
보존한다. 학구도 파일에는 행정동·법정동 코드가 없으므로 해당 코드를 공간 경계에서 추정하지 않는다.

| 파일 | 내용 |
|---|---|
| `data/raw/schoolzone/2025/` | 공식 ZIP, SHA256·기준일 메타데이터, 안전 추출본 |
| `data/processed/busan_elementary_catchment_boundaries_2025.parquet` | 부산 공식 학구 GeoParquet 309개 |
| `data/processed/busan_schoolzone_school_link_2025.parquet` | 학교-학구도 관계 324건과 내부 ID 매핑 근거 |
| `data/processed/busan_apartment_elementary_match_2025.parquet` | 4,521개 단지 전체의 공간 판정과 검토 상태 |
| `reports/schoolzone_2025_quality.csv` | 교육지원청별 경계·공동통학·단지 매칭 수 |
| `reports/phase6_validation.md` | Phase 6 통합 판정과 Phase 7 선행조건 |

## Phase 6.5: 아파트 좌표 보완

K-apt 좌표가 없는 거래 기반 단지에는 국토교통부 실거래 원천의 도로명·지번 주소를 복원한다.
기존 좌표를 다시 지오코딩하지 않으며 도로명, 지번, 단지명+법정동 순서로 후보를 처리한다.
성공과 실패는 모두 질의 해시로 캐시하고 반환 주소의 부산·구군·법정동·도로명·건물번호를 검증한
좌표만 공간매칭에 사용한다. 단지명 후보는 자동 확정하지 않는다.

```powershell
python main.py phase65-audit
python main.py phase65-geocode
python main.py phase65-geocode --retry-failed
python main.py phase65-build
```

최종 좌표는 `data/processed/busan_apartment_coordinates_2025.parquet`, 주소 후보와 시도 이력은
`data/interim/apartment_coordinate_candidates_2025.parquet` 및 `geocode_attempts.parquet`에 저장한다.
기존 공식 직접 근거와 공간근거를 병합한 관계는
`data/processed/busan_apartment_elementary_relation_2025.parquet`이며 `evidence_types`와
`cross_validated`를 보존한다. 상세 품질 판정은 `reports/phase65_validation.md`에서 확인한다.

## Python 환경 설치

Python 3.11 이상. 필요한 의존성만 우선 설치한다. Plotly 보고서는 지원하며 GIS/Streamlit은 해당 단계에서 추가한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`에 `SCHOOLINFO_API_KEY`, 학교 좌표 보강이 필요하면 `KAKAO_API_KEY`를 설정한다.
키를 대화나 소스에 붙여넣지 않는다. 시스템 환경변수가 `.env`보다 우선한다.
기존 아파트 프로젝트의 `.env`를 자동 로드하거나 복사하지 않는다.

기존 가상환경으로도 검증할 수 있다. 이번 실행은 기존 Python 3.13 환경을 읽기 전용으로 사용했으며
기존 패키지/코드를 변경하지 않았다.

```powershell
..\busan_apartment_analysis\.venv\Scripts\python.exe main.py inspect-apartments
..\busan_apartment_analysis\.venv\Scripts\python.exe main.py collect-schools --year 2026
..\busan_apartment_analysis\.venv\Scripts\python.exe main.py geocode-schools
..\busan_apartment_analysis\.venv\Scripts\python.exe -m pytest
```

## 데이터 출처와 확인 범위

- [학교알리미 기본정보 API](https://www.schoolinfo.go.kr/ng/go/pnnggo_a01_l0.do)
- [공식 출력 명세 Excel](https://www.schoolinfo.go.kr/download/OpenAPI_Output.xlsx)
- [공식 시도/시군구 코드 Excel](https://www.schoolinfo.go.kr/download/sido_sggCode.xlsx)
- [인증키 발급 안내](https://www.schoolinfo.go.kr/ng/go/pnnggo_a01_m0.do)
- 로컬 `../busan_apartment_analysis/data/interim/kapt_clean.parquet`와 단지 요약/매칭 로그

2026-09-05 내려받은 공식 Excel은 `data/raw/reference/`에 원본 보관한다.
부산 코드 16행은 `config/schoolinfo_codes.csv`, 기본정보 출력 명세 37행은
`config/schoolinfo_output_fields.csv`에 추출했다. API 요청은 16개 구·군 × 학교급 02/03,
총 32개 배치이며 시군구 조건을 항상 지정한다.

파서는 명세의 `SCHUL_CODE`, `SCHUL_NM`, `SCHUL_KND_SC_CODE`, `SCHUL_RDNMA`,
`ADRES_BRKDN`, `LTTUD`, `LGTUD` 등을 사용한다. 설립구분은 `FOND_SC_CODE`,
설립유형은 별개인 `SCHUL_FOND_TYP_CODE`다. 현재 establishment_type은 설립구분 원값이며
코드값을 추측해서 국립/공립/사립이나 남녀공학 명칭으로 번역하지 않는다.
실제 응답의 `SHL_IDF_CD` 공개 UUID도 보존해 학교 공시 화면과 연결한다.
`HS_KND_SC_NM`는 이번 초·중학교 실제 응답 502개에서 제공되지 않았다. 임의 유형을 채우지 않아
school_type은 결측이며 기존 수집기의 검수 플래그에도 반영된다. 중학교 진학실적 검수와는 별개다.

기본정보 API에는 연도 요청 인자가 없다. `--year`는 수집연도 스냅샷이다.
과거연도 요청은 해당 연도에 보존한 원본만 재사용할 수 있고 새 요청은 차단한다.
원본의 SHA256과 수집시각을 검증하며 현재 응답에 과거 연도를 붙이지 않는다.

## 수집과 갱신

```powershell
python main.py collect-schools --year 2026
python main.py collect-schools --year 2026 --force
python main.py geocode-schools
python main.py geocode-schools --retry-failed
```

기본 수집은 검증된 원본을 재사용한다. `--force`는 기존 원본/메타데이터를 history에
보존한 뒤 새 응답을 저장한다. 응답 바이트를 수정하지 않고 저장하고, 키가 응답에 포함되면
저장을 거부한다. 인증키/요청 URL을 로그에 출력하지 않는다.
통신 재시도와 timeout을 적용한다. 실패/빈 응답 배치는 보고서에 남기며,
32개 배치 모두 검증되기 전에는 기존 `schools.parquet`를 대체하지 않는다.

원본 응답의 학교급·지역·필수 ID/학교명을 검사하고, 선택 필드 누락과 좌표 이상은
manual_review로 남긴다. 폐교/휴교도 삭제하지 않는다. 따라서 수집 학교 수는
재학생이 있는 운영 학교 수와 같다고 보장하지 않는다.
confidence는 파싱 완전성 표시(완전 1.0, 검수대상 0.5)이며 배정 확률이 아니다.

좌표가 없으면 Kakao 주소검색에 도로명/지번 및 건물번호까지의 주소 후보를 전달한다.
정규화한 주소의 SHA256 캐시를 사용해 서로 다른 학교도 같은 주소를 재조회하지 않는다.
검색 실패도 캐시하고 `--retry-failed`로 재조회한다. API 인증/통신 장애는 주소 없음으로
캐시하지 않는다. geocoded_at과 좌표 출처는 학교 원출처와 분리한다.
Kakao 좌표는 통학구역이나 입학배정을 의미하지 않는다.

연 1~2회 공식 코드/명세 변경을 확인한 후 현재 연도로 수집한다. 같은 해 재수집에는
`--force`를 쓴다. 향후 통학구역과 배정계획은 적용연도가 확인된 문서만 함께 사용한다.

## 현재 생성물

| 경로 | 역할 |
|---|---|
| reports/phase1_findings.md | 기존 구조, 실제 매핑, 구현 순서 |
| reports/existing_project_schema.json | 파일/컬럼/행 수/입력 SHA256 |
| reports/phase1_statistics.csv | 실제 단지 통계 |
| data/interim/apartment_master.parquet | 모든 단지, 원 ID, 주소/좌표 |
| data/raw/reference/ | 공식 명세/코드 원본 |
| data/raw/schoolinfo/{year}/ | 실제 수집 후 생성되는 응답/메타데이터 |
| data/processed/schools.parquet | 32배치 수집 성공 후 생성 |
| data/processed/snapshots/{year}/schools.parquet | 연도별 학교 스냅샷 |
| reports/school_collection_status.csv | 32배치 성공/실패/재사용 현황 |
| reports/school_data_quality.csv | 학교 수, 학교급별 수, 수집 시 좌표 비율 |
| reports/manual_review.csv | 마지막 학교 수집/지오코딩의 검수대상 |
| data/interim/school_geocode_cache.json | 주소별 지오코딩 성공/실패 캐시 |
| data/interim/school_geocode_failures.csv | 미해결 학교 주소 |
| reports/school_geocode_quality.csv | 지오코딩 이후 좌표 비율 |
| data/raw/advancement/{year}/ | 학교별 공시 HTML 및 요청/해시 메타데이터 |
| data/processed/middle_school_advancement.parquet | 학교×요청연도, 검증 인원·진학률·불가 사유 |
| data/processed/middle_school_scores.parquet | 중학교별 점수, 원/보정 가중 진학률, 순위 |
| reports/advancement_collection_status.csv | 실제 반환연도 및 모든 수집 시도 상태 |
| reports/middle_school_ranking.html | 브라우저에서 여는 독립 Plotly 보고서 |
| reports/middle_school_ranking.csv | 전체 중학교 지표/검수상태 |
| reports/centum_advancement_validation.csv | 센텀중학교의 연도별 원값과 검증 결과 |

실수집되지 않은 파일은 빈 가짜 결과로 만들지 않는다. 테스트용 학교 응답은 합성 fixture이며
테스트 임시 폴더에만 저장한다. 단지 master의 data_year는 원자료에 없으므로 결측이다.

## 진학현황 수집 및 중학교 점수

```powershell
python main.py collect-advancement --years 2023 2024 2025 2026
python main.py score-middle-schools
python main.py report
```

진학현황은 현재 일반 Open API 목록에 없어, 같은 학교알리미의 **공개 공시 화면**을 사용한다.
공식 [항목별 공시 페이지](https://www.schoolinfo.go.kr/ei/ss/pneiss_a05_s1.do)의 loadGongSi
요청을 확인해 13-다 공개 HTML을 수집한다. 인증키나 로그인은 사용하지 않는다.
파일 첨부 다운로드의 CAPTCHA를 우회하지 않고, 공개 표의 합계행을 읽는다.
원본은 요청연도별로 보존하고 `--force`로 재수집하면 기존 원본을 history에 보관한다.

2026년 요청에 2025년 표가 반환될 수 있다. hidden JG_YEAR, 실제 선택된 공시연도,
학교 UUID를 모두 검사하며, 다른 연도는 `year_mismatch`로 남기고 인원/진학률을 채우지 않는다.
2026년이 공개되기 전에는 2023–2025년이 최근 3개 공개연도다.
과거연도 필터를 지원하는 진학현황 화면과 연도 필터가 없는 기본정보 API를 혼동하지 않는다.

합계행의 `td title`을 실제 관측된 필드 별칭으로 사용하며 남녀 합계, 특목고/자율고 소계,
진학자계, 졸업자 합계를 대조한다. 비율행은 원문 title 오표기 사례가 있어 재사용하지 않고
검증된 인원에서 직접 계산한다. 빈값·비공개·비정수 값을 0으로 간주하지 않는다.

원자료는 외고국제고, 예고체고가 합산되어 있다. 따라서
`foreign_international_hs_count`, `arts_sports_hs_count`를 제공하며,
외고/국제고/예고/체고 개별 열은 결측으로 보존한다. 기타 진학은 영재학교·국외 등도 포함할 수 있어
`other_advancement_count`를 `other_special_hs_count`로 바꾸거나 학업 중심 점수에 더하지 않는다.

점수 계산 절차:

1. 검증된 실적 중 최신 공개연도 Y와 Y-1, Y-2만 사용한다.
2. 각 연도의 부산 평균은 학교별 진학률 평균이 아니라 **진학 인원 합 / 졸업 인원 합**이다.
3. `adjusted_rate = (n * rate + k * busan_mean_rate) / (n + k)`, 기본 k=100.
4. 원/보정 진학률 각각에 Y=0.5, Y-1=0.3, Y-2=0.2 가중평균을 적용한다.
   없는 연도는 나머지 가중치의 합으로 재정규화한다. Y와 Y-2만 있으면 0.5:0.2이며 0.5:0.3이 아니다.
5. 운영 중이며 점수 산출이 가능한 부산 중학교에서 보정 가중 진학률의 평균동률 백분위를 계산한다.
   과학고 0.45, 외고국제고 0.35, 자사고 0.20의 가중합 ×100이 middle_school_score다.
6. 부산/구군 순위는 높은 점수가 1위이며 동점은 공동순위다. 미산출 학교를 0점으로 순위에 넣지 않는다.

연도별 부산 평균에는 해당 연도의 검증된 모든 관측학교를 사용한다. 현재 폐교/휴교 학교는
최종 순위에서 제외한다. `ranking_population`과 `ranking_coverage`로 실제 비교 모집단을 보존한다.
기본정보에 없는 과거 폐교 학교는 이번 모집단에 추가되지 않으므로 과거 전체 부산 학교를 완전 재현한 것은 아니다.
1개년뿐이거나 어느 관측연도의 졸업생이 30명 미만이면 sample_warning=True.
연도 누락·오래된 최신 실적도 검수 표시한다. score_stability는 연도별 보정 지표 백분위 점수의
표준편차를 사용한 `clip(1-std/50, 0, 1)`이며 1개년이면 결측이다. 인과적 학교 효과의 지표가 아니다.

CSV 수동 검수는 `config/advancement_review_template.csv`를 복사해 실제 원문을 대조한 뒤 사용한다.
졸업자/유형별 인원/소계를 모두 채우고 출처 URL, 문서, 수집시각, 검수자, 검수시각이 필요하다.

```powershell
python main.py import-advancement --csv data/interim/reviewed_advancement.csv
python main.py score-middle-schools
python main.py report
```

합계가 맞지 않으면 반영하지 않는다. 검수 CSV 원본과 반영 전 parquet를 보존한다.
수동 검수 자료는 후속 자동수집보다 우선하며 수정은 새 검수 CSV를 명시적으로 가져와 수행한다.
자동 재수집 실패도 기존의 검증된 값을 삭제하지 않는다. 마지막 수집 시도 실패 여부는
`advancement_collection_status.csv`를 확인한다.

## 학군 정의와 후속 아파트 점수 설계

학교 진학실적 → 배정 가능한 초등학교 → 공식 통학구역 → 아파트 순으로 연결한다.
학업 중심 선택고 지표에서 과학고, 외고·국제고, 자사고를 사용하고 예고·체고·마이스터고는
별도 지표로 보존한다. 학교 목적이 다른 진로를 모두 더한 특목고 진학률을 그대로 사용하지 않는다.

점수 설정은 `config/settings.yaml`에 보관한다.
최근 3개년 가중치 0.5/0.3/0.2, 소표본 shrinkage k=100,
과학고/외고·국제고/자사고 percentile 가중치 0.45/0.35/0.20을 적용할 계획이다.
중학교 결측·소표본 처리, 안정성, 원/보정 진학률은 실제 표 기반 회귀 테스트로 검증한다.

초등학교×중학교는 many-to-many다. 공식 학교군 포함은 확정 배정과 다르며
성별/통·반/소지역 조건을 별도 보존한다. 센텀초→센텀중 관계도 하드코딩하지 않는다.
평균/최저 점수와 feeder_exclusivity를 사용하며 최고 중학교 하나만으로 평가하지 않는다.
아파트 점수의 가중합/가중곱 해석은 Phase 7에서 명시하고 독립 함수로 검증한다.

공식 통학구역의 단지명 → 주소·통/반 → 도로명/지번 → 수동 보정 → 최후 거리 fallback
순서로 매칭한다. fuzzy와 거리 추정은 검수대상이며 공식 배정으로 승격하지 않는다.
현재 master에는 통/반이 없으므로 해당 매칭은 검증된 추가자료 없이는 실행할 수 없다.

## 검수 및 기존 프로젝트 연결

먼저 수집 상태 CSV의 실패 배치를 확인하고, 원문/공식 명세와 비교한다. 학교 ID 충돌이나
응답 지역 불일치를 임의 drop_duplicates로 지우지 않는다. 통학구역 문서 검수용 CSV 및
수동 override는 해당 parser 단계에서 출처·적용연도·근거를 갖추어 추가할 예정이다.

최종 `apartment_school_features.parquet`는 아직 생성하지 않았다. Phase 7 완료 후에는
기존 ID를 유지한 단지별 1행 파일로 다음과 같이 외부에서 결합할 수 있도록 설계한다.

```python
features = pd.read_parquet('apartment_school_features.parquet')
result = apartment_data.merge(features, on='internal_complex_id', how='left', validate='many_to_one')
```

기존 프로젝트 코드를 바꾸거나 월별 수집 작업에 학교 API를 추가할 필요가 없다.
연도별 파일 선택은 결합 전에 명시하며 초등학교/중학교 다중 후보 상세 테이블은 별도로 둔다.

## Phase 8 학군 프리미엄 검증

인접 `busan_apartment_analysis` 프로젝트의 개별 실거래와 월별 패널을
`internal_complex_id`로 읽기 전용 결합한다. Phase 7 점수는 snapshot으로
고정하며 가격과의 상관, quintile, 유사단지 pair, 군집 표준오차 회귀 및
상승·하락 월 분석을 생성한다.

```powershell
python main.py phase8-build
streamlit run streamlit_app.py
```

분석 설정은 `config/phase8_analysis.yaml`, 핵심 해석은
`reports/phase8_validation.md`에 기록된다. 84㎡/59㎡ 분석은 각각 실제
80~90㎡/55~65㎡ 거래만 사용한다.

대시보드의 전체 메뉴는 사이드바에 펼쳐서 표시한다. **초등학교 배정관계 수정**
화면에서는 구·군을 먼저 선택한 뒤 해당 지역의 초등학교를 선택하고
중학교별 관계유형, 점수 반영상태와 실제 배정비율을 편집할 수 있다. 수정값은
`config/manual_elementary_middle_overrides.csv`에 원본과 분리해 저장되며,
저장 버튼을 누르면 2026학년도 feeder와 아파트 학군점수를 다시 계산한다.
**초등학교 진학권 순위**에서도 전체 또는 구·군을 선택해 부산 순위와 구·군 내
순위를 함께 비교할 수 있다.

## 검증

```powershell
python -m pytest
```

학교 기본정보 테스트: 32배치 성공/캐시, 키 미노출, 부분실패 시 기존 결과 보호,
과거연도 차단, 변조된 원본 차단, 필수필드/지역/학교급 검사,
누락·좌표 오류 처리, 주소 공유 캐시, 지오코딩 실패 캐시를 검증한다.
추가로 실제 센텀중 HTML의 인원·2026→2025 반환 차단, 진학률, 소표본 보정,
연도 가중치/누락, 동률 백분위, 폐교 제외, 1개년 경고, 중복 키 차단,
검수 CSV 합계 및 기존 출력 보존을 검증한다. 실제 수집 결과는 reports에 별도 기록한다.
