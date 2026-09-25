import sys
from pathlib import Path
import pandas as pd
import numpy as np

BUSAN_DIR = Path("../busan_apartment_analysis")
sys.path.insert(0, str(BUSAN_DIR))
from src.market_cap_batch import ROOT
from src.market_cap import read_master

master = read_master(Path("data/releases/area_master_20260918/market_cap_area_master.csv"))

raw_paths = sorted((ROOT / "data/raw/trade").glob("*/*.parquet"))
frames = [pd.read_parquet(p) for p in raw_paths]
raw = pd.concat(frames, ignore_index=True)

# 1. 레이카운티 (거제동 1536)
rc_trades = raw[raw['aptNm'].str.contains('레이카운티', na=False)]
rc_master = master[master['kapt_code'] == 'A10022890']
print("=== RAYCOUNTY TRADES UNIQUE AREAS ===")
print(rc_trades['excluUseAr'].value_counts())
print("\n=== RAYCOUNTY MASTER UNIQUE AREAS ===")
print(rc_master[['area_group_id', 'exclusive_area_sqm', 'type_name', 'households']])

# 2. 오션테라스 (민락동 780, 781, 782, 783)
ot_trades = raw[raw['aptNm'].str.contains('오션테라스', na=False)]
ot_master = master[master['kapt_code'] == 'A10025075']
print("\n=== OCEAN TERRACE TRADES UNIQUE AREAS ===")
print(ot_trades['excluUseAr'].value_counts().head(10))
print("\n=== OCEAN TERRACE MASTER UNIQUE AREAS ===")
print(ot_master[['area_group_id', 'exclusive_area_sqm', 'type_name', 'households']])

# 3. LG메트로시티 (용호동 176-30)
lg_trades = raw[raw['aptNm'].str.contains('메트로시티', na=False)]
lg_master = master[master['kapt_code'] == 'A60809004']
print("\n=== LG METRO CITY TRADES UNIQUE AREAS ===")
print(lg_trades['excluUseAr'].value_counts().head(10))
print("\n=== LG METRO CITY MASTER UNIQUE AREAS ===")
print(lg_master[['area_group_id', 'exclusive_area_sqm', 'type_name', 'households']].head(10))
