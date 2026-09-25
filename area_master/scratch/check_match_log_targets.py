import pandas as pd
from pathlib import Path

ROOT = Path("../busan_apartment_analysis")
match_log_path = ROOT / "data/processed/apartment_match_log.csv"
log = pd.read_csv(match_log_path, dtype=str).fillna("")

print(f"Total rows in match log: {len(log)}")

# 1. Check Raycounty (거제동 1536, lawd_cd: 26470)
# Trade names in raw: 레이카운티(1단지), 레이카운티(2단지), 레이카운티(3단지), 레이카운티(4단지), 레이카운티(5단지)
print("\n--- Current Raycounty rows in match log ---")
rc = log[log['trade_complex_name'].str.contains('레이카운티', na=False)]
print(rc[['lawd_cd', 'dong', 'jibun', 'complex_name_normalized', 'trade_complex_name', 'kapt_code', 'match_method', 'manual_review', 'candidate_count']])

# 2. Check Ocean Terrace (민락동 780, 781, 782, 783, lawd_cd: 26500)
print("\n--- Current Ocean Terrace rows in match log ---")
ot = log[log['trade_complex_name'].str.contains('오션테라스', na=False)]
print(ot[['lawd_cd', 'dong', 'jibun', 'complex_name_normalized', 'trade_complex_name', 'kapt_code', 'match_method', 'manual_review', 'candidate_count']])

# 3. Check LG Metro City (용호동 176-30, lawd_cd: 26290)
print("\n--- Current LG Metro rows in match log ---")
lg = log[log['trade_complex_name'].str.contains('메트로시티', na=False)]
print(lg[['lawd_cd', 'dong', 'jibun', 'complex_name_normalized', 'trade_complex_name', 'kapt_code', 'match_method', 'manual_review', 'candidate_count']])
