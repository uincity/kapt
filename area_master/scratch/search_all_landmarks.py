import urllib.request
import urllib.parse
import json

headers = {'Referer': 'https://kbland.kr/', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def search_kb(kw):
    params = {'검색구분': 'SRC_NTOTAL', '검색키워드': kw, '요청개수': '20', '일련번호': '1'}
    url = f'https://api.kbland.kr/land-complex/serch/intgraSerch?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            items = data.get('dataBody', {}).get('data', {}).get('data', {}).get('HSCM', {}).get('data', [])
            return items
    except Exception as e:
        return [{'error': str(e)}]

keywords = [
    '해운대두산위브더제니스',
    '해운대아이파크',
    '엘시티',
    '해운대힐스테이트위브',
    'W',
    '서면센트럴스타',
    '힐스테이트이진베이시티',
    '가야역롯데캐슬스카이엘',
    '해운대경동리인뷰2차',
    '부산항일동미라주더오션',
    '오륙도SK',
    '대우마리나',
    '트럼프월드센텀',
    '더샵센텀스타'
]

for kw in keywords:
    items = search_kb(kw)
    busan = [it for it in items if '부산' in str(it.get('BUBADDR', '')) or '부산' in str(it.get('NEWADDRESS', ''))]
    print(f'=== {kw}: Found {len(busan)} Busan complexes ===')
    for it in busan:
        cno = it.get('COMPLEX_NO')
        nm = it.get('HSCM_NM')
        addr = it.get('BUBADDR')
        hh = it.get('THS_NUM')
        print(f"  [{cno}] {nm} | {addr} | {hh}세대")
