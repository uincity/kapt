from pathlib import Path

p = Path("../busan_apartment_analysis/src/market_cap_batch.py")
text = p.read_text(encoding="utf-8")

if "def snap_trade_areas_to_master" not in text:
    func_code = """
def snap_trade_areas_to_master(trades: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    trades = trades.copy()
    master_groups = {code: grp['exclusive_area_sqm'].values for code, grp in master.groupby('kapt_code')}
    
    snapped = []
    for _, row in trades.iterrows():
        code = row['kapt_code']
        area = row['area_sqm']
        candidates = master_groups.get(code, np.array([]))
        if len(candidates) > 0:
            diffs = np.abs(candidates - area)
            close_idx = np.where(diffs < 0.01)[0]
            if len(close_idx) == 1:
                snapped.append(candidates[close_idx[0]])
                continue
        snapped.append(np.floor(area * 100) / 100)
    trades['area_sqm'] = snapped
    return trades
"""
    target = "def load_trades("
    text = text.replace(target, func_code.strip() + "\n\n\n" + target)

    target_call = "trades, audit = load_trades(raw_paths, log)"
    replace_call = "trades, audit = load_trades(raw_paths, log)\n    trades = snap_trade_areas_to_master(trades, master)"
    text = text.replace(target_call, replace_call)

    p.write_text(text, encoding="utf-8")
    print("Successfully updated market_cap_batch.py")
else:
    print("Already updated")
