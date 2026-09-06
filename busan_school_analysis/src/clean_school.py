"""Fields come from the downloaded Schoolinfo OpenAPI_Output.xlsx, sheet 0.

No production response has been observed yet. Live schema validation is mandatory.
"""
import re

import pandas as pd

from .config import provenance

LEVELS = {'02': 'elementary', '03': 'middle'}
FIELDS = {
    'school_public_id': 'SHL_IDF_CD',
    'school_id': 'SCHUL_CODE', 'school_name': 'SCHUL_NM',
    'school_type': 'HS_KND_SC_NM', 'establishment_type': 'FOND_SC_CODE',
    'gender_type': 'COEDU_SC_CODE', 'legal_dong_code': 'ADRCD_ID',
    'education_office': 'JU_ORG_NM', 'road_address': 'SCHUL_RDNMA',
    'legal_address': 'ADRES_BRKDN', 'closed': 'ABSCH_YN', 'suspended': 'CLOSE_YN',
}


def response_rows(payload):
    if not isinstance(payload, dict) or payload.get('resultCode') != 'success':
        # Never echo provider errors: some echo the authentication query.
        raise ValueError('Schoolinfo returned an unsuccessful or invalid response.')
    rows = payload.get('list')
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('Schoolinfo list schema changed.')
    return rows


def clean_schools(payload, *, year, region, level, document, collected_at):
    records = []
    for row in response_rows(payload):
        if any(not row.get(k) for k in ['SCHUL_CODE', 'SCHUL_NM', 'SCHUL_KND_SC_CODE']):
            raise ValueError('Required school fields missing; inspect the saved raw response.')
        if str(row['SCHUL_KND_SC_CODE']) != level:
            raise ValueError('Response school level differs from requested level.')
        region_code = str(row.get('ADRCD_CD') or row.get('ADRCD_ID') or '')
        if region_code and not region_code.startswith(str(region['sgg_code'])):
            raise ValueError('Response region differs from requested district.')
        record = {name: row.get(field) or None for name, field in FIELDS.items()}
        record.update(provenance(year, '학교알리미 Open API', document, collected_at))
        record.update(school_level=LEVELS[level], sido=region['sido'], sigungu=region['sigungu'],
                      source_url='https://www.schoolinfo.go.kr/openApi.do',
                      data_year_basis='collection_snapshot', school_level_code=level)
        record['address'] = record['road_address'] or ' '.join(
            str(row.get(k) or '').strip() for k in ['ADRES_BRKDN', 'DTLAD_BRKDN']).strip() or None
        # Only legal-address text; never infer legal dong from a road name.
        match = re.search(r'([가-힣0-9·]+(?:동|읍|면|리|가))(?:\s|$)', record['legal_address'] or '')
        record['legal_dong'] = match.group(1) if match else None
        lat = pd.to_numeric(row.get('LTTUD'), errors='coerce')
        lon = pd.to_numeric(row.get('LGTUD'), errors='coerce')
        valid = pd.notna(lat) and pd.notna(lon) and 34 <= lat <= 36.5 and 128 <= lon <= 130.5
        record['latitude'] = float(lat) if valid else None
        record['longitude'] = float(lon) if valid else None
        record['coordinate_source'] = 'schoolinfo' if valid else None
        reasons = []
        for field in ['school_type', 'establishment_type', 'gender_type', 'address', 'legal_dong']:
            if record[field] is None:
                reasons.append('missing_' + field)
        if not valid:
            reasons.append('missing_or_invalid_coordinates')
        if record['closed'] == 'Y' or record['suspended'] == 'Y':
            reasons.append('closed_or_suspended')
        record['review_reason'] = ';'.join(reasons)
        record['manual_review'] = bool(reasons)
        # Confidence is parser completeness, not assignment probability.
        record['confidence'] = 1.0 if not reasons else 0.5
        records.append(record)
    return pd.DataFrame(records)
