"""Collect public disclosure HTML with source year checks and raw response caching."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import time

import pandas as pd
import requests

from .clean_advancement import add_rates, parse_advancement
from .config import ROOT, atomic_bytes, now, write_csv, write_json, write_parquet

ENDPOINT = 'https://www.schoolinfo.go.kr/ei/pp/Pneipp_b06_s0p.do'


def request_parameters(school, year):
    # Observed in loadGongSi() of the official item-disclosure page.
    return dict(GS_HANGMOK_CD='06', GS_HANGMOK_NO='13-다', GS_HANGMOK_NM='졸업생의 진로 현황',
                GS_BURYU_CD='JG040', JG_BURYU_CD='JG130', JG_HANGMOK_CD='52', JG_GUBUN='1',
                JG_YEAR2=year, HG_NM=school['school_name'], SHL_IDF_CD=school['school_public_id'],
                GS_TYPE='Y', JG_YEAR=year, CHOSEN_JG_YEAR=year, PRE_JG_YEAR=year, LOAD_TYPE='single')


def collect_one(school, year, *, force, root):
    path = root / f'data/raw/advancement/{year}/{school["school_id"]}.html'
    meta_path = path.with_suffix('.meta.json')
    stamp = now()
    try:
        if path.exists() and meta_path.exists() and not force:
            content = path.read_bytes()
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            if (meta['sha256'] != hashlib.sha256(content).hexdigest()
                    or meta['requested_year'] != year or meta['school_id'] != school['school_id']):
                raise ValueError('raw_cache_integrity_error')
            stamp = meta['collected_at']
        else:
            for attempt in range(3):
                try:
                    response = requests.post(ENDPOINT, data=request_parameters(school, year),
                                             timeout=30, allow_redirects=False)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise requests.RequestException()
                    if response.status_code != 200:
                        raise ValueError('public_page_http_error')
                    content = response.content
                    break
                except requests.RequestException:
                    if attempt == 2:
                        raise ValueError('public_page_network_error') from None
                    time.sleep(2 ** attempt)
            if path.exists():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                atomic_bytes(path.parent / 'history' / f'{path.stem}_{digest}.html', path.read_bytes())
                if meta_path.exists():
                    atomic_bytes(path.parent / 'history' / f'{path.stem}_{digest}.meta.json', meta_path.read_bytes())
            atomic_bytes(path, content)
            write_json(meta_path, dict(school_id=school['school_id'], requested_year=year,
                                      collected_at=stamp, sha256=hashlib.sha256(content).hexdigest(),
                                      source_url=ENDPOINT, request_parameters=request_parameters(school, year)))
            time.sleep(0.25)
        return parse_advancement(content, school=school, year=year,
                                 document=str(path.relative_to(root)), collected_at=stamp)
    except (ValueError, KeyError, TypeError) as error:
        record = parse_advancement(b'', school=school, year=year,
                                   document=str(path.relative_to(root)), collected_at=stamp)
        record['availability'] = 'collection_or_parser_error'
        record['review_reason'] = type(error).__name__
        return record


def collect_advancement(years, *, force=False, root=ROOT, workers=2):
    schools = pd.read_parquet(root / 'data/processed/schools.parquet')
    schools = schools.loc[schools.school_level.eq('middle')]
    if 'school_public_id' not in schools or schools.school_public_id.isna().any():
        raise ValueError('Rebuild schools from cached raw: python main.py collect-schools --year 2026')
    if schools.school_id.duplicated().any():
        raise ValueError('Duplicate school IDs in school master.')
    years = sorted(set(years))
    records = []
    total = len(schools) * len(years)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(collect_one, school, year, force=force, root=root)
                   for year in years for school in schools.to_dict('records')]
        for future in as_completed(futures):
            records.append(future.result())
            if len(records) % 40 == 0:
                print(f'Advancement: {len(records)}/{total}', flush=True)
    frame = add_rates(pd.DataFrame(records)).sort_values(['year', 'middle_school_id'])
    write_csv(root / 'reports/advancement_collection_status.csv', frame[[
        'middle_school_id', 'middle_school_name', 'requested_year', 'observed_year',
        'availability', 'eligible_for_scoring', 'manual_review', 'review_reason', 'source_document']])
    output = root / 'data/processed/middle_school_advancement.parquet'
    # A failed refresh must not replace a previously valid school-year observation.
    if output.exists():
        old = pd.read_parquet(output)
        keys = ['middle_school_id', 'year']
        old_good = old.loc[old.eligible_for_scoring].set_index(keys)
        incoming = frame.set_index(keys)
        preserved = []
        for key in old_good.index.intersection(incoming.index):
            if (not incoming.loc[key, 'eligible_for_scoring']
                    or str(old_good.loc[key, 'parser_version']).endswith('-reviewed-csv')):
                preserved.append(key)
        parts = [old.loc[~old.year.isin(years)], incoming.loc[~incoming.index.isin(preserved)].reset_index(),
                 old_good.loc[old_good.index.isin(preserved)].reset_index()]
        frame = pd.concat([part for part in parts if not part.empty], ignore_index=True)
    write_parquet(output, frame)
    write_csv(root / 'reports/advancement_manual_review.csv', frame.loc[frame.manual_review])
    result = frame.groupby(['year', 'availability']).size().rename('rows').reset_index()
    write_csv(root / 'reports/advancement_quality.csv', result)
    return result.to_dict('records')
