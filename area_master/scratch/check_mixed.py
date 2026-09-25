import pandas as pd

df = pd.read_csv('data/review/area_master_pending.csv')
kapt_df = pd.read_csv('data/intermediate/kapt_complexes.csv')
mixed = df[df['reason_code'] == 'MIXED_RENTAL_COMPLEX']
m = pd.merge(mixed, kapt_df[['kapt_code', 'road_address', 'legal_address', 'approval_date', 'households']], on='kapt_code', how='left')

print(f"Total MIXED_RENTAL_COMPLEX: {len(m)}")
for _, r in m.head(15).iterrows():
    print(f"[{r['kapt_code']}] {r['kapt_name']} | {r['legal_dong']} | {r['kapt_households']}세대 | 주소: {r['road_address']}")
