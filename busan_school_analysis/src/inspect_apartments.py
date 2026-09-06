"""Read the existing project without importing its modules or executing its pipeline."""
import hashlib
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .config import ROOT, now, provenance, settings, write_csv, write_json, write_parquet


def inspect_apartments(root=ROOT):
    source = (root / settings(root)['apartment_project']).resolve()
    inventory = []
    for folder in ['config', 'src', 'data/processed', 'data/interim']:
        for path in sorted((source / folder).glob('*')):
            if not path.is_file():
                continue
            item = dict(path=str(path.relative_to(source)), bytes=path.stat().st_size)
            if path.suffix == '.parquet':
                metadata = pq.ParquetFile(path)
                item.update(rows=metadata.metadata.num_rows,
                            schema={f.name: str(f.type) for f in metadata.schema_arrow})
            elif path.suffix == '.csv':
                item['columns'] = pd.read_csv(path, nrows=0).columns.tolist()
            inventory.append(item)
    files = ['data/interim/kapt_clean.parquet', 'data/interim/kapt_coordinates.parquet',
             'data/processed/busan_complex_summary.csv', 'data/processed/apartment_match_log.csv']
    before = {f: hashlib.sha256((source / f).read_bytes()).hexdigest() for f in files}
    k = pd.read_parquet(source / files[0])
    cache = pd.read_parquet(source / files[1])
    summary = pd.read_csv(source / files[2], dtype={'internal_complex_id': 'string'})
    log = pd.read_csv(source / files[3], dtype={'internal_complex_id': 'string', 'kapt_code': 'string'})
    if summary.internal_complex_id.isna().any() or summary.internal_complex_id.duplicated().any():
        raise ValueError('Existing summary IDs are missing or duplicated.')
    if k.kapt_code.isna().any() or k.kapt_code.duplicated().any():
        raise ValueError('K-apt IDs are missing or duplicated.')
    crosswalk = log[['internal_complex_id', 'kapt_code']].dropna().drop_duplicates()
    if crosswalk.internal_complex_id.duplicated().any():
        raise ValueError('Existing match log contains conflicting ID mappings.')
    # This rule is verified against existing match_complex.py and the actual log.
    if not crosswalk.internal_complex_id.eq(crosswalk.kapt_code).all():
        raise ValueError('Existing K-apt ID policy changed; inspect before reuse.')
    fields = ['internal_complex_id', 'complex_name', 'sigungu', 'dong', 'households',
              'latitude', 'longitude', 'road_address']
    master = summary[fields].merge(crosswalk, on='internal_complex_id', how='left', validate='one_to_one')
    missing = k.loc[~k.kapt_code.isin(master.internal_complex_id)].copy()
    missing['internal_complex_id'] = missing.kapt_code
    master = pd.concat([master, missing[fields + ['kapt_code']]], ignore_index=True)
    master = master.merge(k[['kapt_code', 'legal_address', 'jibun']], on='kapt_code',
                          how='left', validate='many_to_one')
    master['address'] = master.road_address.fillna(master.legal_address)
    master['legal_dong'] = master.dong
    master['is_500plus'] = master.households.astype('Float64').ge(500)
    stamp = now()
    for name, value in provenance(None, 'busan_apartment_analysis', ';'.join(files), stamp).items():
        master[name] = value
    # Upstream has no dataset year/provenance. Do not invent an effective year.
    master['data_year'] = pd.Series(pd.NA, index=master.index, dtype='Int64')
    master['manual_review'] = True
    master['confidence'] = pd.NA
    master['review_reason'] = 'upstream_data_year_unavailable'
    master['source_project'] = str(source)
    master['source_fingerprints'] = ';'.join(f'{f}:{digest}' for f, digest in before.items())
    if master.internal_complex_id.duplicated().any():
        raise ValueError('Master IDs must remain unique.')
    stats = dict(kapt_rows=len(k), kapt_500plus=int(k.households.ge(500).sum()),
                 kapt_coordinates=int(k[['latitude', 'longitude']].notna().all(axis=1).sum()),
                 cache_coordinates=int(cache[['latitude', 'longitude']].notna().all(axis=1).sum()),
                 summary_rows=len(summary), summary_500plus=int(summary.households.ge(500).sum()),
                 summary_missing_households=int(summary.households.isna().sum()),
                 added_kapt_rows=len(missing), master_rows=len(master),
                 master_500plus=int(master.is_500plus.sum()))
    after = {f: hashlib.sha256((source / f).read_bytes()).hexdigest() for f in files}
    if before != after:
        raise RuntimeError('Source changed during inspection; rerun for a consistent snapshot.')
    write_parquet(root / 'data/interim/apartment_master.parquet', master)
    write_json(root / 'reports/existing_project_schema.json',
               dict(source=str(source), inspected_at=stamp, inventory=inventory,
                    input_sha256=before, statistics=stats))
    write_csv(root / 'reports/phase1_statistics.csv',
              pd.DataFrame([dict(metric=k, value=v) for k, v in stats.items()]))
    return stats
