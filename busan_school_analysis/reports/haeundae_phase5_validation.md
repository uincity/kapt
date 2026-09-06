# 해운대교육지원청 Phase 5 검증 보고서

## A. Phase 5 개요

2025 통학구역의 센텀초 전체, 재송1·2동 단지명, 괄호 없는 두 검수 단지를 비교했다. 현재 K-apt 및 학교 좌표는 2025 당시 주소를 보증하지 않는다. 법정동은 행정동/통·반 확정 근거가 아니다. CONFIRMED는 공식 주소 확인 또는 근거 있는 confirmed override에만 부여한다. 점수 집계는 하지 않는다.

## B. 기존 Phase 4 REVIEW 7건 처리 결과

| review_id | elementary_school_name | raw_segment | resolved | resolution_method | candidate_complex_name | reviewer_note |
| --- | --- | --- | --- | --- | --- | --- |
| P5-036-01 | 장산초 | 10통 4반 일부[15-32번지(삼어로 38)] | False | unresolved | None | 원문 보존. 일부/제외 경계와 주소의 확정 대응 미확보 |
| P5-037-04 | 재송초 | 센텀천일스카이원 | False | contextual_candidate | 센텀천일스카이원 | 단지명 후보 및 법정동 확인. 통·반과 2025 적용 주소 근거 미확보 |
| P5-045-02 | 해동초 | 26~28통(해운대초 통학구역 외 일부) | False | unresolved | None | 원문 보존. 일부/제외 경계와 주소의 확정 대응 미확보 |
| P5-047-08 | 해림초 | 센텀미진이지비아 | False | contextual_candidate | 해운대센텀미진이지비아아파트 | 단지명 후보 및 법정동 확인. 통·반과 2025 적용 주소 근거 미확보 |
| P5-049-04 | 해송초 | 13통 1반 일부[798-4, 800-1,6,9, 10,11,12,13,14,15,16,17,19, 801-2,6,11, 806, 806-1,2,5,6,7,8번지] (좌동순환로446번길 15-6,15-7,15-8,15-9,15-10,15-13, 15-14,15-16,17-1, 좌동순환로468번길 21-8, 21-10, 21-12, 23,24-4,24-5,25,26,28-5,28-8,30,34) | False | unresolved | None | 원문 보존. 일부/제외 경계와 주소의 확정 대응 미확보 |
| P5-050-06 | 해운대초 | 32통(산114-1번지 제외) | False | unresolved | None | 원문 보존. 일부/제외 경계와 주소의 확정 대응 미확보 |
| P5-051-04 | 해운대초 | 13통1반 일부(1774-5, 1775-7, 1777-1, 1777-4, 1780-7, 1780-9번지) | False | unresolved | None | 원문 보존. 일부/제외 경계와 주소의 확정 대응 미확보 |

## C. 통학구역 아파트명 → K-apt 매칭 결과

차수 충돌은 제외한다. 후보가 여럿이면 첫 후보를 확정하지 않는다.

| elementary_school_name | raw_apartment_name | complex_name | internal_complex_id | name_score | address_score | viable_candidate_count | match_method | match_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 센텀초 | 센텀파크1차 | 더샵센텀파크1차 | A61271204 | 0.975 | 0.8 | 1 | fuzzy_supported | REVIEW |
| 센텀초 | 센텀파크2차 | 더샵센텀파크2차 | A61271302 | 0.975 | 0.8 | 1 | fuzzy_supported | REVIEW |
| 센텀초 | 센텀스타 | 더샵센텀스타 | A61205003 | 0.9667 | 0.8 | 1 | fuzzy_supported | REVIEW |
| 송수초 | 센텀e편한세상 | 센텀이편한세상 | A61286403 | 0.8571 | 0.8 | 1 | contextual_candidate | REVIEW |
| 송수초 | 센텀피오레1차 | 센텀피오레1차 | A61281512 | 1.0 | 0.8 | 1 | fuzzy_supported | REVIEW |
| 송수초 | 센텀협성르네상스 | 센텀협성르네상스타운 | A61288701 | 0.98 | 0.8 | 2 | contextual_candidate | REVIEW |
| 송수초 | 센텀계룡리슈빌 | None | None | 0.0 | 0.0 | 0 | unresolved | UNRESOLVED |
| 신재초 | 금호아파트 | 금호 | A61283208 | 1.0 | 0.8 | 1 | fuzzy_supported | REVIEW |
| 재송초 | 동부센트레빌 | 센텀동부센트레빌 | A61205002 | 0.975 | 0.8 | 1 | fuzzy_supported | REVIEW |
| 재송초 | 센텀천일스카이원 | 센텀천일스카이원 | A10024903 | 1.0 | 0.8 | 1 | contextual_candidate | REVIEW |
| 해림초 | 센텀미진이지비아 | 해운대센텀미진이지비아아파트 | A10024806 | 0.9727 | 0.8 | 1 | contextual_candidate | REVIEW |

