import json
import pandas as pd
from pathlib import Path

latest = json.loads(Path('data/processed/market_cap/kb/latest.json').read_text(encoding='utf-8'))
run_id = latest['run_id']
detail = pd.read_parquet(f'data/processed/market_cap/kb/{run_id}/areas.parquet')

for code in ['A10022002', 'A10026780', 'A10024953']:
    rows = detail[detail['kapt_code'] == code]
    missing = rows[rows['price_reason'] == 'KB 일반매매가 미확보']
    print(f"\n==================== {code} ====================")
    for j, row in missing.iterrows():
        collected = pd.to_datetime(row.collected_at, errors="coerce")
        start = pd.to_datetime(row.valid_from, errors="coerce")
        end = pd.to_datetime(row.valid_to, errors="coerce")
        cond1 = pd.isna(collected)
        cond2 = pd.notna(start) and collected.normalize() < start
        cond3 = pd.notna(end) and collected.normalize() > end
        print(f"row {row.area_group_id}: collected={row.collected_at}, valid_from={row.valid_from}, valid_to={row.valid_to} -> isna={cond1}, <start={cond2}, >end={cond3}")
