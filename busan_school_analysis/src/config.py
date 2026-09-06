from pathlib import Path
from datetime import datetime, timezone
import json
import os

import pandas as pd
import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PARSER_VERSION = '0.1.0'


def settings(root=ROOT):
    return yaml.safe_load((root / 'config/settings.yaml').read_text(encoding='utf-8'))


def api_key(name, root=ROOT):
    # Do not load or copy the apartment project's credentials.
    return os.getenv(name) or dotenv_values(root / '.env').get(name) or ''


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(content)
    temporary.replace(path)


def write_json(path, value):
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def write_parquet(path, frame):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)


def write_csv(path, frame):
    atomic_bytes(path, frame.to_csv(index=False).encode('utf-8-sig'))


def provenance(year, source, document, collected_at):
    return dict(data_year=year, source_name=source, source_document=str(document),
                collected_at=collected_at, parser_version=PARSER_VERSION,
                manual_review=False, confidence=1.0)
