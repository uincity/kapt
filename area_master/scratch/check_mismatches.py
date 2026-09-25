import pandas as pd
import urllib.request
import urllib.parse
import json

df = pd.read_csv('data/review/area_master_pending.csv')
kapt_df = pd.read_csv('data/intermediate/kapt_complexes.csv')
mismatches = df[df['reason_code'] == 'HOUSEHOLDS_MISMATCH']
m = pd.merge(mismatches, kapt_df[['kapt_code', 'road_address', 'legal_address', 'approval_date']], on='kapt_code', how='left')

print(f"Total HOUSEHOLDS_MISMATCH complexes: {len(m)}")

for _, r in m.iterrows():
    kcode = r['kapt_code']
    kname = r['kapt_name']
    khh = r['kapt_households']
    kbid = r['kb_complex_id']
    print(f"\n[{kcode}] {kname} | K-apt: {khh}세대 | KB ID: {kbid} | 주소: {r['road_address']}")

    if pd.notna(kbid) and str(kbid).strip() and str(kbid).isdigit():
        q_param = urllib.parse.quote("단지기본일련번호")
        url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{q_param}={int(kbid)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kbland.kr/'})
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                types = data.get('dataBody', {}).get('data', [])
                kb_sum = sum(t.get('세대수', 0) for t in types)
                diff = kb_sum - khh
                print(f"  -> KB mpriByType {len(types)}개 타입, 총 {kb_sum}세대 (차이: {diff})")
                for t in types[:5]:
                    print(f"     타입: {t.get('주택형타입내용')}, 전용: {t.get('전용면적')}, 세대수: {t.get('세대수')}")
        except Exception as e:
            print(f"  -> Error fetching KB detail: {e}")
