import urllib.request
import urllib.parse
import json

headers = {'Referer': 'https://kbland.kr/', 'User-Agent': 'Mozilla/5.0'}
for q in ['LG메트로시티', '오션테라스']:
    params = {'검색설정명': 'SRC_NTOTAL', '검색키워드': q, '출력갯수': '20', '페이지설정값': '1'}
    url = f"https://api.kbland.kr/land-complex/serch/intgraSerch?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        items = data.get('dataBody', {}).get('data', {}).get('data', {}).get('HSCM', {}).get('data', [])
        print(f"=== {q} ({len(items)} items) ===")
        tot_hh = 0
        for it in items:
            cno = it.get('COMPLEX_NO')
            name = it.get('HSCM_NM')
            addr = it.get('BUBADDR')
            hh = int(it.get('THS_NUM') or 0)
            road = it.get('NEWADDRESS')
            if '용호동' in str(addr) or '민락동' in str(addr):
                print(f"  [{cno}] {name} | {addr} {it.get('ARNO')} | {hh}세대 | {road}")
                tot_hh += hh
        print(f"  Total households in district: {tot_hh}")
