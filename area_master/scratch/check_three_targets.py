import pandas as pd
import json

targets = {'A10022002': '래미안포레스티지', 'A10026780': '래미안장전', 'A10024953': '포레나부산초읍'}

# Check summary.csv
sum_df = pd.read_csv('data/processed/market_cap/kb/summary.csv')
for k, v in targets.items():
    row = sum_df[sum_df['kapt_code'] == k]
    if not row.empty:
        r = row.iloc[0]
        print(f"summary: {k} {v} - households={r.get('households')}, confirmed={r.get('confirmed_households')}, priced={r.get('priced_households')}, status={r.get('status')}, reason={r.get('reason')}")
    else:
        print(f"summary: {k} {v} not found")

# Check master
master_df = pd.read_csv('data/processed/market_cap/market_cap_area_master.csv')
for k, v in targets.items():
    sub = master_df[master_df['kapt_code'] == k]
    if not sub.empty:
        total_hh = sub['households'].sum()
        priced_sub = sub[sub['price_krw'].notna() & (sub['price_krw'] > 0)]
        unpriced_sub = sub[sub['price_krw'].isna() | (sub['price_krw'] <= 0)]
        print(f"\n==================== {k}: {v} ====================")
        print(f"Total rows: {len(sub)}, Total households: {total_hh}")
        print(f"Priced rows: {len(priced_sub)}, Priced households: {priced_sub['households'].sum()}")
        print(f"Unpriced rows: {len(unpriced_sub)}, Unpriced households: {unpriced_sub['households'].sum()}")
        print("\n[Unpriced Types]:")
        print(unpriced_sub[['area_name', 'exclusive_area', 'supply_area', 'households', 'price_krw']].to_string())
        print("\n[Priced Types Summary]:")
        print(priced_sub[['area_name', 'exclusive_area', 'supply_area', 'households', 'price_krw']].to_string())
    else:
        print(f"master: {k} {v} not in master")
