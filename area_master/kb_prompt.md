# 프로젝트: KB부동산 기반 아파트 평형별 세대수·면적·KB시세 수집 자동화

## 0. 최종 목표

기존 보완 대상 아파트 목록을 기준으로 각 아파트 단지의 다음 정보를 자동 수집한다.

필수 수집 정보:

- kapt_code
- 단지명
- KB complex ID
- KB 단지명
- 평형/type_name
- 타입별 세대수
- 공급면적
- 전용면적
- KB 매매시세
- KB 전세시세
- 매물건수
- 가능하면 KB 월세시세
- KB 시세 기준일
- source URL
- 수집일

최종적으로 기존:

config/market_cap_area_master.csv

형식에 맞는 평형별 세대수 마스터를 생성한다.

입력 대상 목록:

supplement_2026-08.csv

작업 방식은 기존의 건축HUB 세대별 대량조회 방식이 아니라,

K-apt
→ KB 단지 검색
→ KB complex ID 매칭
→ KB 평형별 집계 데이터 수집
→ 검증
→ 정상 데이터 자동 확정
→ 예외만 pending

구조로 변경한다.

건축HUB의 개별 세대 조회는 전체 단지에 사용하지 않는다.

건축HUB/건축물대장은 KB만으로 해결되지 않는 예외 단지의 fallback 용도로만 남긴다.


==================================================
1. 작업 시작 전에 반드시 기존 프로젝트 분석
==================================================

먼저 현재 repository 전체 구조를 확인한다.

특히 다음 파일을 확인한다.

config/market_cap_area_master.csv
supplement_2026-08.csv

실제 CSV 컬럼을 직접 읽고 확인한다.

기존 프로젝트에 다음과 관련된 코드가 있는지도 검색한다.

- K-apt API
- apartment master
- market_cap
- area master
- buildinghub
- playwright
- selenium
- KB부동산
- scraping
- apartment matching
- logging

기존 기능이 있으면 가능한 한 재사용한다.

기존 CSV의 컬럼은 임의로 삭제하거나 변경하지 않는다.


==================================================
2. 전체 실행 전략
==================================================

작업은 다음 단계로 진행한다.

PHASE 1
프로젝트 및 입력 데이터 분석

PHASE 2
K-apt 기본정보 확보

PHASE 3
KB 로그인 브라우저 구현

PHASE 4
"대연SK뷰힐스" 1개 단지 파일럿

PHASE 5
파일럿 자동 검증

PHASE 6
파일럿 성공 시 나머지 대상 단지 자동 진행

PHASE 7
검증 / pending 분리

PHASE 8
market_cap_area_master.csv 생성

파일럿이 성공하지 않은 상태에서 전체 단지로 확대하지 않는다.

다만 파일럿 검증 조건이 모두 PASS하면 별도의 사용자 확인을 기다리지 말고
나머지 대상 단지 처리를 자동으로 계속 진행한다.


==================================================
3. 파일럿 대상
==================================================

첫 파일럿 단지는 반드시:

대연SK뷰힐스

로 한다.

supplement_2026-08.csv에서 해당 단지를 찾아 실제:

- kapt_code
- 단지명
- 법정동
- 도로명주소
- 총세대수
- 사용승인일
- 분양형태

정보를 확보한다.

단지명을 코드에 임의 하드코딩하는 것이 아니라
CSV의 실제 행을 찾아 사용한다.


==================================================
4. K-apt를 단지 identity 기준으로 사용
==================================================

대상 단지마다 가능하면 다음 K-apt 정보를 확보한다.

- kapt_code
- kapt_name
- legal_dong_name
- legal_dong_code
- road_address
- jibun_address
- total_households
- approval_date
- sale_type

K-apt는 평형별 상세 면적을 가져오기 위한 용도가 아니다.

K-apt의 역할은:

"이 단지가 정확히 어떤 아파트인가"

를 판별하기 위한 master identity 및 검증 기준이다.


==================================================
5. KB 로그인 방식
==================================================

KB부동산은 로그인 상태에서 원하는 평형 정보가 더 잘 표시되므로
Playwright persistent browser context 방식을 사용한다.

아이디 / 비밀번호를 코드에 저장하지 않는다.

첫 실행:

