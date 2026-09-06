import hashlib
import json
import time
from datetime import datetime

import pandas as pd
import requests

from .clean_school import clean_schools, response_rows
from .config import (ROOT, api_key, atomic_bytes, now, settings,
                     write_csv, write_json, write_parquet)


def download(session, params, cfg):
    for attempt in range(cfg['retries'] + 1):
        try:
            response = session.get(cfg['endpoint'], params=params, timeout=cfg['timeout'],
                                   allow_redirects=False)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < cfg['retries']:
                    time.sleep(0.5 * 2 ** attempt)
                    continue
            if response.status_code != 200:
                raise ValueError(f'Schoolinfo HTTP {response.status_code}; request details suppressed.')
            return response.content
        except requests.RequestException:
            if attempt >= cfg['retries']:
                raise ValueError('Schoolinfo connection failed; request details suppressed.') from None
            time.sleep(0.5 * 2 ** attempt)
    raise ValueError('Schoolinfo retry limit reached.')


def collect_schools(year, *, force=False, root=ROOT, session=None):
    cfg = settings(root)['schoolinfo']
    regions = pd.read_csv(root / 'config/schoolinfo_codes.csv', dtype=str)
    if len(regions) != 16 or regions.sgg_code.nunique() != 16 or not regions.sido_code.eq('26').all():
        raise ValueError('Verified Busan district table must contain 16 unique districts.')
    key = api_key('SCHOOLINFO_API_KEY', root)
    session = session or requests.Session()
    frames, statuses = [], []
    for region in regions.to_dict('records'):
        for level in cfg['levels']:
            path = root / f'data/raw/schoolinfo/{year}/{region["sgg_code"]}_{level}.json'
            meta_path = path.with_suffix('.meta.json')
            reused = path.exists() and meta_path.exists() and not force
            status = dict(data_year=year, sigungu=region['sigungu'], school_level_code=level,
                          source_document=str(path.relative_to(root)), reused=reused,
                          rows=0, status='failed', reason='')
            try:
                if reused:
                    meta = json.loads(meta_path.read_text(encoding='utf-8'))
                    content = path.read_bytes()
                    if (meta['sha256'] != hashlib.sha256(content).hexdigest()
                            or meta['data_year'] != year
                            or datetime.fromisoformat(meta['collected_at']).year != year):
                        raise ValueError('Cached raw provenance mismatch; inspect or use --force.')
                else:
                    if year != datetime.now().year:
                        raise ValueError('Basic API has no historical year parameter; only existing snapshots can be reused.')
                    if not key:
                        raise ValueError('SCHOOLINFO_API_KEY is not configured in the new project .env or environment.')
                    params = dict(apiKey=key, apiType='0', sidoCode=region['sido_code'],
                                  sggCode=region['sgg_code'], schulKndCode=level)
                    content = download(session, params, cfg)
                    if key.encode() in content:
                        raise ValueError('Response echoed API key; response was not persisted.')
                    # Archive previous raw bytes before --force replaces the current snapshot.
                    if path.exists():
                        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                        atomic_bytes(path.parent / 'history' / f'{path.stem}_{digest}.json', path.read_bytes())
                        if meta_path.exists():
                            atomic_bytes(path.parent / 'history' / f'{path.stem}_{digest}.meta.json', meta_path.read_bytes())
                    atomic_bytes(path, content)
                    meta = dict(data_year=year, collected_at=now(),
                                sha256=hashlib.sha256(content).hexdigest(),
                                source_url=cfg['endpoint'], params={k: v for k, v in params.items() if k != 'apiKey'})
                    write_json(meta_path, meta)
                    time.sleep(cfg['interval'])
                payload = json.loads(content)
                response_rows(payload)
                frame = clean_schools(payload, year=year, region=region, level=level,
                                      document=str(path.relative_to(root)), collected_at=meta['collected_at'])
                status['rows'] = len(frame)
                status['status'] = 'ok' if len(frame) else 'empty_review'
                if len(frame):
                    frames.append(frame)
            except (ValueError, KeyError, TypeError):
                # Fixed messages avoid exposing arbitrary provider errors or cache content.
                status['reason'] = ('missing_api_key' if not reused and not key else
                                    'historical_snapshot_unavailable' if not reused and year != datetime.now().year else
                                    'request_or_schema_or_cache_validation_failed')
            statuses.append(status)
    report = pd.DataFrame(statuses)
    write_csv(root / 'reports/school_collection_status.csv', report)
    failed = int(report.status.ne('ok').sum())
    if failed:
        raise ValueError(f'{failed}/32 school batches incomplete; see reports/school_collection_status.csv. Existing schools.parquet was preserved.')
    schools = pd.concat(frames, ignore_index=True)
    if schools.school_id.duplicated().any():
        raise ValueError('Duplicate school IDs across districts; inspect raw files before publishing.')
    write_parquet(root / f'data/processed/snapshots/{year}/schools.parquet', schools)
    write_parquet(root / 'data/processed/schools.parquet', schools)
    write_csv(root / 'reports/manual_review.csv', schools.loc[schools.manual_review])
    counts = dict(school_count=len(schools), elementary_count=int(schools.school_level.eq('elementary').sum()),
                  middle_count=int(schools.school_level.eq('middle').sum()),
                  geocode_success_rate=float(schools.latitude.notna().mean()),
                  manual_review_count=int(schools.manual_review.sum()))
    write_csv(root / 'reports/school_data_quality.csv',
              pd.DataFrame([dict(data_year=year, metric=k, value=v) for k, v in counts.items()]))
    return counts
