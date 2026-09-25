import sys
from pathlib import Path
import pandas as pd

BUSAN_DIR = Path("../busan_apartment_analysis")
sys.path.insert(0, str(BUSAN_DIR))
from src.market_cap_batch import load_complexes, ROOT

complexes = load_complexes()

names = ['LG메트로시티', '오션테라스', '레이카운티']
for name in names:
    sub = complexes[complexes['complex_name'].str.contains(name, na=False)]
    print(f"=== Complexes matching '{name}' in K-apt (>=500 cohort) ===")
    print(sub[['kapt_code', 'complex_name', 'sigungu', 'dong', 'households', 'sale_type']].to_string())

# Also search all complexes in kapt_clean.parquet
kapt_clean = pd.read_parquet(ROOT / "data/interim/kapt_clean.parquet")
for name in names:
    sub = kapt_clean[kapt_clean['complex_name'].str.contains(name, na=False)]
    print(f"\n=== Complexes matching '{name}' in all K-apt clean ===")
    print(sub[['kapt_code', 'complex_name', 'sigungu', 'dong', 'total_households', 'sale_type']].to_string())
