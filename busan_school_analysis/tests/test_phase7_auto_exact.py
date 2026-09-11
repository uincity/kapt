import pandas as pd

from src.phase7_auto_exact import official_exact_candidate_audit
from src.relation_overrides import load_overrides


def test_official_exact_rule_selects_only_32_bukbu_pdf_rows():
    relations=pd.read_parquet("data/processed/busan_elementary_middle_relation_2026.parquet")
    audit=official_exact_candidate_audit(relations)
    selected=audit[audit.auto_exact_pass]
    assert len(audit)==37
    assert len(selected)==32
    assert selected.official_bukbu_pdf.all()
    assert selected.male_female_same_single_school.all()
    assert selected.elementary_school_id.is_unique


def test_applied_exact_overrides_have_full_share_and_unique_school():
    overrides=load_overrides("config/manual_elementary_middle_overrides.csv")
    exact=overrides[overrides.relation_type.eq("EXACT")&overrides.relation_status.eq("ACTIVE")]
    assert len(exact)==33
    assert pd.to_numeric(exact.assignment_share).eq(1.0).all()
    assert exact.elementary_school_id.is_unique


def test_yongso_is_possible_not_exact():
    overrides=load_overrides("config/manual_elementary_middle_overrides.csv")
    yongso=overrides[overrides.elementary_school_id.eq("S020002045")]
    active=yongso[yongso.relation_status.eq("ACTIVE")]
    assert len(active)==2
    assert active.relation_type.eq("ELIGIBLE").all()
    assert set(pd.to_numeric(active.assignment_share))=={0.5}

