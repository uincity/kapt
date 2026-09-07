"""Collect the official MOIS administrative/legal-dong code bundle."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import requests
from .config import ROOT, atomic_bytes, write_json

SOURCE_URL = "https://www.mois.go.kr/cmm/fms/FileDown.do?atchFileId=FILE_001399377CsGSGj&fileSn=1"
SOURCE_DATE = "2025-11-03"

def collect_admin_codes(*, force=False, root=ROOT, session=requests):
    path=Path(root)/"data/raw/admin_codes/2025/jscode20251103.zip"
    meta=path.with_suffix(".metadata.json")
    if path.exists() and not force:
        content=path.read_bytes()
        if meta.exists() and hashlib.sha256(content).hexdigest()!=__import__('json').loads(meta.read_text(encoding='utf-8'))['sha256']:
            raise ValueError("Administrative-code cache hash mismatch")
        if not meta.exists():
            write_json(meta,{"source_url":SOURCE_URL,"source_date":SOURCE_DATE,"download_time":None,"sha256":hashlib.sha256(content).hexdigest()})
        return {"status":"cached","path":str(path),"sha256":hashlib.sha256(content).hexdigest()}
    response=session.get(SOURCE_URL,timeout=60); response.raise_for_status(); content=response.content
    if not content.startswith(b"PK"): raise ValueError("MOIS response is not a ZIP archive")
    atomic_bytes(path,content); digest=hashlib.sha256(content).hexdigest()
    write_json(meta,{"source_url":SOURCE_URL,"source_date":SOURCE_DATE,"download_time":datetime.now(timezone.utc).isoformat(),"sha256":digest})
    return {"status":"downloaded","path":str(path),"sha256":digest}