1. Chromium/Chrome을 headless=False 상태로 실행
2. KB부동산 페이지 이동
3. 사용자가 직접 정상적인 방법으로 로그인
4. 로그인 완료 여부 확인
5. persistent browser profile 저장

예:

data/browser/kb_profile/

개념적으로:

chromium.launch_persistent_context(
    user_data_dir="data/browser/kb_profile",
    headless=False
)

형태를 사용한다.

다음 실행부터 같은 프로필을 사용하여
기존 로그인 세션을 재사용한다.

세션이 만료되었으면:

[LOGIN REQUIRED]

상태를 화면에 표시하고
사용자가 다시 로그인할 수 있도록 브라우저를 띄운다.

아이디/비밀번호 자동 입력,
CAPTCHA 우회,
인증 우회,
자동화 방지 우회 기능은 만들지 않는다.

KB 서비스의 접근 제한과 이용조건을 준수한다.


==================================================
6. KB 데이터 수집 방식의 우선순위
==================================================

KB 단지 페이지에서 평형 정보를 수집할 때 다음 순서를 따른다.

1순위
로그인된 브라우저가 정상적인 화면 표시 과정에서 수신하는
Fetch/XHR의 구조화된 JSON 응답

2순위
페이지 내부에서 사용하는 구조화 데이터 / application state

3순위
DOM에 표시된 평형선택 UI

DOM scraping부터 바로 구현하지 않는다.

먼저 대연SK뷰힐스 단지 한 곳에서
평형선택 메뉴를 열 때 발생하는 정상적인 Fetch/XHR 응답을 조사한다.

목표 데이터:

- KB complex ID
- 평형 type ID
- type_name
- households
- supply_area_sqm
- exclusive_area_sqm
- KB sale price
- KB jeonse price
- KB monthly-rent data if available
- KB price 기준일

구조화된 응답에 해당 데이터가 존재하면
가능하면 이를 사용한다.

단, KB 인증을 우회하거나
브라우저 외부에서 인증 토큰을 탈취/재사용하는 방식으로 구현하지 않는다.

로그인된 정상 Playwright 세션 안에서 처리한다.


==================================================
7. KB 단지 검색의 핵심 원칙
==================================================

K-apt 단지명과 KB 단지명은 정확히 일치하지 않을 수 있다.

따라서 exact string 검색만 사용하면 안 된다.

기본 검색어는:

법정동명 + K-apt 단지명

으로 한다.

예:

대연동 대연SK뷰힐스

용호동 LG메트로시티1차

문현동 OO아파트


==================================================
8. 검색어 생성 전략
==================================================

대상 단지마다 여러 검색어 후보를 생성한다.

우선순위:

QUERY 1

{동명} {원본 K-apt 단지명}

QUERY 2

{동명} {정규화 단지명}

QUERY 3

{구명} {동명} {정규화 단지명}

QUERY 4

{동명} {핵심 단지명}

단, 검색 결과가 이미 충분히 확보되면
불필요한 추가 검색을 하지 않는다.


==================================================
9. 단지명 normalization
==================================================

검색용 normalization과 검증용 normalization을 구분한다.

검색용에서는 다음 정도를 허용한다.

- 연속 공백 제거
- 앞뒤 공백 제거
- 괄호 표현 정리
- 영문 대소문자 통일
- 특수문자 정리
- "아파트", "APT" 등의 일반 접미사 차이를 어느 정도 허용
- "제1차" ↔ "1차"
- 로마숫자 등 명백한 표기 차이 정규화

그러나 다음 정보는 절대 제거하면 안 된다.

- 1차 / 2차 / 3차 / 5차
- 1단지 / 2단지
- 센트럴 / 더샵 / 퍼스트 / 스카이 등 단지 구분어
- SK뷰 / 자이 / 롯데캐슬 등 핵심 브랜드
- 동/서/남/북 단지 구분
- A/B단지 등 실제 단지를 구별하는 토큰

예:

LG메트로시티1차
LG메트로시티2차
LG메트로시티5차

를 모두

LG메트로시티

로 만들어 자동 확정하면 안 된다.


==================================================
10. KB 검색 결과는 절대 첫 번째 항목 자동 선택 금지
==================================================

검색 결과가 나오면
첫 번째 결과를 즉시 선택하지 않는다.

상위 후보 여러 개를 수집한다.

각 후보에서 가능한 한 다음 정보를 확보한다.

