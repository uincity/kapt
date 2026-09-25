# -*- coding: utf-8 -*-
import json
from pathlib import Path

adj_path = Path("../busan_apartment_analysis/config/market_cap_kb_adjustments.json")
with open(adj_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

# Add 남천자이 (A10023420)
code = "A10023420"
config["complexes"][code] = {
    "name": "남천자이아파트",
    "households": 913,
    "scope": "전체 분양 주거용 세대",
    "reason": "최상층 펜트하우스 6세대(57~63평형) KB 미고시; 인접 대형 평형(49평) 단가 기반 정상 보정"
}

with open(adj_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print("Updated market_cap_kb_adjustments.json with 남천자이 (913 households)!")
