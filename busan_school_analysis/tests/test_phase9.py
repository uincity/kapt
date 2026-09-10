import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.phase9_elementary_demand import (_validate_payload, cluster_demand_types,
    engineer_demand_features, score_elementary_demand)


def longitudinal(n=30):
    rows=[]
    for i in range(n):
      for year in (2024,2025,2026):
        base=80+i*3+(year-2024)*(i%5-1)
        row={"elementary_school_id":f"S{i:03}","elementary_school_name":f"학교{i}","data_year":year,
             "total_students":base*6,"total_classes":24,"students_per_class":base/4,
             "transfer_in":20+i%7,"transfer_out":15+i%4,"transfer_report_students":base*6,
             "sigungu_requested":"해운대구"}
        for grade in range(1,7):
          row[f"grade{grade}_students"]=base+grade+(3 if grade>=5 and i%3==0 else 0)
          row[f"grade{grade}_classes"]=4; row[f"grade{grade}_transfer_in"]=3; row[f"grade{grade}_transfer_out"]=2
        rows.append(row)
    return pd.DataFrame(rows)


def config():
    return {"winsor_limits":[.01,.99],"score_weights":{"size":.2,"mobility":.25,"growth":.25,"upper_cohort":.3},"cluster_k":[3,4],"minimum_cluster_size":2}


def test_phase9_official_schema_and_scope_validation():
    row={"SCHUL_CODE":"S1","SCHUL_NM":"학교","SCHUL_KND_SC_CODE":"02","ADRCD_CD":"26350101","ADRCD_NM":"해운대구","JU_ORG_CODE":"J","JU_ORG_NM":"지원청","PBAN_EXCP_YN":"N","BNHH_YN":"N"}
    row.update({f"COL_S{i}":10 for i in range(1,7)})
    row.update({"COL_S7": 0, "COL_S8": 0})
    row.update({f"COL_C{i}":1 for i in range(1,7)})
    row.update({"COL_C7": 0, "COL_C8": 0})
    row.update({"COL_S_SUM":60,"COL_C_SUM":6,"COL_SUM":10})
    assert len(_validate_payload(json.dumps({"resultCode":"success","list":[row]}).encode(),"09","26350"))==1


def test_phase9_rejects_non_busan_or_wrong_school_level():
    with pytest.raises(ValueError):
      _validate_payload(json.dumps({"resultCode":"success","list":[{"SCHUL_CODE":"S1","SCHUL_KND_SC_CODE":"03","ADRCD_CD":"11"}]}).encode(),"09","26350")


def test_adjusted_upper_grade_index_uses_busan_structure():
    f=engineer_demand_features(longitudinal())
    assert f.adjusted_upper_grade_index.notna().all()
    weighted=(f.upper_lower_ratio*(f.grade1_students+f.grade2_students)).sum()/(f.grade1_students+f.grade2_students).sum()
    assert weighted>0


def test_same_cohort_growth_is_tracked_across_years():
    f=engineer_demand_features(longitudinal())
    assert f.cohort_growth.notna().all() and f.adjusted_cohort_growth.notna().all()


def test_elementary_demand_score_is_zero_to_one_hundred():
    s=score_elementary_demand(engineer_demand_features(longitudinal()),config())
    assert s.elementary_demand_score.between(0,100).all() and s.elementary_demand_rank.notna().all()


def test_elementary_score_requires_no_phase7_or_price_columns():
    f=engineer_demand_features(longitudinal())
    assert "school_zone_score" not in f and "price_per_m2" not in f
    assert score_elementary_demand(f,config()).elementary_demand_score.notna().all()


def test_small_school_rate_reliability_is_lower():
    d=longitudinal(2); d.loc[d.elementary_school_id.eq("S000"),"total_students"]=60
    f=engineer_demand_features(d)
    assert f.set_index("elementary_school_id").demand_reliability["S000"] < f.set_index("elementary_school_id").demand_reliability["S001"]


def test_clusters_are_exploratory_and_profiles_cover_schools():
    s=score_elementary_demand(engineer_demand_features(longitudinal(60)),config())
    out,comparison,profiles,model,k=cluster_demand_types(s,config())
    assert out.demand_cluster_id.notna().all() and profiles.school_count.sum()==len(out)
    assert set(comparison.model)=={"KMEANS","GMM"} and model in {"KMEANS","GMM"}
