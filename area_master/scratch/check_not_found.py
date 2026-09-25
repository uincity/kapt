import pandas as pd

df = pd.read_csv('data/review/area_master_pending.csv')
kapt_df = pd.read_csv('data/intermediate/kapt_complexes.csv')
not_found = df[df['reason_code'] == 'KB_COMPLEX_NOT_FOUND']
m = pd.merge(not_found, kapt_df[['kapt_code', 'road_address', 'legal_address', 'approval_date']], on='kapt_code', how='left')

print(f"Total KB_COMPLEX_NOT_FOUND complexes: {len(m)}")
print("Sample 20 complexes:")
for _, r in m.head(20).iterrows():
    print(f"[{r['kapt_code']}] {r['kapt_name']} | {r['legal_dong']} | {r['kapt_households']}세대 | 도로명: {r['road_address']}")