- kb_complex_id
- kb_name
- address
- legal_dong
- road_address
- total_households
- completion/approval year if available
- KB 상세페이지 URL

검색 결과에서 정보가 부족하다면
후보의 상세페이지까지 최소한으로 조회하여 검증한다.


==================================================
11. kapt_code ↔ KB complex ID 매칭
==================================================

최종 단지 매칭은 이름 하나로 결정하지 않는다.

다음 정보를 종합한다.

가장 중요한 기준:

1. 법정동 일치
2. 주소 일치
3. 총세대수 일치
4. 단지명 유사도
5. 사용승인/준공 시점 일치

권장 내부 점수 예시:

법정동 정확히 일치         +30
도로명 주소 정확히 일치    +40
지번 핵심값 일치           +40
총세대수 정확히 일치       +25
정규화 단지명 정확히 일치  +20
단지명 높은 유사도         +10~18
사용승인 연도 일치         +10

실제 데이터 특성을 보고 점수는 조정할 수 있다.

하지만 점수만으로 처리하지 말고 HARD RULE도 적용한다.


==================================================
12. KB 단지 매칭 HARD RULE
==================================================

다음 조건을 적용한다.

CASE A

주소 일치
+
총세대수 일치

→ 매우 높은 confidence
→ 자동 확정 가능


CASE B

동 일치
+
단지명 매우 유사
+
총세대수 일치

→ 높은 confidence
→ 자동 확정 가능


CASE C

동 일치
+
이름만 비슷함
+
세대수 불일치

→ 자동 확정 금지
→ pending


CASE D

단지명 동일
+
주소 또는 동 불일치

→ 자동 확정 금지


CASE E

동일 브랜드/단지의 여러 차수 존재

예:

LG메트로시티1차
LG메트로시티2차
LG메트로시티3차

→ 주소 + 세대수 + 차수 정보 확인 전까지 자동 확정 금지


CASE F

상위 후보 2개가 거의 같은 score

→ 임의 선택 금지
→ pending


==================================================
13. 매칭 confidence 상태
==================================================

매칭 결과에 다음 상태를 둔다.

exact
high
medium
low
unmatched

자동 수집 가능한 것은 기본적으로:

exact
high

만 사용한다.

medium / low / unmatched는 검토 대상이다.

다만 기준은 코드 내 명확한 상수/설정값으로 분리한다.


==================================================
14. KB complex ID 매핑 캐시
==================================================

단지를 한 번 정확히 찾았으면
향후에는 다시 이름으로 검색하지 않는다.

다음 파일을 만든다.

data/mapping/kb_complex_mapping.csv

컬럼 예:

kapt_code
kapt_name
legal_dong
kapt_address
kapt_households

kb_complex_id
kb_name
kb_address
kb_households
kb_url

match_score
match_confidence
match_method
verified_at

다음 실행부터:

kapt_code
→ kb_complex_id

매핑이 exact/high 상태로 존재하면
KB 검색을 생략하고 해당 complex ID의 상세페이지로 직접 이동한다.

사이트의 단지 ID가 변경되거나 페이지가 존재하지 않을 때만
재검색한다.


==================================================
15. 파일럿에서 평형선택 데이터 수집
==================================================

대연SK뷰힐스의 KB complex ID를 확정한 후
KB 단지 상세 페이지를 연다.

시세 화면에서:

"면적 / 평형 선택"

UI 또는 이에 대응하는 데이터 요청을 찾는다.

평형 목록 전체에서 최소 다음 값을 수집한다.

- type_name
- households
- supply_area_sqm
- exclusive_area_sqm

예:

24평
공급 80.61㎡
전용 59.99㎡
200세대

24평
공급 80.84㎡
전용 59.97㎡
26세대

29평
공급 98.86㎡
전용 74.29㎡
72세대

33평
공급 112.28㎡
전용 84.99㎡
425세대


==================================================
16. KB시세도 동시에 수집
==================================================

가능하면 각 면적유형별로 다음 시세를 수집한다.

매매:

- KB 일반가
- KB 상위평균가
- KB 하위평균가

전세:

- KB 일반가
- KB 상위평균가
- KB 하위평균가

월세:

- 보증금
- 월세 하한
- 월세 상한

가능한 범위에서 저장한다.

그리고 반드시:

- KB 시세 기준일
- collected_at

