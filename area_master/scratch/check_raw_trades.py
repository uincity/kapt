import sys
from pathlib import Path
import pandas as pd

BUSAN_DIR = Path("../busan_apartment_analysis")
sys.path.insert(0, str(BUSAN_DIR))
from src.market_cap_batch import ROOT

# 1. Check K-apt for ocean terrace
kapt_clean = pd.read_parquet(ROOT / "data/interim/kapt_clean.parquet")
print("=== K-apt for Ocean Terrace ===")
print(kapt_clean[kapt_clean['complex_name'].str.contains('오션테라스|오션|테라스', na=False)][['kapt_code', 'complex_name', 'dong', 'jibun', 'households']])

# 2. Check trades for Raycounty
raw_paths = sorted((ROOT / "data/raw/trade").glob("*/*.parquet"))
frames = [pd.read_parquet(p) for p in raw_paths]
raw_all = pd.concat(frames, ignore_index=True)
print("\n=== Raw trade complex names for 레이카운티 ===")
rc_trades = raw_all[raw_all['aptNm'].str.contains('레이카운티', na=False)]
print(rc_trades[['aptNm', 'umdNm', 'jibun']].drop_duplicates().to_string())

print("\n=== Raw trade complex names for 오션테라스 ===")
ot_trades = raw_all[raw_all['aptNm'].str.contains('오션테라스', na=False)]
print(ot_trades[['aptNm', 'umdNm', 'jibun']].drop_duplicates().to_string())

print("\n=== Raw trade complex names for LG메트로 ===")
lg_trades = raw_all[raw_all['aptNm'].str.contains('메트로', na=False)]
print(lg_trades[['aptNm', 'umdNm', 'jibun']].drop_duplicates().to_string())
