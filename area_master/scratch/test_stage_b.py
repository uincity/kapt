import urllib.request
import urllib.parse
import json

def search(q):
    params = urllib.parse.urlencode({
        '검색설정명': 'SRC_NTOTAL',
        '검색키워드': q,
        '출력갯수': '10',
        '페이지설정값': '1'
    })
    url = f"https://api.kbland.kr/land-complex/serch/intgraSerch?{params}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kbland.kr/'})
    try:
        with urllib.request.urlopen(req) as resp:
            d = json.loads(resp.read().decode('utf-8'))
            hscm = d.get('dataBody', {}).get('data', {}).get('data', {}).get('HSCM', {}).get('data', [])
            print(f"Results for '{q}': {len(hscm)} items")
            for h in hscm:
                print(f"  [{h.get('COMPLEX_NO')}] {h.get('HSCM_NM')} | {h.get('BUBADDR')} | {h.get('THS_NUM')}세대 | 도로명: {h.get('NEWADDRESS')}")
    except Exception as e:
        print(f"Error for '{q}': {e}")

if __name__ == '__main__':
    print("=== Test: W 아파트 ===")
    search('용호동 더블유')
    search('분포로 145')

    print("\n=== Test: 대연힐스테이트푸르지오 ===")
    search('대연동 대연힐스테이트푸르지오')
    search('대연동 힐스테이트푸르지오')
    search('수영로 345')

    print("\n=== Test: 연제롯데캐슬데시앙 ===")
    search('연산동 연제롯데캐슬데시앙')
    search('연제롯데캐슬데시앙')
