import pandas as pd
import json

import json
from pathlib import Path

targets = ['A10022002', 'A10026780', 'A10024953']

latest = json.loads(Path('data/processed/market_cap/kb/latest.json').read_text(encoding='utf-8'))
run_id = latest['run_id']
summary = pd.read_csv('data/processed/market_cap/kb/summary.csv')
detail = pd.read_parquet(f'data/processed/market_cap/kb/{run_id}/areas.parquet')
master = pd.read_csv('data/processed/market_cap/market_cap_area_master.csv')

for code in targets:
    s_row = summary[summary['kapt_code'] == code]
    d_rows = detail[detail['kapt_code'] == code]
    m_rows = master[master['kapt_code'] == code]
    
    print(f"\n==================== {code} ====================")
    if not s_row.empty:
        sr = s_row.iloc[0]
        print(f"Summary: households={sr.households}, confirmed={sr.confirmed_households}, priced={sr.priced_households}")
        print(f"Status: {sr.status}, Reason: {sr.reason}")
    else:
        print("Summary: Not found!")
        
    print(f"Detail count: {len(d_rows)}, Detail hh sum: {d_rows['households'].sum() if not d_rows.empty else 0}")
    if not d_rows.empty:
        print("Detail verification_status unique:", d_rows['verification_status'].unique().tolist())
        print("Detail scope unique:", d_rows['scope'].unique().tolist())
        print("Detail price_reason value_counts:\n", d_rows['price_reason'].value_counts().to_dict())
        print("Detail price_krw notna sum:", d_rows[d_rows['price_krw'].notna()]['households'].sum())
        print("Detail unpriced types:")
        print(d_rows[d_rows['price_krw'].isna()][['area_group_id', 'exclusive_area_sqm', 'households', 'price_reason']])
    
    print(f"Master count: {len(m_rows)}, Master hh sum: {m_rows['households'].sum() if not m_rows.empty else 0}")
    if not m_rows.empty:
        print("Master verification_status:", m_rows['verification_status'].unique().tolist())
        print("Master scope:", m_rows['scope'].unique().tolist())
