"""Explicit, documented CSV fallback for rows that require human source review."""
import hashlib
from pathlib import Path

import pandas as pd

from .clean_advancement import TITLES, VERSION, add_rates
from .config import ROOT, atomic_bytes, write_parquet

REQUIRED = ['year', 'middle_school_id', *TITLES, 'source_name', 'source_url', 'source_document',
            'collected_at', 'reviewed_by', 'reviewed_at']


def import_advancement(csv_path, root=ROOT):
    path = Path(csv_path)
    content = path.read_bytes()
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if frame.empty or set(REQUIRED) - set(frame.columns):
        raise ValueError('CSV requires the populated columns in config/advancement_review_template.csv')
    if frame[REQUIRED].eq('').any().any():
        raise ValueError('All source, reviewer and count fields are required.')
    for column in ['year', *TITLES]:
        if not frame[column].str.fullmatch(r'\d+').all():
            raise ValueError('Counts and years must be nonnegative integers, not suppressed values.')
        frame[column] = frame[column].astype(int)
    if frame.duplicated(['middle_school_id', 'year']).any():
        raise ValueError('CSV contains duplicate school-year keys.')
    for column in ['collected_at', 'reviewed_at']:
        if pd.to_datetime(frame[column], errors='coerce', utc=True).isna().any():
            raise ValueError('CSV provenance dates must be valid timestamps.')
    r = frame
    valid = (
        (r.science_hs_count + r.foreign_international_hs_count + r.arts_sports_hs_count + r.meister_hs_count).eq(r.special_purpose_total)
        & (r.autonomous_private_hs_count + r.autonomous_public_hs_count).eq(r.autonomous_total)
        & (r.general_hs_count + r.specialized_hs_count + r.special_purpose_total + r.autonomous_total + r.other_advancement_count).eq(r.advancement_total)
        & (r.advancement_total + r.employment_count + r.unaccredited_alternative_count + r.unknown_destination_count).eq(r.graduates))
    if not valid.all():
        raise ValueError('CSV count totals do not reconcile; no output changed.')
    schools = pd.read_parquet(root / 'data/processed/schools.parquet')
    schools = schools.loc[schools.school_level.eq('middle')].set_index('school_id')
    if not frame.middle_school_id.isin(schools.index).all():
        raise ValueError('CSV school IDs must exist in the middle-school master.')
    digest = hashlib.sha256(content).hexdigest()
    raw_path = root / f'data/raw/advancement/manual/{digest}.csv'
    atomic_bytes(raw_path, content)
    frame['manual_csv_document'] = str(raw_path.relative_to(root))
    frame['middle_school_name'] = frame.middle_school_id.map(schools.school_name)
    frame['sigungu'] = frame.middle_school_id.map(schools.sigungu)
    frame['school_public_id'] = frame.middle_school_id.map(schools.school_public_id)
    frame['data_year'] = frame['requested_year'] = frame['observed_year'] = frame.year
    frame['parser_version'] = VERSION + '-reviewed-csv'
    frame['availability'] = 'available'
    frame['eligible_for_scoring'] = frame.graduates.gt(0)
    frame['manual_review'] = frame.graduates.eq(0)
    frame['confidence'] = 1.0
    frame['review_reason'] = 'human_reviewed_csv'
    for field in ['foreign_language_hs_count', 'international_hs_count', 'arts_hs_count',
                  'sports_hs_count', 'other_special_hs_count']:
        frame[field] = None
    frame['category_resolution'] = 'foreign_international_combined;arts_sports_combined;other_special_not_separate'
    frame = add_rates(frame)
    output = root / 'data/processed/middle_school_advancement.parquet'
    if output.exists():
        old = pd.read_parquet(output)
        atomic_bytes(root / f'data/interim/advancement_before_manual_{digest}.parquet', output.read_bytes())
        key = pd.MultiIndex.from_frame(frame[['middle_school_id', 'year']])
        keep = ~pd.MultiIndex.from_frame(old[['middle_school_id', 'year']]).isin(key)
        frame = pd.concat([old.loc[keep], frame], ignore_index=True)
    write_parquet(output, frame)
    return dict(imported_rows=len(r), raw_csv=str(raw_path))
