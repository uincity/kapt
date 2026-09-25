import urllib.request
import urllib.parse
import json
import pandas as pd
from decimal import Decimal

headers = {
    'Referer': 'https://kbland.kr/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}
param = urllib.parse.quote('단지기본일련번호')

def fetch_complex_types(cids):
    types = []
    for cid in cids:
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
                sup_pyeong = str(it.get("공급면적평N") or it.get("공급면적평") or "").strip()
                if type_char and sup_pyeong:
                    type_name = f"{sup_pyeong}평{type_char}"
                elif type_char:
                    type_name = f"{type_char}타입"
                elif sup_pyeong:
                    type_name = f"{sup_pyeong}평"
                else:
                    type_name = f"{ex_sqm}㎡"
                types.append({
                    'cid': cid,
                    'type_id': type_id,
                    'type_name': type_name,
                    'households': households,
                    'exclusive_area_sqm': ex_sqm,
                    'supply_area_sqm': sup_sqm,
                    'sale_gen': int(it.get("매매일반거래가") or 0),
                    'sale_low': int(it.get("매매하한가") or 0),
                    'sale_up': int(it.get("매매상한가") or 0),
                })
    return types

# 1. Ocean Terrace (38319, 38320, 38321, 38322)
ot_types = fetch_complex_types(['38319', '38320', '38321', '38322'])
df_ot = pd.DataFrame(ot_types)
print(f"=== Ocean Terrace: {len(df_ot)} types, Total HH: {df_ot['households'].sum()} ===")
ot_grp = df_ot.groupby(['exclusive_area_sqm', 'supply_area_sqm', 'type_name']).agg({
    'households': 'sum',
    'sale_gen': 'mean'
}).reset_index()
print(ot_grp.to_string())

# 2. LG Metro City (5389, 5388, 5392, 12245, 12293, 13012)
lg_types = fetch_complex_types(['5389', '5388', '5392', '12245', '12293', '13012'])
df_lg = pd.DataFrame(lg_types)
print(f"\n=== LG Metro City: {len(df_lg)} types, Total HH: {df_lg['households'].sum()} ===")
lg_grp = df_lg.groupby(['exclusive_area_sqm', 'supply_area_sqm', 'type_name']).agg({
    'households': 'sum',
    'sale_gen': 'mean'
}).reset_index()
print(lg_grp.to_string())
