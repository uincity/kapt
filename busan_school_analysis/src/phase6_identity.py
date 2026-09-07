"""School-ID, address provenance and administrative-area helpers."""
from __future__ import annotations
import pandas as pd


def build_school_name_mapping(names: pd.DataFrame, schools: pd.DataFrame, year: int) -> pd.DataFrame:
    rows = []
    for item in names.to_dict("records"):
        candidates = schools[schools.school_name.eq(item["school_name"])]
        if item.get("school_level"):
            candidates = candidates[candidates.school_level.eq(item["school_level"])]
        if item.get("education_office"):
            candidates = candidates[candidates.education_office.astype(str).str.contains(str(item["education_office"]))]
        unique = candidates.school_id.dropna().unique()
        ok = len(unique) == 1
        rows.append({"school_name": item["school_name"], "school_id": unique[0] if ok else None,
                     "data_year": year, "education_office": item.get("education_office"),
                     "match_method": "name+level+office" if ok else "unresolved",
                     "confidence": 1.0 if ok else 0.0, "manual_review": not ok})
    return pd.DataFrame(rows)


def scores_by_id(scores: pd.DataFrame, schools: pd.DataFrame) -> pd.DataFrame:
    # Existing Phase 3 IDs are authoritative; school names are only a consistency check.
    valid = set(schools.school_id.dropna())
    out = scores.copy()
    out["join_status"] = out.middle_school_id.map(lambda x: "MATCHED" if x in valid else "ID_NOT_FOUND")
    columns = ["middle_school_id", "middle_school_name", "data_year", "middle_school_score",
               "busan_rank", "sigungu_rank", "join_status"]
    return out[[c for c in columns if c in out.columns]]


def build_address_history(apartments: pd.DataFrame, source_year=None) -> pd.DataFrame:
    frame = apartments.copy()
    result = pd.DataFrame({
        "internal_complex_id": frame.get("internal_complex_id"), "kapt_code": frame.get("kapt_code"),
        "complex_name": frame.get("complex_name"), "address": frame.get("address"),
        "road_address": frame.get("road_address"), "legal_dong_code": frame.get("legal_dong_code"),
        "valid_from": pd.NA, "valid_to": pd.NA, "address_source": "current_kapt_snapshot",
        "source_year": source_year, "current_flag": True,
        "address_source_type": "CURRENT_KAPT", "address_source_year": source_year,
        "address_temporal_match": bool(source_year == 2025)})
    return result


def validate_admin_area(address_legal, address_admin, spatial_legal=None, spatial_admin=None) -> dict:
    available = spatial_legal is not None or spatial_admin is not None
    consistent = None if not available else address_legal == spatial_legal and address_admin == spatial_admin
    return {"spatial_legal_dong_code": spatial_legal, "spatial_admin_dong_code": spatial_admin,
            "address_legal_dong_code": address_legal, "address_admin_dong_code": address_admin,
            "admin_area_consistent": consistent, "admin_area_conflict": consistent is False,
            "manual_review": consistent is False}
