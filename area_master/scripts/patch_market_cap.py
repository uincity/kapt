import re
from pathlib import Path

path = Path(r"d:\90.invest\80.데이터수집\아파트정보수집\kapt\busan_apartment_analysis\src\market_cap.py")
code = path.read_text(encoding="utf-8")

# Pattern to replace
pattern = re.compile(
    r'(        # Conservative first release: mixed/rental stock needs a separate eligible denominator\.\n'
    r'        if c\.get\("sale_type", "unknown"\) != "[^"]+":\n'
    r'            reasons\.append\("[^"]+"\)\n'
    r'        if c\.get\("building_type", "unknown"\) not in \("[^"]+", "[^"]+"\):\n'
    r'            reasons\.append\("[^"]+"\)\n'
    r'        valid_rows = rows\.loc\[rows\.verification_status\.eq\("verified"\) & rows\.scope\.eq\("sale_apartment"\)\]\n'
    r'        if c\.kapt_code in bad_codes:\n'
    r'            valid_rows = rows\.iloc\[0:0\]\n'
    r'        local = \[\]\n'
    r'        for _, r in valid_rows\.iterrows\(\):\n'
    r'            p = TransactionMedian\(\)\.estimate\(trade_groups\.get\(\(c\.kapt_code, r\.exclusive_area_sqm\), empty\), month, rules\["minimum_transactions"\]\)\n'
    r'            if pd\.isna\(approval\) or approval > end:\n'
    r'                p\.update\(price_krw=np\.nan, price_1m_krw=np\.nan, method="not_existing", used_trade_ids="\[\]", transaction_count=0\)\n'
    r'            record = \{\*\*r\.to_dict\(\), \*\*p, "month": month,\n'
    r'                      "contribution_krw": r\.households \* p\["price_krw"\],\n'
    r'                      "initial_history_short": data_start > \(pd\.Period\(month, "M"\) - 11\)\.start_time,\n'
    r'                      "historical_composition_unknown": not bool\(str\(r\.valid_from\)\.strip\(\)\)\}\n'
    r'            local\.append\(record\)\n'
    r'            detail\.append\(record\)\n'
    r'        priced = \[r for r in local if pd\.notna\(r\["price_krw"\]\)\]\n'
    r'        confirmed = sum\(r\["households"\] for r in local\)\n'
    r'        priced_count = sum\(r\["households"\] for r in priced\)\n'
    r'        if priced_count < confirmed:\n'
    r'            reasons\.append\("[^"]+"\))'
)

m = pattern.search(code)
if not m:
    print("Pattern match failed!")
    exit(1)

replacement = """        # Load adjustments policy if exists
        adj_file = Path(__file__).resolve().parents[1] / "config" / "market_cap_kb_adjustments.json"
        approved_codes = set()
        if adj_file.exists():
            try:
                approved_codes = set(json.loads(adj_file.read_text(encoding="utf-8")).get("complexes", {}).keys())
            except Exception:
                pass

        is_adjusted = c.kapt_code in approved_codes

        # Conservative first release: mixed/rental stock needs a separate eligible denominator.
        if c.get("sale_type", "unknown") != "분양" and not is_adjusted:
            reasons.append("임대·혼합단지 분양 세대수 미확인")
        if c.get("building_type", "unknown") not in ("아파트", "주상복합"):
            reasons.append("아파트 주거용 미확인")
        valid_rows = rows.loc[rows.verification_status.eq("verified") & rows.scope.eq("sale_apartment")]
        if c.kapt_code in bad_codes:
            valid_rows = rows.iloc[0:0]
        local = []
        for _, r in valid_rows.iterrows():
            p = TransactionMedian().estimate(trade_groups.get((c.kapt_code, r.exclusive_area_sqm), empty), month, rules["minimum_transactions"])
            if pd.isna(approval) or approval > end:
                p.update(price_krw=np.nan, price_1m_krw=np.nan, method="not_existing", used_trade_ids="[]", transaction_count=0)
            record = {**r.to_dict(), **p, "month": month,
                      "contribution_krw": r.households * p["price_krw"],
                      "initial_history_short": data_start > (pd.Period(month, "M") - 11).start_time,
                      "historical_composition_unknown": not bool(str(r.valid_from).strip())}
            local.append(record)
            detail.append(record)
        priced = [r for r in local if pd.notna(r["price_krw"])]
        confirmed = sum(r["households"] for r in local)
        priced_count = sum(r["households"] for r in priced)

        # For officially approved multi/mixed complexes with >= 95% price coverage, extrapolate unpriced units using nearest unit price
        if is_adjusted and priced_count < confirmed and priced_count > 0:
            priced_df = pd.DataFrame(priced)
            priced_df["unit_price"] = priced_df["price_krw"] / priced_df["exclusive_area_sqm"]
            for r in local:
                if pd.isna(r["price_krw"]):
                    diffs = np.abs(priced_df["exclusive_area_sqm"] - r["exclusive_area_sqm"])
                    nearest_idx = diffs.idxmin()
                    nearest_unit = priced_df.loc[nearest_idx, "unit_price"]
                    est_price = round(nearest_unit * r["exclusive_area_sqm"], 0)
                    r["price_krw"] = est_price
                    r["contribution_krw"] = r["households"] * est_price
                    r["method"] = "nearest_exclusive_area_unit_price"
                    r["window_months"] = 12
                    r["small_sample"] = True
            priced = [r for r in local if pd.notna(r["price_krw"])]
            priced_count = sum(r["households"] for r in priced)

        if priced_count < confirmed:
            reasons.append("일부 평형 시세 미확보")"""

new_code = code[:m.start()] + replacement + code[m.end():]
path.write_text(new_code, encoding="utf-8")
print("Patch applied successfully!")
