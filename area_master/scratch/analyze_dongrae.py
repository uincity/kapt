import json
import urllib.request
import urllib.parse
from decimal import Decimal
import pandas as pd
from pathlib import Path

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

parsed_types = []

for cid, cname in complexes:
    # Get price date
    price_date = ""
    try:
        base_prc_url = f"https://api.kbland.kr/land-price/price/BasePrcInfoNew?{param}={cid}"
        req = urllib.request.Request(base_prc_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            sise = data.get('dataBody', {}).get('data', {}).get('시세', [])
            if sise:
                raw_date = sise[0].get('시세기준년월일') or sise[0].get('기준년월일') or ""
                if len(raw_date) == 8:
                    price_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    except Exception as e:
        print(f"Error fetching price date for {cid}: {e}")

    api_url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{param}={cid}"
    req = urllib.request.Request(api_url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        items = data.get('dataBody', {}).get('data', [])
        print(f"[{cid}] {cname}: {len(items)} items, price_date: {price_date}")
        for item in items:
            type_id = str(item.get("면적일련번호") or "")
            households = int(item.get("세대수") or 0)
            ex_sqm = float(item.get("전용면적") or 0)
            sup_sqm = float(item.get("공급면적") or 0)
            type_char = str(item.get("주택형타입내용") or "").strip()
            sup_pyeong = str(item.get("공급면적평N") or item.get("공급면적평") or "").strip()
            if type_char and sup_pyeong:
                type_name = f"{sup_pyeong}평{type_char}"
            elif type_char:
                type_name = f"{type_char}타입"
            elif sup_pyeong:
                type_name = f"{sup_pyeong}평"
            else:
                type_name = f"{ex_sqm}㎡"

            kb_sale_general = int(item.get("매매일반거래가") or 0)
            kb_sale_upper = int(item.get("매매상한가") or 0)
            kb_sale_lower = int(item.get("매매하한가") or 0)

            parsed_types.append({
                'kb_complex_id': cid,
                'kb_complex_name': cname,
                'kb_type_id': type_id,
                'type_name': type_name,
                'households': households,
                'exclusive_area_sqm': ex_sqm,
                'supply_area_sqm': sup_sqm,
                'kb_sale_general': kb_sale_general,
                'kb_sale_upper': kb_sale_upper,
                'kb_sale_lower': kb_sale_lower,
                'kb_price_date': price_date,
            })

df_parsed = pd.DataFrame(parsed_types)
print(f"\nTotal parsed types: {len(df_parsed)}")
print(f"Total households: {df_parsed['households'].sum()}")

# Load master rows for A10023975
master = pd.read_csv('data/releases/area_master_20260918/market_cap_area_master.csv')
d_master = master[master['kapt_code'] == 'A10023975']
print(f"\nMaster rows: {len(d_master)}, Total master households: {d_master['households'].sum()}")

print("\n--- MASTER ROWS vs PARSED KB TYPES ---")
for _, m_row in d_master.iterrows():
    matches = df_parsed[
        (df_parsed['exclusive_area_sqm'] == m_row['exclusive_area_sqm']) &
        (df_parsed['supply_area_sqm'] == m_row['supply_area_sqm']) &
        (df_parsed['type_name'] == m_row['type_name'])
    ]
    sum_h = matches['households'].sum()
    matched_ids = matches['kb_complex_id'].tolist()
    print(f"Master: {m_row['area_group_id']} | {m_row['exclusive_area_sqm']}m2 / {m_row['supply_area_sqm']}m2 | {m_row['type_name']} | {m_row['households']}세대 -> Matched {len(matches)} KB types (sum hh: {sum_h}, cids: {matched_ids})")
