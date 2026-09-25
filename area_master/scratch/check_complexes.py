import pandas as pd
from pathlib import Path

latest = Path('../busan_apartment_analysis/data/processed/market_cap/kb/f6360add89efdeb30006564b')
complexes = pd.read_parquet(latest / 'complexes.parquet')
for code in ['A10023963', 'A10023625', 'A10024602', 'A61481111', 'A10027690', 'A10022267', 'A10022890', 'A10028145', 'A10024318', 'A10023975']:
    c = complexes[complexes['kapt_code'] == code]
    if len(c):
        print(f"{code}: priced={c['priced_households'].values[0]}, cap={c['market_cap_krw'].values[0]}, reason={c['reason'].values[0]}")
    else:
        print(f"{code}: NOT IN COMPLEXES")
