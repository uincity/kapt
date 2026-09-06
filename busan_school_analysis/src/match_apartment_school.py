from difflib import SequenceMatcher
import math
from pathlib import Path
import re
import unicodedata

import pandas as pd

from .config import ROOT, now, write_csv, write_parquet


def normalize_complex_name(value):
    value = unicodedata.normalize('NFKC', str(value or '')).lower()
    value = re.sub(r'\(주\)|주식회사', '', value)
    value = re.sub(r'(?<![a-z])(iii|ii|iv|i)\s*차', lambda m: str({'i': 1, 'ii': 2, 'iii': 3, 'iv': 4}[m[1]]) + '차', value)
    value = re.sub(r'제\s*(\d+)\s*차', r'\1차', value)
    value = re.sub(r'(\d+)\s*차', r'\1차', value)
    value = re.sub(r'\(\s*([^()]*)\s*\)', r'\1', value)
    value = re.sub(r'㈜|\(주\)|주식회사', '', value)
    value = re.sub(r'아파트단지|아파트|apt\.?', '', value, flags=re.I)
    return re.sub(r'[^0-9a-z가-힣]', '', value)


def name_similarity(raw_name, candidate_name):
    raw, candidate = normalize_complex_name(raw_name), normalize_complex_name(candidate_name)
    if not raw or not candidate:
        return 0.0
    if raw == candidate:
        return 1.0
    phases = [re.findall(r'(\d+)차', name) for name in (raw, candidate)]
    if all(phases) and phases[0] != phases[1]:
        return 0.0
    ratio = SequenceMatcher(None, raw, candidate).ratio()
    if raw in candidate or candidate in raw:
        ratio = max(ratio, 0.9 + 0.1 * min(len(raw), len(candidate)) / max(len(raw), len(candidate)))
    return round(min(1.0, ratio), 4)


def _base_dong(value):
    return re.sub(r'\d+(?=동$)', '', str(value or '').replace(' ', ''))


def address_similarity(catchment_dong, apartment):
    expected = _base_dong(catchment_dong)
    legal = _base_dong(apartment.get('legal_dong'))
    dong = _base_dong(apartment.get('dong'))
    if expected and expected in {legal, dong}:
        address = str(apartment.get('legal_address') or apartment.get('address') or '')
        if address and address != 'nan' and '해운대구' in address and expected in address:
            return 0.8  # A legal dong is not confirmation of administrative dong/tong/ban.
        return 0.4
    if apartment.get('sigungu') == '해운대구':
        return 0.2
    return 0.0


def haversine_m(lat1, lon1, lat2, lon2):
    values = [lat1, lon1, lat2, lon2]
    if any(pd.isna(value) for value in values):
        return None
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)


def spatial_outlier(distance_m, threshold_m=5000):
    return distance_m is not None and distance_m > threshold_m


def classify_match(raw_name, candidate_name, *, name_score, address_score,
                   viable_candidate_count, contextual=False, official_address_confirmed=False):
    if contextual:
        if viable_candidate_count == 1 and name_score >= 0.9 and official_address_confirmed:
            return 'contextual_supported', 'REVIEW', 'medium', True
        return 'contextual_candidate', 'REVIEW', 'low', True
    raw_exact = str(raw_name or '').strip() == str(candidate_name or '').strip()
    normalized_exact = normalize_complex_name(raw_name) == normalize_complex_name(candidate_name)
    if raw_exact and official_address_confirmed and address_score >= 0.8 and viable_candidate_count == 1:
        return 'official_exact', 'CONFIRMED', 'high', False
    if normalized_exact and official_address_confirmed and address_score >= 0.8 and viable_candidate_count == 1:
        return 'normalized_exact', 'CONFIRMED', 'high', False
    if name_score >= 0.9 and address_score >= 0.8 and viable_candidate_count == 1:
        return 'fuzzy_supported', 'REVIEW', 'medium', True
    if name_score >= 0.72:
        return 'contextual_candidate', 'REVIEW', 'low', True
    return 'unresolved', 'UNRESOLVED', 'low', True


def load_overrides(path):
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path, dtype=str).fillna('')
    required = {'data_year', 'education_office', 'elementary_school_name', 'raw_apartment_name',
                'internal_complex_id', 'override_type', 'evidence_source', 'evidence_text'}
    if not required.issubset(frame.columns):
        raise ValueError('Manual apartment-school override schema is incomplete.')
    return frame


