import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import ROOT
from src.phase10_incremental_price_validation import _fit_ml


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_frozen_phase7_phase8_phase9_inputs_unchanged():
    frozen=json.loads((ROOT/"data/snapshots/phase95_input_hashes.json").read_text(encoding="utf-8"))["input_hashes"]
    assert all(sha(ROOT/path)==digest for path,digest in frozen.items())
    baseline=json.loads((ROOT/"data/snapshots/phase8_baseline_benchmark.json").read_text(encoding="utf-8"))
    assert baseline["primary_sample"]==487 and baseline["within_legal_dong_demeaned_spearman"]==.005


def test_school_join_integrity_and_ranges():
    d=pd.read_parquet(ROOT/"data/processed/phase95_elementary_middle_combined.parquet")
    assert len(d)==319 and d.school_id.notna().all() and not d.school_id.duplicated().any()
    assert d.elementary_demand_score.dropna().between(0,100).all()
    assert d.phase7_school_score.dropna().between(0,100).all()
    assert d.EM_interaction.dropna().between(0,1).all()
    assert (d.combined_data_status.eq("BOTH")== (d.elementary_demand_score.notna()&d.phase7_school_score.notna())).all()


def test_missing_api_schools_are_not_imputed():
    d=pd.read_parquet(ROOT/"data/processed/phase95_elementary_middle_combined.parquet").set_index("school_id")
    for school_id in ["S020001238","S020001463","S020001474"]:
        assert d.loc[school_id,"phase9_data_status"]=="ELEMENTARY_DEMAND_MISSING_API"
        assert pd.isna(d.loc[school_id,"elementary_demand_score"])


def test_common_sample_integrity_and_same_sample_comparison():
    d=pd.read_parquet(ROOT/"data/processed/phase10_common_sample.parquet")
    assert not d.internal_complex_id.duplicated().any()
    assert d.households.ge(500).all() and d.school_score_quality.eq("HIGH").all()
    assert d.phase9_coverage_status.eq("COMPLETE").all()
    assert d.elementary_demand_score.notna().all() and d.phase7_school_score.notna().all()
    ml=pd.read_csv(ROOT/"reports/phase10_ml_group_split_detail.csv")
    for _,g in ml.groupby("split_id"):
        assert g.train_rows.nunique()==1 and g.test_rows.nunique()==1
        assert g.train_apartments.nunique()==1 and g.test_apartments.nunique()==1


def test_time_aligned_analysis_has_no_future_school_data():
    d=pd.read_parquet(ROOT/"data/processed/phase10_time_aligned_sample.parquet")
    assert d.elementary_data_year.notna().all()
    assert (d.elementary_data_year<=d.transaction_year).all()
    assert set(d.elementary_data_year.astype(int).unique())=={2024,2025,2026}


def test_threshold_sensitivity_is_fixed_and_complete():
    d=pd.read_csv(ROOT/"reports/phase95_threshold_sensitivity.csv")
    assert d.high_threshold_top_pct.tolist()==[10,20,25,30]
    count_cols=["HIGH_E_HIGH_M","HIGH_E_LOW_M","LOW_E_HIGH_M","LOW_E_LOW_M","UNCLASSIFIED_MISSING"]
    assert d[count_cols].sum(axis=1).eq(319).all()


def test_ml_group_split_is_deterministic_on_small_frame():
    rows=[]
    for i in range(30):
        for j in range(2):
            e=20+i*2; m=30+i
            rows.append({"internal_complex_id":f"A{i:03}","price_per_sqm":2_000_000+i*100_000+j*10_000,"legal_dong":f"동{i%5}","apartment_age":5+i%20,"log_households":np.log(500+i*10),"floor":5+j,"area_group":"80_90" if j else "55_65","parking_per_household":1+i%3/10,"elementary_demand_score":e,"phase7_school_score":m,"EM_interaction":e/100*m/100})
    frame=pd.DataFrame(rows)
    a=_fit_ml(frame)[0]; b=_fit_ml(frame)[0]
    pd.testing.assert_frame_equal(a,b)
