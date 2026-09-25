import urllib.request
import urllib.parse
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

def search(q):
    params = urllib.parse.urlencode({'검색설정명': 'SRC_NTOTAL', '검색키워드': q, '출력갯수': '5', '페이지설정값': '1'})
    url = f'https://api.kbland.kr/land-complex/serch/intgraSerch?{params}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kbland.kr/'})
    with urllib.request.urlopen(req) as resp:
        d = json.loads(resp.read().decode('utf-8'))
        for h in d.get('dataBody', {}).get('data', {}).get('data', {}).get('HSCM', {}).get('data', []):
            cid = h.get('COMPLEX_NO')
            print(f"[{cid}] {h.get('HSCM_NM')} | {h.get('BUBADDR')} | {h.get('THS_NUM')}세대")
            q2 = urllib.parse.quote('단지기본일련번호')
            u2 = f'https://api.kbland.kr/land-complex/complex/mpriByType?{q2}={cid}'
            r2 = urllib.request.Request(u2, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kbland.kr/'})
            try:
                with urllib.request.urlopen(r2) as resp2:
                    d2 = json.loads(resp2.read().decode('utf-8'))
                    types = d2.get('dataBody', {}).get('data', [])
                    kb_sum = sum(t.get('세대수', 0) for t in types)
                    print(f"   KB mpriByType 합계: {kb_sum}세대 (타입 {len(types)}개)")
                    for t in types:
                        print(f"     {t.get('주택형타입내용')} | {t.get('전용면적')}㎡ | {t.get('세대수')}세대")
            except Exception as e:
                print('Error:', e)

if __name__ == '__main__':
    print("대신푸르지오 (K-apt: 959세대):")
    search('서대신동 대신푸르지오')