## D. 센텀초 상세 validation

| raw_catchment_text | raw_apartment_name | complex_name | internal_complex_id | households | apartment_address | distance_m | match_method | confidence | match_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 19～22통(센텀파크1, 2차), 26통(센텀스타) | 센텀파크1차 | 더샵센텀파크1차 | A61271204 | 2752.0 | 부산광역시 해운대구 센텀중앙로 145 | 531.8 | fuzzy_supported | medium | REVIEW |
| 19～22통(센텀파크1, 2차), 26통(센텀스타) | 센텀파크2차 | 더샵센텀파크2차 | A61271302 | 998.0 | 부산광역시 해운대구 센텀중앙로 142 | 241.4 | fuzzy_supported | medium | REVIEW |
| 19～22통(센텀파크1, 2차), 26통(센텀스타) | 센텀스타 | 더샵센텀스타 | A61205003 | 629.0 | 부산광역시 해운대구 센텀동로 123 | 523.1 | fuzzy_supported | medium | REVIEW |

## E. 500세대 이상 관련 아파트

후보 관계도 포함하는 검증 view이며 확정 학군 목록이 아니다. 작은 단지는 전체 파일에 유지한다.

| elementary_school_name | internal_complex_id | complex_name | households | match_status |
| --- | --- | --- | --- | --- |
| 센텀초 | A61271204 | 더샵센텀파크1차 | 2752.0 | REVIEW |
| 센텀초 | A61271302 | 더샵센텀파크2차 | 998.0 | REVIEW |
| 센텀초 | A61205003 | 더샵센텀스타 | 629.0 | REVIEW |
| 송수초 | A61286403 | 센텀이편한세상 | 1190.0 | REVIEW |
| 송수초 | A61281512 | 센텀피오레1차 | 774.0 | REVIEW |
| 재송초 | A61205002 | 센텀동부센트레빌 | 703.0 | REVIEW |

## F. 초등학교 → 중학교 관계

