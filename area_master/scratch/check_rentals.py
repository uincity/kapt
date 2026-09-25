import pandas as pd

kapt_df = pd.read_csv('data/intermediate/kapt_complexes.csv')
pending_df = pd.read_csv('data/review/area_master_pending.csv')
rentals = pending_df[pending_df['reason_code'] == 'RENTAL_COMPLEX']
m = pd.merge(rentals[['kapt_code']], kapt_df, on='kapt_code', how='left')

print('Rental complexes sale_type values:')
print(m['sale_type'].value_counts(dropna=False))

print('\nSample 15 rental complexes:')
for _, r in m.head(15).iterrows():
    print(f"[{r['kapt_code']}] {r['kapt_name']} | sale_type: {r['sale_type']} | {r['households']}세대 | 주소: {r['legal_address']}")
