import sys
from pathlib import Path
import pandas as pd
import numpy as np

BUSAN_DIR = Path("../busan_apartment_analysis")
sys.path.insert(0, str(BUSAN_DIR))
from src.market_cap_batch import load_trades, ROOT
from src.market_cap import read_master

master = read_master(Path("data/releases/area_master_20260918/market_cap_area_master.csv"))
raw_paths = sorted((ROOT / "data/raw/trade").glob("*/*.parquet"))
log = ROOT / "data/processed/apartment_match_log.csv"
trades, audit = load_trades(raw_paths, log)

# Test area snapping function
def snap_area_to_master(trades_df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    trades_df = trades_df.copy()
    master_groups = {code: grp['exclusive_area_sqm'].values for code, grp in master_df.groupby('kapt_code')}
    
    snapped_areas = []
    snapped_count = 0
    
    for _, row in trades_df.iterrows():
        code = row['kapt_code']
        area = row['area_sqm']
        
        candidates = master_groups.get(code, np.array([]))
        if len(candidates) > 0:
            diffs = np.abs(candidates - area)
            close_idx = np.where(diffs < 0.01)[0]
            if len(close_idx) == 1:
                snapped_areas.append(candidates[close_idx[0]])
                snapped_count += 1
                continue
        # Fallback to 2-decimal truncation
        snapped_areas.append(np.floor(area * 100) / 100)
        
    trades_df['area_sqm'] = snapped_areas
    return trades_df

d_trades = trades[trades['kapt_code'] == 'A10023975']
print(f"Dongrae trades count: {len(d_trades)}")
snapped_dongrae = snap_area_to_master(d_trades, master)
print("Snapped unique area_sqm for Dongrae:")
print(snapped_dongrae['area_sqm'].value_counts())

# Check match with master
d_master = master[master['kapt_code'] == 'A10023975']
print("\nMaster areas for Dongrae:")
print(d_master[['area_group_id', 'exclusive_area_sqm', 'type_name', 'households']])

m_areas = set(d_master['exclusive_area_sqm'])
t_areas = set(snapped_dongrae['area_sqm'])
print(f"\nAll trade areas in master? {t_areas.issubset(m_areas)}")
print(f"Trade areas: {sorted(t_areas)}")
print(f"Master areas: {sorted(m_areas)}")
print(f"Trade areas not in master: {t_areas - m_areas}")