| elementary_school_name | middle_school_name | assignment_type | assignment_certainty | gender_condition | guaranteed_assignment | middle_school_score | score_reference_year |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 센텀초 | 반안중 | group_membership | group_only | coed | False | 16.294117647058826 | 2025.0 |
| 센텀초 | 인지중 | group_membership | group_only | coed | False | 71.11764705882354 | 2025.0 |
| 센텀초 | 반여중 | group_membership | group_only | coed | False | 32.73529411764706 | 2025.0 |
| 센텀초 | 장산중 | group_membership | group_only | coed | False | 56.823529411764696 | 2025.0 |
| 센텀초 | 센텀중 | group_membership | group_only | coed | False | 98.91176470588236 | 2025.0 |
| 센텀초 | 재송중 | group_membership | group_only | male | False | 18.88235294117647 | 2025.0 |
| 센텀초 | 재송여중 | group_membership | group_only | female | False | 27.117647058823525 | 2025.0 |
| 센텀초 | 장산중 | general_priority | conditional_not_guaranteed | all | False | 56.823529411764696 | 2025.0 |
| 센텀초 | 재송중 | general_priority | conditional_not_guaranteed | male | False | 18.88235294117647 | 2025.0 |
| 센텀초 | 재송여중 | general_priority | conditional_not_guaranteed | female | False | 27.117647058823525 | 2025.0 |
| 송수초 | 반안중 | group_membership | group_only | coed | False | 16.294117647058826 | 2025.0 |
| 송수초 | 인지중 | group_membership | group_only | coed | False | 71.11764705882354 | 2025.0 |
| 송수초 | 반여중 | group_membership | group_only | coed | False | 32.73529411764706 | 2025.0 |
| 송수초 | 장산중 | group_membership | group_only | coed | False | 56.823529411764696 | 2025.0 |
| 송수초 | 센텀중 | group_membership | group_only | coed | False | 98.91176470588236 | 2025.0 |
| 송수초 | 재송중 | group_membership | group_only | male | False | 18.88235294117647 | 2025.0 |
| 송수초 | 재송여중 | group_membership | group_only | female | False | 27.117647058823525 | 2025.0 |
| 송수초 | 장산중 | general_priority | conditional_not_guaranteed | all | False | 56.823529411764696 | 2025.0 |
| 송수초 | 재송중 | general_priority | conditional_not_guaranteed | male | False | 18.88235294117647 | 2025.0 |
| 송수초 | 재송여중 | general_priority | conditional_not_guaranteed | female | False | 27.117647058823525 | 2025.0 |
| 송수초 | 센텀중 | preference | conditional_not_guaranteed | all | False | 98.91176470588236 | 2025.0 |
| 송수초 | 장산중 | preference | conditional_not_guaranteed | all | False | 56.823529411764696 | 2025.0 |
| 신재초 | 반안중 | group_membership | group_only | coed | False | 16.294117647058826 | 2025.0 |
| 신재초 | 인지중 | group_membership | group_only | coed | False | 71.11764705882354 | 2025.0 |
| 신재초 | 반여중 | group_membership | group_only | coed | False | 32.73529411764706 | 2025.0 |
| 신재초 | 장산중 | group_membership | group_only | coed | False | 56.823529411764696 | 2025.0 |
| 신재초 | 센텀중 | group_membership | group_only | coed | False | 98.91176470588236 | 2025.0 |
| 신재초 | 재송중 | group_membership | group_only | male | False | 18.88235294117647 | 2025.0 |
| 신재초 | 재송여중 | group_membership | group_only | female | False | 27.117647058823525 | 2025.0 |
| 신재초 | 반여중 | general_priority | conditional_not_guaranteed | female | False | 32.73529411764706 | 2025.0 |
| 재송초 | 반안중 | group_membership | group_only | coed | False | 16.294117647058826 | 2025.0 |
| 재송초 | 인지중 | group_membership | group_only | coed | False | 71.11764705882354 | 2025.0 |
| 재송초 | 반여중 | group_membership | group_only | coed | False | 32.73529411764706 | 2025.0 |
| 재송초 | 장산중 | group_membership | group_only | coed | False | 56.823529411764696 | 2025.0 |
| 재송초 | 센텀중 | group_membership | group_only | coed | False | 98.91176470588236 | 2025.0 |
| 재송초 | 재송중 | group_membership | group_only | male | False | 18.88235294117647 | 2025.0 |
| 재송초 | 재송여중 | group_membership | group_only | female | False | 27.117647058823525 | 2025.0 |
| 재송초 | 반여중 | general_priority | conditional_not_guaranteed | female | False | 32.73529411764706 | 2025.0 |
| 해림초 | None | unresolved | unresolved | None | False | nan | nan |

## G. 센텀초 → 센텀중 판정 결과

현재 상태: **group_only**. 2025 시행계획 일반우선배정 표의 센텀초 14학교군과 학교군 HTML의 센텀중 포함을 연결한 참고 관계다. 개별 지원자격/배정 확정이 아니다. 센텀초 일반우선배정 명시 후보는 장산중·재송중·재송여중이다.