을 저장한다.

표시되지 않는 값은 추정하지 말고 빈칸으로 둔다.


==================================================
17. KB 원본 데이터는 별도 저장
==================================================

market_cap_area_master.csv로 바로 변환하지 않는다.

먼저 KB에서 가져온 원자료를 별도로 보존한다.

예:

data/raw/kb/kb_area_types.csv

권장 컬럼:

kapt_code
kapt_name

kb_complex_id
kb_complex_name
kb_url

kb_type_id
type_name

households
supply_area_sqm
exclusive_area_sqm

kb_sale_general
kb_sale_upper
kb_sale_lower

kb_jeonse_general
kb_jeonse_upper
kb_jeonse_lower

kb_monthly_deposit
kb_monthly_low
kb_monthly_high

kb_price_date
collected_at

source_method


==================================================
18. 전용면적 precision 매우 중요
==================================================

KB 화면에서 전용면적이 소수점 2자리까지만 표시될 수 있다.

예:

59.99
59.97
74.29
84.99

이 값을 임의로 더 정밀한 값으로 추정하지 않는다.

특히 다음 경우:

84A → 84.99
84B → 84.99

이라고 화면에 표시되더라도
실제 원 전용면적이:

84.9923
84.9948

처럼 다를 가능성이 있다.

따라서 화면상 동일한 84.99라고 해서
무조건 세대수를 합쳐서는 안 된다.


==================================================
19. 내부 JSON의 면적 정밀도 우선 확인
==================================================

화면에는 2자리만 보이더라도
Fetch/XHR JSON에 더 높은 정밀도 전용면적이 존재하는지 확인한다.

예:

displayArea = 84.99
actualExclusiveArea = 84.9923

같은 구조가 있으면
actual 값을 사용한다.

내부 데이터에서도 2자리 값만 존재한다면
그 값을 KB 원본 면적으로 저장하되
다른 type_name끼리 자동 병합하지 않는다.

즉:

type_name이 다름
+
KB 표시 전용면적 동일
+
원본 고정밀 면적 없음

이면:

자동 GROUP BY 금지

하고 필요하면 pending 처리한다.


==================================================
20. 동일 전용면적 A/B/C 합산 규칙
==================================================

정확한 원본 전용면적이 동일하다는 것이 확인된 경우만 합산한다.

예:

59A / 59.9794 / 120
59B / 59.9794 / 98
59C / 59.9842 / 50

결과:

59.9794 / 218
59.9842 / 50

반드시:

kapt_code
+
정확한 exclusive_area_sqm

기준으로 GROUP BY 한다.

다음을 절대 하지 않는다.

round(area, 2)

후 GROUP BY.


==================================================
21. area_group_id
==================================================

정확한 전용면적을 확보한 경우:

59.9794

→

exclusive_59_9794

84.99

→

exclusive_84_99

형태로 생성한다.

단지 내 unique 여부를 검증한다.


==================================================
22. KB 평형별 세대수 합계 검증
==================================================

단지 하나를 수집한 후:

sum(KB type households)

를 계산한다.

그리고:

K-apt total_households

와 비교한다.

예:

KB 합계 = 1,000
K-apt = 1,000

이면 강한 검증 근거이다.

그러나 다음 단지는 단순 합계 일치만으로 verified 하지 않는다.

- 임대 포함
- 장기전세 포함
- 공공임대 포함
- 분양 + 임대 혼합
- 오피스텔 혼합
- 기타 비매매 세대 포함


==================================================
23. sale_apartment scope
==================================================

최종 market_cap_area_master.csv의 scope는:

sale_apartment

이다.

따라서 모든 세대를 무조건 포함하면 안 된다.

K-apt 분양형태 등을 확인한다.

일반 분양 단지:
자동 검증 가능

혼합/임대 단지:
별도 검증 필요

불확실하면:

verification_status = pending

으로 둔다.


==================================================
24. 대연SK뷰힐스 파일럿 성공 조건
==================================================

대연SK뷰힐스에 대해 다음 조건을 모두 확인한다.

[PILOT CHECK 1]

supplement 파일에서 해당 단지의 kapt_code를 정확히 찾음

[PILOT CHECK 2]

K-apt 기본정보 확보 성공

[PILOT CHECK 3]

"대연동 + 대연SK뷰힐스" 검색으로 KB 후보 확보 성공
또는 합리적인 fallback 검색 성공

