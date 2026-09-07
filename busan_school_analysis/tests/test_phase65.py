import pandas as pd

import src.phase65_coordinates as p65
from src.phase6_identity import validate_admin_area


def candidate(kind="ROAD_ADDRESS", **changes):
    value = {
        "internal_complex_id": "A1", "candidate_type": kind, "candidate_priority": 1,
        "query_text": "부산광역시 해운대구 센텀로 10", "query_key": "key",
        "provider": "KAKAO_ADDRESS", "sigungu": "해운대구", "legal_dong": "재송동",
        "lawd_cd": "26350", "road_name_evidence": "센텀로", "road_number_evidence": "10",
        "jibun_evidence": "100-1", "complex_name": "센텀아파트",
    }
    value.update(changes)
    return value


def document(**changes):
    value = {
        "x": "129.12", "y": "35.18", "address_type": "ROAD_ADDR",
        "address": {"address_name":"부산 해운대구 재송동 100-1", "region_1depth_name":"부산",
                    "region_2depth_name":"해운대구", "region_3depth_name":"재송동",
                    "region_3depth_h_name":"재송1동", "b_code":"2635010400", "h_code":"2635052000",
                    "main_address_no":"100", "sub_address_no":"1", "mountain_yn":"N"},
        "road_address": {"address_name":"부산 해운대구 센텀로 10", "road_name":"센텀로",
                         "main_building_no":"10", "sub_building_no":"", "building_name":"센텀아파트"},
    }
    value.update(changes)
    return value


def test_missing_coordinate_classification():
    master = pd.DataFrame([{"internal_complex_id":"T1", "kapt_code":None, "complex_name":"가",
                            "households":None, "address":None, "road_address":None,
                            "legal_dong":"재송동", "latitude":None, "longitude":None}])
    evidence = pd.DataFrame([{"internal_complex_id":"T1", "raw_road_address":"부산 해운대구 센텀로 1",
                              "raw_lot_address":"부산 해운대구 재송동 1", "address_evidence_source":"OFFICIAL",
                              "normalized_road_address":"부산 해운대구 센텀로 1",
                              "normalized_lot_address":"부산 해운대구 재송동 1"}])
    assert p65.classify_missing_coordinates(master, evidence).missing_reason.iloc[0] == "KAPT_UNMATCHED"


def test_reuse_existing_coordinates():
    master = pd.DataFrame([{"internal_complex_id":"A1", "kapt_code":"A1", "latitude":None, "longitude":None}])
    coords = pd.DataFrame([{"kapt_code":"A1", "latitude":35.1, "longitude":129.1, "geocoded_at":"2025-01-01"}])
    kapt = pd.DataFrame([{"kapt_code":"A1", "complex_name":"가", "road_address":"부산로 1", "legal_address":"가동 1"}])
    result = p65.reuse_existing_coordinates(master, pd.DataFrame(), kapt, coords)
    assert result.iloc[0].reuse_method == "internal_complex_id_exact"


def test_coordinate_cache(tmp_path, monkeypatch):
    candidates = pd.DataFrame([candidate()])
    (tmp_path/"data/interim").mkdir(parents=True)
    candidates.to_parquet(tmp_path/"data/interim/apartment_coordinate_candidates_2025.parquet", index=False)
    monkeypatch.setattr(p65, "phase65_audit", lambda **kwargs: {})
    monkeypatch.setattr(p65, "api_key", lambda *args: "secret")
    monkeypatch.setattr(p65, "settings", lambda root: {"kakao":{"endpoint":"x","retries":0,"timeout":1,"interval":0}})
    calls = []
    monkeypatch.setattr(p65, "_request", lambda *args: calls.append(1) or document())
    session = object()
    p65.phase65_geocode(root=tmp_path, session=session)
    p65.phase65_geocode(root=tmp_path, session=session)
    assert len(calls) == 1


def test_failed_coordinate_cache_requires_retry(tmp_path, monkeypatch):
    candidates = pd.DataFrame([candidate()])
    (tmp_path/"data/interim").mkdir(parents=True)
    candidates.to_parquet(tmp_path/"data/interim/apartment_coordinate_candidates_2025.parquet", index=False)
    pd.DataFrame([{**candidate(), "attempted_at":"2025-01-01", "cache_reused":False,
                   "success":False, "geocode_validation_status":"REJECTED",
                   "validation_reason":"not_found"}]).to_parquet(
                       tmp_path/"data/interim/geocode_attempts.parquet", index=False)
    monkeypatch.setattr(p65, "phase65_audit", lambda **kwargs: {})
    monkeypatch.setattr(p65, "api_key", lambda *args: "secret")
    monkeypatch.setattr(p65, "settings", lambda root: {"kakao":{"endpoint":"x","retries":0,"timeout":1,"interval":0}})
    calls = []
    monkeypatch.setattr(p65, "_request", lambda *args: calls.append(1))
    result = p65.phase65_geocode(root=tmp_path, session=object())
    assert result["api_attempts"] == 0 and not calls


