# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import urllib.request
import urllib.parse
import json

headers = {'Referer': 'https://kbland.kr/', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def search(q):
    params = {'검색설정명': 'SRC_NTOTAL', '검색키워드': q, '출력갯수': '20', '페이지설정값': '1'}
    url = f'https://api.kbland.kr/land-complex/serch/intgraSerch?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            items = data.get('dataBody', {}).get('data', {}).get('data', {}).get('HSCM', {}).get('data', [])
            return items
    except Exception as e:
        print(f"Error {q}: {e}")
        return []

keywords = [
    '두산위브더제니스',
    '해운대아이파크',
    '엘시티',
    '서면센트럴스타',
    '힐스테이트이진베이시티',
    '오륙도SK',
    '대우마리나',
    '경동리인뷰2차',
    '일동미라주더오션',
    '가야역롯데캐슬',
    '트럼프월드센텀',
    '센텀스타',
    '더더블유'
]

for q in keywords:
    items = search(q)
    print(f"=== {q} ({len(items)} found) ===")
    for it in items:
        addr = str(it.get('BUBADDR', ''))
        cno = it.get('COMPLEX_NO')
        nm = it.get('HSCM_NM')
        hh = it.get('THS_NUM')
        road = it.get('NEWADDRESS')
        if any(g in addr for g in ['부산', '해운대', '남구', '부산진구', '서구', '동구', '수영구']):
            print(f"  [{cno}] {nm} | {addr} | {hh}세대 | {road}")
