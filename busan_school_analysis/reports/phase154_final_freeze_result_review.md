# Phase 15.4 최종 동결 및 결과 검토

## 1. Final Model Status

- 최종 상태: **BUSAN_APARTMENT_VALUE_MODEL_FINAL_FROZEN**
- 마지막 분석 단계: Phase 15.3, Phase 15.4는 동결·검토·표현 단계
- 향후 모델 재학습: 금지. 동결 원본을 이용한 조회와 검토만 허용
- Local Value Gap 상태: **LOCAL_VALUE_GAP_USABLE_WITH_CAUTION**

## 2. School Module

- School Core Score: 557/560개
- School Score 10점 증가 가격 연관: 4.33%
- School Value Gap: 500/560개, 기존 Phase 14.9 값 그대로 보존

## 3. Local Price Module

- 선택 모델: Model F / sparse fallback F3
- Global / 법정동 FE / Model F RMSE: 0.38215 / 0.24614 / 0.19574
- Model F R²: 0.8599
- Fair Price coverage: 502/560개
- 95% 예측구간 폭 중앙값: 67.95%로 불확실성이 크다.

## 4. Local Value Gap

- coverage: 502/560개
- 중앙값: 2.92%
- 6M/12M Spearman: 0.9650
- 기간 방향 일치: 91.2%
- Strong undervalued / overvalued: 8 / 4개

## 5. Dual Signal

- 판정: **DUAL_SIGNAL_COMPLEMENTARY**
- School Gap–Local Gap Spearman: 0.7502
- DOUBLE_POSITIVE / ROBUST_DUAL_POSITIVE: 183 / 94개
- 별도 합산점수 없이 두 신호와 신뢰도를 함께 제시한다.

## 6. Final Candidate Classes

- CORE_CANDIDATE (94개): 금곡화목타운, 금곡3단지주공, 삼익그린, 명지오션시티한신휴플러스, 협성피닉스타운, 도시화명그린(295), 금곡9단지주공, 센텀대림, 명지두산위브포세이돈, 협진태양·조성아파트, 일동미라주, 극동스타클래스, 그린숲속아파트, 해운대 센트럴파크, 당감뜨란채, 대우그린1, 퀸덤1차아인슈타인타운, LH뜨란채아파트, 퀸덤1차링컨타운, 상록
- LOCAL_VALUE (58개): 센텀리버SKVIEW, 대연롯데캐슬, 삼환, 롯데캐슬라센트, 화명롯데캐슬카이저, 더샵명지퍼스트월드2단지, 브라운스톤연제2단지, 연지자이2차, 센텀롯데캐슬아파트, 안락뜨란채2단지
- SCHOOL_VALUE (30개): 화승, 일광대성베르힐, 일광한신더휴센트럴포레2단지, 이지더원1차오션포레, 엘지신주례1, 센텀비치푸르지오, 일성인포, 롯데4, 국제마마뉴비치타운, 학장벽산
- WATCHLIST (262개): 화명유림, 다송, 삼한힐파크, 유림아시아드, 시영(1~5동), 서면베르빌2, 센텀우신골든빌, 장산동국, 신다대, 연산엘지
- FULLY_PRICED_OR_NEGATIVE (116개): 연산더샵, 대우, 자유, 대연SKVIEWHills(2단지), 이편한세상금정산, 다대푸르지오, 삼성, 대연자이, 더 래디언트 금정산, 다대롯데캐슬블루

Class 내부 순위는 구간 상태, Local·모델·School 신뢰도, 기간 안정성, 양의 확률, Local Gap, School Gap 순의 사전 고정된 사전식 규칙이다. 가중 합산점수는 없다.

## 7. Model Limitations

- 제한 플래그: LOW_SCHOOL_CONFIDENCE 239개, EXTREME_RESIDUAL 141개, WIDE_PREDICTION_INTERVAL 125개, LOW_TRANSACTION 62개, MISSING_SCHOOL_SCORE 60개, LOW_MODEL_CONFIDENCE 58개, MISSING_FAIR_PRICE 58개, LEGAL_DONG_BIAS 29개
- 법정동 bias: 29개 단지, 10개 법정동
- 모델에 없는 조망·재건축·브랜드·동/향·내부상태 등은 residual 또는 audit 한계로 남긴다.
- Local Gap은 수익을 보장하는 저평가 지표가 아니며 의사결정 전 개별 확인이 필요하다.

## 8. High Audit Candidates

- Phase 15.3 HIGH audit 후보 33개를 그대로 포함했다.
- 유형은 extreme gap, 법정동 bias, 넓은 예측구간, 낮은 거래량, fallback, 미설명 premium/discount 가능성이다.

## 9. Data Integrity

- 보호 파일: 320개
- 변경 파일: 0개
- pytest: 기존 388 + 신규 60 = 448 PASS, 실패 0개
- Fair Price, School Gap, Local Gap, prediction interval은 원본과 동일하다.

## 10. Final Usage Guide

1. `final_review_class`로 검토 목적을 고른다.
2. `model_confidence`, `local_gap_confidence`, `gap_confidence`를 확인한다.
3. 예측구간과 6M/12M 관측가격을 비교한다.
4. `model_limitation_detail`, 법정동 bias, HIGH audit 사유를 검토한다.
5. 원본 거래·현장 특성을 확인한 뒤 의사결정한다.

운영 가능한 Fair Price·Local Gap 결과는 502개 단지이며, School Core는 557개 단지에 존재한다. 기본 운영 파일은 `phase154_final_apartment_value_master.csv`와 `phase154_final_model_freeze.json`이다.
