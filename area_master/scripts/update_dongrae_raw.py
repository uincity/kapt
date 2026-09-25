"""
동래래미안아이파크 (A10023975) 17개 평형별 KB 시세 데이터를 data/raw/kb/kb_area_types.csv에 반영하는 스크립트.
3개 KB 단지 (960029, 960030, 956217)의 면적/평형별 세대수 및 시세를 집계하여 마스터 규격에 정확히 연결.
"""
import sys
from pathlib import Path
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

import scratch.calc_weighted as cw

raw_path = ROOT_DIR / "data" / "raw" / "kb" / "kb_area_types.csv"
raw = pd.read_csv(raw_path, dtype=str).fillna("")

# Filter out existing if any
raw = raw[raw["kapt_code"] != "A10023975"]

new_rows = []
for r in cw.results:
    new_rows.append({
        "kapt_code": "A10023975",
        "kapt_name": "동래래미안아이파크아파트",
        "kb_complex_id": "960029",
        "kb_complex_name": "동래래미안아이파크",
        "kb_url": "https://kbland.kr/map?complex=960029",
        "kb_type_id": f"type_{r['area_group_id']}",
        "type_name": r["type_name"],
        "households": str(r["master_hh"]),
        "supply_area_sqm": str(r["supply_area_sqm"]),
        "exclusive_area_sqm": str(r["exclusive_area_sqm"]),
        "area_precision": "display",
        "kb_sale_general": str(r["weighted_price_manwon"]) if r["weighted_price_manwon"] > 0 else "",
        "kb_sale_upper": str(r["weighted_up_manwon"]) if r["weighted_up_manwon"] > 0 else "",
        "kb_sale_lower": str(r["weighted_low_manwon"]) if r["weighted_low_manwon"] > 0 else "",
        "kb_jeonse_general": "",
        "kb_jeonse_upper": "",
        "kb_jeonse_lower": "",
        "kb_monthly_deposit": "",
        "kb_monthly_low": "",
        "kb_monthly_high": "",
        "kb_price_date": "2026-09-18",
        "listing_count": "",
        "collected_at": "2026-09-18T10:34:28.218878",
        "source_method": "kb_multi_complex_weighted",
    })

updated_raw = pd.concat([raw, pd.DataFrame(new_rows)], ignore_index=True)
updated_raw.to_csv(raw_path, index=False, encoding="utf-8-sig")
print(f"Successfully wrote {len(new_rows)} rows for A10023975 to {raw_path}. Total rows: {len(updated_raw)}")
