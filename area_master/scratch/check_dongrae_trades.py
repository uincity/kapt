import sys
from pathlib import Path
import pandas as pd

BUSAN_DIR = Path("../busan_apartment_analysis")
sys.path.insert(0, str(BUSAN_DIR))
from src.market_cap_batch import load_trades, ROOT

raw_paths = sorted((ROOT / "data/raw/trade").glob("*/*.parquet"))
log = ROOT / "data/processed/apartment_match_log.csv"
trades, audit = load_trades(raw_paths, log)

dongrae_trades = trades[trades['kapt_code'] == 'A10023975']
print(f"Total Dongrae trades: {len(dongrae_trades)}")
if len(dongrae_trades) > 0:
    print("\nArea distribution in Dongrae trades:")
    print(dongrae_trades['area_sqm'].value_counts())
    print("\nSample Dongrae trades:")
    print(dongrae_trades[['deal_date', 'area_sqm', 'floor', 'deal_amount_krw', 'complex_name']].head(10).to_string())
else:
    print("Checking if complex_name has 동래래미안 in all trades:")
    sub = trades[trades['complex_name'].str.contains('래미안아이파크|동래래미안', na=False)]
    print(f"Found {len(sub)} trades with name match:")
    print(sub[['kapt_code', 'complex_name', 'dong', 'jibun', 'area_sqm']].head(10).to_string())
