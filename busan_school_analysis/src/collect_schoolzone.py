"""Download immutable 2025 Schoolzone public-data snapshots with provenance."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import requests

from .config import ROOT, atomic_bytes, now, write_json


LIST_URL = "https://schoolzone.emac.kr/publicData/publicDataList.do"
DOWNLOAD_URL = "https://schoolzone.emac.kr/publicData/publicDataFileDownload.do"
SNAPSHOT_DATE = "2025-09-22"
SOURCES = {
    "elementary_catchment": {
        "ntt_id": "2950",
        "attachment_id": "FILE_000000100002961",
        "file_sn": "0",
        "filename": "elementary_catchment_20250922.zip",
        "title": "한국지방교육행정연구재단 초등학교 통학구역 및 공동통학구역(2025.09.22.)",
    },
    "school_zone_link": {
        "ntt_id": "2945",
        "attachment_id": "FILE_000000100002956",
        "file_sn": "0",
        "filename": "school_zone_link_20250922.zip",
        "title": "한국지방교육행정연구재단 학교-학구도 연계정보(2025.09.22.)",
    },
}


def _download_url(source: dict) -> str:
    return (f"{DOWNLOAD_URL}?nttId={source['ntt_id']}"
            f"&atchFileId={source['attachment_id']}&fileSn={source['file_sn']}")


def _valid_zip(content: bytes) -> None:
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise ValueError("Schoolzone archive integrity check failed.")
    except BadZipFile as exc:
        raise ValueError("Schoolzone response is not a ZIP archive.") from exc


def collect_schoolzone(year=2025, *, force=False, root=ROOT, session=None) -> dict:
    if year != 2025:
        raise ValueError("This collector is pinned to the official 2025-09-22 snapshot.")
    session = session or requests.Session()
    base = Path(root) / "data/raw/schoolzone/2025"
    base.mkdir(parents=True, exist_ok=True)
    results = {}
    for key, source in SOURCES.items():
        path = base / source["filename"]
        meta_path = path.with_suffix(".metadata.json")
        reused = path.exists() and meta_path.exists() and not force
        if reused:
            content = path.read_bytes()
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            digest = hashlib.sha256(content).hexdigest()
            if (metadata.get("sha256") != digest or metadata.get("data_year") != 2025
                    or metadata.get("snapshot_date") != SNAPSHOT_DATE):
                raise ValueError(f"Schoolzone cache provenance mismatch: {path.name}")
            _valid_zip(content)
            results[key] = {"status": "cached", "path": str(path), "sha256": digest,
                            "bytes": len(content)}
            continue
        response = session.get(_download_url(source), timeout=180)
        if response.status_code != 200:
            raise ValueError(f"Schoolzone download failed with HTTP {response.status_code}.")
        content = response.content
        _valid_zip(content)
        digest = hashlib.sha256(content).hexdigest()
        atomic_bytes(path, content)
        metadata = {
            "data_year": 2025,
            "snapshot_date": SNAPSHOT_DATE,
            "source_name": "학구도안내서비스 공공데이터",
            "source_title": source["title"],
            "source_list_url": LIST_URL,
            "source_url": _download_url(source),
            "ntt_id": source["ntt_id"],
            "attachment_id": source["attachment_id"],
            "file_sn": source["file_sn"],
            "collected_at": now(),
            "sha256": digest,
            "bytes": len(content),
        }
        write_json(meta_path, metadata)
        results[key] = {"status": "downloaded", "path": str(path), "sha256": digest,
                        "bytes": len(content)}
    return results

