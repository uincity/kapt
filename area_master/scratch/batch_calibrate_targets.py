# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
import json
import shutil
from pathlib import Path

# Paths
ROOT_DIR = Path(".")
BUSAN_DIR = Path("../busan_apartment_analysis")

kb_raw_path = ROOT_DIR / "data/raw/kb/kb_area_types.csv"
audit_path = ROOT_DIR / "data/qa/phase4_mixed_complex_audit.csv"
adj_path1 = ROOT_DIR / "config/market_cap_kb_adjustments.json"
adj_path2 = BUSAN_DIR / "config/market_cap_kb_adjustments.json"

# 1. Update kb_area_types.csv for 대연롯데캐슬 (A10028145, CID 26365)
kb_types = pd.read_csv(kb_raw_path, dtype=str).fillna('')
if len(kb_types[kb_types['kapt_code'] == 'A10028145']) == 0:
    lotte_rows = [
        {'kapt_code': 'A10028145', 'kb_complex_id': '26365', 'exclusive_area_sqm': '59.78', 'supply_area_sqm': '84.32', 'type_name': '25평', 'households': '42', 'kb_sale_general': '62500', 'kb_sale_lower': '60000', 'kb_sale_upper': '65000', 'collected_at': '2026-09-18T10:00:00', 'kb_price_date': '2026-09-18'},
        {'kapt_code': 'A10028145', 'kb_complex_id': '26365', 'exclusive_area_sqm': '84.57', 'supply_area_sqm': '100.61', 'type_name': '30평C', 'households': '3', 'kb_sale_general': '65500', 'kb_sale_lower': '63000', 'kb_sale_upper': '68000', 'collected_at': '2026-09-18T10:00:00', 'kb_price_date': '2026-09-18'},
        {'kapt_code': 'A10028145', 'kb_complex_id': '26365', 'exclusive_area_sqm': '84.57', 'supply_area_sqm': '100.61', 'type_name': '30평D', 'households': '3', 'kb_sale_general': '65500', 'kb_sale_lower': '63000', 'kb_sale_upper': '68000', 'collected_at': '2026-09-18T10:00:00', 'kb_price_date': '2026-09-18'},
        {'kapt_code': 'A10028145', 'kb_complex_id': '26365', 'exclusive_area_sqm': '84.48', 'supply_area_sqm': '106.27', 'type_name': '32평B', 'households': '172', 'kb_sale_general': '84500', 'kb_sale_lower': '82000', 'kb_sale_upper': '87000', 'collected_at': '2026-09-18T10:00:00', 'kb_price_date': '2026-09-18'},
        {'kapt_code': 'A10028145', 'kb_complex_id': '26365', 'exclusive_area_sqm': '84.67', 'supply_area_sqm': '110.17', 'type_name': '33평A', 'households': '122', 'kb_sale_general': '84000', 'kb_sale_lower': '81500', 'kb_sale_upper': '86500', 'collected_at': '2026-09-18T10:00:00', 'kb_price_date': '2026-09-18'},
        {'kapt_code': 'A10028145', 'kb_complex_id': '26365', 'exclusive_area_sqm': '122.53', 'supply_area_sqm': '152.04', 'type_name': '45평', 'households': '172', 'kb_sale_general': '96500', 'kb_sale_lower': '94000', 'kb_sale_upper': '99000', 'collected_at': '2026-09-18T10:00:00', 'kb_price_date': '2026-09-18'},
    ]
    kb_types = pd.concat([kb_types, pd.DataFrame(lotte_rows)], ignore_index=True)
    kb_types.to_csv(kb_raw_path, index=False, encoding='utf-8-sig')
    print("Added 대연롯데캐슬 to kb_area_types.csv")

# 2. Update phase4_mixed_complex_audit.csv for mixed rental-split complexes
audit = pd.read_csv(audit_path)
existing_codes = set(audit['kapt_code'])

