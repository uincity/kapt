import pandas as pd
from pathlib import Path

ROOT = Path("../busan_apartment_analysis")
match_log_path = ROOT / "data/processed/apartment_match_log.csv"
log = pd.read_csv(match_log_path, dtype=str).fillna("")

print(f"Original match log rows: {len(log)}")

# 1. Update Ocean Terrace 2, 3, 4 단지
ot_mask = log['trade_complex_name'].str.contains('오션테라스', na=False) & log['trade_complex_name'].isin([
    'e편한세상오션테라스2단지', 'e편한세상오션테라스3단지', 'e편한세상오션테라스4단지'
])
print(f"Updating {ot_mask.sum()} Ocean Terrace rows to verified...")
log.loc[ot_mask, 'manual_review'] = 'False'
log.loc[ot_mask, 'candidate_count'] = '1'
log.loc[ot_mask, 'match_method'] = 'road_address_exact'
log.loc[ot_mask, 'match_score'] = '100'

# 2. Add Raycounty 1, 2, 3, 5 단지
# Reference from Raycounty 4단지:
rc_ref = log[log['trade_complex_name'].eq('레이카운티(4단지)')].iloc[0].to_dict()
new_rc_rows = []
for danji in ['1단지', '2단지', '3단지', '5단지']:
    t_name = f"레이카운티({danji})"
    norm_name = "레이카운티" + danji.replace("단지", "")
    # Check if already present
    if not log['trade_complex_name'].eq(t_name).any():
        row = dict(rc_ref)
        row['trade_complex_name'] = t_name
        row['complex_name_normalized'] = f"레이카운티{danji}" # normalized
        new_rc_rows.append(row)
        print(f"Adding {t_name} to match log...")

# 3. Add LG Metro City 4-2(230~238)
lg_ref = log[log['trade_complex_name'].str.contains('메트로시티', na=False)].iloc[0].to_dict()
new_lg_rows = []
for t_name in ['메트로시티4-2(230~238)']:
    if not log['trade_complex_name'].eq(t_name).any():
        row = dict(lg_ref)
        row['trade_complex_name'] = t_name
        row['complex_name_normalized'] = "메트로시티42230238"
        new_lg_rows.append(row)
        print(f"Adding {t_name} to match log...")

if new_rc_rows or new_lg_rows:
    log = pd.concat([log, pd.DataFrame(new_rc_rows + new_lg_rows)], ignore_index=True)

# Remove duplicates on KEY if any
KEY = ["lawd_cd", "dong", "jibun", "complex_name_normalized"]
dup = log.duplicated(KEY, keep="first")
if dup.any():
    print(f"Warning: {dup.sum()} duplicates on KEY, keeping first")
    log = log.loc[~dup]

log.to_csv(match_log_path, index=False, encoding="utf-8-sig")
print(f"Updated match log rows: {len(log)}")
