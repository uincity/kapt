"""
대연힐스테이트푸르지오(A60802001) 통합 보정 및 시가총액 산정 스크립트.
"""
import json
import urllib.request
import urllib.parse
from pathlib import Path
import pandas as pd
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
BUSAN_DIR = ROOT_DIR.parent / "busan_apartment_analysis"

headers = {
    'Referer': 'https://kbland.kr/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}
param = urllib.parse.quote('단지기본일련번호')

def fetch_kb_types(cids):
    types = []
    for cid in cids:
        url = f"https://api.kbland.kr/land-complex/complex/mpriByType?{param}={cid}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for it in data.get('dataBody', {}).get('data', []):
                type_id = str(it.get("면적일련번호") or "")
                households = int(it.get("세대수") or 0)
                ex_sqm = float(it.get("전용면적") or 0)
                sup_sqm = float(it.get("공급면적") or 0)
                type_char = str(it.get("주택형타입내용") or "").strip()
                sup_pyeong = str(it.get("공급면적평N") or it.get("공급면적평") or "").strip()
                if type_char and sup_pyeong:
                    type_name = f"{sup_pyeong}평{type_char}"
                elif type_char:
                    type_name = f"{type_char}타입"
                elif sup_pyeong:
                    type_name = f"{sup_pyeong}평"
                else:
                    type_name = f"{ex_sqm}㎡"
                types.append({
                    'cid': cid,
                    'type_id': type_id,
                    'type_name': type_name,
                    'households': households,
                    'exclusive_area_sqm': ex_sqm,
                    'supply_area_sqm': sup_sqm,
                    'sale_gen': int(it.get("매매일반거래가") or 0),
                    'sale_low': int(it.get("매매하한가") or 0),
                    'sale_up': int(it.get("매매상한가") or 0),
                    'jeonse_gen': int(it.get("전세일반거래가") or 0),
                })
    return types

code = "A60802001"
kapt_name = "대연힐스테이트푸르지오"
cids = ["26745", "26888"]
rep_cid = "26745"
scope = "전체 주거 세대 (아파트 2,100세대 + 주상복합 204세대 전체 2,304세대 전수 산정)"

print(f"Fetching KB types for {kapt_name} ({'+'.join(cids)})...")
raw_types = fetch_kb_types(cids)
df_t = pd.DataFrame(raw_types)
print(f"Fetched {len(df_t)} types, total households = {df_t['households'].sum()}")

# Aggregation
agg_rows = []
for (ex_sqm, t_name), group in df_t.groupby(["exclusive_area_sqm", "type_name"], sort=False):
    hh = group["households"].sum()
    hh_eff = hh if hh > 0 else 1
    sup = round((group["supply_area_sqm"] * group["households"]).sum() / hh_eff, 2)
    if sup < ex_sqm:
        sup = ex_sqm
    gen = round((group["sale_gen"] * group["households"]).sum() / hh_eff, 0) if (group["sale_gen"] > 0).any() else 0
    low = round((group["sale_low"] * group["households"]).sum() / hh_eff, 0) if (group["sale_low"] > 0).any() else 0
    up = round((group["sale_up"] * group["households"]).sum() / hh_eff, 0) if (group["sale_up"] > 0).any() else 0
    jeon = round((group["jeonse_gen"] * group["households"]).sum() / hh_eff, 0) if (group["jeonse_gen"] > 0).any() else 0

    agg_rows.append({
        "exclusive_area_sqm": float(ex_sqm),
        "type_name": t_name,
        "households": int(hh),
        "supply_area_sqm": sup,
        "sale_gen": gen,
        "sale_low": low,
        "sale_up": up,
        "jeonse_gen": jeon,
    })
grouped = pd.DataFrame(agg_rows)

# File paths
master_rel_path = ROOT_DIR / "data/releases/area_master_20260918/market_cap_area_master.csv"
master_cfg_path = ROOT_DIR / "config/market_cap_area_master.csv"
master_busan_path = BUSAN_DIR / "config/market_cap_area_master.csv"
raw_path = ROOT_DIR / "data/raw/kb/kb_area_types.csv"
status_rel_path = ROOT_DIR / "data/releases/area_master_20260918/area_master_complex_status.csv"
status_path = ROOT_DIR / "data/status/area_master_complex_status.csv"
kb_map_path = ROOT_DIR / "data/mapping/kb_complex_mapping.csv"
kb_map_busan_path = BUSAN_DIR / "config/mapping/kb_complex_mapping.csv"
state_path = ROOT_DIR / "data/state/kb_collection_state.json"
adj_path = BUSAN_DIR / "config/market_cap_kb_adjustments.json"
split_path = ROOT_DIR / "data/qa/phase4_mixed_complex_audit.csv"

master_df = pd.read_csv(master_rel_path, dtype=str).fillna("")
raw_df = pd.read_csv(raw_path, dtype=str).fillna("")
status_df = pd.read_csv(status_path, dtype=str).fillna("") if status_path.exists() else pd.DataFrame()
status_rel_df = pd.read_csv(status_rel_path, dtype=str).fillna("")
kb_map_df = pd.read_csv(kb_map_path, dtype=str).fillna("")
state_dict = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
adj_dict = json.loads(adj_path.read_text(encoding="utf-8")) if adj_path.exists() else {"complexes": {}}
split_df = pd.read_csv(split_path)

# 1. Update master rows
master_df = master_df[master_df["kapt_code"] != code]
new_m_rows = []
for idx, r in grouped.iterrows():
    area_str = f"{r['exclusive_area_sqm']:g}".replace(".", "_")
    area_group_id = f"exclusive_{area_str}"
    if len(grouped[grouped["exclusive_area_sqm"] == r["exclusive_area_sqm"]]) > 1:
        area_group_id = f"{area_group_id}_{str(r['type_name']).replace(' ', '')}"
    new_m_rows.append({
        "kapt_code": code,
        "area_group_id": area_group_id,
        "exclusive_area_sqm": str(r["exclusive_area_sqm"]),
        "supply_area_sqm": str(r["supply_area_sqm"]),
        "type_name": r["type_name"],
        "households": str(r["households"]),
        "source": f"KB부동산 단지 시세/평형정보 ({'+'.join(cids)})",
        "verified_at": "2026-09-21",
        "valid_from": "",
        "valid_to": "",
        "verification_status": "verified",
        "scope": "sale_apartment",
        "notes": scope
    })
master_df = pd.concat([master_df, pd.DataFrame(new_m_rows)], ignore_index=True)
print(f"Added {len(new_m_rows)} master rows.")

# 2. Update raw rows
raw_df = raw_df[raw_df["kapt_code"] != code]
new_raw_rows = []
current_m = master_df[master_df["kapt_code"] == code]
for _, mr in current_m.iterrows():
    m_matches = grouped[
        (grouped["exclusive_area_sqm"] == float(mr["exclusive_area_sqm"])) &
        (grouped["type_name"] == mr["type_name"])
    ]
    if len(m_matches) == 1:
        gr = m_matches.iloc[0]
        price = int(gr["sale_gen"])
        low = int(gr["sale_low"])
        up = int(gr["sale_up"])
        jeon = int(gr["jeonse_gen"])
    else:
        price, low, up, jeon = 0, 0, 0, 0

    new_raw_rows.append({
        "kapt_code": code,
        "kapt_name": kapt_name,
        "kb_complex_id": rep_cid,
        "kb_complex_name": kapt_name,
        "kb_url": f"https://kbland.kr/map?complex={rep_cid}",
        "kb_type_id": f"type_{mr['area_group_id']}",
        "type_name": mr["type_name"],
        "households": str(mr["households"]),
        "supply_area_sqm": str(mr["supply_area_sqm"]),
        "exclusive_area_sqm": str(mr["exclusive_area_sqm"]),
        "area_precision": "display",
        "kb_sale_general": str(price) if price > 0 else "",
        "kb_sale_upper": str(up) if up > 0 else "",
        "kb_sale_lower": str(low) if low > 0 else "",
        "kb_jeonse_general": str(jeon) if jeon > 0 else "",
        "kb_jeonse_upper": "",
        "kb_jeonse_lower": "",
        "kb_monthly_deposit": "",
        "kb_monthly_low": "",
        "kb_monthly_high": "",
        "kb_price_date": "2026-09-21",
        "listing_count": "",
        "collected_at": "2026-09-21T13:30:00.000000",
        "source_method": "kb_api_verified",
    })
raw_df = pd.concat([raw_df, pd.DataFrame(new_raw_rows)], ignore_index=True)
print(f"Added {len(new_raw_rows)} raw rows.")

# 3. Update status
for s_df in [status_df, status_rel_df]:
    if s_df.empty:
        continue
    s_idx = s_df.index[s_df["kapt_code"] == code]
    if len(s_idx) == 1:
        i = s_idx[0]
        s_df.at[i, "final_status"] = "VERIFIED_MASTER"
        s_df.at[i, "master_included"] = "True"
        s_df.at[i, "excluded"] = "False"
        s_df.at[i, "pending"] = "False"
        s_df.at[i, "verification_source"] = f"KB부동산 ({'+'.join(cids)})"
        s_df.at[i, "area_row_count"] = str(len(new_m_rows))
        s_df.at[i, "notes"] = scope

# 4. Update KB Mapping
kb_idx = kb_map_df.index[kb_map_df["kapt_code"] == code]
if len(kb_idx) == 1:
    i = kb_idx[0]
    kb_map_df.at[i, "kb_complex_id"] = "+".join(cids)
    kb_map_df.at[i, "kb_name"] = kapt_name
    kb_map_df.at[i, "match_confidence"] = "exact"
    kb_map_df.at[i, "kb_households"] = "2304"
    kb_map_df.at[i, "kb_url"] = f"https://kbland.kr/map?complex={rep_cid}"

# 5. Update state dict
state_dict[code] = {
    "status": "VERIFIED",
    "kb_complex_id": "+".join(cids),
    "match_confidence": "exact",
    "attempts": 1,
    "last_error": f"KB 평형별 세대수(2304) 등록 완료 ({'+'.join(cids)})",
    "updated_at": "2026-09-21T13:40:00.000000"
}

# 6. Update adjustment policy
if "complexes" not in adj_dict:
    adj_dict["complexes"] = {}
adj_dict["complexes"][code] = {
    "households": 2304,
    "scope": scope
}

# 7. Update split audit
if code in split_df["kapt_code"].values:
    split_df = split_df[split_df["kapt_code"] != code]

split_df = pd.concat([split_df, pd.DataFrame([{
    "kapt_code": code,
    "kapt_name": kapt_name,
    "sale_households": 2304,
    "rental_households_excluded": 0,
    "kapt_households": 2304,
    "split_validity": "OFFICIALLY_SUPPORTED",
    "source_type": "KB & OFFICIAL_NOTICE"
}])], ignore_index=True)

# Save files
master_df.to_csv(master_rel_path, index=False, encoding="utf-8-sig")
master_df.to_csv(master_cfg_path, index=False, encoding="utf-8-sig")
if master_busan_path.parent.exists():
    master_df.to_csv(master_busan_path, index=False, encoding="utf-8-sig")

raw_df.to_csv(raw_path, index=False, encoding="utf-8-sig")

if not status_df.empty:
    status_df.to_csv(status_path, index=False, encoding="utf-8-sig")
status_rel_df.to_csv(status_rel_path, index=False, encoding="utf-8-sig")

kb_map_df.to_csv(kb_map_path, index=False, encoding="utf-8-sig")
kb_map_busan_path.parent.mkdir(parents=True, exist_ok=True)
kb_map_df.to_csv(kb_map_busan_path, index=False, encoding="utf-8-sig")

state_path.write_text(json.dumps(state_dict, ensure_ascii=False, indent=2), encoding="utf-8")
if adj_path.parent.exists():
    adj_path.write_text(json.dumps(adj_dict, ensure_ascii=False, indent=2), encoding="utf-8")

split_df.to_csv(split_path, index=False, encoding="utf-8-sig")

print("대연힐스테이트푸르지오 INTEGRATION COMPLETED SUCCESSFULLY!")
