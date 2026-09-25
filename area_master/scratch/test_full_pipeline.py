import pandas as pd
import numpy as np
import json
from pathlib import Path
import sys

sys.path.insert(0, '../busan_apartment_analysis')
from src.market_cap_kb import link_prices, estimate_kb, adjusted_valuation, MASTER_COLUMNS
from src.market_cap import read_master
from src.market_cap_batch import load_complexes

master_path = Path('data/releases/area_master_20260918/market_cap_area_master.csv')
status_path = Path('data/releases/area_master_20260918/area_master_complex_status.csv')
split_path = Path('data/qa/phase4_mixed_complex_audit.csv')
raw_path = Path('data/raw/kb/kb_area_types.csv')
adj_path = Path('../busan_apartment_analysis/config/market_cap_kb_adjustments.json')

types = read_master(master_path)
raw = pd.read_csv(raw_path, dtype=str).fillna("")
status = pd.read_csv(status_path, dtype=str).fillna("")
splits = pd.read_csv(split_path)
complexes = load_complexes()

# 1. Prepare raw rows for A10023975
import scratch.calc_weighted as cw

# Convert weighted results to raw format
# Columns: kapt_code, kapt_name, kb_complex_id, kb_complex_name, kb_url, kb_type_id,
# type_name, households, supply_area_sqm, exclusive_area_sqm, area_precision,
# kb_sale_general, kb_sale_upper, kb_sale_lower, kb_jeonse_general, kb_jeonse_upper,
# kb_jeonse_lower, kb_monthly_deposit, kb_monthly_low, kb_monthly_high, kb_price_date,
# listing_count, collected_at, source_method

new_raw_rows = []
for r in cw.results:
    new_raw_rows.append({
        'kapt_code': 'A10023975',
        'kapt_name': '동래래미안아이파크아파트',
        'kb_complex_id': '960029', # 대표 ID or 960029
        'kb_complex_name': '동래래미안아이파크',
        'kb_url': 'https://kbland.kr/map?complex=960029',
        'kb_type_id': f"type_{r['area_group_id']}",
        'type_name': r['type_name'],
        'households': str(r['master_hh']),
        'supply_area_sqm': str(r['supply_area_sqm']),
        'exclusive_area_sqm': str(r['exclusive_area_sqm']),
        'area_precision': 'display',
        'kb_sale_general': str(r['weighted_price_manwon']) if r['weighted_price_manwon'] > 0 else "",
        'kb_sale_upper': str(r['weighted_up_manwon']) if r['weighted_up_manwon'] > 0 else "",
        'kb_sale_lower': str(r['weighted_low_manwon']) if r['weighted_low_manwon'] > 0 else "",
        'kb_jeonse_general': "",
        'kb_jeonse_upper': "",
        'kb_jeonse_lower': "",
        'kb_monthly_deposit': "",
        'kb_monthly_low': "",
        'kb_monthly_high': "",
        'kb_price_date': '2026-09-18',
        'listing_count': '',
        'collected_at': '2026-09-18T10:34:28.218878',
        'source_method': 'kb_multi_complex_weighted',
    })

sim_raw = pd.concat([raw, pd.DataFrame(new_raw_rows)], ignore_index=True)
print(f"Simulated raw rows: {len(sim_raw)}")

detail = link_prices(types, sim_raw)
d_detail = detail[detail['kapt_code'] == 'A10023975']
print("\n--- LINK PRICES RESULT FOR A10023975 ---")
print(d_detail[['area_group_id', 'exclusive_area_sqm', 'type_name', 'households', 'price_krw', 'price_reason']].to_string())

totals = estimate_kb(complexes.loc[complexes.households.ge(500)], detail, status, splits)
d_totals = totals[totals['kapt_code'] == 'A10023975']
print("\n--- ESTIMATE KB RESULT FOR A10023975 ---")
print(d_totals[['kapt_code', 'complex_name', 'households', 'eligible_households', 'priced_households', 'market_cap_krw', 'status', 'reason']].to_dict('records'))

# Test with adjustment policy
policy = json.loads(adj_path.read_text(encoding='utf-8'))
policy['complexes']['A10023975'] = {
    'households': 3853,
    'scope': '전체 분양 주거 세대 (임대 포함 정밀 단가 보정)'
}

totals_adj, detail_adj = adjusted_valuation(totals, detail, policy)
d_totals_adj = totals_adj[totals_adj['kapt_code'] == 'A10023975']
print("\n--- ADJUSTED VALUATION RESULT FOR A10023975 ---")
print(d_totals_adj[['kapt_code', 'complex_name', 'households', 'eligible_households', 'priced_households', 'estimated_households', 'adjusted_market_cap_krw', 'adjusted_status', 'adjusted_scope']].to_dict('records'))
print(f"Adjusted Market Cap: {d_totals_adj['adjusted_market_cap_krw'].values[0] / 1e8:,.0f} 억원")
