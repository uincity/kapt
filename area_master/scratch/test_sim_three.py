import json
import pandas as pd
from pathlib import Path

latest = json.loads(Path('data/processed/market_cap/kb/latest.json').read_text(encoding='utf-8'))
run_id = latest['run_id']
summary = pd.read_csv('data/processed/market_cap/kb/summary.csv')
detail = pd.read_parquet(f'data/processed/market_cap/kb/{run_id}/areas.parquet')

test_rules = {
    'A10022002': {
        'households': 4043,
        'scope': '전체 주거 세대 (4,043세대 보정 산정)'
    },
    'A10026780': {
        'households': 1938,
        'scope': '전체 주거 세대 (1,938세대 보정 산정)'
    },
    'A10024953': {
        'households': 1113,
        'scope': '전체 주거 세대 (1,113세대 보정 산정)'
    }
}

for code, rule in test_rules.items():
    print(f"\n==================== Testing {code} ====================")
    rows = detail[detail['kapt_code'] == code].copy()
    s_row = summary[summary['kapt_code'] == code].iloc[0]
    
    print(f"Summary households: {s_row['households']}, rule households: {rule['households']}")
    print(f"Detail households sum: {rows['households'].sum()}")
    print(f"Summary reason: {s_row['reason']}")
    
    blockers = [r for r in str(s_row['reason']).split("; ")
                if r and r not in ("임대혼합 분양 세대 확인 필요", "KB 시세 미공시 타입 존재")]
    print(f"Blockers: {blockers}")
    
    donors = rows.loc[rows.price_krw.notna() & rows.exclusive_area_sqm.gt(0)]
    print(f"Donors count: {len(donors)}, Donors hh: {donors['households'].sum()}")
    
    missing = rows.loc[rows.price_krw.isna()]
    print(f"Missing count: {len(missing)}, Missing hh: {missing['households'].sum()}")
    
    # Check kb_complex_id match
    print("Donor kb_complex_id:", donors['kb_complex_id'].unique().tolist())
    print("Missing kb_complex_id:", missing['kb_complex_id'].unique().tolist())
    
    # Simulate extrapolation
    sim_detail = rows.copy()
    sim_detail['adjusted_price_krw'] = sim_detail['price_krw']
    for j, row in missing.iterrows():
        candidates = donors.loc[donors.kb_complex_id.eq(row.kb_complex_id)]
        if candidates.empty:
            print(f"WARNING: No candidate for area_group_id={row.area_group_id}, kb_complex_id={row.kb_complex_id}")
            continue
        distance = (candidates.exclusive_area_sqm - row.exclusive_area_sqm).abs()
        nearest = candidates.loc[distance == distance.min()]
        unit = ((nearest.price_krw / nearest.exclusive_area_sqm) * nearest.households).sum() / nearest.households.sum()
        sim_detail.at[j, 'adjusted_price_krw'] = round(unit * row.exclusive_area_sqm)
        print(f"Extrapolated {row.area_group_id} ({row.exclusive_area_sqm}m2, {row.households}hh): {round(unit * row.exclusive_area_sqm / 1e8, 2)}억원 (단가 {unit/1e4:.1f}만원/m2, nearest={nearest['exclusive_area_sqm'].tolist()}m2)")
        
    total_mcap = (sim_detail['households'] * sim_detail['adjusted_price_krw']).sum()
    print(f"==> Total Adjusted Market Cap: {total_mcap / 1e8:,.1f}억원 ({total_mcap / 1e12:.2f}조원)")
    print(f"==> Average per household: {total_mcap / rule['households'] / 1e8:.2f}억원")
