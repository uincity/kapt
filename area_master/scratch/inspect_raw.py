import pandas as pd

raw = pd.read_csv('data/raw/kb/kb_area_types.csv')
print("Columns of raw:")
print(raw.columns.tolist())
print("\nSample 5 rows of raw:")
for _, r in raw.head(5).iterrows():
    print(dict(r))

# Check if there are any complexes where multiple raw rows have the same kapt_code
print("\nTop 5 kapt_codes by row count in raw:")
print(raw['kapt_code'].value_counts().head(5))
