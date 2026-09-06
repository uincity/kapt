"""Independent address cache; uses the same Kakao Local address endpoint as upstream."""
import hashlib
import json
import re
import time

import pandas as pd
import requests

from .config import ROOT, api_key, now, settings, write_csv, write_json, write_parquet


def address_candidates(road, legal):
    values = []
    for raw in [road, legal]:
        if pd.isna(raw) or not str(raw).strip():
            continue
        address = re.sub(r'\s+', ' ', str(raw).strip())
        variants = [address]
        for pattern in [r'^(.+?(?:로|길)\s*\d+(?:-\d+)?)',
                        r'^(.+?(?:동|가|읍|면|리)\s+(?:산\s*)?\d+(?:-\d+)?)']:
            match = re.match(pattern, address)
            if match:
                variants.append(match.group(1).strip())
        for value in variants:
            if value not in values:
                values.append(value)
    return values


def lookup(session, address, key, cfg):
    for attempt in range(cfg['retries'] + 1):
        try:
            response = session.get(cfg['endpoint'], params={'query': address},
                                   headers={'Authorization': f'KakaoAK {key}'},
                                   timeout=cfg['timeout'], allow_redirects=False)
            if response.status_code in {401, 403}:
                raise ValueError('Kakao authentication failed; check KAKAO_API_KEY.')
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.RequestException()
            if response.status_code != 200:
                raise ValueError('Kakao request failed.')
            documents = response.json()['documents']
            if not documents:
                return dict(status='not_found', latitude=None, longitude=None)
            lat, lon = float(documents[0]['y']), float(documents[0]['x'])
            if not (34 <= lat <= 36.5 and 128 <= lon <= 130.5):
                return dict(status='out_of_region', latitude=None, longitude=None)
            return dict(status='success', latitude=lat, longitude=lon)
        except requests.RequestException:
            if attempt >= cfg['retries']:
                raise ValueError('Kakao network retry limit reached.') from None
            time.sleep(0.5 * 2 ** attempt)
        except (KeyError, TypeError):
            raise ValueError('Kakao response schema changed.') from None


def geocode_schools(*, retry_failed=False, root=ROOT, session=None):
    path = root / 'data/processed/schools.parquet'
    if not path.exists():
        raise ValueError('Run collect-schools successfully before geocode-schools.')
    frame = pd.read_parquet(path)
    cfg = settings(root)['kakao']
    key = api_key('KAKAO_API_KEY', root)
    cache_path = root / 'data/interim/school_geocode_cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    session = session or requests.Session()
    requests_made = 0
    for index, row in frame.iterrows():
        if pd.notna(row.latitude) and pd.notna(row.longitude):
            continue
        for address in address_candidates(row.address, row.legal_address):
            digest = hashlib.sha256(address.encode()).hexdigest()
            record = cache.get(digest)
            if record is None or (retry_failed and record['status'] != 'success'):
                if not key:
                    raise ValueError('KAKAO_API_KEY is not configured in the new project .env or environment.')
                record = lookup(session, address, key, cfg)
                record.update(address=address, collected_at=now(),
                              source_url=cfg['endpoint'], parser_version='0.1.0')
                cache[digest] = record
                write_json(cache_path, cache)
                requests_made += 1
                time.sleep(cfg['interval'])
            if record['status'] == 'success':
                frame.loc[index, ['latitude', 'longitude']] = [record['latitude'], record['longitude']]
                frame.loc[index, 'coordinate_source'] = 'kakao'
                frame.loc[index, 'geocoded_at'] = record['collected_at']
                frame.loc[index, 'geocode_query'] = address
                frame.loc[index, 'geocode_source_url'] = record['source_url']
                # Address geocoding is not a reviewed school location.
                reasons = [s for s in str(row.review_reason or '').split(';')
                           if s and s != 'missing_or_invalid_coordinates']
                frame.loc[index, 'review_reason'] = ';'.join(reasons + ['geocoded_location_review'])
                frame.loc[index, 'manual_review'] = True
                break
    failures = frame.loc[frame.latitude.isna() | frame.longitude.isna()]
    write_csv(root / 'data/interim/school_geocode_failures.csv', failures)
    write_csv(root / 'reports/manual_review.csv', frame.loc[frame.manual_review])
    write_parquet(path, frame)
    for year, subset in frame.groupby('data_year'):
        write_parquet(root / f'data/processed/snapshots/{year}/schools.parquet', subset)
    write_csv(root / 'reports/school_geocode_quality.csv', pd.DataFrame([{
        'school_count': len(frame), 'coordinates_count': len(frame) - len(failures),
        'geocode_success_rate': (len(frame) - len(failures)) / len(frame) if len(frame) else None,
        'requests_made': requests_made, 'reported_at': now()}]))
    return dict(school_count=len(frame), failure_count=len(failures), requests_made=requests_made)
