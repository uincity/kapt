# -*- coding: utf-8 -*-
"""
삼익비치(A61301003) 및 95% 이상 고커버리지 소수 평형 미거래 단지 일괄 보정 스크립트
"""
import json
from pathlib import Path
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
BUSAN_DIR = ROOT_DIR.parent / "busan_apartment_analysis"

# 1. Patch market_cap.py in busan_apartment_analysis if not already patched
mc_path = BUSAN_DIR / "src/market_cap.py"
mc_code = mc_path.read_text(encoding="utf-8")

old_str = '    approved_codes = set(rules.get("approved_multi_complexes", []))'
new_str = '''    approved_codes = set(rules.get("approved_multi_complexes", []))
    adj_file = Path(__file__).resolve().parents[1] / "config" / "market_cap_kb_adjustments.json"
    if adj_file.exists():
        try:
            approved_codes |= set(json.loads(adj_file.read_text(encoding="utf-8")).get("complexes", {}).keys())
        except Exception:
            pass'''

if old_str in mc_code and "adj_file = Path(__file__)" not in mc_code:
    mc_code = mc_code.replace(old_str, new_str, 1)
    mc_path.write_text(mc_code, encoding="utf-8")
    print("[1] Successfully patched market_cap.py to load adjustments JSON.")
else:
    print("[1] market_cap.py already patched or target string modified.")

# 2. Identify 95%+ coverage pure minor unpriced complexes from the latest 2026-08 run
manifest = json.loads((BUSAN_DIR / "data/processed/market_cap/manifest.json").read_text(encoding="utf-8"))
# Find latest run for 2026-08
runs_2026_08 = manifest.get("months", {}).get("2026-08", [])
latest_run_id = runs_2026_08[-1]["run_id"] if runs_2026_08 else "a58ea16fb4adf045b2af2aa3"
print(f"Using base run_id: {latest_run_id}")

df_c = pd.read_parquet(BUSAN_DIR / f"data/processed/market_cap/2026-08/{latest_run_id}/complexes.parquet")
kapt_clean = pd.read_parquet(BUSAN_DIR / "data/raw/kapt/busan_complexes.parquet")
code_to_name = dict(zip(kapt_clean["kaptCode"], kapt_clean["kaptName"]))

# Candidates: coverage >= 0.95 and unpriced due to '일부 평형 시세 미확보' only (or 삼익비치)
unpriced = df_c[df_c["market_cap_krw"].isna()].copy()
candidates = unpriced[
    ((unpriced["reason"] == "일부 평형 시세 미확보") & (unpriced["price_coverage"] >= 0.95)) |
    (unpriced["kapt_code"] == "A61301003")
].copy()

print(f"[2] Found {len(candidates)} complexes to calibrate (including 삼익비치).")

# 3. Update market_cap_kb_adjustments.json in both directories
adj_paths = [
    ROOT_DIR / "config/market_cap_kb_adjustments.json",
    BUSAN_DIR / "config/market_cap_kb_adjustments.json"
]

for ap in adj_paths:
    if ap.exists():
        data = json.loads(ap.read_text(encoding="utf-8"))
    else:
        data = {"version": "approved-price-adjustments-v2", "method": "nearest_exclusive_area_unit_price", "complexes": {}}
    
    if "complexes" not in data:
        data["complexes"] = {}
        
    for _, row in candidates.iterrows():
        code = row["kapt_code"]
        name = code_to_name.get(code, row["complex_name"])
        hh = int(row["households"])
        priced_hh = int(row["priced_households"])
        cov = row["price_coverage"]
        data["complexes"][code] = {
            "name": name,
            "households": hh,
            "scope": f"전체 주거 세대 ({hh:,}세대 전수 산정, 커버리지 {cov*100:.1f}%, 소수 평형 인접 외삽)",
            "reason": f"실거래 {priced_hh:,}/{hh:,}세대 확보 ({cov*100:.1f}%), 결측 소수 평형 인접 전용단가 외삽 적용"
        }
    
    ap.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[3] Updated adjustments JSON at: {ap} (Total complexes: {len(data['complexes'])})")

# 4. Also add candidate codes to market_cap.json approved_multi_complexes for double safety
rule_path = BUSAN_DIR / "config/market_cap.json"
rule_data = json.loads(rule_path.read_text(encoding="utf-8"))
approved_list = set(rule_data.get("approved_multi_complexes", []))
for code in candidates["kapt_code"]:
    approved_list.add(code)
rule_data["approved_multi_complexes"] = sorted(list(approved_list))
rule_path.write_text(json.dumps(rule_data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[4] Updated market_cap.json approved_multi_complexes (Total: {len(rule_data['approved_multi_complexes'])})")
