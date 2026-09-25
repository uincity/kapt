import json
import urllib.request
import urllib.parse
import pandas as pd

headers = {
    'Referer': 'https://kbland.kr/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}
param = urllib.parse.quote('단지기본일련번호')
for cid, cname in [('960029', '2단지'), ('960030', '3단지'), ('956217', '1,4단지')]:
    url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{param}={cid}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        for it in data.get('dataBody', {}).get('data', []):
            ex = it.get('전용면적')
            sup = it.get('공급면적')
            tname = it.get('주택형타입내용')
            hh = it.get('세대수')
            if '84' in str(ex) or '59' in str(ex):
                print(f"[{cname}] 전용: {ex}, 공급: {sup}, 타입: {tname}, 세대: {hh}")
