import sys
from pathlib import Path
import pandas as pd

BUSAN_DIR = Path("../busan_apartment_analysis")
sys.path.insert(0, str(BUSAN_DIR))
from src.market_cap_batch import load_trades, ROOT

raw_paths = sorted((ROOT / "data/raw/trade").glob("*/*.parquet"))
log = ROOT / "data/processed/apartment_match_log.csv"
trades, audit = load_trades(raw_paths, log)

print("=== VERIFY MATCHED TRADES COUNT ===")
for code, name in [
    ('A10023975', '동래래미안아이파크'),
    ('A10022890', '레이카운티'),
    ('A10025075', 'e편한세상오션테라스'),
    ('A60809004', 'LG메트로시티'),
]:
    sub = trades[trades['kapt_code'] == code]
    print(f"[{code}] {name}: {len(sub)} trades matched! (unique complex names in trade: {sub['complex_name'].unique().tolist()})")