def apply_override(raw_name, school_name, auto_result, overrides, *, year=2025, office='haeundae'):
    if overrides.empty:
        return auto_result
    rows = overrides[(overrides.data_year.astype(str) == str(year)) &
                     (overrides.education_office == office) &
                     (overrides.elementary_school_name == school_name) &
                     (overrides.raw_apartment_name == raw_name)]
    if rows.empty:
        return auto_result
    if len(rows) != 1:
        raise ValueError('Conflicting or split overrides require one separately evidenced target per row; automatic publication refused.')
    row = rows.iloc[0]
    if row.override_type not in {'confirmed', 'rejected', 'alias', 'split', 'unresolved'}:
        raise ValueError('Unknown override_type.')
    if any(not str(row.get(field, '')).strip() for field in ('evidence_source', 'evidence_text', 'reason', 'verified_at')):
        raise ValueError('Manual override requires source, evidence, reason and verified_at.')
    result = dict(auto_result)
    result['automatic_evidence_source'] = result.get('evidence_source')
    result['automatic_evidence_text'] = result.get('evidence_text')
    result.update(override_type=row.override_type, override_applied=True,
                  evidence_source=row.evidence_source, evidence_text=row.evidence_text,
                  evidence_type='manual_' + row.override_type)
    if row.override_type == 'confirmed':
        if not str(row.internal_complex_id).strip():
            raise ValueError('Confirmed override requires a target internal_complex_id.')
        result.update(internal_complex_id=row.internal_complex_id, match_method='manual_override',
                      match_status='CONFIRMED', confidence='high', manual_review=False)
    elif row.override_type in ('alias', 'split'):
        result.update(internal_complex_id=row.internal_complex_id, match_method='manual_override',
                      match_status='REVIEW', confidence='medium', manual_review=True)
    else:
        result.update(match_method='unresolved', match_status='UNRESOLVED',
                      internal_complex_id=None, confidence='low', manual_review=True)
    result['official_catchment_match'] = result['match_status'] == 'CONFIRMED'
    if result['internal_complex_id'] is None:
        for field in ['kapt_code', 'complex_name', 'households', 'apartment_address', 'legal_dong',
                      'legal_address', 'road_address', 'distance_m']:
            result[field] = None
    return result


def candidate_rows(raw_name, catchment_row, apartments, school_row):
    candidates = apartments[(apartments.sigungu == '해운대구') & apartments.kapt_code.notna()].copy()
    # Phase 5 first-pass boundary. No adjacent dong expansion is needed for Centum/Re-song.
    candidates = candidates[candidates.apply(
        lambda row: _base_dong(row.legal_dong) == _base_dong(catchment_row.dong) or
                    _base_dong(row.dong) == _base_dong(catchment_row.dong), axis=1)]
    rows = []
    for apartment in candidates.to_dict('records'):
        name_score = name_similarity(raw_name, apartment['complex_name'])
        address_score = address_similarity(catchment_row.dong, apartment)
        distance = haversine_m(apartment.get('latitude'), apartment.get('longitude'),
                               school_row.get('latitude'), school_row.get('longitude'))
        rows.append(dict(data_year=2025, education_office='haeundae',
                         elementary_school_name=catchment_row.elementary_school_name,
                         raw_catchment_text=catchment_row.catchment_text, raw_apartment_name=raw_name,
                         normalized_raw_name=normalize_complex_name(raw_name),
                         candidate_internal_complex_id=apartment['internal_complex_id'],
                         candidate_kapt_code=apartment.get('kapt_code'),
                         candidate_complex_name=apartment['complex_name'],
                         candidate_address=apartment.get('address'),
                         candidate_legal_address=apartment.get('legal_address'),
                         candidate_road_address=apartment.get('road_address'),
                         candidate_legal_dong=apartment.get('legal_dong'),
                         candidate_households=apartment.get('households'), name_score=name_score,
                         dong_match=address_score >= 0.8, address_score=address_score,
                         distance_m=distance, spatial_outlier=spatial_outlier(distance)))
    rows.sort(key=lambda row: (-row['name_score'], -row['address_score'],
                               row['candidate_internal_complex_id']))
    for rank, row in enumerate(rows, 1):
        row['candidate_rank'] = rank
        row['candidate_count'] = len(rows)
        row['viable_candidate_count'] = sum(x['name_score'] >= 0.72 for x in rows)
    return rows