def test_road_address_priority():
    audit = pd.DataFrame([{**candidate(), "raw_road_address":"부산 해운대구 센텀로 10",
                           "raw_lot_address":"부산 해운대구 재송동 100-1",
                           "normalized_road_address":"부산 해운대구 센텀로 10",
                           "normalized_lot_address":"부산 해운대구 재송동 100-1", "households":100}])
    result = p65.address_candidates(audit)
    assert result.iloc[0].candidate_type == "ROAD_ADDRESS"


def test_lot_address_fallback():
    result = p65.validate_geocode(document(), candidate("LOT_ADDRESS"))
    assert result["geocode_validation_status"] == "CONFIRMED"


def test_name_address_fallback_review():
    result = p65.validate_geocode(document(), candidate("NAME_ADDRESS"))
    assert result["geocode_validation_status"] == "REVIEW"


def test_geocode_sigungu_validation():
    doc = document(); doc["address"] = {**doc["address"], "region_2depth_name":"수영구"}
    assert p65.validate_geocode(doc, candidate())["geocode_validation_status"] == "REJECTED"


def test_geocode_legal_dong_validation():
    doc = document(); doc["address"] = {**doc["address"], "region_3depth_name":"우동", "b_code":"2635010500"}
    assert not p65.validate_geocode(doc, candidate())["legal_dong_match"]


def test_outside_busan_rejected():
    doc = document(); doc["address"] = {**doc["address"], "region_1depth_name":"서울"}
    assert p65.validate_geocode(doc, candidate())["geocode_validation_status"] == "REJECTED"


def test_spatial_admin_conflict():
    assert validate_admin_area("1", "2", "1", "3")["manual_review"]


def test_duplicate_coordinate_review():
    frame = pd.DataFrame([{"latitude":35.1,"longitude":129.1,"coordinates_valid":True,"legal_dong":"가동"},
                          {"latitude":35.1,"longitude":129.1,"coordinates_valid":True,"legal_dong":"나동"}])
    assert p65.duplicate_coordinate_flags(frame).duplicate_coordinate_review.all()


def test_500_household_priority():
    audit = pd.DataFrame([{**candidate(), "internal_complex_id":"small", "households":100,
                           "raw_road_address":"부산 해운대구 센텀로 1", "raw_lot_address":None,
                           "normalized_road_address":None,"normalized_lot_address":None},
                          {**candidate(), "internal_complex_id":"large", "households":500,
                           "raw_road_address":"부산 해운대구 센텀로 2", "raw_lot_address":None,
                           "normalized_road_address":None,"normalized_lot_address":None}])
    assert p65.address_candidates(audit).iloc[0].internal_complex_id == "large"


def test_missing_coordinate_official_direct_preserved():
    boundary = pd.DataFrame(columns=["official_catchment_match"])
    direct = pd.DataFrame([{"internal_complex_id":"A1", "elementary_school_id":"S1",
                            "elementary_school_name":"가초", "official_address_confirmed":False}])
    result = p65.merge_coordinate_evidence(boundary, direct)
    assert result.iloc[0].evidence_types == ["OFFICIAL_DIRECT"]


def test_boundary_match_many_to_many():
    boundary = pd.DataFrame([{"internal_complex_id":"A1","school_id":"S1","school_name":"가초","official_catchment_match":True},
                             {"internal_complex_id":"A1","school_id":"S2","school_name":"나초","official_catchment_match":True}])
    result = p65.merge_coordinate_evidence(boundary, pd.DataFrame())
    assert set(result.elementary_school_id) == {"S1", "S2"}


def test_coordinate_evidence_merge():
    boundary = pd.DataFrame([{"internal_complex_id":"A1","school_id":"S1","school_name":"가초","official_catchment_match":True}])
    direct = pd.DataFrame([{"internal_complex_id":"A1","elementary_school_id":"S1","elementary_school_name":"가초",
                            "official_address_confirmed":True,"match_method":"exact","match_status":"CONFIRMED"}])
    result = p65.merge_coordinate_evidence(boundary, direct).iloc[0]
    assert result.cross_validated and set(result.evidence_types) == {"OFFICIAL_BOUNDARY","OFFICIAL_DIRECT","OFFICIAL_ADDRESS"}


def test_low_confidence_not_auto_confirmed():
    result = p65.validate_geocode(document(), candidate("NAME_ADDRESS"))
    assert result["geocode_validation_status"] != "CONFIRMED"
