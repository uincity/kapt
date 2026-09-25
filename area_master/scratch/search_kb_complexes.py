import urllib.request
import urllib.parse
import json

headers = {
    'Referer': 'https://kbland.kr/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

# Search KB for LG메트로시티 and e편한세상오션테라스
def search_kb(q):
    encoded = urllib.parse.quote(q)
    url = f"https://api.kbland.kr/land-search/search/integratedSearch?word={encoded}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        list_items = data.get('dataBody', {}).get('data', {}).get('단지목록', [])
        return list_items

print("=== SEARCH LG메트로시티 ===")
for it in search_kb("LG메트로시티"):
    print(it.get('단지기본일련번호'), it.get('단지명'), it.get('법정동명'), it.get('총세대수'))

print("\n=== SEARCH e편한세상오션테라스 ===")
for it in search_kb("오션테라스"):
    print(it.get('단지기본일련번호'), it.get('단지명'), it.get('법정동명'), it.get('총세대수'))
