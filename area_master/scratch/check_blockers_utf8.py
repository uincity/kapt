# -*- coding: utf-8 -*-
import pandas as pd

df = pd.read_csv('data/processed/market_cap/kb/summary.csv', encoding='utf-8')
for code in ['A10022002', 'A10026780', 'A10024953']:
    r1 = df[df['kapt_code']==code]['reason'].iloc[0]
    parts = r1.split('; ')
    allowed = ('임대혼합 분양 세대 확인 필요', 'KB 시세 미공시 타입 존재')
    blockers = [p for p in parts if p and p not in allowed]
    print(f'{code}: r1={repr(r1)}, blockers={blockers}')
