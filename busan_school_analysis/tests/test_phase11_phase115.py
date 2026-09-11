import json

import numpy as np
import pandas as pd

from src.phase11_middle_catchment_demand import (
    build_middle_catchment,
    classify_assignment_edges,
    phase11_input_hashes,
)


def test_phase11_immutable_inputs_match_snapshot():
    snapshot=json.loads(open("data/snapshots/phase11_input_hashes.json",encoding="utf-8").read())
    assert phase11_input_hashes()==snapshot["input_hashes"]


def test_edge_statuses_are_preserved_and_no_probability_is_used():
    source=pd.read_parquet("data/processed/busan_elementary_middle_relation_2026.parquet")
    audit=pd.read_parquet("data/processed/phase11_assignment_edges_audit.parquet")
    assert len(audit)==len(source)==811
    for col in ["relation_status","relation_type","original_relation_status","original_relation_type","assignment_share"]:
        pd.testing.assert_series_equal(audit[col],source[col],check_names=False)
    assert not audit.probability_used.any()
    assert set(audit.phase11_edge_class)=={"CONFIRMED","POSSIBLE","AMBIGUOUS","EXCLUDED"}


def test_excluded_edges_are_never_aggregated():
    audit=pd.read_parquet("data/processed/phase11_assignment_edges_audit.parquet")
    excluded=audit.phase11_edge_class.isin(["AMBIGUOUS","EXCLUDED"])
    assert not audit.loc[excluded,"used_in_confirmed_aggregate"].any()
    assert not audit.loc[excluded,"used_in_broad_aggregate"].any()


def test_middle_aggregation_range_and_integrity():
    middle=pd.read_parquet("data/processed/phase11_middle_catchment_demand.parquet")
    assert middle.middle_school_id.is_unique
    for col in [c for c in middle if c.startswith(("confirmed_E_","broad_E_")) and not c.endswith("count")]:
        assert middle[col].dropna().between(0,100).all()
    assert (middle.total_elementary_count==middle.broad_school_count).all()
    assert (middle.confirmed_school_count<=middle.total_elementary_count).all()


def test_network_degrees_equal_active_unique_edges_and_retains_all_edges():
    graph=pd.read_parquet("data/processed/phase11_school_network.parquet")
    audit=pd.read_parquet("data/processed/phase11_assignment_edges_audit.parquet")
    graph_edges=graph[graph.record_type.eq("EDGE")]
    assert len(graph_edges)==len(audit)
    usable=audit[audit.used_in_broad_aggregate].drop_duplicates(["elementary_school_id","middle_school_id"])
    expected=usable.groupby("middle_school_id").elementary_school_id.nunique()
    nodes=graph[graph.record_type.eq("MIDDLE_NODE")].set_index("middle_school_id")
    for school_id,count in expected.items(): assert nodes.loc[school_id,"degree"]==count


def test_centum_confirmed_override_is_preserved():
    audit=pd.read_parquet("data/processed/phase11_assignment_edges_audit.parquet")
    row=audit[audit.elementary_school_id.eq("S020001905")&audit.override_applied.fillna(False)&audit.guaranteed_assignment.fillna(False)]
    assert len(row)==1
    assert row.iloc[0].phase11_edge_class=="CONFIRMED"
    assert row.iloc[0].used_in_confirmed_aggregate
    middle=pd.read_parquet("data/processed/phase11_middle_catchment_demand.parquet")
    result=middle[middle.middle_school_id.eq(row.iloc[0].middle_school_id)].iloc[0]
    assert result.confirmed_school_count==1
    assert np.isclose(result.confirmed_E_median,89.52671081677705)


def test_phase115_school_ids_and_missing_values_are_explicit():
    e=pd.read_parquet("data/processed/phase115_elementary_migration_features.parquet")
    assert e.elementary_school_id.is_unique
    assert len(e)==302
    assert e.assignment_ambiguity_grade.notna().all()
    assert e.broad_middle_quality_median.isna().sum()>0


def test_annual_features_use_same_year_official_rows():
    annual=pd.read_parquet("data/processed/phase115_annual_migration_features.parquet")
    raw=pd.read_parquet("data/processed/phase9_elementary_student_longitudinal.parquet")
    assert set(annual.data_year)=={2024,2025,2026}
    check=annual[["elementary_school_id","data_year","total_students"]].merge(
        raw[["elementary_school_id","data_year","total_students"]],on=["elementary_school_id","data_year"],suffixes=("_a","_raw"),validate="one_to_one")
    pd.testing.assert_series_equal(check.total_students_a,check.total_students_raw,check_names=False)


def test_confirmed_only_report_uses_documented_power_threshold():
    report=pd.read_csv("reports/phase115_confirmed_only_validation.csv",encoding="utf-8-sig")
    strict=report[report["sample"].eq("STRICT_CONFIRMED_ONLY")]
    assert len(strict)==2
    assert (strict.power_warning==strict.apartment_count.lt(30)).all()


def test_assignment_classifier_is_deterministic():
    rel=pd.read_parquet("data/processed/busan_elementary_middle_relation_2026.parquet")
    a=classify_assignment_edges(rel); b=classify_assignment_edges(rel)
    pd.testing.assert_series_equal(a.phase11_edge_class,b.phase11_edge_class)
