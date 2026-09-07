# Phase 6.5 validation

**READY**

## A. 좌표 누락 원인

초기 누락 3,053개는 K-apt 미연결 거래 단지이며 공식 실거래 주소를 복원했다.

## B. 좌표 재사용 및 지오코딩

기존 1,468개, 재사용 0개, 주소 검증 통과 3,050개, 중복좌표 검토 제외 후 신규 확정 3,050개.
좌표 source별 건수: KAKAO_ROAD: 2,722, KAPT_EXISTING: 1,468, KAKAO_LOT: 328.

| candidate_type | attempts | API result | confirmed | confirmed rate |
|---|---:|---:|---:|---:|
| LOT_ADDRESS | 677 | 674 | 674 | 99.56% |
| NAME_ADDRESS | 638 | 571 | 0 | 0.00% |
| ROAD_ADDRESS | 3,053 | 2,725 | 2,722 | 89.16% |

## C. 전체 좌표 커버리지

1,468/4,521 (32.47%) → 4,518/4,521 (99.93%)

## D. 500세대 이상 좌표 커버리지

560/560 → 560/560 (100.00%)

## E. 공식 학구도 공간매칭

경계 포함 단지 1,466개 → 4,512개, 신규 3,046개. 공간관계 1,484건 → 4,536건, 신규 3,052건. 경계 밖 6개.

| internal_complex_id | complex_name | distance_m |
|---|---|---:|
| A60476805 | 현대 | 18.0 |
| A61409006 | 솔내음파미유 | 21.7 |
| TRADE_1748CEF5F4F1 | 글로벌빌라트 | 17.3 |
| TRADE_489639814B84 | 문화파크 | 79.9 |
| TRADE_881B7692D27A | 삼성비치타운 | 81.3 |
| TRADE_FE1B3F77D36A | 동남주상복합 | 20.8 |

## F. REVIEW/UNRESOLVED

{"REVIEW": 3}

| internal_complex_id | complex_name | status | reason |
|---|---|---|---|
| TRADE_6424A16E4B38 | 아시아드코오롱하늘채 | REVIEW | legal_dong_mismatch |
| TRADE_8B8529FBDEAE | 대동맨션 | REVIEW | legal_dong_mismatch |
| TRADE_924B1EA84CE9 | 안락시영(충렬) | REVIEW | legal_dong_mismatch |

## G. 근거 병합

공동통학 many-to-many를 유지한 최종 관계 4,537건. 기존 직접 근거는 삭제하지 않고 `evidence_types`에 병합했다.

## H. 제한

학구도 경계에는 법정동·행정동 경계가 없어 해당 공간 일치값을 추정하지 않았다. Kakao 반환 법정동/행정동 코드는 주소 검증 근거로 별도 보존했다.

## I. Phase 7 진행 가능 여부

**READY** — 500세대 이상 좌표 커버리지 기준으로 판정했다. Phase 7은 자동 시작하지 않는다.