[PILOT CHECK 4]

KB complex ID를 high/exact confidence로 확정

[PILOT CHECK 5]

평형 선택 전체 목록 수집 성공

[PILOT CHECK 6]

각 타입의 households 수집 성공

[PILOT CHECK 7]

각 타입의 supply_area_sqm 수집 성공

[PILOT CHECK 8]

각 타입의 exclusive_area_sqm 수집 성공

[PILOT CHECK 9]

최소 KB 매매 일반가 수집 성공

[PILOT CHECK 10]

KB 평형별 세대수 합계와 K-apt 총세대수 검증 완료

[PILOT CHECK 11]

원본 KB 데이터 파일 저장 완료

[PILOT CHECK 12]

market_cap_area_master 형태의 변환 테스트 성공


==================================================
25. 파일럿 PASS / FAIL
==================================================

위 핵심 조건을 만족하면 화면에 명확하게:

========================================
PILOT SUCCESS
대연SK뷰힐스 수집 및 검증 완료
전체 단지 수집을 시작합니다.
========================================

를 출력한다.

그리고 자동으로 나머지 대상 단지를 처리한다.

사용자의 추가 확인을 기다리지 않는다.


파일럿이 실패하면:

========================================
PILOT FAILED
전체 단지 처리를 시작하지 않습니다.
========================================

를 출력한다.

그리고 다음 정보를 보여준다.

- 실패 단계
- 실패 원인
- 실제 KB 검색 결과
- 후보 단지
- match score
- 부족한 데이터
- 수정이 필요한 코드
- 권장 해결방법

파일럿 실패 상태에서는
560개 전체 작업으로 확대하지 않는다.


==================================================
26. 전체 수집 진행정보를 화면에 표시
==================================================

전체 실행 중 현재 진행상황이 반드시 보이게 한다.

단순히 로그파일에만 저장하지 않는다.

터미널 화면에 실시간 진행률을 출력한다.

rich 또는 tqdm 같은 라이브러리를 사용해도 좋다.

예:

[  1/560 |   0.2%] 대연SK뷰힐스
  K-apt       OK
  KB Search   OK
  KB Match    OK  score=115 confidence=exact
  KB Types    8 types
  Households  994 / K-apt 994  MATCH
  KB Prices   OK
  Result      VERIFIED
  elapsed     3.8s

[  2/560 |   0.4%] LG메트로시티1차
  K-apt       OK
  KB Search   OK
  KB Match    OK  score=105 confidence=high
  KB Types    10 types
  Households  2,637 / K-apt 2,637 MATCH
  KB Prices   OK
  Result      VERIFIED
  elapsed     4.2s

[  3/560 |   0.5%] ...

최소한 화면 상단 또는 하단에 전체 통계도 계속 갱신한다.

예:

TOTAL 560
PROCESSED 73
VERIFIED 64
PENDING 6
FAILED 3
REMAINING 487
ELAPSED 00:07:42
AVG/COMPLEX 6.3 sec


가능하면 ETA도 표시한다.

단, ETA는 단순 추정값으로 표시한다.


==================================================
27. 단계별 상태 코드
==================================================

각 단지마다 상태를 기록한다.

예:

WAITING
SEARCHING
MATCHING
COLLECTING_TYPES
COLLECTING_PRICES
VALIDATING
VERIFIED
PENDING
FAILED

현재 어떤 단지를 어느 단계에서 처리 중인지
화면에서 바로 알 수 있어야 한다.


==================================================
28. 에러 메시지를 숨기지 않는다
==================================================

실패 시 단순:

ERROR

만 표시하지 않는다.

예:

PENDING:
KB search returned 3 similar complexes

FAILED:
KB area selector not found after page structure change

RETRY:
HTTP/navigation timeout 2/3

LOGIN REQUIRED:
KB session expired

등 구체적인 원인을 표시한다.


==================================================
29. checkpoint / resume
==================================================

560개를 처리하다 중간에 프로그램이 종료되어도
처음부터 다시 시작하면 안 된다.

각 단지 처리 완료 시 checkpoint를 저장한다.

예:

data/state/kb_collection_state.json

또는 SQLite를 사용해도 된다.

저장 정보:

kapt_code
status
kb_complex_id
attempts
last_error
updated_at

