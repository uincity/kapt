import urllib.request
import urllib.parse
import json

headers = {
    'Referer': 'https://kbland.kr/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}
param = urllib.parse.quote('단지기본일련번호')
cid = '956217'
url = f'https://api.kbland.kr/land-complex/complex/mpriByType?{param}={cid}'
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read().decode('utf-8'))
    for it in data.get('dataBody', {}).get('data', []):
        print(it.get('면적일련번호'), it.get('공급면적'), it.get('전용면적'), it.get('주택형타입내용'), it.get('세대수'),
              '매매:', it.get('매매일반거래가'), '전세:', it.get('전세일반거래가'), '월세:', it.get('월세보증금액'), it.get('월임대최저금액'))
