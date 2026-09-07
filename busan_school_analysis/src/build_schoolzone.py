"""Build Busan 2025 catchments and apartment assignments from official polygons."""
from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd

from .collect_schoolzone import LIST_URL, SNAPSHOT_DATE, SOURCES
from .config import ROOT, now, write_csv, write_parquet


BOUNDARY_COLUMNS = {
    "HAKGUDO_ID": "school_zone_id",
    "HAKGUDO_NM": "school_zone_name",
    "HAKGUDO_GB": "school_zone_type_code",
    "SD_CD": "sido_code",
    "SGG_CD": "sigungu_code",
    "EDU_UP_CD": "regional_office_code",
    "EDU_UP_NM": "regional_office_name",
    "EDU_CD": "education_office_code",
    "EDU_NM": "education_office_name",
    "CRE_DT": "created_date",
    "UPD_DT": "updated_date",
    "BASE_DT": "base_date",
}
LINK_COLUMNS = [
    "school_zone_id", "external_school_id", "school_name", "school_level",
    "regional_office_code", "regional_office_name", "education_office_code",
    "education_office_name", "base_date",
]


def _extract_named(zip_path: Path, output_dir: Path, prefix: str, allowed: set[str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with ZipFile(zip_path) as archive:
        for member in archive.infolist():
            suffix = Path(member.filename).suffix.lower()
            if suffix not in allowed or member.is_dir():
                continue
            target = output_dir / f"{prefix}{suffix}"
            target.write_bytes(archive.read(member))
            written.append(target)
    return written


def _normal_school_name(value) -> str:
    value = re.sub(r"\([^)]*(휴교|폐교)[^)]*\)", "", str(value))
    return re.sub(r"\s+", "", value).replace("초등학교", "초")


def map_internal_school_ids(links: pd.DataFrame, boundaries: pd.DataFrame,
                            schools: pd.DataFrame) -> pd.DataFrame:
    out = links.merge(boundaries[["school_zone_id", "sigungu_code"]],
                      on="school_zone_id", how="left", validate="many_to_one")
    out["_name"] = out.school_name.map(_normal_school_name)
    current = schools.loc[schools.school_level.eq("elementary")].copy()
    current = current.loc[current.closed.fillna("N").ne("Y") & current.suspended.fillna("N").ne("Y")]
    current["_name"] = current.school_name.map(_normal_school_name)
    current["education_office_name"] = current.education_office.astype(str)
    mapped = []
    reference_year = pd.to_numeric(current.data_year, errors="coerce").max()
    for item in out.to_dict("records"):
        candidates = current.loc[current["_name"].eq(item["_name"])]
        method = "ACTIVE_NAME"
        if len(candidates) > 1:
            same_office = candidates.loc[candidates.education_office_name.eq(item["education_office_name"])]
            candidates = same_office if len(same_office) == 1 else candidates
            method = "ACTIVE_NAME_OFFICE"
        matched = candidates.iloc[0] if len(candidates) == 1 else None
        status_note = "휴교" if "휴교" in str(item["school_name"]) else None
        item.update({
            "school_id": None if matched is None else matched.school_id,
            "school_name_current": None if matched is None else matched.school_name,
            "school_education_office_current": None if matched is None else matched.education_office,
            "school_id_match_status": ("UNRESOLVED" if matched is None else
                                       "MATCHED_NAME_STATUS_REVIEW" if status_note else
                                       f"MATCHED_{method}"),
            "school_id_match_confidence": 0.0 if matched is None else 0.7 if status_note else 0.95,
            "school_reference_year": reference_year,
            "official_school_status_note": status_note,
            "manual_review": matched is None or status_note is not None,
        })
        mapped.append(item)
    return pd.DataFrame(mapped).drop(columns=["_name"], errors="ignore")


def spatial_match_apartments(apartments: pd.DataFrame, boundaries: gpd.GeoDataFrame,
                             links: pd.DataFrame) -> pd.DataFrame:
    valid = apartments.latitude.notna() & apartments.longitude.notna()
    points = gpd.GeoDataFrame(apartments.loc[valid].copy(), geometry=gpd.points_from_xy(
        apartments.loc[valid, "longitude"], apartments.loc[valid, "latitude"]), crs="EPSG:4326")
    points = points.to_crs(boundaries.crs)
    joined = gpd.sjoin(points, boundaries[["school_zone_id", "school_zone_name",
                                           "school_zone_type", "education_office_name", "geometry"]],
                       how="left", predicate="intersects").drop(columns=["index_right"])
    outside_ids = joined.loc[joined.school_zone_id.isna(), "internal_complex_id"].unique()
    if len(outside_ids):
        nearest_points = points.loc[points.internal_complex_id.isin(outside_ids)]
        nearest = gpd.sjoin_nearest(
            nearest_points,
            boundaries[["school_zone_id", "school_zone_name", "geometry"]],
            how="left", distance_col="nearest_boundary_distance_m").reset_index(drop=True)
        nearest = nearest.sort_values("nearest_boundary_distance_m").drop_duplicates("internal_complex_id")
        nearest = nearest[["internal_complex_id", "school_zone_id", "school_zone_name",
                           "nearest_boundary_distance_m"]].rename(columns={
                               "school_zone_id": "nearest_school_zone_id",
                               "school_zone_name": "nearest_school_zone_name"})
        joined = joined.merge(nearest, on="internal_complex_id", how="left")
    else:
        joined["nearest_school_zone_id"] = pd.NA
        joined["nearest_school_zone_name"] = pd.NA
        joined["nearest_boundary_distance_m"] = pd.NA
    joined = joined.merge(links, on="school_zone_id", how="left", suffixes=("", "_link"))
    joined["data_year"] = 2025
    joined["boundary_base_date"] = SNAPSHOT_DATE
    joined["evidence_type"] = "OFFICIAL_SCHOOLZONE_BOUNDARY"
    joined["official_catchment_match"] = joined.school_zone_id.notna()
    joined["match_status"] = joined.school_zone_id.notna().map(
        {True: "OFFICIAL_BOUNDARY_MATCH", False: "OUTSIDE_OFFICIAL_BOUNDARY"})
    joined["address_source_type"] = "CURRENT_KAPT"
    joined["address_temporal_match"] = False
    joined["source_name"] = "학구도안내서비스 공공데이터"
    joined["source_url"] = LIST_URL
    link_review = joined["manual_review"].fillna(False) if "manual_review" in joined else False
    joined["manual_review"] = joined.school_zone_id.isna() | joined.school_id.isna() | link_review
    joined["confidence"] = joined.school_zone_id.notna().astype(float)
    joined["spatial_legal_dong_code"] = pd.NA
    joined["spatial_admin_dong_code"] = pd.NA
    joined["admin_area_validation_status"] = "NOT_AVAILABLE_IN_SCHOOLZONE_BOUNDARY"
    result = pd.DataFrame(joined.drop(columns="geometry"))
    missing = apartments.loc[~valid].copy()
    if not missing.empty:
        for column in result.columns:
            if column not in missing:
                missing[column] = pd.NA
        missing["data_year"] = 2025
        missing["boundary_base_date"] = SNAPSHOT_DATE
        missing["evidence_type"] = "OFFICIAL_SCHOOLZONE_BOUNDARY"
        missing["official_catchment_match"] = False
        missing["match_status"] = "COORDINATE_MISSING"
        missing["address_source_type"] = "CURRENT_KAPT"
        missing["address_temporal_match"] = False
        missing["source_name"] = "학구도안내서비스 공공데이터"
        missing["source_url"] = LIST_URL
        missing["manual_review"] = True
        missing["confidence"] = 0.0
        missing["admin_area_validation_status"] = "COORDINATE_MISSING"
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="The behavior of DataFrame concatenation with empty or all-NA entries")
            result = pd.concat([result, missing[result.columns]], ignore_index=True)
    return result


def build_schoolzone(year=2025, *, root=ROOT) -> dict:
    if year != 2025:
        raise ValueError("The official boundary build is pinned to 2025-09-22.")
    root = Path(root)
    raw = root / "data/raw/schoolzone/2025"
    for source in SOURCES.values():
        path = raw / source["filename"]
        meta_path = path.with_suffix(".metadata.json")
        if not path.exists() or not meta_path.exists():
            raise FileNotFoundError("Run collect-schoolzone --year 2025 first.")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("snapshot_date") != SNAPSHOT_DATE:
            raise ValueError("Schoolzone snapshot date mismatch.")
    extracted = raw / "extracted"
    _extract_named(raw / SOURCES["elementary_catchment"]["filename"], extracted,
                   "elementary_catchment", {".shp", ".shx", ".dbf", ".prj", ".cpg", ".qmd"})
    _extract_named(raw / SOURCES["school_zone_link"]["filename"], extracted,
                   "school_zone_link", {".csv"})

    boundaries = gpd.read_file(extracted / "elementary_catchment.shp", encoding="euc-kr")
    if boundaries.crs is None or boundaries.crs.to_epsg() != 5186:
        raise ValueError(f"Unexpected Schoolzone CRS: {boundaries.crs}")
    missing = set(BOUNDARY_COLUMNS) - set(boundaries.columns)
    if missing:
        raise ValueError(f"Schoolzone boundary schema changed: {sorted(missing)}")
    boundaries = boundaries.loc[boundaries.SD_CD.astype(str).eq("26")].rename(columns=BOUNDARY_COLUMNS)
    if boundaries.empty or boundaries.school_zone_id.duplicated().any():
        raise ValueError("Busan Schoolzone boundary IDs are empty or duplicated.")
    if set(boundaries.base_date.dropna().astype(str)) != {SNAPSHOT_DATE}:
        raise ValueError("Boundary BASE_DT is not the requested snapshot date.")
    boundaries["school_zone_type"] = boundaries.school_zone_type_code.map(
        {"0": "GENERAL", "1": "SHARED"}).fillna("UNKNOWN")
    boundaries["data_year"] = 2025
    boundaries["source_name"] = "학구도안내서비스 공공데이터"
    boundaries["source_url"] = LIST_URL
    boundaries["source_document"] = str((raw / SOURCES["elementary_catchment"]["filename"]).relative_to(root))
    boundaries["collected_at"] = now()
    boundaries["boundary_evidence_type"] = "OFFICIAL_BOUNDARY"

    links = pd.read_csv(extracted / "school_zone_link.csv", encoding="cp949", dtype=str)
    if links.shape[1] != len(LINK_COLUMNS):
        raise ValueError("Schoolzone link CSV schema changed.")
    links.columns = LINK_COLUMNS
    links = links.loc[(links.regional_office_code.eq("7150000"))
                      & links.school_level.eq("초등학교")].copy()
    if set(links.school_zone_id) != set(boundaries.school_zone_id):
        raise ValueError("Busan elementary boundary/link coverage mismatch.")
    if set(links.base_date.dropna()) != {SNAPSHOT_DATE}:
        raise ValueError("School-zone link base date mismatch.")
    links = map_internal_school_ids(links, boundaries, pd.read_parquet(root / "data/processed/schools.parquet"))
    links["data_year"] = 2025
    links["source_name"] = "학구도안내서비스 공공데이터"
    links["source_url"] = LIST_URL
    links["source_document"] = str((raw / SOURCES["school_zone_link"]["filename"]).relative_to(root))

    processed = root / "data/processed"
    write_parquet(processed / "busan_elementary_catchment_boundaries_2025.parquet", boundaries)
    write_parquet(processed / "busan_schoolzone_school_link_2025.parquet", links)
    coordinate_path = root / "data/processed/busan_apartment_coordinates_2025.parquet"
    apartments = (pd.read_parquet(coordinate_path) if coordinate_path.exists()
                  else pd.read_parquet(root / "data/interim/apartment_master.parquet"))
    if "coordinates_valid" in apartments:
        invalid = ~apartments.coordinates_valid.fillna(False)
        apartments.loc[invalid, ["latitude", "longitude"]] = pd.NA
    matches = spatial_match_apartments(apartments, boundaries, links)
    write_parquet(processed / "busan_apartment_elementary_match_2025.parquet", matches)

    office_quality = (boundaries.groupby("education_office_name", dropna=False)
                      .agg(boundary_count=("school_zone_id", "nunique"),
                           shared_boundary_count=("school_zone_type", lambda x: int(x.eq("SHARED").sum())))
                      .reset_index())
    apt_by_office = (matches.loc[matches.official_catchment_match]
                     .groupby("education_office_name").internal_complex_id.nunique()
                     .rename("matched_apartment_count"))
    office_quality = office_quality.merge(apt_by_office, on="education_office_name", how="left").fillna(
        {"matched_apartment_count": 0})
    write_csv(root / "reports/schoolzone_2025_quality.csv", office_quality)
    summary = {
        "status": "READY",
        "snapshot_date": SNAPSHOT_DATE,
        "boundary_count": int(boundaries.school_zone_id.nunique()),
        "shared_boundary_count": int(boundaries.school_zone_type.eq("SHARED").sum()),
        "school_link_count": len(links),
        "school_id_matched": int(links.school_id.notna().sum()),
        "school_id_unresolved": int(links.school_id.isna().sum()),
        "apartment_count": int(apartments.internal_complex_id.nunique()),
        "apartment_boundary_matched": int(matches.loc[matches.official_catchment_match,
                                                        "internal_complex_id"].nunique()),
        "apartment_outside_boundary": int(matches.loc[
            matches.match_status.eq("OUTSIDE_OFFICIAL_BOUNDARY"), "internal_complex_id"].nunique()),
        "apartment_coordinate_missing": int(matches.loc[matches.match_status.eq("COORDINATE_MISSING"),
                                                          "internal_complex_id"].nunique()),
        "apartment_school_relations": int(matches.official_catchment_match.sum()),
    }
    (root / "reports/schoolzone_2025_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