프로그램을 다시 실행하면:

VERIFIED 완료 단지
→ skip

PENDING
→ 기본적으로 skip 또는 옵션에 따라 retry

FAILED
→ retry 가능

미처리
→ 처리

하도록 한다.


==================================================
30. CLI 실행 옵션
==================================================

가능하면 아래와 같은 인터페이스를 구현한다.

전체 실행:

python scripts/build_kb_area_master.py

파일럿만:

python scripts/build_kb_area_master.py --pilot

특정 단지만:

python scripts/build_kb_area_master.py --kapt-code XXXXX

특정 단지명:

python scripts/build_kb_area_master.py --name "대연SK뷰힐스"

pending 재시도:

python scripts/build_kb_area_master.py --retry-pending

failed 재시도:

python scripts/build_kb_area_master.py --retry-failed

KB complex ID 매핑만:

python scripts/build_kb_area_master.py --mapping-only

평형 데이터만:

python scripts/build_kb_area_master.py --collect-only

처음부터 재수집:

python scripts/build_kb_area_master.py --refresh

브라우저 표시:

python scripts/build_kb_area_master.py --headed


==================================================
31. 속도보다 안정성 우선
==================================================

KB에 과도한 병렬 요청을 보내지 않는다.

560개를 동시에 처리하지 않는다.

기본적으로 순차 처리 또는 매우 낮은 concurrency를 사용한다.

예:

1~2개 수준

자동화 방지에 걸리면 우회하지 않는다.

필요하면:

- 요청 간 간격
- 정상 페이지 navigation
- 캐시
- retry
- exponential backoff

를 사용한다.

무리한 속도 최적화보다
안정적인 수집을 우선한다.


==================================================
32. retry
==================================================

일시적인 오류는 자동 재시도한다.

예:

navigation timeout
network timeout
temporary page load failure

최대 3회 정도.

예:

Attempt 1/3
Attempt 2/3
Attempt 3/3

3회 실패 시 해당 단지를 FAILED 또는 PENDING 처리하고
다음 단지로 진행한다.

한 단지 때문에 전체 batch가 멈추지 않게 한다.


==================================================
33. 로그인 세션 만료 처리
==================================================

수집 중 KB 로그인 세션이 만료되면
계속 실패를 반복하지 않는다.

로그인 페이지로 redirect된 것을 감지하면:

1. 전체 처리 일시정지
2. 화면에 LOGIN REQUIRED 표시
3. 브라우저 창 유지
4. 사용자가 직접 로그인
5. 로그인 성공 감지
6. 직전 단지부터 자동 재개

하도록 한다.


==================================================
34. raw 데이터 캐시
==================================================

이미 정상 수집한 KB 데이터는
불필요하게 다시 조회하지 않는다.

예:

data/cache/kb/

또는 SQLite cache 사용 가능.

refresh 옵션이 있을 때만 강제 갱신한다.


==================================================
35. 최종 market_cap_area_master.csv 작성
==================================================

기존 CSV의 모든 컬럼을 유지한다.

필수 필드:

kapt_code
area_group_id
exclusive_area_sqm
households
source
verified_at
verification_status
scope

scope:

sale_apartment

verified_at:

실제 검증한 날짜

YYYY-MM-DD

source:

가능하면 KB 단지 URL과 데이터 출처를 식별할 수 있게 기록한다.

예:

KB부동산 단지 시세/평형정보 | https://...

확인이 필요한 선택항목은 빈칸으로 둔다.


==================================================
36. valid_from 절대 주의
==================================================

valid_from은 자료 조회일이 아니다.

다음을 넣지 않는다.

- KB 시세 기준일
- collected_at
- verified_at
- 사용승인일

해당 세대 구성이 적용되기 시작한 날짜라는
명확한 근거가 없으면:

valid_from = ""

으로 둔다.


==================================================
37. verification_status
==================================================

다음과 같은 경우만 verified 후보로 한다.

- KB complex ID 매칭 confidence가 exact/high
- 평형별 세대수 확보
- 공급/전용면적 확보
- source 확보
- 세대수 합계 검증 성공 또는 이에 준하는 공식 검증
- sale_apartment 범위 문제가 없음

하나라도 중요한 불확실성이 있으면:

pending

으로 한다.

억지로 verified 비율을 높이지 않는다.