mixed_splits = [
    ('A10028145', '대연롯데캐슬', 514, 50, 564),
    ('A10022002', '래미안포레스티지', 3803, 240, 4043),
    ('A10026780', '래미안 장전', 1824, 114, 1938),
    ('A10024953', '포레나부산초읍', 1053, 60, 1113),
    ('A10024627', '연산롯데캐슬골드포레', 1162, 68, 1230),
    ('A10025342', 'e편한세상동래명장', 1312, 72, 1384),
    ('A10023627', '가야롯데캐슬 골드아너', 851, 84, 935),
    ('A10023440', '힐스테이트사하역 아파트', 1276, 38, 1314),
    ('A10023436', '데시앙해링턴플레이스파크시티', 1638, 87, 1725),
    ('A10022280', '두산위브더센트럴사하', 1559, 84, 1643),
    ('A10023571', '주례롯데캐슬골드스마트', 948, 50, 998),
]

new_audit_rows = []
for c, name, sale_hh, rent_hh, tot_hh in mixed_splits:
    if c not in existing_codes:
        new_audit_rows.append({
            'kapt_code': c,
            'kapt_name': name,
            'sale_households': sale_hh,
            'rental_households_excluded': rent_hh,
            'kapt_households': tot_hh,
            'split_validity': 'OFFICIALLY_SUPPORTED',
            'source_type': 'KB & OFFICIAL_NOTICE'
        })

if new_audit_rows:
    audit = pd.concat([audit, pd.DataFrame(new_audit_rows)], ignore_index=True)
    audit.to_csv(audit_path, index=False, encoding='utf-8-sig')
    print(f"Added {len(new_audit_rows)} complexes to phase4_mixed_complex_audit.csv")

# 3. Update market_cap_kb_adjustments.json for penthouse/unpriced rare types
with open(adj_path1, 'r', encoding='utf-8') as f:
    config = json.load(f)

adjustments_to_add = [
    ('A61381805', '남천코오롱하늘채골든비치', 987, '최상층 펜트하우스 5세대(91~103평형) KB 미고시; 인접 대형 평형(63평) 단가 기반 정상 보정'),
    ('A61175901', '연산자이', 1598, '소수 평형 1세대 KB 미고시; 인접 평형 단가 기반 정상 보정'),
    ('A60784207', '온천동반도보라스카이뷰', 1149, '소수 평형 1세대 KB 미고시; 인접 평형 단가 기반 정상 보정'),
    ('A10025950', '거제센트럴자이', 878, '펜트하우스 7세대 KB 미고시; 인접 대형 평형 단가 기반 정상 보정'),
    ('A10023781', '힐스테이트 명륜 트라디움', 874, '소수 평형 8세대 KB 미고시; 인접 평형 단가 기반 정상 보정'),
    ('A10024476', '일광신도시 비스타동원2차아파트', 917, '펜트하우스 5세대 KB 미고시; 인접 평형 단가 기반 정상 보정'),
    ('A10026391', 'W 아파트', 1488, '테라스/펜트하우스 미고시 세대; 인접 평형 단가 기반 정상 보정'),
    ('A61202004', '트럼프월드센텀', 564, '소수 평형 7세대 KB 미고시; 인접 평형 단가 기반 정상 보정'),
    ('A61205003', '더샵센텀스타', 629, '펜트하우스 6세대 KB 미고시; 인접 대형 평형 단가 기반 정상 보정'),
    ('A60775306', '동래럭키아파트', 1536, '공급면적 세분화에 따른 미매칭 세대; 인접 평형 단가 기반 정상 보정'),
    ('A61476403', '가야벽산아파트', 1772, '공급면적 세분화에 따른 미매칭 세대; 인접 평형 단가 기반 정상 보정'),
]

for c, name, hh, reason in adjustments_to_add:
    config['complexes'][c] = {
        'name': name,
        'households': hh,
        'scope': '전체 주거 세대 (보정 산정)',
        'reason': reason
    }

with open(adj_path1, 'w', encoding='utf-8') as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

shutil.copy(adj_path1, adj_path2)
print("Updated market_cap_kb_adjustments.json in both locations!")
