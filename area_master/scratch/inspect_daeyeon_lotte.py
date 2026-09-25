# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import urllib.request
import urllib.parse
import json

headers = {'Referer': 'https://kbland.kr/', 'User-Agent': 'Mozilla/5.0'}
param = urllib.parse.quote('단지기본일련번호')
cid = '26365'
url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{param}={cid}"
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    items = data.get('dataBody', {}).get('data', [])
    print(f"=== Types for 대연롯데캐슬 (CID {cid}, {len(items)} items) ===")
    tot_hh = 0
    priced_hh = 0
    for it in items:
        hh = int(it.get('세대수') or 0)
        pr = int(it.get('매매일반거래가') or 0)
        tot_hh += hh
        if pr > 0:
            priced_hh += hh
        print(f"  {it.get('면적일련번호')} | {it.get('주택형타입내용')} | {it.get('공급면적평')}평 | {it.get('전용면적')}m2 | {it.get('공급면적')}m2 | {hh}세대 | 매매일반가: {pr:,}만원")
    print(f"Total HH: {tot_hh}, Priced HH: {priced_hh}")