==================================================
38. pending 사유 코드
==================================================

pending에 reason code를 저장한다.

예:

KB_COMPLEX_NOT_FOUND

KB_COMPLEX_AMBIGUOUS

ADDRESS_MISMATCH

HOUSEHOLDS_MISMATCH

AREA_NOT_AVAILABLE

AREA_PRECISION_AMBIGUOUS

TYPE_HOUSEHOLDS_MISSING

KB_PRICE_MISSING

MIXED_RENTAL_COMPLEX

LOGIN_REQUIRED

PAGE_STRUCTURE_CHANGED

SOURCE_VALIDATION_FAILED

등.


==================================================
39. pending 결과 파일
==================================================

다음 파일을 만든다.

data/review/area_master_pending.csv

가능하면 컬럼:

kapt_code
kapt_name
legal_dong

kb_complex_id
kb_name

reason_code
reason

match_score
match_confidence

kapt_households
kb_households

types_found

recommended_next_action
source_url


==================================================
40. fallback 전략
==================================================

KB로 해결되지 않는 단지만 fallback 대상으로 분리한다.

우선순위:

1. KB 재검색/다른 검색어
2. 기존 KB complex ID 검증
3. 공식 입주자모집공고
4. 청약홈
5. LH/BMC/사업주체 공식자료
6. 필요한 경우 건축HUB
7. 최종적으로 건축물대장

건축HUB 개별 세대 수집을
560개 전체에 실행하지 않는다.


==================================================
41. 기존 건축HUB 코드 처리
==================================================

기존에 이미 구현한 건축HUB 수집 코드는 삭제하지 않는다.

fallback module로 재사용한다.

예:

if kb_verified:
    skip_buildinghub()

elif kb_pending:
    queue_for_fallback()

즉 건축HUB는 exception path로 이동한다.


==================================================
42. 권장 프로젝트 구조
==================================================

기존 repository 구조를 우선한다.

새 구조가 필요하다면 예:

src/
  kb_area_master/
    config.py
    models.py
    kapt.py
    kb_browser.py
    kb_search.py
    kb_matcher.py
    kb_collector.py
    kb_parser.py
    area_normalizer.py
    validator.py
    exporter.py
    progress.py
    state.py

scripts/
  build_kb_area_master.py

data/
  browser/
    kb_profile/

  mapping/
    kb_complex_mapping.csv

  raw/
    kb/
      kb_area_types.csv

  review/
    area_master_pending.csv
    area_master_conflicts.csv

  state/
    kb_collection_state.json


==================================================
43. 주요 데이터 모델
==================================================

가능하면 typed model/dataclass/Pydantic 등을 사용한다.

ComplexCandidate:

kapt_code
kb_complex_id
kb_name
kb_address
kb_households
match_score
match_confidence
match_reasons

AreaType:

kb_type_id
type_name
households
supply_area_sqm
exclusive_area_sqm
area_precision
price...

ValidationResult:

status
reason_codes
expected_households
collected_households


==================================================
44. 테스트 작성
==================================================

최소한 다음 테스트를 만든다.

TEST 1
단지명 공백 차이

"대연SK뷰힐스"
"대연 SK뷰힐스"

후보로 인식


TEST 2
차수 보존

"LG메트로시티1차"
"LG메트로시티2차"

다른 단지로 인식


TEST 3
동명 우선

같은 단지명이 다른 동에 존재하면
다른 동 후보 자동 확정 금지


TEST 4
세대수 검증

K-apt 1,000
KB type 합계 1,000

PASS


TEST 5

K-apt 1,000
KB 980

PENDING


TEST 6
전용면적 exact grouping

59.9794 / 120
59.9794 / 98

→ 218


TEST 7
전용면적 분리

59.9794
59.9842

→ 두 행


TEST 8
표시값 84.99가 같은 다른 타입인데
고정밀 원본 면적이 없음

→ 자동 merge 금지


TEST 9
valid_from

근거 없음

→ blank


TEST 10
재실행

이미 VERIFIED인 단지

→ 재수집 없이 skip


==================================================
45. 실행 중 로그 파일도 저장
==================================================

화면 출력과 별도로:

logs/kb_area_collection.log

파일에 상세 로그를 기록한다.

각 로그에:

timestamp
kapt_code
complex name
phase
result
elapsed
error

등을 기록한다.

