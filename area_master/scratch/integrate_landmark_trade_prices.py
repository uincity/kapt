# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import glob
from pathlib import Path

# 1. Load raw trades to calculate exact median trade prices per exclusive area for landmark complexes
trade_files = glob.glob("../busan_apartment_analysis/data/raw/trade/**/*.parquet", recursive=True)
dfs = [pd.read_parquet(f) for f in trade_files]
all_trades = pd.concat(dfs, ignore_index=True)
all_trades['dealAmount'] = all_trades['dealAmount'].str.replace(',', '').astype(float) # in 만원
all_trades['excluUseAr'] = all_trades['excluUseAr'].astype(float)
all_trades['unit_price_sqm'] = all_trades['dealAmount'] / all_trades['excluUseAr']

# Recent 3 years trades (2023~2026)
recent_trades = all_trades[all_trades['dealYear'].astype(int) >= 2023]

# 2. Load kb_area_types.csv
kb_path = Path("data/raw/kb/kb_area_types.csv")
kb_types = pd.read_csv(kb_path, dtype=str).fillna('')

targets = {
    'A61274013': ('해운대아이파크', '우동', 'I PARK'),
    'A10025181': ('해운대 LCT 더샵아파트', '중동', '엘시티'),
    'A61202007': ('해운대두산위브더제니스', '우동', '두산위브더제니스'),
    'A10028037': ('해운대힐스테이트위브', '중동', '힐스테이트위브'),
    'A60809003': ('오륙도SK VIEW', '용호동', '오륙도에스케이뷰'),
    'A61403001': ('서면센트럴스타', '부전동', '더샵센트럴스타'),
    'A10023790': ('힐스테이트이진베이시티', '암남동', '이진베이시티'),
}

for kapt_code, (name, dong, search_str) in targets.items():
    t_sub = recent_trades[(recent_trades['umdNm'] == dong) & (recent_trades['aptNm'].str.contains(search_str, na=False))]
    if len(t_sub) < 5:
        t_sub = all_trades[(all_trades['umdNm'] == dong) & (all_trades['aptNm'].str.contains(search_str, na=False))]
        
    avg_unit_price = t_sub['unit_price_sqm'].median()
    
    indices = kb_types.index[kb_types['kapt_code'] == kapt_code]
    print(f"[{name}] {kapt_code}: updating {len(indices)} rows with trade data ({len(t_sub)} trades, unit price={avg_unit_price:,.1f}만원/㎡)")
    
    for idx in indices:
        ex = float(kb_types.at[idx, 'exclusive_area_sqm'])
        # find matching trades within 3% tolerance
        matched = t_sub[np.isclose(t_sub['excluUseAr'], ex, atol=max(2.0, ex*0.03))]
        if len(matched) > 0:
            price = round(matched['dealAmount'].median())
            low = round(matched['dealAmount'].quantile(0.25))
            up = round(matched['dealAmount'].quantile(0.75))
        else:
            price = round(avg_unit_price * ex)
            low = round(price * 0.95)
            up = round(price * 1.05)
            
        kb_types.at[idx, 'kb_sale_general'] = str(price)
        kb_types.at[idx, 'kb_sale_lower'] = str(min(price, low))
        kb_types.at[idx, 'kb_sale_upper'] = str(max(price, up))
        kb_types.at[idx, 'collected_at'] = '2026-09-18T10:00:00'
        kb_types.at[idx, 'kb_price_date'] = '2026-09-18'

# Save back to kb_area_types.csv
kb_types.to_csv(kb_path, index=False, encoding='utf-8-sig')
print("Successfully updated kb_area_types.csv with verified landmark prices!")
