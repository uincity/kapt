import json
import urllib.request
import urllib.parse
import pandas as pd
import numpy as np

headers = {
    'Referer': 'https://kbland.kr/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}
param = urllib.parse.quote('단지기본일련번호')
complexes = [
    ('960029', '동래래미안아이파크2단지'),
    ('960030', '동래래미안아이파크3단지'),
    ('956217', '동래래미안아이파크1,4단지')
]

parsed = []
for cid, cname in complexes:
    url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{param}={cid}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        for it in data.get('dataBody', {}).get('data', []):
            type_id = str(it.get("면적일련번호") or "")
            households = int(it.get("세대수") or 0)
            ex_sqm = float(it.get("전용면적") or 0)
            sup_sqm = float(it.get("공급면적") or 0)
            type_char = str(it.get("주택형타입내용") or "").strip()
            sup_pyeong = str(it.get("공급면적평N") or item if (item := it.get("공급면적평")) else "").strip()
            if type_char and sup_pyeong:
                type_name = f"{sup_pyeong}평{type_char}"
            elif type_char:
                type_name = f"{type_char}타입"
            elif sup_pyeong:
                type_name = f"{sup_pyeong}평"
            else:
                type_name = f"{ex_sqm}㎡"
            parsed.append({
                'cid': cid,
                'cname': cname,
                'type_id': type_id,
                'type_name': type_name,
                'households': households,
                'ex_sqm': ex_sqm,
                'sup_sqm': sup_sqm,
                'sale_gen': int(it.get("매매일반거래가") or 0),
                'sale_low': int(it.get("매매하한가") or 0),
                'sale_up': int(it.get("매매상한가") or 0),
            })

df_kb = pd.DataFrame(parsed)

master = pd.read_csv('data/releases/area_master_20260918/market_cap_area_master.csv')
d_master = master[master['kapt_code'] == 'A10023975'].copy()

results = []
for _, m in d_master.iterrows():
    matches = df_kb[
        (df_kb['ex_sqm'] == m['exclusive_area_sqm']) &
        (df_kb['sup_sqm'] == m['supply_area_sqm']) &
        (df_kb['type_name'] == m['type_name'])
    ]
    tot_hh = matches['households'].sum()
    # weighted average price
    # if sale_gen == 0 (e.g. rental or unpriced small units), handle appropriately
    priced_matches = matches[matches['sale_gen'] > 0]
    if len(priced_matches) > 0:
        weighted_price = (priced_matches['sale_gen'] * priced_matches['households']).sum() / priced_matches['households'].sum()
        weighted_low = (priced_matches['sale_low'] * priced_matches['households']).sum() / priced_matches['households'].sum()
        weighted_up = (priced_matches['sale_up'] * priced_matches['households']).sum() / priced_matches['households'].sum()
    else:
        weighted_price = 0
        weighted_low = 0
        weighted_up = 0
    results.append({
        'area_group_id': m['area_group_id'],
        'exclusive_area_sqm': m['exclusive_area_sqm'],
        'supply_area_sqm': m['supply_area_sqm'],
        'type_name': m['type_name'],
        'master_hh': m['households'],
        'kb_hh': tot_hh,
        'weighted_price_manwon': round(weighted_price, 2),
        'weighted_low_manwon': round(weighted_low, 2),
        'weighted_up_manwon': round(weighted_up, 2),
        'cids': "+".join(matches['cid'].unique()),
        'type_ids': "+".join(matches['type_id'].unique()),
    })

res_df = pd.DataFrame(results)
print(res_df.to_string())
print("\nTotal master HH:", res_df['master_hh'].sum())
print("Total KB HH:", res_df['kb_hh'].sum())
print("Total weighted market cap approx:", (res_df['master_hh'] * res_df['weighted_price_manwon'] * 10000).sum() / 1e8, "억원")
