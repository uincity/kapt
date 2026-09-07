# Phase 6 validation

## A. Phase 6 개요

학구도안내서비스가 공개한 2025-09-22 공식 공간 경계를 부산 5개 교육지원청의 초등 통학구역 원천으로 적용했다. 공간자료 구축은 **READY**이며, 전체 아파트 학군 산출은 좌표 누락 때문에 **READY_WITH_REVIEW**이다.

## B. Phase 5 보완점별 해결 결과

| 항목 | 판정 |
|---|---|
| 학구도안내서비스 2025-09-22 공식 경계 적용 | PASS |
| 경계-학교 연계표 학구 ID 전수 연결 | PASS |
| 행정동-법정동 공식 crosswalk 구축 | PASS |
| 경계자료의 행정동 코드 부재 명시 | REVIEW |
| 현재 K-apt 주소의 2025 temporal mismatch flag 적용 | PASS |
| 복합 통·반·번지 및 제외조건 parser 적용 | PASS |
| 괄호 없는 단지명 grammar 적용 | PASS |
| 브랜드/별칭/차수 evidence와 주소 evidence 분리 | PASS |
| 중입 PDF parser table-based 구조 적용 | PASS |
| 학교군 적용연도 evidence 저장 | PASS |
| middle school score를 school_id 기준으로 연결 | PASS |

## C. 공식 공간자료

2025-09-22 기준 부산 초등 통학구역 309개와 학교 연계 324건을 보존했다. 일반 경계와 공동통학 경계를 구분하며 EPSG:5186 원 좌표계를 GeoParquet에 기록했다.

## D. 행정동-법정동 crosswalk

행정안전부 KiKmix 2025-11-03 공식 원천으로 부산 유효 관계 361건을 구축했다. 학구도 경계에는 행정동·법정동 코드가 없으므로 공간 매칭 결과에 코드가 없는 상태를 명시하며 추정하지 않았다.

## E. 과거/현재 아파트 주소 처리

현재 K-apt snapshot은 2025 주소로 간주하지 않는다. 현재 검증 좌표로 4,512개가 공식 경계에 포함됐고 6개는 경계 밖 검토로 보냈다. 좌표 미확정 3개도 결과에서 제외하지 않고 `COORDINATE_MISSING`으로 보존했다.

## F. Catchment Parser v2 결과

기존 텍스트 컴포넌트 문법은 유지한다. 부산 전체 판정의 우선 근거는 공식 폴리곤과 학교-학구도 연계표이다.

## G. Middle Assignment PDF Parser v2

5개 지원청 공식 2025 시행계획에서 PDF layout/HWPX table header를 모두 탐지했다. 전체 중입 관계 행 추출은 후속 작업이다.

## H. school_id 기반 relation

공식 학구 ID와 외부 학교 ID를 원형 보존하고, 2026 학교 마스터의 활성 학교명으로 내부 ID 324건을 연결했다. 2025 휴교 표기 1건은 상태 불일치 검토 대상으로 유지했다.

## I. 교육지원청별 품질 비교

| office | elementary_count | boundary_count | parsed_rate | admin_code_match_rate | matched_apartment_count | middle_relation_rate | school_id_match_rate | manual_review_count | source_year_verified | status |
|---|---|---|---|---|---|---|---|---|---|---|
| haeundae | 65 | 66 | 1.0 | 0.0 | 942 | 0.0 | 1.0 | 0 | True | OFFICIAL_BOUNDARY_READY |
| dongnae | 61 | 56 | 1.0 | 0.0 | 1184 | 0.0 | 1.0 | 0 | True | OFFICIAL_BOUNDARY_READY |
| nambu | 61 | 57 | 1.0 | 0.0 | 1002 | 0.0 | 1.0 | 1 | True | OFFICIAL_BOUNDARY_READY |
| bukbu | 75 | 76 | 1.0 | 0.0 | 450 | 0.0 | 1.0 | 0 | True | OFFICIAL_BOUNDARY_READY |
| seobu | 56 | 54 | 1.0 | 0.0 | 934 | 0.0 | 1.0 | 0 | True | OFFICIAL_BOUNDARY_READY |

## J. 부산 전체 apartment-elementary 결과

공식 경계로 아파트-초등학교 관계 4,536건을 생성했다. 공동통학구역은 아파트 한 곳에 여러 학교 관계를 그대로 보존한다.

## K. 부산 전체 elementary-middle 결과

공식 2025 시행계획의 파일 구조 검증은 완료했다. 관계 행 추출과 초등-중학교 ID 연결은 후속 작업이다.

## L. unresolved/manual_review

좌표 미확정 3개, 경계 밖 6개, 2025 휴교/2026 활성 상태 불일치 1건을 수동검토 대상으로 남겼다.

## M. Phase 7 진행 가능 여부

**READY_WITH_REVIEW** — 공식 초등 통학구역 관계를 분석할 수 있다. 좌표 미확정 3개와 중입 관계 행 추출은 후속 검토 대상이다.