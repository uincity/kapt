import io
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

from src.build_schoolzone import map_internal_school_ids, spatial_match_apartments
from src.collect_schoolzone import collect_schoolzone


def _zip_bytes(name="fixture.txt", value=b"official"):
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(name, value)
    return stream.getvalue()


class _Response:
    status_code = 200
    content = _zip_bytes()


class _Session:
    def get(self, url, timeout):
        assert "publicDataFileDownload.do" in url and timeout == 180
        return _Response()


def test_schoolzone_collector_writes_and_verifies_cache(tmp_path):
    first = collect_schoolzone(root=tmp_path, session=_Session())
    assert all(item["status"] == "downloaded" for item in first.values())
    second = collect_schoolzone(root=tmp_path, session=None)
    assert all(item["status"] == "cached" for item in second.values())


def test_schoolzone_internal_id_uses_unique_name_across_office_boundary():
    links = pd.DataFrame([{
        "school_zone_id": "Z1", "school_name": "가초등학교", "education_office_name": "남부",
    }])
    boundaries = pd.DataFrame([{"school_zone_id": "Z1", "sigungu_code": "530"}])
    schools = pd.DataFrame([{
        "school_id": "S1", "school_name": "가초등학교", "school_level": "elementary",
        "education_office": "북부", "closed": "N", "suspended": "N", "data_year": 2026,
    }])
    mapped = map_internal_school_ids(links, boundaries, schools)
    assert mapped.loc[0, "school_id"] == "S1"
    assert mapped.loc[0, "school_id_match_status"] == "MATCHED_ACTIVE_NAME"


def test_schoolzone_boundary_match_preserves_shared_school_relations():
    boundaries = gpd.GeoDataFrame([{
        "school_zone_id": "Z1", "school_zone_name": "공동통학구역",
        "school_zone_type": "SHARED", "education_office_name": "해운대",
        "geometry": Polygon([(0, 0), (100, 0), (100, 100), (0, 100)]),
    }], crs="EPSG:5186")
    point = gpd.GeoSeries.from_xy([50], [50], crs="EPSG:5186").to_crs(4326).iloc[0]
    apartments = pd.DataFrame([
        {"internal_complex_id": "A1", "latitude": point.y, "longitude": point.x},
        {"internal_complex_id": "A2", "latitude": None, "longitude": None},
    ])
    links = pd.DataFrame([
        {"school_zone_id": "Z1", "school_id": "S1", "school_name": "가초"},
        {"school_zone_id": "Z1", "school_id": "S2", "school_name": "나초"},
    ])
    result = spatial_match_apartments(apartments, boundaries, links)
    matched = result[result.internal_complex_id.eq("A1")]
    assert matched.official_catchment_match.all()
    assert set(matched.school_id) == {"S1", "S2"}
    assert result.evidence_type.eq("OFFICIAL_SCHOOLZONE_BOUNDARY").all()
    assert result.loc[result.internal_complex_id.eq("A2"), "match_status"].iloc[0] == "COORDINATE_MISSING"
