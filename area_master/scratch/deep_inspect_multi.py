import sys
from pathlib import Path
import pandas as pd

BUSAN_DIR = Path("../busan_apartment_analysis")
sys.path.insert(0, str(BUSAN_DIR))
from src.market_cap_batch import load_complexes, ROOT

# Check apartment_match_log.csv for these complexes
match_log = pd.read_csv(ROOT / "data/processed/apartment_match_log.csv")
targets = ['LG메트로', '메트로시티', '오션테라스', '레이카운티', '동래래미안']
for t in targets:
    sub = match_log[match_log['trade_complex_name'].str.contains(t, na=False) | match_log['kapt_complex_name'].str.contains(t, na=False)]
    print(f"\n--- Matches for '{t}' in apartment_match_log.csv ---")
    cols = ['kapt_code', 'trade_complex_name', 'kapt_complex_name', 'dong', 'jibun', 'match_method', 'manual_review', 'candidate_count']
    print(sub[cols].drop_duplicates().to_string())
