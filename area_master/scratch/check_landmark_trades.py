# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
import glob

trade_files = glob.glob("../busan_apartment_analysis/data/raw/trade/**/*.parquet", recursive=True)
dfs = []
for f in trade_files:
    try:
        df = pd.read_parquet(f)
        dfs.append(df)
    except Exception:
        pass

all_trades = pd.concat(dfs, ignore_index=True)
print(f"Total raw trades: {len(all_trades)}")

targets = ['두산위브더제니스', '아이파크', '엘시티', '센트럴스타', '이진베이시티', '오륙도']
for t in targets:
    m = all_trades[all_trades['aptNm'].str.contains(t, na=False)]
    print(f"=== Trades for {t}: {len(m)} records ===")
    if len(m) > 0:
        recent = m.sort_values(['dealYear', 'dealMonth', 'dealDay'], ascending=False).head(5)
        print(recent[['dealYear', 'dealMonth', 'dealDay', 'umdNm', 'aptNm', 'excluUseAr', 'dealAmount', 'floor']].to_string(index=False))
