from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

import requests

from .config import ROOT, PARSER_VERSION, atomic_bytes, now, write_json
from .parse_catchment import CATCHMENT_URL, raw_catchment_rows


def _archive(paths, directory):
    existing = [Path(path) for path in paths if Path(path).exists()]
    if not existing:
        return
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    target = Path(directory) / stamp
    target.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, target / path.name)


def collect_catchments(office, year, *, force=False, root=ROOT, session=requests):
    if office != 'haeundae' or year != 2025:
        raise ValueError('Phase 4 PoC supports only --office haeundae --year 2025.')
    base = Path(root) / f'data/raw/education_office/{office}/{year}'
    path = base / 'elementary_catchment.html'
    meta_path = base / 'elementary_catchment_metadata.json'
    if path.exists() and meta_path.exists() and not force:
        content = path.read_bytes()
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        if hashlib.sha256(content).hexdigest() != meta.get('content_hash'):
            raise ValueError('Cached catchment hash mismatch; use --force after reviewing the file.')
        raw_catchment_rows(content.decode('utf-8'))
        return {'status': 'cached', 'path': str(path), 'rows': len(raw_catchment_rows(content.decode('utf-8')))}
    response = session.get(CATCHMENT_URL, timeout=30)
    response.raise_for_status()
    content = response.content
    html = content.decode(response.encoding or 'utf-8', errors='replace')
    if '2025학년도' not in html:
        raise ValueError('Official page no longer identifies the data as 2025; raw output was not published.')
    rows = raw_catchment_rows(html)
    if force:
        _archive([path, meta_path], base / 'history')
    collected = now()
    atomic_bytes(path, content)
    write_json(meta_path, dict(data_year=year, education_office=office, source_url=CATCHMENT_URL,
                               collected_at=collected, http_status=response.status_code,
                               content_hash=hashlib.sha256(content).hexdigest(),
                               parser_version=PARSER_VERSION))
    return {'status': 'downloaded', 'path': str(path), 'rows': len(rows)}
