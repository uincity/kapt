# Phase 15.1 Local Market Discovery

## 1. 데이터
- Phase 14.9 universe: 560개 단지
- Clustering eligible/excluded: 494/66
- 거래가격 표본: 503개 단지, 133,772건; clustering eligible 교집합 494개
- Core feature: 11개 — 가격수준·가격변화·단지구조/유동성 그룹 균형 적용
- 학군 Core·예상 프리미엄·Value Gap은 군집 입력에서 제외했다.
- 500세대 이상 coverage: 560개 중 494개

## 2. Cluster 선택
- K 후보: 3~15
- 선택 K: **3**
- Silhouette 0.1968, Davies-Bouldin 1.5903, Calinski-Harabasz 179.3
- KMeans와 Ward ARI: 0.6797
- 공간적으로 분절된 pure cluster: 3개

## 3. 가격 동질성
```csv
definition,apartment_count,market_count,within_log_price_variance,variance_ratio_vs_busan,within_price_mad,mean_market_price_iqr,within_price_change_variance
BUSAN,494,1,0.29179005772348693,1.0,1837064.5731980759,3783850.570833956,0.004985166452260082
GU,494,15,0.19194981819295712,0.6578353618026875,1213215.636670099,2650509.1228597867,0.004058484173604698
LEGAL_DONG,494,92,0.11895992259936955,0.4076901164058893,789327.1376229592,1446492.1065392264,0.003124666471894278
ALGORITHMIC,494,3,0.08266120098170293,0.2832899846780808,863903.2817208825,2151146.191398408,0.0027539400291125876
HYBRID,494,92,0.11895992259936955,0.4076901164058893,789327.1376229592,1446492.1065392264,0.003124666471894278
```

Hybrid의 법정동 대비 log-price 내부분산 변화: 0.00% 개선.

## 4. 안정성
- 12M vs 24M ARI/NMI: 0.9935/0.9883
- Bootstrap 100회 median stability: 1.000
- Stability ≥0.80/≥0.90: 491/487개

## 5. 최종 시장
- 최종 정의: **LEGAL_DONG**
- 최종 시장 수: 92개
- 법정동 92개 중 pure cluster에서 분리된 동: 52개
- Pure cluster는 각각 여러 법정동을 결합했으며 3개 모두 공간 분절 판정이다.
- 최소표본 관점에서 LOW인 최종 법정동 시장: 48개
- 판정: **LEGAL_DONG_BASELINE_PREFERRED**

## 6. 법정동과 Algorithm Cluster 관계
- 대표 법정동 분할: 해운대구 좌동(28개, 2군집); 해운대구 우동(19개, 2군집); 북구 화명동(18개, 3군집); 연제구 연산동(16개, 3군집); 사하구 다대동(15개, 2군집)
- 대표 법정동 병합: ALG00: 강서구 명지동(22), 부산진구 부암동(11), 해운대구 반여동(10), 북구 화명동(9); ALG01: 해운대구 좌동(21), 해운대구 우동(15), 남구 대연동(9), 연제구 연산동(8); ALG02: 사하구 다대동(10), 사상구 학장동(9), 북구 만덕동(8), 북구 금곡동(7)
- Pure algorithm은 법정동보다 log-price 내부분산을 30.51% 줄였지만 모든 군집이 원거리 지역을 결합했다.
- 명시적 hybrid 최소표본 규칙을 통과한 법정동 세분화는 0개였다. 따라서 Hybrid는 법정동과 동일하며 개선률도 0%다.

## 7. 주요 이상 사례
- 공간 분절 pure cluster: 3개
- Bootstrap stability < 0.80: 3개 단지
- 입력 feature 부족: 66개 단지; 임의 시장 배정 없이 `INSUFFICIENT_CLUSTER_FEATURES` 유지
- 월별 아파트 가격지수는 희소 거래로 신뢰할 수 있는 pairwise 상관을 만들기 어려워 계산하지 않았다. 대신 `within_price_change_variance`를 동일 기준으로 비교했다.

## 8. 핵심 질문과 판정
1. Pure data clustering에서 가장 안정적인 수는 K=3이나, 공식 생활권으로 해석할 수 없는 비공간적 가격·구조 군집이다.
2. 채택 가능한 Hybrid의 법정동 대비 가격 동질성 개선은 0.00%다.
3. 시간창 변경 안정성은 높다: 12M–24M ARI 0.9935, 12M–FULL ARI 0.9680.
4. Bootstrap stability 0.80 이상은 491개, 0.90 이상은 487개다.
5. 법정동 분할 대표 사례는 위 목록과 같지만, 세분 시장별 최소표본 규칙을 충족하지 못했다.
6. 세 pure cluster 모두 여러 법정동을 합쳤고 최대 공간 범위가 20km를 넘어 `NON_LOCAL_PRICE_CLUSTER`로 제외했다.
7. Phase 15.2 비교단위는 **법정동**이 가장 타당하다. 표본이 작은 48개 시장은 상위 지리단위 fallback이 필요하다.

최종 판정은 **LEGAL_DONG_BASELINE_PREFERRED**이다. Pure data cluster의 수치적 가격 동질성은 높지만 공간적 지역성이 없고, 규칙 기반 Hybrid는 법정동을 개선하지 못했다.

## 9. 검증
- Phase 7~14.9 보호 manifest: 233개 파일, 분석 종료 시 SHA-256 변경 0개
- 기존 테스트 263개와 Phase 15.1 신규 테스트 37개: 전체 **300 PASS**
- 신규 테스트는 보호 해시, 가격 집계, leakage, scaling/군집 재현성, label alignment, 시간·bootstrap 안정성, hybrid 규칙, mapping·summary·crosswalk 무결성을 검증한다.

Phase 15.2는 자동 진행하지 않는다. 이 시장권역은 공식 행정·생활권이 아니라 현재 보유 거래 및 단지특성에 기반한 가격 비교 목적의 데이터 구획이다.
