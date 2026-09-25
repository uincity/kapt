import urllib.request
import urllib.parse
import json

headers = {'Referer': 'https://kbland.kr/', 'User-Agent': 'Mozilla/5.0'}
def search(q):
    params = {'검색설정명': 'SRC_NTOTAL', '검색키워드': q, '출력갯수': '20', '페이지설정값': '1'}
    url = f"https://api.kbland.kr/land-complex/serch/intgraSerch?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        d = data.get('dataBody', {}).get('data', {})
        print(f"[{q}] Response top keys:", list(d.keys()))
        if '단지' in d:
            for item in d['단지']:
                print(" ", item.get('단지기본일련번호'), item.get('단지명'), item.get('법정동명'), item.get('총세대수'))
        elif 'data' in d and isinstance(d['data'], dict):
            for k, v in d['data'].items():
                print(f"  sub-key {k}:")
                if isinstance(v, list):
                    for item in v[:5]:
                        if isinstance(item, dict):
                            print("   ", item.get('단지기본일련번호'), item.get('단지명'), item.get('법정동명'), item.get('총세대수'))

search("LG메트로시티")
search("오션테라스")
