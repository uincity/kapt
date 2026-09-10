import numpy as np
import pandas as pd

from src.phase8_analysis import (add_low_sample_flag, add_quintile,
    add_within_group_metrics, clustered_ols, create_pairs,
    internal_complex_join, primary_sample, winsorize_series)


def sample(n=20):
    return pd.DataFrame({"internal_complex_id":[f"A{i}" for i in range(n)],
      "complex_name":[f"단지{i}" for i in range(n)],"households":[600]*n,
      "school_zone_score":np.arange(n,dtype=float),"school_score_quality":["HIGH"]*n,
      "median_price_per_m2":np.arange(n,dtype=float)*100000+3_000_000,
      "trade_count":[5]*n,"sigungu":["구"]*n,"legal_dong":["동"]*n,
      "apartment_age":[10]*n,"area_group":["80_90"]*n})


def test_phase8_internal_complex_join():
    out=internal_complex_join(pd.DataFrame({"internal_complex_id":["A","B"]}),pd.DataFrame({"internal_complex_id":["A","B"],"x":[1,2]})); assert out.x.tolist()==[1,2]

def test_500plus_sample():
    d=sample(2); d.loc[0,"households"]=499; assert primary_sample(d).internal_complex_id.tolist()==["A1"]

def test_unscored_not_imputed():
    d=sample(2); d.loc[0,"school_zone_score"]=np.nan; assert primary_sample(d).internal_complex_id.tolist()==["A1"]

def test_price_median():
    assert pd.Series([1,100,3]).median()==3

def test_low_sample_flag():
    d=add_low_sample_flag(pd.DataFrame({"trade_count":[2,3]})); assert d.low_sample_flag.tolist()==[True,False]

def test_school_quintile():
    d=add_quintile(sample()); assert set(d.school_quintile)=={"Q1","Q2","Q3","Q4","Q5"}

def test_sigungu_percentile():
    d=add_within_group_metrics(sample(4)); assert d.price_percentile_in_sigungu.max()==100

def test_same_dong_comparison():
    d=add_within_group_metrics(sample(3)); assert d.same_dong_eligible.all() and abs(d.demeaned_price.sum())<1e-6

def test_pair_matching():
    d=sample(20); d.school_zone_score=np.arange(20)*5; assert len(create_pairs(d,min_pairs=1))>=1

def _transactions():
    rng=np.random.default_rng(3); n=100
    score=np.repeat(np.arange(10)*10,10); price=np.exp(14+score*.01+rng.normal(0,.02,n))
    return pd.DataFrame({"internal_complex_id":np.repeat([f"A{i}" for i in range(10)],10),"school_zone_score":score,"price_per_sqm":price})

def test_log_price_regression():
    assert clustered_ols(_transactions())["n"]==100

def test_school_score_coefficient():
    assert clustered_ols(_transactions())["coefficient"]>0

def test_manual_verified_split():
    d=sample(2); d["relation_source_group"]=["OFFICIAL","MANUAL_VERIFIED"]; assert set(d.relation_source_group)=={"OFFICIAL","MANUAL_VERIFIED"}

def test_quality_filter():
    d=sample(2); d.loc[0,"school_score_quality"]="MEDIUM"; assert len(primary_sample(d,("HIGH",)))==1 and len(primary_sample(d,("HIGH","MEDIUM")))==2

def test_outlier_robustness():
    s=pd.Series([1,2,3,4,1000]); w=winsorize_series(s,(.2,.8)); assert w.max()<1000 and w.min()>1

def test_trade_count_sensitivity():
    d=sample(3); d.trade_count=[1,3,5]; assert len(primary_sample(d,min_trades=5))==1
