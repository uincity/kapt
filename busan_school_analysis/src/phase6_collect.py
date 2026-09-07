from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, re
from pathlib import Path
import requests
from .config import ROOT, atomic_bytes, write_json
from .education_offices import SOURCES


def detect_data_year(text: str) -> tuple[int | None, str, str]:
    years = {int(x) for x in re.findall(r"(20\d{2})\s*학년도", text)}
    if len(years) == 1:
        return years.pop(), "page_body", "high"
    return None, "not_verified", "unknown"


def collect_office_catchment(office, year, *, force=False, root=ROOT, session=requests):
    if office not in SOURCES:
        raise ValueError(f"Unknown education office: {office}")
    results=[]
    for index,url in enumerate(SOURCES[office].catchment_urls,1):
        base=Path(root)/f"data/raw/education_office/{office}/{year}"
        path=base/f"elementary_catchment_{index}.html"
        meta=base/f"elementary_catchment_{index}_metadata.json"
        if path.exists() and meta.exists() and not force:
            results.append(json.loads(meta.read_text(encoding="utf-8"))); continue
        response=session.get(url,timeout=30); response.raise_for_status()
        content=response.content; text=content.decode(response.encoding or "utf-8",errors="replace")
        detected,source,confidence=detect_data_year(text)
        record={"education_office":office,"requested_year":year,"data_year":detected,
                "data_year_source":source,"data_year_confidence":confidence,"source_url":url,
                "download_time":datetime.now(timezone.utc).isoformat(),"sha256":hashlib.sha256(content).hexdigest(),
                "publication_status":"accepted" if detected==year else "year_mismatch"}
        # Preserve mismatched evidence separately; never publish it under the requested-year canonical name.
        target=path if detected==year else base/"rejected_year_evidence"/path.name
        target_meta=meta if detected==year else base/"rejected_year_evidence"/meta.name
        atomic_bytes(target,content); write_json(target_meta,record); results.append(record)
    return results


def collect_all_catchments(year, **kwargs):
    return {office: collect_office_catchment(office,year,**kwargs) for office in SOURCES}