def build_apartment_matches(catchments, apartments, schools, overrides=None):
    overrides = pd.DataFrame() if overrides is None else overrides
    if apartments.internal_complex_id.duplicated().any():
        raise ValueError('Apartment IDs are not unique.')
    centum = catchments[catchments.dong.isin(['재송1동', '재송2동']) |
                        catchments.elementary_school_name.eq('센텀초') |
                        (catchments.manual_review & catchments.catchment_type.eq('unparsed'))]
    candidate_records, matches = [], []
    for row in centum.itertuples():
        school = schools[schools.school_name.str.replace('등학교', '', regex=False).eq(row.elementary_school_name)]
        if len(school) != 1:
            raise ValueError(f'Nonunique or missing elementary school: {row.elementary_school_name}')
        school_row = school.iloc[0].to_dict()
        names = row.apartment_name_pattern
        contextual = row.catchment_type == 'unparsed'
        if contextual:
            names = [row.raw_segment]
        if names is None or (isinstance(names, float) and pd.isna(names)):
            continue
        for raw_name in list(names):
            candidates = candidate_rows(raw_name, row, apartments, school_row)
            candidate_records.extend(candidates)
            viable = [item for item in candidates if item['name_score'] >= 0.72]
            top = viable[0] if viable else None
            if top is None:
                matches.append(dict(data_year=2025, internal_complex_id=None, kapt_code=None,
                                    complex_name=None, households=None, apartment_address=None,
                                    legal_dong=None, elementary_school_id=school_row['school_id'],
                                    elementary_school_name=row.elementary_school_name, raw_catchment_text=row.catchment_text,
                                    raw_apartment_name=raw_name, name_score=0.0, address_score=0.0,
                                    distance_m=None, spatial_outlier=False, match_method='unresolved',
                                    match_status='UNRESOLVED', official_catchment_match=False,
                                    confidence='low', manual_review=True, evidence_type='official_name_only',
                                    evidence_source=row.source_url, evidence_text=row.raw_segment,
                                    viable_candidate_count=0, override_applied=False))
                matches[-1]['education_office'] = 'haeundae'
                continue
            method, status, confidence, review = classify_match(
                raw_name, top['candidate_complex_name'], name_score=top['name_score'],
                address_score=top['address_score'], viable_candidate_count=len(viable), contextual=contextual)
            result = dict(data_year=2025, internal_complex_id=top['candidate_internal_complex_id'],
                          kapt_code=top['candidate_kapt_code'], complex_name=top['candidate_complex_name'],
                          households=top['candidate_households'], apartment_address=top['candidate_address'],
                          legal_dong=top['candidate_legal_dong'], elementary_school_id=school_row['school_id'],
                          elementary_school_name=row.elementary_school_name, raw_catchment_text=row.catchment_text,
                          raw_apartment_name=raw_name, name_score=top['name_score'],
                          address_score=top['address_score'], distance_m=top['distance_m'],
                          spatial_outlier=top['spatial_outlier'], match_method=method, match_status=status,
                          official_catchment_match=status == 'CONFIRMED', confidence=confidence,
                          manual_review=review or top['spatial_outlier'],
                          evidence_type='official_catchment_name+kapt_name_address',
                          evidence_source=row.source_url, evidence_text=row.raw_segment,
                          viable_candidate_count=len(viable), override_applied=False)
            result['education_office'] = 'haeundae'
            result['address_evidence_level'] = 'legal_dong_only'
            result['official_address_confirmed'] = False
            result['legal_address'] = top['candidate_legal_address']
            result['road_address'] = top['candidate_road_address']
            result['apartment_source_document'] = 'data/interim/apartment_master.parquet'
            result['apartment_data_year_basis'] = 'upstream_year_unknown; current snapshot, not verified 2025'
            result = apply_override(raw_name, row.elementary_school_name, result, overrides)
            if result['override_applied'] and result['internal_complex_id'] is not None:
                selected = apartments[apartments.internal_complex_id.eq(result['internal_complex_id'])]
                if len(selected) != 1:
                    raise ValueError('Override target ID is missing or ambiguous.')
                selected = selected.iloc[0]
                result.update(kapt_code=selected.kapt_code, complex_name=selected.complex_name,
                              households=selected.households, apartment_address=selected.address,
                              legal_dong=selected.legal_dong, legal_address=selected.legal_address,
                              road_address=selected.road_address,
                              distance_m=haversine_m(selected.latitude, selected.longitude,
                                                    school_row['latitude'], school_row['longitude']))
                result['name_score'] = name_similarity(raw_name, selected.complex_name)
                result['address_score'] = address_similarity(row.dong, selected.to_dict())
                result['spatial_outlier'] = spatial_outlier(result['distance_m'])
            if result['spatial_outlier']:
                result.update(match_status='REVIEW', official_catchment_match=False, manual_review=True)
            matches.append(result)
    # Overrides also apply when automatic candidate search found nothing.
    for result in matches:
        if result['internal_complex_id'] is None and not result['override_applied']:
            updated = apply_override(result['raw_apartment_name'], result['elementary_school_name'], result, overrides)
            if updated['internal_complex_id'] is not None:
                selected = apartments[apartments.internal_complex_id.eq(updated['internal_complex_id'])]
                if len(selected) != 1:
                    raise ValueError('Override target ID is missing or ambiguous.')
                target = selected.iloc[0]
                school = schools[schools.school_id.eq(updated['elementary_school_id'])].iloc[0]
                updated.update(kapt_code=target.kapt_code, complex_name=target.complex_name,
                               households=target.households, apartment_address=target.address,
                               legal_dong=target.legal_dong, legal_address=target.legal_address,
                               road_address=target.road_address,
                               distance_m=haversine_m(target.latitude, target.longitude, school.latitude, school.longitude))
                updated['name_score'] = name_similarity(updated['raw_apartment_name'], target.complex_name)
                updated['address_score'] = 0.0  # No automatic address support existed for this unresolved name.
                updated['spatial_outlier'] = spatial_outlier(updated['distance_m'])
                if updated['spatial_outlier']:
                    updated.update(match_status='REVIEW', official_catchment_match=False, manual_review=True)
            result.update(updated)
    return pd.DataFrame(candidate_records), pd.DataFrame(matches)


def filter_500plus(frame):
    return frame[pd.to_numeric(frame.households, errors='coerce').ge(500)].copy()
