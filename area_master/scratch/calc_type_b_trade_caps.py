# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
import numpy as np
import glob

# 1. Type A calculation (KB based)
# W 아파트 (A10026391)
# 트럼프월드센텀 (A61202004)
# 더샵센텀스타 (A61205003)
# 대우마리나1,2차 (A61282215)
# 부산항일동미라주더오션 (A10023963)

# 2. Type B calculation (Recent Trade based - 1년 이내 또는 가장 최근 거래 평단가 x 평형별 세대수)
trade_files = glob.glob("../busan_apartment_analysis/data/raw/trade/**/*.parquet", recursive=True)
dfs = [pd.read_parquet(f) for f in trade_files]
all_trades = pd.concat(dfs, ignore_index=True)
all_trades['deal_ymd'] = all_trades['dealYear'].astype(str) + all_trades['dealMonth'].astype(str).str.zfill(2) + all_trades['dealDay'].astype(str).str.zfill(2)
all_trades['dealAmount'] = all_trades['dealAmount'].str.replace(',', '').astype(float) * 10000 # to KRW
all_trades['excluUseAr'] = all_trades['excluUseAr'].astype(float)
all_trades['unit_price_sqm'] = all_trades['dealAmount'] / all_trades['excluUseAr']

# Master area types
master = pd.read_csv("data/releases/area_master_20260918/market_cap_area_master.csv")

type_b_targets = {
    'A61202007': ('해운대두산위브더제니스', '우동', '두산위브더제니스', 1788),
    'A61274013': ('해운대아이파크', '우동', 'I PARK', 1631),
    'A10025181': ('해운대 LCT 더샵', '중동', '엘시티', 882),
    'A61403001': ('더샵센트럴스타', '부전동', '더샵센트럴스타', 1360),
    'A10023790': ('힐스테이트이진베이시티', '암남동', '이진베이시티', 1368),
    'A60809003': ('오륙도SK뷰', '용호동', '오륙도에스케이뷰', 3000),
    'A10028037': ('해운대힐스테이트위브', '중동', '힐스테이트위브', 2369),
}

print("=== Type B Trade-based Market Cap Valuation ===")
for kapt_code, (name, dong, search_str, total_hh) in type_b_targets.items():
    m_types = master[master['kapt_code'] == kapt_code]
    t_sub = all_trades[(all_trades['umdNm'] == dong) & (all_trades['aptNm'].str.contains(search_str, na=False))]
    
    # Calculate average unit price per sqm for the complex across recent 2 years (2024~2026)
    recent_trades = t_sub[t_sub['dealYear'].astype(int) >= 2024]
    if len(recent_trades) < 5:
        recent_trades = t_sub # fallback to all
        
    avg_unit_price = recent_trades['unit_price_sqm'].median()
    
    # Or match by nearest exclusive area
    complex_cap = 0
    priced_hh_count = 0
    for idx, row in m_types.iterrows():
        ex = float(row['exclusive_area_sqm'])
        hh = float(row['households'])
        # find matching trades within 5% area
        matched_trades = recent_trades[np.isclose(recent_trades['excluUseAr'], ex, atol=2.0)]
        if len(matched_trades) > 0:
            area_price = matched_trades['dealAmount'].median()
        else:
            # extrapolate with avg unit price
            area_price = avg_unit_price * ex
        complex_cap += area_price * hh
        priced_hh_count += hh
        
    print(f"[{name}] {kapt_code}:")
    print(f"  총 세대수: {total_hh}세대, 실거래 데이터: {len(t_sub)}건 (최근 2년 {len(recent_trades)}건)")
    print(f"  실거래 기반 시가총액: {complex_cap:,.0f}원 ({complex_cap/1e12:.2f}조원 / {complex_cap/1e8:,.1f}억원)")
    print(f"  세대당 평균가: {complex_cap/total_hh/1e8:.2f}억원")
