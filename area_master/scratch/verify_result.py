import pandas as pd
from pathlib import Path

run_dir = Path('../busan_apartment_analysis/data/processed/market_cap/kb/0c4bbcaf4b149c6ba449a1b1')
complexes = pd.read_parquet(run_dir / 'complexes.parquet')
areas = pd.read_parquet(run_dir / 'areas.parquet')

c = complexes[complexes['kapt_code'] == 'A10023975']
print('=== DONGRAE COMPLEX RESULT ===')
for k, v in c.iloc[0].to_dict().items():
    print(f'  {k}: {v}')

print('\n=== DONGRAE AREAS (17 types) ===')
a = areas[areas['kapt_code'] == 'A10023975']
print(a[['area_group_id', 'exclusive_area_sqm', 'type_name', 'households', 'price_krw', 'adjusted_price_krw', 'price_method', 'price_reason']].to_string())

complexes_adj = complexes.copy()
complexes_adj['cap_eok'] = complexes_adj['adjusted_market_cap_krw'] / 1e8
complexes_adj['adj_rank'] = complexes_adj['adjusted_market_cap_krw'].rank(method='min', ascending=False)
complexes_adj['adj_gu_rank'] = complexes_adj.groupby('sigungu')['adjusted_market_cap_krw'].rank(method='min', ascending=False)

c_adj = complexes_adj[complexes_adj['kapt_code'] == 'A10023975'].iloc[0]
print('\n=== RANKING SUMMARY ===')
print(f"Complex: {c_adj['complex_name']}")
print(f"Households: {c_adj['households']} (Priced: {c_adj['priced_households']}, Estimated: {c_adj['estimated_households']})")
print(f"Adjusted Market Cap: {c_adj['cap_eok']:,.1f} 억원 ({c_adj['adjusted_market_cap_krw']:,.0f} 원)")
print(f"Busan Overall Rank: {c_adj['adj_rank']:.0f} 위")
print(f"Dongrae-gu Rank: {c_adj['adj_gu_rank']:.0f} 위")

print('\n=== BUSAN TOP 5 APARTMENTS BY ADJUSTED MARKET CAP ===')
top5 = complexes_adj.sort_values('adj_rank').head(5)
print(top5[['adj_rank', 'adj_gu_rank', 'complex_name', 'sigungu', 'households', 'cap_eok', 'adjusted_status']].to_string(index=False))