근거: [시행계획 게시물](https://home.pen.go.kr/haeundae/na/ntt/selectNttInfo.do?mi=11419&bbsId=3550&nttSn=879684) 첨부 PDF 인쇄 26쪽 기타1 및 [학교군 안내](https://home.pen.go.kr/haeundae/cm/cntnts/cntntsView.do?cntntsId=253&mi=11431). 학교군 HTML 적용연도 미표시로 temporal_review를 저장한다.

## H. unresolved/manual_review 목록

| elementary_school_name | raw_apartment_name | match_method | match_status |
| --- | --- | --- | --- |
| 센텀초 | 센텀파크1차 | fuzzy_supported | REVIEW |
| 센텀초 | 센텀파크2차 | fuzzy_supported | REVIEW |
| 센텀초 | 센텀스타 | fuzzy_supported | REVIEW |
| 송수초 | 센텀e편한세상 | contextual_candidate | REVIEW |
| 송수초 | 센텀피오레1차 | fuzzy_supported | REVIEW |
| 송수초 | 센텀협성르네상스 | contextual_candidate | REVIEW |
| 송수초 | 센텀계룡리슈빌 | unresolved | UNRESOLVED |
| 신재초 | 금호아파트 | fuzzy_supported | REVIEW |
| 재송초 | 동부센트레빌 | fuzzy_supported | REVIEW |
| 재송초 | 센텀천일스카이원 | contextual_candidate | REVIEW |
| 해림초 | 센텀미진이지비아 | contextual_candidate | REVIEW |

기존 검수 7건은 review_resolution CSV에 보존한다. 괄호 없는 두 이름은 법정동 수준 주소만 확인되어 contextual_candidate다.

## I. 데이터 품질 지표

```json
{
  "raw_apartment_names": 11,
  "validation_rows": 11,
  "candidate_search_success_rate": 0.9090909090909091,
  "match_status": {
    "CONFIRMED": 0,
    "REVIEW": 10,
    "UNRESOLVED": 1
  },
  "match_methods": {
    "official_exact": 0,
    "normalized_exact": 0,
    "fuzzy_supported": 6,
    "contextual_candidate": 4,
    "contextual_supported": 0,
    "manual_override": 0,
    "unresolved": 1
  },
  "manual_override_count": 0,
  "address_support_rate": 0.9090909090909091,
  "official_confirmed_rate": 0.0,
  "households_500plus_rows": 6,
  "households_500plus_confirmed_rate": 0.0,
  "unknown_households": 1,
  "spatial_outlier_count": 0,
  "relation_counts": {
    "exact": 0,
    "eligible": 0,
    "group_only": 28,
    "conditional_not_guaranteed": 10,
    "unresolved": 1
  },
  "centum_middle_status": "group_only",
  "review_total": 7,
  "review_resolved": 0
}
```

비율 분모는 validation_rows(단지명×초등학교)다. 500세대 비율은 세대수 확인 view 행이 분모다. 유사도 0.72 이상 후보를 보존한다. name_score는 확률이 아니며 주소점수 0.8은 법정동 보조근거다.

## J. Phase 6 확대 적용 가능 여부

검수용 후보 생성은 확대 가능하다. 자동 확정은 공식 주소/통·반·연도 근거 보강 후 진행한다.

## K. Phase 6 전에 수정해야 할 규칙

- 행정동↔법정동 후보 변환 휴리스틱을 공식 코드·경계 자료로 교체한다.
- Phase 4 중입 PDF의 고정 학교명 표 추출을 변경 fixture로 검증하고 원문/페이지 해시를 연결한다.
- 복합 통, 번지, 동호수 조건을 명시 문법으로 파싱한다.
- 별칭·브랜드·차수 차이는 주소 근거와 분리하고 여러 후보를 자동 축약하지 않는다.
- 2025 적용 자료와 현재 K-apt/학교군 스냅샷의 시간 차이를 보완한다.
- 검증된 학교 ID 매핑을 유지하고 group_only를 eligible/exact로 승격하지 않는다.
