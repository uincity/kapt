import sys
from pathlib import Path
import pandas as pd
import numpy as np

BUSAN_DIR = Path("../busan_apartment_analysis")
sys.path.insert(0, str(BUSAN_DIR))
from src.market_cap_batch import load_trades, ROOT
from src.market_cap import read_master

master = read_master(Path("data/releases/area_master_20260918/market_cap_area_master.csv"))
d_master = master[master['kapt_code'] == 'A10023975']
print("=== DONGRAE MASTER EXCLUSIVE AREAS ===")
print(d_master[['area_group_id', 'exclusive_area_sqm', 'type_name', 'households']].to_string())

raw_paths = sorted((ROOT / "data/raw/trade").glob("*/*.parquet"))
log = ROOT / "data/processed/apartment_match_log.csv"
trades, audit = load_trades(raw_paths, log)
d_trades = trades[trades['kapt_code'] == 'A10023975']
print("\n=== DONGRAE TRADES UNIQUE AREA_SQM ===")
print(d_trades['area_sqm'].value_counts())

print("\n=== CLOSEST MASTER MATCH FOR EACH TRADE AREA ===")
for trade_area, cnt in d_trades['area_sqm'].value_counts().items():
    diffs = (d_master['exclusive_area_sqm'] - trade_area).abs()
    min_diff = diffs.min()
    best_match = d_master.loc[diffs.idxmin()]
    print(f"Trade Area: {trade_area:8.4f} (count: {cnt:3d}) -> Best Master: {best_match['exclusive_area_sqm']:6.2f} (diff: {min_diff:7.4f}, type: {best_match['type_name']}, group: {best_match['area_group_id']})")
