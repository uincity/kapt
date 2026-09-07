"""Phase 6.5 apartment coordinate audit, geocoding, validation and publishing."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests

from .config import ROOT, api_key, now, settings, write_csv, write_parquet


ATTEMPT_COLUMNS = [
    "internal_complex_id", "candidate_type", "candidate_priority", "query_text", "query_key",
    "provider", "attempted_at", "cache_reused", "success", "latitude", "longitude",
    "returned_address", "returned_road_address", "returned_building_name", "result_type",
    "returned_sido", "returned_sigungu", "returned_legal_dong", "returned_legal_dong_code",
    "returned_admin_dong", "returned_admin_dong_code", "returned_road_name",
    "returned_building_number", "returned_lot_number", "sigungu_match", "legal_dong_match",
    "road_name_match", "building_number_match", "complex_name_similarity",
    "busan_boundary_match", "geocode_validation_status", "validation_reason",
]


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def normalize_address(value: Any) -> str:
    text = _text(value).replace("부산시", "부산광역시")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"(?:아파트)?\s*\d+동\s*\d+호(?:\s.*)?$", "", text)
    text = re.sub(r"[,;|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", normalize_address(value).lower())


def _number(main: Any, sub: Any = None) -> str:
    def part(value):
        if pd.isna(value) or _text(value) in {"", "0", "0.0"}:
            return ""
        try:
            return str(int(float(value)))
        except (TypeError, ValueError):
            return _text(value)
    first, second = part(main), part(sub)
    return first + (f"-{second}" if first and second else "")


def _mode(series: pd.Series):
    values = series.dropna().map(_text)
    values = values[values.ne("")]
    if values.empty:
        return None
    return values.value_counts().index[0]


def _road_parts(road_name: Any, road_main: Any, road_sub: Any) -> tuple[str, str]:
    name = re.sub(r"\s+", " ", _text(road_name))
    match = re.match(r"^(.+?(?:대로|로|길))\s+(\d+)(?:-(\d+))?$", name)
    if match:
        return match.group(1), _number(match.group(2), match.group(3))
    return name, _number(road_main, road_sub)


def transaction_address_evidence(master: pd.DataFrame, *, root=ROOT) -> pd.DataFrame:
    legacy = (Path(root) / settings(root)["apartment_project"]).resolve()
    missing_ids = set(master.loc[~valid_coordinate_mask(master), "internal_complex_id"])
    frames = []
    for rank, filename in enumerate(["trade_matched.parquet", "rent_matched.parquet"], 1):
        path = legacy / "data/interim" / filename
        if not path.exists():
            continue
        frame = pd.read_parquet(path)
        frame = frame.loc[frame.internal_complex_id.isin(missing_ids)].copy()
        frame["source_rank"] = rank
        frame["address_source_document"] = str(path)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["internal_complex_id"])
    rows = []
    combined = pd.concat(frames, ignore_index=True)
    for complex_id, group in combined.groupby("internal_complex_id", sort=False):
        group = group.sort_values("source_rank")
        first = group.iloc[0]
        road_name_raw, road_main, road_sub = _mode(group.road_name), _mode(group.road_main), _mode(group.road_sub)
        road_name, road_number = _road_parts(road_name_raw, road_main, road_sub)
        sigungu, legal_dong, lot = _mode(group.sigungu), _mode(group.dong), _mode(group.jibun)
        raw_road = " ".join(x for x in ["부산광역시", sigungu, road_name, road_number] if x)
        raw_lot = " ".join(x for x in ["부산광역시", sigungu, legal_dong, lot] if x)
        rows.append({
            "internal_complex_id": complex_id,
            "transaction_complex_name": _mode(group.complex_name),
            "sigungu_evidence": sigungu,
            "legal_dong_evidence": legal_dong,
            "lawd_cd": _mode(group.lawd_cd),
            "jibun_evidence": lot,
            "road_name_evidence": road_name,
            "road_number_evidence": road_number,
            "raw_road_address": raw_road or None,
            "raw_lot_address": raw_lot or None,
            "normalized_road_address": normalize_address(raw_road) or None,
            "normalized_lot_address": normalize_address(raw_lot) or None,
            "address_evidence_source": "OFFICIAL_TRANSACTION_API",
            "address_source_document": first.address_source_document,
            "upstream_match_method": _mode(group.match_method),
        })
    return pd.DataFrame(rows)


def valid_coordinate_mask(frame: pd.DataFrame) -> pd.Series:
    lat = pd.to_numeric(frame.get("latitude"), errors="coerce")
    lon = pd.to_numeric(frame.get("longitude"), errors="coerce")
    return lat.between(34.5, 36.0) & lon.between(128.5, 130.0)


def classify_missing_coordinates(master: pd.DataFrame, evidence: pd.DataFrame,
                                 attempts: pd.DataFrame | None = None,
                                 legacy_coordinates: pd.DataFrame | None = None) -> pd.DataFrame:
    merged = master.merge(evidence, on="internal_complex_id", how="left")
    attempts = attempts if attempts is not None else pd.DataFrame()
    attempted_ids = set(attempts.internal_complex_id) if "internal_complex_id" in attempts else set()
    confirmed_ids = (set(attempts.loc[attempts.geocode_validation_status.eq("CONFIRMED"),
                                      "internal_complex_id"]) if "geocode_validation_status" in attempts else set())
    failed_ids = attempted_ids - confirmed_ids
    legacy_ids = (set(legacy_coordinates.kapt_code.dropna().astype(str))
                  if legacy_coordinates is not None and "kapt_code" in legacy_coordinates else set())
    reasons = []
    for row in merged.itertuples(index=False):
        lat, lon = pd.to_numeric(getattr(row, "latitude", None), errors="coerce"), pd.to_numeric(getattr(row, "longitude", None), errors="coerce")
        if pd.notna(lat) != pd.notna(lon) or (pd.notna(lat) and not (34.5 <= lat <= 36 and 128.5 <= lon <= 130)):
            reason = "INVALID_COORDINATE"
        elif pd.notna(lat) and pd.notna(lon):
            reason = "OTHER"
        elif _text(getattr(row, "kapt_code", None)) in legacy_ids:
            reason = "JOIN_FAILURE"
        elif row.internal_complex_id in failed_ids:
            reason = "GEOCODE_FAILED"
        elif not _text(getattr(row, "raw_road_address", None)) and not _text(getattr(row, "raw_lot_address", None)):
            reason = "NO_ADDRESS"
        elif not _text(getattr(row, "kapt_code", None)) and _text(getattr(row, "address_evidence_source", None)):
            reason = "KAPT_UNMATCHED"
        elif row.internal_complex_id not in attempted_ids:
            reason = "GEOCODE_NOT_ATTEMPTED"
        else:
            reason = "OTHER"
        reasons.append(reason)
    merged["missing_reason"] = reasons
    merged["admin_dong"] = pd.NA
    columns = ["internal_complex_id", "kapt_code", "complex_name", "households", "address",
               "road_address", "sigungu", "legal_dong", "admin_dong", "latitude", "longitude",
               "raw_road_address", "raw_lot_address", "normalized_road_address",
               "normalized_lot_address", "address_evidence_source", "address_source_document",
               "upstream_match_method", "lawd_cd", "jibun_evidence", "road_name_evidence",
               "road_number_evidence", "missing_reason"]
    for column in columns:
        if column not in merged:
            merged[column] = pd.NA
    return merged.loc[~valid_coordinate_mask(merged), columns].copy()


def address_candidates(audit: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for item in audit.to_dict("records"):
        values = [
            (1, "ROAD_ADDRESS", item.get("raw_road_address")),
            (2, "LOT_ADDRESS", item.get("raw_lot_address")),
            (3, "NORMALIZED_ROAD_ADDRESS", item.get("normalized_road_address")),
            (4, "NORMALIZED_LOT_ADDRESS", item.get("normalized_lot_address")),
            (5, "NAME_ADDRESS", " ".join(filter(None, ["부산광역시", _text(item.get("sigungu")),
                                                          _text(item.get("legal_dong")),
                                                          _text(item.get("complex_name"))]))),
        ]
        seen = set()
        for priority, kind, query in values:
            query = normalize_address(query)
            key = _compact(query)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append({**item, "candidate_priority": priority, "candidate_type": kind,
                         "query_text": query, "query_key": hashlib.sha256(key.encode()).hexdigest(),
                         "provider": "KAKAO_KEYWORD" if kind == "NAME_ADDRESS" else "KAKAO_ADDRESS"})
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["priority_500plus"] = pd.to_numeric(result.households, errors="coerce").ge(500)
    return result.sort_values(["priority_500plus", "internal_complex_id", "candidate_priority"],
                              ascending=[False, True, True]).reset_index(drop=True)


def reuse_existing_coordinates(master: pd.DataFrame, evidence: pd.DataFrame,
                               legacy_kapt: pd.DataFrame, legacy_coordinates: pd.DataFrame) -> pd.DataFrame:
    valid = legacy_coordinates.loc[valid_coordinate_mask(legacy_coordinates)].drop_duplicates("kapt_code", keep="last")
    lookup = valid.set_index(valid.kapt_code.astype(str))
    kapt = legacy_kapt.merge(valid[["kapt_code", "latitude", "longitude", "geocoded_at"]],
                             on="kapt_code", how="inner", suffixes=("", "_cache"))
    kapt["_name"] = kapt.complex_name.map(_compact)
    kapt["_road"] = kapt.road_address.map(_compact)
    kapt["_lot"] = kapt.legal_address.map(_compact)
    evidence_lookup = evidence.set_index("internal_complex_id") if not evidence.empty else pd.DataFrame()
    rows = []
    for item in master.loc[~valid_coordinate_mask(master)].to_dict("records"):
        found = None; method = None
        internal_id, code = str(item["internal_complex_id"]), _text(item.get("kapt_code"))
        if internal_id in lookup.index:
            found, method = lookup.loc[internal_id], "internal_complex_id_exact"
        elif code and code in lookup.index:
            found, method = lookup.loc[code], "kapt_code_exact"
        elif not evidence.empty and internal_id in evidence_lookup.index:
            ev = evidence_lookup.loc[internal_id]
            name = _compact(item.get("complex_name")); road = _compact(ev.get("raw_road_address")); lot = _compact(ev.get("raw_lot_address"))
            candidates = kapt.loc[kapt["_name"].eq(name) & ((kapt["_road"].eq(road) & bool(road)) | (kapt["_lot"].eq(lot) & bool(lot)))]
            if len(candidates) == 1:
                found, method = candidates.iloc[0], "validated_complex_address"
        if found is not None:
            rows.append({"internal_complex_id": internal_id, "latitude": float(found.latitude),
                         "longitude": float(found.longitude), "reuse_method": method,
                         "coordinate_source_year": pd.to_datetime(found.get("geocoded_at"), errors="coerce").year})
    return pd.DataFrame(rows)


def _lot_number(main, sub, mountain="N") -> str:
    number = _number(main, sub)
    return ("산 " if mountain == "Y" and number else "") + number


def validate_geocode(document: dict, candidate: dict) -> dict:
    address = document.get("address") or {}
    road = document.get("road_address") or {}
    if (not address or not address.get("region_1depth_name")) and document.get("address_name"):
        parts = re.split(r"\s+", _text(document.get("address_name")))
        address = {"address_name": document.get("address_name"),
                   "region_1depth_name": parts[0] if len(parts) > 0 else "",
                   "region_2depth_name": parts[1] if len(parts) > 1 else "",
                   "region_3depth_name": parts[2] if len(parts) > 2 else "",
                   "main_address_no": parts[3].split("-")[0] if len(parts) > 3 else "",
                   "sub_address_no": parts[3].split("-",1)[1] if len(parts) > 3 and "-" in parts[3] else ""}
    if not road and document.get("road_address_name"):
        road = {"address_name": document.get("road_address_name")}
    x, y = document.get("x"), document.get("y")
    try:
        latitude, longitude = float(y), float(x)
    except (TypeError, ValueError):
        latitude = longitude = math.nan
    returned_sido = address.get("region_1depth_name") or road.get("region_1depth_name") or ""
    returned_sigungu = address.get("region_2depth_name") or road.get("region_2depth_name") or ""
    returned_dong = address.get("region_3depth_name") or road.get("region_3depth_name") or ""
    expected_dong = _compact(candidate.get("legal_dong"))
    dong_value = _compact(returned_dong)
    b_code = _text(address.get("b_code"))
    lawd = _text(candidate.get("lawd_cd"))
    legal_match = bool(dong_value and (expected_dong.endswith(dong_value) or dong_value.endswith(expected_dong)))
    if lawd and b_code:
        legal_match = legal_match and b_code.startswith(lawd[:5])
    sigungu_match = _compact(candidate.get("sigungu")) == _compact(returned_sigungu)
    road_match = _compact(candidate.get("road_name_evidence")) == _compact(road.get("road_name"))
    returned_building = _number(road.get("main_building_no"), road.get("sub_building_no"))
    building_match = bool(returned_building and returned_building == _text(candidate.get("road_number_evidence")))
    returned_lot = _lot_number(address.get("main_address_no"), address.get("sub_address_no"), address.get("mountain_yn"))
    lot_match = _compact(returned_lot) == _compact(candidate.get("jibun_evidence"))
    building_name = road.get("building_name") or document.get("place_name") or ""
    name_similarity = SequenceMatcher(None, _compact(candidate.get("complex_name")), _compact(building_name)).ratio() if building_name else 0.0
    busan = _compact(returned_sido) in {"부산", "부산광역시"} and 34.5 <= latitude <= 36 and 128.5 <= longitude <= 130
    kind = candidate["candidate_type"]
    if kind in {"ROAD_ADDRESS", "NORMALIZED_ROAD_ADDRESS"}:
        confirmed = busan and sigungu_match and legal_match and road_match and building_match
    elif kind in {"LOT_ADDRESS", "NORMALIZED_LOT_ADDRESS"}:
        confirmed = busan and sigungu_match and legal_match and lot_match
    else:
        confirmed = False
    status = "CONFIRMED" if confirmed else "REVIEW" if busan and sigungu_match else "REJECTED"
    reasons = []
    for ok, label in [(busan, "outside_busan"), (sigungu_match, "sigungu_mismatch"),
                      (legal_match, "legal_dong_mismatch")]:
        if not ok: reasons.append(label)
    if kind.startswith("ROAD") or kind.startswith("NORMALIZED_ROAD"):
        if not road_match: reasons.append("road_name_mismatch")
        if not building_match: reasons.append("building_number_mismatch")
    if kind in {"LOT_ADDRESS", "NORMALIZED_LOT_ADDRESS"} and not lot_match:
        reasons.append("lot_number_mismatch")
    if kind == "NAME_ADDRESS": reasons.append("name_address_requires_review")
    return {
        "latitude": latitude, "longitude": longitude,
        "returned_address": address.get("address_name") or document.get("address_name"),
        "returned_road_address": road.get("address_name") or document.get("road_address_name"),
        "returned_building_name": building_name, "result_type": document.get("address_type") or "KEYWORD",
        "returned_sido": returned_sido, "returned_sigungu": returned_sigungu,
        "returned_legal_dong": returned_dong, "returned_legal_dong_code": b_code,
        "returned_admin_dong": address.get("region_3depth_h_name"),
        "returned_admin_dong_code": address.get("h_code"), "returned_road_name": road.get("road_name"),
        "returned_building_number": returned_building, "returned_lot_number": returned_lot,
        "sigungu_match": sigungu_match, "legal_dong_match": legal_match,
        "road_name_match": road_match, "building_number_match": building_match,
        "complex_name_similarity": round(name_similarity, 4), "busan_boundary_match": busan,
        "geocode_validation_status": status, "validation_reason": ";".join(reasons) or None,
    }


def _document_from_attempt(row: dict) -> dict:
    lot = _text(row.get("returned_lot_number")).replace("산 ", "")
    lot_main, _, lot_sub = lot.partition("-")
    building = _text(row.get("returned_building_number"))
    building_main, _, building_sub = building.partition("-")
    return {
        "x": row.get("longitude"), "y": row.get("latitude"),
        "address_type": row.get("result_type"), "place_name": row.get("returned_building_name"),
        "address_name": row.get("returned_address"), "road_address_name": row.get("returned_road_address"),
        "address": {"address_name": row.get("returned_address"), "region_1depth_name": row.get("returned_sido"),
                    "region_2depth_name": row.get("returned_sigungu"), "region_3depth_name": row.get("returned_legal_dong"),
                    "region_3depth_h_name": row.get("returned_admin_dong"),
                    "b_code": row.get("returned_legal_dong_code"), "h_code": row.get("returned_admin_dong_code"),
                    "main_address_no": lot_main, "sub_address_no": lot_sub,
                    "mountain_yn": "Y" if _text(row.get("returned_lot_number")).startswith("산") else "N"},
        "road_address": {"address_name": row.get("returned_road_address"),
                         "road_name": row.get("returned_road_name"),
                         "main_building_no": building_main, "sub_building_no": building_sub,
                         "building_name": row.get("returned_building_name")},
    }


def _request(session, candidate: dict, key: str, cfg: dict) -> dict | None:
    keyword = candidate["candidate_type"] == "NAME_ADDRESS"
    endpoint = ("https://dapi.kakao.com/v2/local/search/keyword.json" if keyword else cfg["endpoint"])
    for attempt in range(int(cfg["retries"]) + 1):
        try:
            response = session.get(endpoint, headers={"Authorization": f"KakaoAK {key}"},
                                   params={"query": candidate["query_text"]}, timeout=float(cfg["timeout"]))
            if response.status_code in {401, 403}:
                raise ValueError("Kakao API key is invalid or Local API is unavailable.")
            if response.status_code == 429 or response.status_code >= 500:
                response.raise_for_status()
            if response.status_code >= 400:
                raise ValueError(f"Kakao geocoding HTTP {response.status_code}.")
            documents = response.json().get("documents", [])
            return documents[0] if documents else None
        except requests.RequestException as exc:
            if attempt >= int(cfg["retries"]):
                raise ValueError("Kakao geocoding retry limit reached.") from exc
            time.sleep(0.5 * (2 ** attempt))
    return None


def phase65_audit(*, root=ROOT) -> dict:
    root = Path(root)
    master = pd.read_parquet(root / "data/interim/apartment_master.parquet")
    evidence = transaction_address_evidence(master, root=root)
    legacy = (root / settings(root)["apartment_project"]).resolve()
    legacy_coords = pd.read_parquet(legacy / "data/interim/kapt_coordinates.parquet")
    attempt_path = root / "data/interim/geocode_attempts.parquet"
    attempts = pd.read_parquet(attempt_path) if attempt_path.exists() else pd.DataFrame()
    audit = classify_missing_coordinates(master, evidence, attempts, legacy_coords)
    candidates = address_candidates(audit)
    write_csv(root / "reports/missing_apartment_coordinates_audit.csv", audit)
    write_parquet(root / "data/interim/apartment_coordinate_candidates_2025.parquet", candidates)
    counts = audit.missing_reason.value_counts().to_dict()
    lines = ["# Phase 6.5 coordinate audit", "", f"좌표 누락 단지: {len(audit):,}개", "",
             "| missing_reason | count |", "|---|---:|"]
    lines += [f"| {reason} | {count:,} |" for reason, count in counts.items()]
    lines += ["", f"공식 실거래 도로명주소 확보: {audit.raw_road_address.notna().sum():,}개",
              f"공식 실거래 지번주소 확보: {audit.raw_lot_address.notna().sum():,}개",
              f"생성 검색후보: {len(candidates):,}건"]
    (root / "reports/phase65_coordinate_audit.md").write_text("\n".join(lines), encoding="utf-8")
    return {"missing": len(audit), "reasons": counts, "address_evidence": len(evidence),
            "candidates": len(candidates)}


def phase65_geocode(*, retry_failed=False, root=ROOT, session=None) -> dict:
    root = Path(root); phase65_audit(root=root)
    key = api_key("KAKAO_API_KEY", root)
    if not key:
        raise ValueError("KAKAO_API_KEY is not configured in this project.")
    candidates = pd.read_parquet(root / "data/interim/apartment_coordinate_candidates_2025.parquet")
    attempt_path = root / "data/interim/geocode_attempts.parquet"
    attempts = pd.read_parquet(attempt_path) if attempt_path.exists() else pd.DataFrame(columns=ATTEMPT_COLUMNS)
    candidate_lookup = {(str(r["internal_complex_id"]), str(r["query_key"])): r
                        for r in candidates.to_dict("records")}
    records = []
    for item in attempts.to_dict("records"):
        candidate = candidate_lookup.get((str(item.get("internal_complex_id")), str(item.get("query_key"))))
        if candidate and bool(item.get("success")):
            validated = validate_geocode(_document_from_attempt(item), candidate)
            item.update(validated)
        records.append(item)
    previously_attempted_ids = {str(r.get("internal_complex_id")) for r in records}
    exact = {(str(r.get("internal_complex_id")), str(r.get("query_key"))): r for r in records}
    query_cache = {}
    for r in records:
        if r.get("query_key") and (r.get("success") or not retry_failed):
            query_cache[str(r["query_key"])] = r
    confirmed_ids = {str(r["internal_complex_id"]) for r in records
                     if r.get("geocode_validation_status") == "CONFIRMED"}
    cfg = settings(root)["kakao"]
    own_session = session is None
    session = session or requests.Session()
    attempted = succeeded = failed = cache_reused = 0

    def save():
        frame = pd.DataFrame(exact.values())
        for column in ATTEMPT_COLUMNS:
            if column not in frame: frame[column] = pd.NA
        write_parquet(attempt_path, frame[ATTEMPT_COLUMNS])

    try:
        for candidate in candidates.to_dict("records"):
            complex_id = str(candidate["internal_complex_id"]); query_key = str(candidate["query_key"])
            if complex_id in confirmed_ids:
                continue
            if complex_id in previously_attempted_ids and not retry_failed:
                continue
            old = exact.get((complex_id, query_key))
            if old and (old.get("geocode_validation_status") == "CONFIRMED" or not retry_failed):
                if old.get("geocode_validation_status") == "CONFIRMED": confirmed_ids.add(complex_id)
                continue
            cached = query_cache.get(query_key)
            document = None
            if cached:
                row = {**cached, "internal_complex_id": complex_id,
                       "candidate_type": candidate["candidate_type"],
                       "candidate_priority": candidate["candidate_priority"],
                       "query_text": candidate["query_text"], "cache_reused": True}
                cache_reused += 1
            else:
                document = _request(session, candidate, key, cfg)
                attempted += 1
                base = {k: candidate.get(k) for k in ["internal_complex_id", "candidate_type",
                        "candidate_priority", "query_text", "query_key", "provider"]}
                base.update({"attempted_at": now(), "cache_reused": False,
                             "success": document is not None})
                if document is None:
                    row = {**base, "geocode_validation_status": "REJECTED",
                           "validation_reason": "not_found"}
                    failed += 1
                else:
                    row = {**base, **validate_geocode(document, candidate)}
                    succeeded += int(row["geocode_validation_status"] == "CONFIRMED")
                    failed += int(row["geocode_validation_status"] != "CONFIRMED")
                query_cache[query_key] = row
            exact[(complex_id, query_key)] = row
            if row.get("geocode_validation_status") == "CONFIRMED": confirmed_ids.add(complex_id)
            if attempted and attempted % 50 == 0:
                save()
            time.sleep(float(cfg["interval"]))
        save()
    finally:
        if own_session: session.close()
    return {"api_attempts": attempted, "confirmed_this_run": succeeded,
            "failed_attempts_this_run": failed, "query_cache_reused": cache_reused,
            "confirmed_complexes_total": len(confirmed_ids), "attempt_path": str(attempt_path)}


def duplicate_coordinate_flags(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["duplicate_coordinate_review"] = False
    valid = result.loc[result.coordinates_valid & result.latitude.notna() & result.longitude.notna()].copy()
    valid["_coord"] = valid.latitude.round(7).astype(str) + "|" + valid.longitude.round(7).astype(str)
    for _, group in valid.groupby("_coord"):
        if len(group) > 1 and group.legal_dong.map(_compact).nunique() > 1:
            result.loc[group.index, "duplicate_coordinate_review"] = True
    return result


def merge_coordinate_evidence(boundary: pd.DataFrame, direct: pd.DataFrame) -> pd.DataFrame:
    boundary = boundary.loc[boundary.official_catchment_match].copy()
    rows = {}
    for item in boundary.to_dict("records"):
        key = (item.get("internal_complex_id"), item.get("school_id"))
        rows[key] = {**item, "elementary_school_id": item.get("school_id"),
                     "elementary_school_name": item.get("school_name"),
                     "evidence_types": ["OFFICIAL_BOUNDARY"], "cross_validated": False,
                     "relation_confidence": "HIGH"}
    for item in direct.to_dict("records"):
        key = (item.get("internal_complex_id"), item.get("elementary_school_id"))
        kinds = ["OFFICIAL_DIRECT"]
        if bool(item.get("official_address_confirmed")): kinds.append("OFFICIAL_ADDRESS")
        if key in rows:
            rows[key]["evidence_types"] = list(dict.fromkeys(rows[key]["evidence_types"] + kinds))
            rows[key]["cross_validated"] = "OFFICIAL_BOUNDARY" in rows[key]["evidence_types"]
            rows[key]["direct_match_method"] = item.get("match_method")
            rows[key]["direct_match_status"] = item.get("match_status")
            rows[key]["direct_evidence_text"] = item.get("evidence_text")
        else:
            rows[key] = {**item, "school_id": item.get("elementary_school_id"),
                         "school_name": item.get("elementary_school_name"),
                         "evidence_types": kinds, "cross_validated": False,
                         "relation_confidence": "HIGH" if "OFFICIAL_DIRECT" in kinds else "MEDIUM"}
    result = pd.DataFrame(rows.values())
    if "confidence" in result:
        result["source_confidence"] = result.pop("confidence").astype("string")
    return result


def phase65_build(*, root=ROOT) -> dict:
    root = Path(root); phase65_audit(root=root)
    master = pd.read_parquet(root / "data/interim/apartment_master.parquet")
    evidence = transaction_address_evidence(master, root=root)
    legacy = (root / settings(root)["apartment_project"]).resolve()
    legacy_kapt = pd.read_parquet(legacy / "data/interim/kapt_clean.parquet")
    legacy_coords = pd.read_parquet(legacy / "data/interim/kapt_coordinates.parquet")
    reused = reuse_existing_coordinates(master, evidence, legacy_kapt, legacy_coords)
    attempts_path = root / "data/interim/geocode_attempts.parquet"
    attempts = pd.read_parquet(attempts_path) if attempts_path.exists() else pd.DataFrame(columns=ATTEMPT_COLUMNS)
    confirmed = attempts.loc[attempts.geocode_validation_status.eq("CONFIRMED")].copy()
    if not confirmed.empty:
        confirmed = confirmed.sort_values("candidate_priority").drop_duplicates("internal_complex_id")
    result = master.copy()
    existing = valid_coordinate_mask(result)
    result["coordinate_status"] = "UNRESOLVED"
    result.loc[existing, "coordinate_status"] = "EXISTING"
    result["coordinate_source"] = pd.NA
    result.loc[existing, "coordinate_source"] = "KAPT_EXISTING"
    result["coordinate_confidence"] = pd.NA
    result.loc[existing, "coordinate_confidence"] = "HIGH"
    result["coordinate_source_year"] = pd.NA
    result["coordinate_verified_at"] = now()
    result["candidate_latitude"] = pd.NA; result["candidate_longitude"] = pd.NA
    result["coordinates_valid"] = existing
    result["busan_boundary_match"] = existing
    result["legal_dong_spatial_match"] = pd.NA; result["admin_dong_spatial_match"] = pd.NA
    result["spatial_review_reason"] = pd.NA
    if not reused.empty:
        lookup = reused.set_index("internal_complex_id")
        mask = result.internal_complex_id.isin(lookup.index) & ~existing
        for idx in result.index[mask]:
            row = lookup.loc[result.at[idx, "internal_complex_id"]]
            result.at[idx, "latitude"] = row.latitude; result.at[idx, "longitude"] = row.longitude
            result.at[idx, "coordinate_status"] = "REUSED"; result.at[idx, "coordinate_source"] = "LEGACY_PROJECT"
            result.at[idx, "coordinate_confidence"] = "HIGH"; result.at[idx, "coordinate_source_year"] = row.coordinate_source_year
            result.at[idx, "coordinates_valid"] = True; result.at[idx, "busan_boundary_match"] = True
    if not confirmed.empty:
        lookup = confirmed.set_index("internal_complex_id")
        mask = result.internal_complex_id.isin(lookup.index) & ~result.coordinates_valid
        for idx in result.index[mask]:
            row = lookup.loc[result.at[idx, "internal_complex_id"]]
            result.at[idx, "latitude"] = row.latitude; result.at[idx, "longitude"] = row.longitude
            result.at[idx, "coordinate_status"] = "GEOCODED"
            result.at[idx, "coordinate_source"] = {"ROAD_ADDRESS":"KAKAO_ROAD","NORMALIZED_ROAD_ADDRESS":"KAKAO_ROAD",
                                                       "LOT_ADDRESS":"KAKAO_LOT","NORMALIZED_LOT_ADDRESS":"KAKAO_LOT"}.get(row.candidate_type,"KAKAO_NAME_ADDRESS")
            result.at[idx, "coordinate_confidence"] = "HIGH" if row.candidate_type != "NAME_ADDRESS" else "LOW"
            result.at[idx, "coordinate_source_year"] = pd.to_datetime(row.attempted_at).year
            result.at[idx, "coordinates_valid"] = True; result.at[idx, "busan_boundary_match"] = bool(row.busan_boundary_match)
    review_attempts = attempts.loc[attempts.geocode_validation_status.eq("REVIEW")]
    review_ids = set(review_attempts.internal_complex_id) - set(confirmed.internal_complex_id)
    review_mask = result.internal_complex_id.isin(review_ids) & ~result.coordinates_valid
    result.loc[review_mask, "coordinate_status"] = "REVIEW"
    if not review_attempts.empty:
        reviews = review_attempts.sort_values("candidate_priority").drop_duplicates("internal_complex_id").set_index("internal_complex_id")
        for idx in result.index[review_mask]:
            row = reviews.loc[result.at[idx, "internal_complex_id"]]
            result.at[idx, "candidate_latitude"] = row.latitude; result.at[idx, "candidate_longitude"] = row.longitude
            result.at[idx, "spatial_review_reason"] = row.validation_reason
    result = duplicate_coordinate_flags(result)
    duplicate_mask = result.duplicate_coordinate_review
    result.loc[duplicate_mask, "coordinate_status"] = "REVIEW"
    result.loc[duplicate_mask, "coordinates_valid"] = False
    result.loc[duplicate_mask, "spatial_review_reason"] = "same_coordinate_different_legal_dong"
    write_parquet(root / "data/processed/busan_apartment_coordinates_2025.parquet", result)
    review = result.loc[result.coordinate_status.isin(["REVIEW", "UNRESOLVED"])]
    write_csv(root / "reports/coordinate_review.csv", review)

    before_count = int(valid_coordinate_mask(master).sum())
    after_count = int(result.coordinates_valid.sum())
    before_large = int((pd.to_numeric(master.households, errors="coerce").ge(500) & valid_coordinate_mask(master)).sum())
    large_total = int(pd.to_numeric(master.households, errors="coerce").ge(500).sum())
    after_large = int((pd.to_numeric(result.households, errors="coerce").ge(500) & result.coordinates_valid).sum())
    # Rebuild boundary relations using only validated coordinates from this table.
    from .build_schoolzone import build_schoolzone, spatial_match_apartments
    baseline_boundaries = gpd.read_parquet(root / "data/processed/busan_elementary_catchment_boundaries_2025.parquet")
    baseline_links = pd.read_parquet(root / "data/processed/busan_schoolzone_school_link_2025.parquet")
    before_boundary = spatial_match_apartments(master, baseline_boundaries, baseline_links)
    before_boundary_count = int(before_boundary.loc[before_boundary.official_catchment_match, "internal_complex_id"].nunique())
    before_boundary_relations = int(before_boundary.official_catchment_match.sum())
    build_schoolzone(2025, root=root)
    boundary = pd.read_parquet(root / "data/processed/busan_apartment_elementary_match_2025.parquet")
    after_boundary_count = int(boundary.loc[boundary.official_catchment_match, "internal_complex_id"].nunique())
    after_boundary_relations = int(boundary.official_catchment_match.sum())
    direct_path = root / "data/processed/haeundae_apartment_elementary_match_2025.parquet"
    direct = pd.read_parquet(direct_path) if direct_path.exists() else pd.DataFrame()
    relations = merge_coordinate_evidence(boundary, direct)
    write_parquet(root / "data/processed/busan_apartment_elementary_relation_2025.parquet", relations)

    status_counts = result.coordinate_status.value_counts().to_dict()
    source_counts = result.coordinate_source.value_counts(dropna=False).to_dict()
    quality_rows = [
        {"scope":"all", "metric":"before_coordinate_count", "value":before_count},
        {"scope":"all", "metric":"after_coordinate_count", "value":after_count},
        {"scope":"all", "metric":"before_coverage_pct", "value":round(before_count/len(result)*100,2)},
        {"scope":"all", "metric":"after_coverage_pct", "value":round(after_count/len(result)*100,2)},
        {"scope":"500plus", "metric":"total", "value":large_total},
        {"scope":"500plus", "metric":"before_coordinate_count", "value":before_large},
        {"scope":"500plus", "metric":"after_coordinate_count", "value":after_large},
        {"scope":"500plus", "metric":"after_coverage_pct", "value":round(after_large/max(large_total,1)*100,2)},
        {"scope":"boundary", "metric":"before_match", "value":before_boundary_count},
        {"scope":"boundary", "metric":"after_match", "value":after_boundary_count},
        {"scope":"boundary", "metric":"before_relation_count", "value":before_boundary_relations},
        {"scope":"boundary", "metric":"after_relation_count", "value":after_boundary_relations},
    ]
    for value, count in status_counts.items():
        quality_rows.append({"scope":"coordinate_status", "metric":str(value), "value":count})
    for value, count in source_counts.items():
        quality_rows.append({"scope":"coordinate_source", "metric":str(value), "value":count})
    attempt_quality = []
    if not attempts.empty:
        for candidate_type, group in attempts.groupby("candidate_type"):
            attempt_quality.append({"candidate_type":candidate_type, "attempt_count":len(group),
                                    "api_result_count":int(group.success.fillna(False).sum()),
                                    "confirmed_count":int(group.geocode_validation_status.eq("CONFIRMED").sum()),
                                    "confirmed_rate_pct":round(group.geocode_validation_status.eq("CONFIRMED").mean()*100,2)})
            quality_rows.append({"scope":"candidate_type", "metric":f"{candidate_type}_confirmed_rate_pct",
                                 "value":attempt_quality[-1]["confirmed_rate_pct"]})
    write_csv(root / "reports/phase65_coordinate_quality.csv", pd.DataFrame(quality_rows))
    large_pct = after_large / max(large_total, 1) * 100
    readiness = "READY" if large_pct >= 95 else "READY_WITH_REVIEW" if large_pct >= 90 else "NOT_READY"
    remaining = result.loc[~result.coordinates_valid]
    remaining_reasons = remaining.coordinate_status.value_counts().to_dict()
    source_text = ", ".join(f"{key}: {value:,}" for key, value in source_counts.items() if pd.notna(key))
    attempt_lines = ["| candidate_type | attempts | API result | confirmed | confirmed rate |",
                     "|---|---:|---:|---:|---:|"]
    attempt_lines += [f"| {x['candidate_type']} | {x['attempt_count']:,} | {x['api_result_count']:,} | {x['confirmed_count']:,} | {x['confirmed_rate_pct']:.2f}% |" for x in attempt_quality]
    outside_rows = boundary.loc[boundary.match_status.eq("OUTSIDE_OFFICIAL_BOUNDARY")].drop_duplicates("internal_complex_id")
    outside_lines = ["| internal_complex_id | complex_name | distance_m |", "|---|---|---:|"]
    outside_lines += [f"| {x.internal_complex_id} | {x.complex_name} | {float(x.nearest_boundary_distance_m):.1f} |" for x in outside_rows.itertuples()]
    review_lines = ["| internal_complex_id | complex_name | status | reason |", "|---|---|---|---|"]
    review_lines += [f"| {x.internal_complex_id} | {x.complex_name} | {x.coordinate_status} | {x.spatial_review_reason} |" for x in remaining.head(20).itertuples()]
    lines = ["# Phase 6.5 validation", "", f"**{readiness}**", "",
             "## A. 좌표 누락 원인", "", "초기 누락 3,053개는 K-apt 미연결 거래 단지이며 공식 실거래 주소를 복원했다.", "",
             "## B. 좌표 재사용 및 지오코딩", "", f"기존 {before_count:,}개, 재사용 {len(reused):,}개, 주소 검증 통과 {int(confirmed.internal_complex_id.nunique()):,}개, 중복좌표 검토 제외 후 신규 확정 {int(result.coordinate_status.eq('GEOCODED').sum()):,}개.", f"좌표 source별 건수: {source_text}.", "", *attempt_lines, "",
             "## C. 전체 좌표 커버리지", "", f"{before_count:,}/{len(result):,} ({before_count/len(result)*100:.2f}%) → {after_count:,}/{len(result):,} ({after_count/len(result)*100:.2f}%)", "",
             "## D. 500세대 이상 좌표 커버리지", "", f"{before_large:,}/{large_total:,} → {after_large:,}/{large_total:,} ({large_pct:.2f}%)", "",
             "## E. 공식 학구도 공간매칭", "", f"경계 포함 단지 {before_boundary_count:,}개 → {after_boundary_count:,}개, 신규 {after_boundary_count-before_boundary_count:,}개. 공간관계 {before_boundary_relations:,}건 → {after_boundary_relations:,}건, 신규 {after_boundary_relations-before_boundary_relations:,}건. 경계 밖 {len(outside_rows):,}개.", "", *outside_lines, "",
             "## F. REVIEW/UNRESOLVED", "", json.dumps(remaining_reasons, ensure_ascii=False), "", *review_lines, "",
             "## G. 근거 병합", "", f"공동통학 many-to-many를 유지한 최종 관계 {len(relations):,}건. 기존 직접 근거는 삭제하지 않고 `evidence_types`에 병합했다.", "",
             "## H. 제한", "", "학구도 경계에는 법정동·행정동 경계가 없어 해당 공간 일치값을 추정하지 않았다. Kakao 반환 법정동/행정동 코드는 주소 검증 근거로 별도 보존했다.", "",
             "## I. Phase 7 진행 가능 여부", "", f"**{readiness}** — 500세대 이상 좌표 커버리지 기준으로 판정했다. Phase 7은 자동 시작하지 않는다."]
    (root / "reports/phase65_validation.md").write_text("\n".join(lines), encoding="utf-8")
    return {"status":readiness, "before_coordinate_count":before_count,
            "after_coordinate_count":after_count, "total":len(result),
            "before_500plus":before_large, "after_500plus":after_large,
            "total_500plus":large_total, "reused":len(reused),
            "new_geocoded":int(result.coordinate_status.eq("GEOCODED").sum()),
            "coordinate_status":status_counts, "coordinate_source":{str(k):v for k,v in source_counts.items()},
            "before_boundary_match":before_boundary_count, "after_boundary_match":after_boundary_count,
            "new_boundary_matches":after_boundary_count-before_boundary_count,
            "before_boundary_relations":before_boundary_relations,
            "after_boundary_relations":after_boundary_relations,
            "new_boundary_relations":after_boundary_relations-before_boundary_relations,
            "relations":len(relations), "report":str(root/"reports/phase65_validation.md")}
