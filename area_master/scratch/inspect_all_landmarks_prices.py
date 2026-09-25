# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import urllib.request
import urllib.parse
import json

headers = {'Referer': 'https://kbland.kr/', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
param = urllib.parse.quote('단지기본일련번호')

targets = {
    'A61202007': ('해운대두산위브더제니스', ['16104']),
    'A61274013': ('해운대아이파크', ['16105']),
    'A10025181': ('해운대 LCT 더샵', ['31733']),
    'A10026391': ('W 아파트(용호동)', ['29506']),
    'A61202004': ('트럼프월드센텀', ['14223']),
    'A61205003': ('더샵센텀스타', ['15822']),
    'A61403001': ('더샵센트럴스타(부전동)', ['20048']),
    'A10023790': ('힐스테이트이진베이시티', ['39443']),
    'A60809003': ('오륙도SK뷰', ['15692']),
    'A61282215': ('대우마리나1,2차', ['6106', '6107']),
    'A10023963': ('부산항일동미라주더오션', ['43695', '43696']),
    'A10020213': ('가야역롯데캐슬스카이엘', ['2136163']),
    'A10022568': ('해운대경동리인뷰2차', ['1037915']),
}

for kapt_code, (name, cids) in targets.items():
    all_items = []
    for cid in cids:
        url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{param}={cid}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                items = data.get('dataBody', {}).get('data', [])
                all_items.extend(items)
        except Exception as e:
            print(f"Error for {name} ({cid}): {e}")
            
    tot_hh = sum(int(it.get('세대수') or 0) for it in all_items)
    priced_hh = sum(int(it.get('세대수') or 0) for it in all_items if int(it.get('매매일반거래가') or 0) > 0)
    prices = [int(it.get('매매일반거래가') or 0) for it in all_items if int(it.get('매매일반거래가') or 0) > 0]
    
    print(f"=== [{name}] {kapt_code} (CIDs: {cids}) ===")
    print(f"  Types: {len(all_items)}, Total HH: {tot_hh}, Priced HH: {priced_hh} ({priced_hh/tot_hh*100:.1f}%)" if tot_hh > 0 else f"  No items")
    if prices:
        print(f"  Price range: {min(prices):,}만 ~ {max(prices):,}만원, Sample: {prices[:3]}")