민감한 로그인 토큰,
쿠키,
비밀번호 등은 로그에 기록하지 않는다.


==================================================
46. 전체 종료 시 결과 요약
==================================================

전체 작업 종료 후 화면에 다음 형태의 요약을 표시한다.

========================================
KB AREA MASTER COLLECTION COMPLETED
========================================

Total complexes          : 560
Processed                : XXX
Verified                 : XXX
Pending                  : XXX
Failed                   : XXX

KB exact matches         : XXX
KB high matches          : XXX
KB medium/low matches    : XXX

Total area/type rows     : XXXX

Household sum matched    : XXX
Household sum mismatch   : XXX

Elapsed                  : HH:MM:SS

Output:
config/market_cap_area_master.csv

Raw:
data/raw/kb/kb_area_types.csv

Mapping:
data/mapping/kb_complex_mapping.csv

Review:
data/review/area_master_pending.csv

========================================


==================================================
47. 결과 품질 보고
==================================================

최종적으로 다음 내용을 보고한다.

1. 대연SK뷰힐스 파일럿 결과
2. 대연SK뷰힐스의 K-apt 정보
3. 매칭된 KB complex ID
4. KB 단지명
5. 매칭 confidence와 근거
6. 수집된 평형 개수
7. 평형별 세대수 합계
8. K-apt 총세대수
9. 공급/전용면적 확보 여부
10. KB시세 확보 여부
11. 전체 대상 단지 수
12. verified 단지 수
13. pending 단지 수
14. failed 단지 수
15. pending 주요 사유
16. 최종 생성 row 수
17. 전체 처리시간
18. 평균 단지 처리시간
19. fallback이 필요한 단지 수


==================================================
48. 매우 중요한 금지사항
==================================================

절대 하지 않는다.

1. KB 검색 결과 첫 번째 항목을 무조건 단지로 확정

2. 단지명만 비슷하다는 이유로 자동 확정

3. LG메트로시티1차/2차 같은 차수 정보를 제거해서 같은 단지로 취급

4. 다른 동의 동일/유사 단지를 자동 선택

5. KB 표시 전용면적을 임의로 더 정밀한 숫자로 추정

6. 서로 다른 type_name의 동일한 2자리 전용면적을 근거 없이 합산

7. 전용면적을 round한 뒤 GROUP BY

8. KB 세대수 합계가 K-apt와 다르는데 verified 처리

9. 혼합/임대 단지를 검증 없이 sale_apartment 처리

10. valid_from에 verified_at 또는 시세 기준일을 넣기

11. KB ID/password를 코드에 저장

12. CAPTCHA/인증/접근제한 우회 기능 구현

13. 560개 전체에 건축HUB 세대별 조회 실행

14. 한 단지 실패 때문에 전체 batch 중단

15. 처리 진행상황을 사용자에게 숨긴 채 장시간 실행


==================================================
49. 실제 작업 시작 지시
==================================================

지금부터 단순 설계 설명만 하지 말고 실제 repository를 분석하고 코드를 구현한다.

반드시 다음 순서대로 진행한다.

STEP 1
repository 및 CSV 분석

STEP 2
K-apt 기본정보 로직 확인/구현

STEP 3
Playwright persistent KB browser 구현

STEP 4
대연SK뷰힐스 K-apt 정보 확인

STEP 5
"동명 + 단지명"으로 KB 검색

STEP 6
KB 후보 분석 및 complex ID 확정

STEP 7
대연SK뷰힐스 평형 선택 데이터 수집

STEP 8
공급면적 / 전용면적 / 세대수 / KB시세 저장

STEP 9
K-apt 총세대수와 비교

STEP 10
파일럿 PASS/FAIL 자동 판정

STEP 11
PASS이면 나머지 대상 단지 자동 실행

STEP 12
실시간 progress 화면 표시

STEP 13
checkpoint를 지속적으로 저장

STEP 14
pending/failed를 분리하면서 끝까지 진행

STEP 15
market_cap_area_master.csv 생성

STEP 16
최종 validation 실행

STEP 17
결과 통계와 문제점 보고

대연SK뷰힐스 파일럿이 PASS하기 전에는
전체 batch를 실행하지 않는다.

대연SK뷰힐스가 PASS하면
별도의 사용자 승인 없이 나머지 대상 단지 수집으로 자동 진행한다.