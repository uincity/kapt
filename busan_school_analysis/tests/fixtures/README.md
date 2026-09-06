# 실제 공개 표 fixture

센텀중학교(학교 ID S020001910)의 학교알리미 공개 진로현황 화면을
2026-09-05 조회한 응답 바이트를 그대로 보관한다.

- 출처: https://www.schoolinfo.go.kr/ei/pp/Pneipp_b06_s0p.do
- 조회 경로 근거: https://www.schoolinfo.go.kr/ei/ss/pneiss_a05_s1.do 의 loadGongSi 함수
- 공시항목: 13-다, JG_HANGMOK_CD=52, GS_HANGMOK_CD=06
- 학교 공개 ID: bfc013ae-ea6d-4eb2-b2fb-f42899174b01
- centum_2024.html: 실제 2024년 표
- centum_2025.html: 실제 2025년 표
- centum_2026.html: 2026 요청에 2025년이 반환된 사례. 연도 혼동 방지 회귀 테스트

표의 외고국제고/예고체고는 원문부터 합산 범주다.
charset 선언과 달리 CP949 바이트인 응답도 파싱할 수 있어야 한다.

`haeundae_catchment_2025.html`과 `haeundae_middle_groups.html`은 2026-09-05에 내려받은
해운대교육지원청 공식 페이지 snapshot이다. Phase 4 테스트는 외부 접속 없이 센텀초
통학구역과 학교군 many-to-many 구조를 검증한다.
