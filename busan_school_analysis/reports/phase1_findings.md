# Phase 1: 기존 프로젝트 구조 및 재사용 설계

2026-09-05에 `../busan_apartment_analysis`의 README, requirements, config, src, main.py,
app.py, data/processed 및 data/interim을 직접 확인했다. 기존 파일을 수정하거나 기존 build를 실행하지 않았다.

## 실제 파일과 규모

| 파일 | 행 수 | 재사용 목적 |
|---|---:|---|
| data/interim/kapt_clean.parquet | 1,468 | K-apt 단지명, 세대수, 도로명/지번주소, 좌표 |
| data/interim/kapt_coordinates.parquet | 1,468 | Kakao 좌표 캐시, geocoded_at |
| data/processed/busan_complex_summary.csv | 4,409 | 기존 internal_complex_id 및 전체 단지 모집단 |
| data/processed/busan_apartment_monthly.parquet | 581,334 | 기존 ID·K-apt 코드 관계와 월 패널 인터페이스 |
| data/processed/busan_apartment_rent_monthly.parquet | 660,468 | 전월세 패널; 학군 계산에는 불필요 |
| data/processed/apartment_match_log.csv | 실행 보고서 참조 | internal_complex_id ↔ kapt_code 명시적 연결 |

K-apt 1,468개 중 500세대 이상은 560개이며 모두 좌표가 있다. 기존 단지 요약에는
K-apt 1,356개와 비 K-apt 3,053개가 있다. 요약만 사용하면 K-apt 112개가 빠지고,
500세대 이상 단지는 503개만 남는다. 따라서 요약에 빠진 K-apt를 추가한
4,521개 단지 master를 새 프로젝트에 생성한다. 500세대 이상은 560개다.
세대수 미상 3,053개는 500세대 미만으로 간주하지 않고 nullable boolean으로 보존한다.

## 실제 컬럼 대응

| 새 인터페이스 | 확인한 기존 컬럼/규칙 |
|---|---|
| internal_complex_id | 단지 요약의 internal_complex_id 그대로 보존 |
| kapt_code | apartment_match_log의 명시적 연결 |
| complex_name | complex_name |
| address | road_address 우선, 없으면 legal_address |
| legal_dong | dong (통·반 정보는 없음) |
| households | households |
| latitude / longitude | latitude / longitude |
| legal_address / jibun | kapt_clean의 동일 컬럼 |

`kapt_clean`에는 internal_complex_id가 없고, 단지 요약에는 kapt_code 및 legal_address가 없다.
`src/match_complex.py`는 K-apt 매칭 시 internal_complex_id=kapt_code,
미매칭 시 TRAD 계열 ID를 생성한다. 기존 match log에서 이 규칙을 검증한 뒤
새로 추가하는 K-apt에만 같은 ID 규칙을 적용한다. 비 K-apt ID를 재계산하지 않는다.

기존 데이터에는 학군용 data_year와 원수집 provenance가 없다. 파일 수정일을 기준연도로
둔갑시키지 않고 data_year=결측, manual_review=True로 기록한다. 입력 SHA256,
검사시각과 파일명을 보관한다. 검사시각은 원자료 수집일이 아니다.

## 기존 실행 구조와 재사용 범위

기존 main.py는 argparse, src/pipeline.py는 수집·정제·매칭·집계를 담당한다.
app.py는 processed 파일을 읽는다. src/geocode_kakao.py는 Kakao Local 주소검색,
도로명→지번 후보, timeout/retry 및 영속 캐시를 사용한다. 기존 geocode_kapt는
기존 월 패널까지 갱신하므로 호출하지 않는다. 학교용 수집/캐시는 독립 구현한다.
Python 환경은 기존 .venv의 실행 파일을 검증에만 활용하며 패키지를 변경하지 않는다.

## 신규 파일과 구현 순서

1. Phase 1: `src/inspect_apartments.py`, `reports/existing_project_schema.json`,
   `reports/phase1_statistics.csv`, `data/interim/apartment_master.parquet`.
2. Phase 2: `config/schoolinfo_codes.csv`, 공식 명세에 근거한 필드 매핑,
   `src/collect_schoolinfo.py`, `src/clean_school.py`, `src/geocode_school.py`,
   `main.py`, `schools.parquet`, 원본 응답/메타데이터, 수집 품질보고서 및 테스트.
3. Phase 3: 진학현황 실제 제공 경로와 응답 확인 후 collect/clean_advancement,
   score_middle_school 구현. 공식 API 출력 Excel/목록에 졸업생 진로 항목이
   현재 보이지 않으므로 존재하지 않는 apiType/필드를 추측하지 않는다.
4. Phase 4: 해운대 공식 통학구역·중입배정 문서 확보, 지원청별 adapter와 검수 CSV.
5. Phase 5: 센텀초·센텀중 관계를 원문으로 검증하고 재송동/센텀 단지와 연결.
6. Phase 6: 나머지 네 지원청 adapter 확장. 연도 혼합을 차단.
7. Phase 7: 공식명시→주소/통·반→도로명/지번→수동보정→거리추정 순서로 매칭.
   fuzzy는 근거와 점수를 보존하고 검수한다. 초→중 many-to-many와 조건을 유지한다.
   아파트 최종 interface는 internal_complex_id별 1행, 상세 후보는 별도 테이블로 둔다.
8. Phase 8: 검증된 parquet에 기반한 Streamlit/Plotly 지도·필터 화면.
9. Phase 9: 단계별 테스트를 합쳐 통합 pytest, 연도·누락·확정/추정 품질 검증.

단계별 실제 데이터가 검증되기 전에 전체 점수/대시보드를 대량 생성하지 않는다.
기본정보 API는 연도 요청 인자가 없으므로 수집연도 스냅샷으로 관리한다.
과거 기본정보를 현재 응답으로 소급 생성하지 않는다.
