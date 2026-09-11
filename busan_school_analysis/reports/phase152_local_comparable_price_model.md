# Phase 15.2 Local Comparable Price Model

## 1. Dataset
- 전체 master: 560개 단지
- 모델 공통표본: 500개 단지, 132,979건, 93개 법정동
- Temporal split: 2025-02-03까지 train 99,751건 / 이후 test 33,228건
- 현재 기준 충분/소표본 법정동: 44/57

## 2. Model Comparison
model,school_variant,test_transactions,test_apartments,rmse,mae,mape,median_ape,r2,apartment_weighted_rmse,dong_equal_weighted_rmse,calibration_slope,calibration_intercept
D,NO_SCHOOL,33228,500,0.2530288852647987,0.19412554939949286,0.21103418012792471,0.15628901564609662,0.7659371634530938,0.27631864003170253,0.22425650931109378,1.156142944843631,-2.4887999382038544
F,NO_SCHOOL,33228,500,0.20766559287605416,0.159489572704753,0.17200559255910114,0.12899032845225622,0.8423400617674809,0.22785735268881255,0.19762940874820809,1.1168807888374097,-1.8806121102901852
G,NO_SCHOOL,33228,500,0.41843614031543375,0.32685305169155887,0.3463426143783021,0.2623085160763039,0.35989586246177585,0.42531035850313986,0.41849310061540007,1.2913878027942256,-4.531043471480009
L,NO_SCHOOL,33228,500,0.2553783780273718,0.1860541520343877,0.20934833722111648,0.13990841635958967,0.7615702144787884,0.28465709669473,0.3327437154189828,1.127358695132682,-2.059692789660456
D,SCHOOL,33228,500,0.24614026112634435,0.18719184561845756,0.20465118637817825,0.14884099785378158,0.778508240333624,0.2708248787285515,0.2202431341935387,1.150909025605755,-2.4095267117612513
F,SCHOOL,33228,500,0.1957385999668175,0.14880120254147564,0.16097076079262335,0.11755834005519603,0.8599299722114869,0.21803077367072501,0.1915495365962389,1.1198489325709633,-1.9281325591447191
G,SCHOOL,33228,500,0.38215465337021326,0.299020654202404,0.31874549798108276,0.24505583000886375,0.46608691582939976,0.3863064144323098,0.3873141578344552,1.2507486477003635,-3.9175217047264232
L,SCHOOL,33228,500,0.23717521497911376,0.17417426082532797,0.1935443374885694,0.13265085564407125,0.7943489812407645,0.26379864547235754,0.3080688737316415,1.1181217487602053,-1.9096753860064637


- 선택 모델: **F**
- Global / Dong FE / 선택 모델 RMSE: 0.38215 / 0.24614 / 0.19574
- 판정: **LOCAL_COMPARABLE_MODEL_PARTIALLY_SUPPORTED**

## 3. School Feature
- 선택 Model F의 No-school 대비 School RMSE 개선: +5.743%
- Dong FE의 No-school 대비 School RMSE 개선: +2.722%
- 판정: **LOCAL_SCHOOL_FEATURE_USEFUL**
- 법정동별 school coefficient 방향: 양수 77개 / 음수 15개 / 0 또는 미산출 1개.
- 소표본의 local slope 폭주를 피하기 위해 F3 공통 regularized slope를 사용했다. Freeze 점수는 변경하지 않았다.

## 4. Fallback
- 선택 방식: **F3** (F1 same-gu, F2 profile hierarchy, F3 regularized dong partial pooling 비교)
- 현재 fallback level 분포: {'0': 44, '1': 53, '2': 4}
- Phase 15.1의 48개 LOW 시장은 clustering 가능 92개 시장 기준이며, 여기의 57개는 전체 master 101개 법정동에 5개 단지 AND 최근 100거래 기준을 적용한 수다.
- 모든 fallback은 target price를 사용하지 않고 단지 구조·공간·train sample만으로 결정했다.

## 5. Fair Price
- 산출: 502/560개 (89.64%)
- 95% prediction interval 폭 중앙값: 67.95%
- Confidence: {'HIGH': 312, 'MEDIUM': 190, 'LOW': 58}
- `local_value_gap_pct`는 생성하지 않았다.

## 6. Model Error
- 선택 모델 OOS RMSE/MAE/R²: 0.19574/0.14880/0.8599
- 안정적인 10개 동: 일광읍삼성리(0.057); 좌천동(0.060); 서대신동2가(0.062); 초읍동(0.069); 당리동(0.076); 범전동(0.081); 괴정동(0.090); 기장읍서부리(0.090); 괘법동(0.092); 봉래동2가(0.093)
- 불안정한 10개 동: 당감동(0.382); 동삼동(0.381); 청룡동(0.339); 가야동(0.333); 광안동(0.328); 덕포동(0.317); 덕천동(0.311); 기장읍청강리(0.300); 부전동(0.297); 장림동(0.292)
- Apartment group holdout는 별도 보고서에 보존했다.
- Group holdout 평균 RMSE Global/Dong FE: 0.38250/0.30070.

## 7. Audit
- Fair price audit: 163개 flag row
- 입력 부족 단지는 값을 추정하지 않고 `FAIR_PRICE_NOT_AVAILABLE`로 유지했다.

## 8. Final Decision
1. Global 대비 선택 모델 RMSE 변화는 +48.78%다.
2. Global + Legal Dong FE 대비 변화는 +20.48%다.
3. Freeze School Core Score의 OOS utility 판정은 `LOCAL_SCHOOL_FEATURE_USEFUL`다.
4. 소표본 법정동 fallback은 `F3`가 선택됐다.
5. 신뢰 가능한 Fair Price는 confidence HIGH/MEDIUM 기준 502개다.
6. Prediction interval 폭 중앙값은 67.95%다.
7. Phase 15.3 준비 여부는 `True`이나, LOW confidence는 제외해야 한다.

최종 판정은 **LOCAL_COMPARABLE_MODEL_PARTIALLY_SUPPORTED**이다. Fair Price는 현재 데이터와 대표 조건에 따른 설명 가능한 가격 기준선이며 감정가나 투자신호가 아니다.

## 9. Validation
- Phase 7~15.1 보호 파일: 263개, SHA-256 변경 0개
- 기존 테스트 300개 + Phase 15.2 신규 테스트 40개 = 전체 **340 PASS**
- Fair Price identity, interval ordering, temporal leakage, target 제외, fallback hierarchy와 residual identity를 검증했다.

Phase 15.3은 자동 실행하지 않는다.
