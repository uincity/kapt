import urllib.request
import urllib.parse
import json

def search(q):
    params = urllib.parse.urlencode({'검색설정명': 'SRC_NTOTAL', '검색키워드': q, '출력갯수': '5', '페이지설정값': '1'})
    url = f'https://api.kbland.kr/land-complex/serch/intgraSerch?{params}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kbland.kr/'})
    try:
        with urllib.request.urlopen(req) as resp:
            d = json.loads(resp.read().decode('utf-8'))
            hscm = d.get('dataBody', {}).get('data', {}).get('data', {}).get('HSCM', {}).get('data', [])
            print(f"Results for '{q}': {len(hscm)} items")
            for h in hscm:
                print(f"  [{h.get('COMPLEX_NO')}] {h.get('HSCM_NM')} | {h.get('BUBADDR')} | {h.get('THS_NUM')}세대 | {h.get('NEWADDRESS')}")
    except Exception as e:
        print(f"Error for '{q}': {e}")

if __name__ == '__main__':
    print("1. 오륙도로 85:")
    search('오륙도로 85')

    print("\n2. 용당동 아이파크:")
    search('용당동 아이파크')

    print("\n3. 온천서로 65:")
    search('온천서로 65')

    print("\n4. 당감동 주공:")
    search('당감동 주공')
