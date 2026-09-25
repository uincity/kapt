import pandas as pd

df = pd.read_csv('data/review/area_master_pending.csv')
kapt_df = pd.read_csv('data/intermediate/kapt_complexes.csv')
low_conf = df[df['reason_code'].isin(['LOW_MATCH_CONFIDENCE', 'KB_COMPLEX_AMBIGUOUS'])]
m = pd.merge(low_conf, kapt_df[['kapt_code', 'road_address', 'legal_address', 'approval_date']], on='kapt_code', how='left')

print(f"Total Low Confidence/Ambiguous: {len(m)}")
for _, r in m.iterrows():
    print(f"[{r['kapt_code']}] {r['kapt_name']} | {r['legal_dong']} | {r['kapt_households']}세대 | 승인: {r['approval_date']} | 도로명: {r['road_address']} | 지번: {r['legal_address']}")
