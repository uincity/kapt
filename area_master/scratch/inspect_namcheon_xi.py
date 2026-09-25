# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import urllib.request
import urllib.parse
import json
import pandas as pd

raw_kb = pd.read_csv('data/raw/kb/kb_area_types.csv', dtype=str).fillna('')
sub = raw_kb[raw_kb['kapt_code'] == 'A10023420']
print(f"KB raw rows for 남천자이: {len(sub)}")
if len(sub) > 0:
    print(sub[['kb_complex_id', 'exclusive_area_sqm', 'supply_area_sqm', 'type_name', 'households', 'kb_sale_general']].to_string())

# Search KB Land for 남천자이 CID
headers = {'Referer': 'https://kbland.kr/', 'User-Agent': 'Mozilla/5.0'}
params = {'검색설정명': 'SRC_NTOTAL', '검색키워드': '남천자이', '출력갯수': '20', '페이지설정값': '1'}
url = f"https://api.kbland.kr/land-complex/serch/intgraSerch?{urllib.parse.urlencode(params)}"
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    items = data.get('dataBody', {}).get('data', {}).get('data', {}).get('HSCM', {}).get('data', [])
    print(f"\n=== Search results for 남천자이 ({len(items)}) ===")
    for it in items:
        print(f"  [{it.get('COMPLEX_NO')}] {it.get('HSCM_NM')} | {it.get('BUBADDR')} | {it.get('THS_NUM')}세대")
        cid = it.get('COMPLEX_NO')
        
# Fetch live types for cid
param = urllib.parse.quote('단지기본일련번호')
url_types = f"https://api.kbland.kr/land-complex/complex/mpriByType?{param}={cid}"
req2 = urllib.request.Request(url_types, headers=headers)
with urllib.request.urlopen(req2, timeout=10) as resp2:
    data2 = json.loads(resp2.read().decode('utf-8'))
    t_items = data2.get('dataBody', {}).get('data', [])
    print(f"\n=== Types for CID {cid} ({len(t_items)}) ===")
    tot_hh = 0
    priced_hh = 0
    for it in t_items:
        hh = int(it.get('세대수') or 0)
        pr = int(it.get('매매일반거래가') or 0)
        tot_hh += hh
        if pr > 0:
            priced_hh += hh
        print(f"  {it.get('주택형타입내용')} | {it.get('공급면적평')}평 | {it.get('전용면적')}m2 | {hh}세대 | 매매일반가: {pr:,}만원")
    print(f"Total HH: {tot_hh}, Priced HH: {priced_hh} ({priced_hh/tot_hh*100:.1f}%)")
