import pandas as pd

from src.relation_overrides import apply_relation_overrides, save_school_overrides


def _relations():
    return pd.DataFrame([
        {"elementary_school_id":"E1","elementary_school_name":"센텀초","middle_school_id":"M1","middle_school_name":"센텀중","relation_type":"ELIGIBLE","relation_status":"ACTIVE"},
        {"elementary_school_id":"E1","elementary_school_name":"센텀초","middle_school_id":"M2","middle_school_name":"재송중","relation_type":"ELIGIBLE","relation_status":"ACTIVE"},
    ])


def test_relation_override_preserves_original_and_applies_effective_values(tmp_path):
    path=tmp_path/"overrides.csv"
    rows=pd.DataFrame([{"override_enabled":True,"elementary_school_id":"E1","elementary_school_name":"센텀초","middle_school_id":"M1","middle_school_name":"센텀중","relation_type":"EXACT","relation_status":"ACTIVE","assignment_share":"1","override_reason":"실제 배정 확인","override_source":"검증 문서"}])
    save_school_overrides(path,rows,"E1")
    out=apply_relation_overrides(_relations(),path)
    changed=out[out.middle_school_id.eq("M1")].iloc[0]
    assert changed.original_relation_type=="ELIGIBLE" and changed.relation_type=="EXACT"
    assert changed.override_applied and changed.assignment_share==1


def test_relation_override_can_exclude_candidate_without_deleting_evidence(tmp_path):
    path=tmp_path/"overrides.csv"
    rows=pd.DataFrame([{"override_enabled":True,"elementary_school_id":"E1","elementary_school_name":"센텀초","middle_school_id":"M2","middle_school_name":"재송중","relation_type":"ELIGIBLE","relation_status":"EXCLUDED_NOT_APPLICABLE","assignment_share":"0","override_reason":"비배정 확인","override_source":"검증 문서"}])
    save_school_overrides(path,rows,"E1")
    out=apply_relation_overrides(_relations(),path)
    assert len(out)==2
    assert out.loc[out.middle_school_id.eq("M2"),"relation_status"].iloc[0]=="EXCLUDED_NOT_APPLICABLE"
