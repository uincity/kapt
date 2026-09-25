import sys, json, urllib.request, urllib.parse
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

df = pd.read_csv('data/review/area_master_pending.csv')
kapt_df = pd.read_csv('data/intermediate/kapt_complexes.csv')
mismatches = df[df['reason_code'] == 'HOUSEHOLDS_MISMATCH']
m = pd.merge(mismatches, kapt_df[['kapt_code', 'road_address', 'legal_address', 'approval_date']], on='kapt_code', how='left')

for _, r in m.iterrows():
    kcode = r['kapt_code']
    kname = r['kapt_name']
    khh = int(r['kapt_households'])
    kbid = str(r['kb_complex_id']).split('.')[0]
    
    q_param = urllib.parse.quote("단지기본일련번호")
    url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{q_param}={kbid}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://kbland.kr/'})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            types = data.get('dataBody', {}).get('data', [])
            kb_sum = sum(t.get('세대수', 0) for t in types)
            diff = kb_sum - khh
            print(f"[{kcode}] {kname} | K-apt: {khh}세대 | KB: {kb_sum}세대 (차이: {diff:+d}) | KB_ID: {kbid}")
            # 차이 분석
            type_summary = ", ".join(f"{t.get('전용면적')}㎡({t.get('세대수')}세대)" for t in types)
            print(f"   타입들: {type_summary}")
    except Exception as e:
        print(f"[{kcode}] {kname} Error: {e}")
