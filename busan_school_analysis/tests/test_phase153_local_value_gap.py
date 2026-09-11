from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.config import ROOT
from src.phase153_local_value_gap import (
    NEUTRAL_EPSILON_PCT,
    audit_priority,
    candidate_class,
    dual_category,
    gap_pct,
    interval_status,
    local_gap_confidence,
    signal_sign,
    temporal_status,
    verify_manifest,
)


MASTER_PATH=ROOT/"data/processed/phase153_local_value_gap.csv"


@pytest.fixture(scope="module")
def data(): return pd.read_csv(MASTER_PATH,encoding="utf-8-sig")


def test_01_phase7_to_phase152_protected_hashes_unchanged():
    m=pd.read_csv(ROOT/"reports/phase153_protected_manifest.csv",encoding="utf-8-sig")
    assert len(m)>=263 and m.unchanged.all()


def test_02_phase152_fair_price_unchanged():
    m=pd.read_csv(ROOT/"reports/phase153_protected_manifest.csv",encoding="utf-8-sig")
    row=m[m.path.eq("data/processed/phase152_local_fair_price.csv")]
    assert len(row)==1 and bool(row.unchanged.iloc[0])


def test_03_phase152_has_no_official_gap():
    d=pd.read_csv(ROOT/"data/processed/phase152_local_fair_price.csv",encoding="utf-8-sig")
    assert "local_value_gap_pct" not in d.columns


@pytest.mark.parametrize("months",[6,12])
def test_04_05_observed_price_median_correct(data,months):
    tx=pd.read_parquet(ROOT/"data/processed/phase135_transaction_sample.parquet")
    end=tx.transaction_date.max(); expected=tx[tx.transaction_date.gt(end-pd.DateOffset(months=months))].groupby("apartment_id").price_per_sqm.median()
    actual=data.set_index("apartment_id")[f"observed_unit_price_{months}m"].dropna(); common=actual.index.intersection(expected.index)
    assert np.allclose(actual.loc[common],expected.loc[common])


def test_06_no_future_transaction_leakage(data):
    tx=pd.read_parquet(ROOT/"data/processed/phase135_transaction_sample.parquet")
    assert tx.transaction_date.max()==pd.Timestamp("2026-08-28")
    assert data.observed_unit_price_12m.notna().sum()<=tx.apartment_id.nunique()


def test_07_local_gap_formula(data):
    d=data.dropna(subset=["local_value_gap_pct"])
    assert np.allclose(d.local_value_gap_pct,(d.local_fair_total_price/d.observed_market_price_12m-1)*100)


def test_08_lower_gap_formula(data):
    d=data.dropna(subset=["fair_price_lower_gap_pct"])
    assert np.allclose(d.fair_price_lower_gap_pct,(d.fair_price_lower/d.observed_market_price_12m-1)*100)


def test_09_upper_gap_formula(data):
    d=data.dropna(subset=["fair_price_upper_gap_pct"])
    assert np.allclose(d.fair_price_upper_gap_pct,(d.fair_price_upper/d.observed_market_price_12m-1)*100)


def test_10_12m_is_official_gap(data):
    assert np.allclose(data.local_value_gap_pct.dropna(),data.local_value_gap_12m_pct.dropna())


@pytest.mark.parametrize("a,b,expected",[(1,2,"STABLE_POSITIVE"),(-1,-2,"STABLE_NEGATIVE"),(1,-1,"MIXED"),(np.nan,1,"INSUFFICIENT")])
def test_11_temporal_classification(a,b,expected): assert temporal_status(a,b)==expected


@pytest.mark.parametrize("value,expected",[(2.99,"NEUTRAL"),(3.01,"POSITIVE"),(-3.01,"NEGATIVE"),(np.nan,"MISSING")])
def test_12_neutral_band(value,expected): assert signal_sign(value)==expected


def test_13_interval_strong_undervalued(): assert interval_status(20,1,40)=="STRONG_UNDERVALUED_SIGNAL"
def test_14_interval_potential_undervalued(): assert interval_status(10,-20,30)=="POTENTIAL_UNDERVALUED_SIGNAL"
def test_15_interval_within_range(): assert interval_status(2,-20,30)=="WITHIN_MODEL_RANGE"
def test_16_interval_potential_overvalued(): assert interval_status(-10,-30,20)=="POTENTIAL_OVERVALUED_SIGNAL"
def test_17_interval_strong_overvalued(): assert interval_status(-20,-40,-1)=="STRONG_OVERVALUED_SIGNAL"


def _confidence_row(**changes):
    base=dict(model_confidence="HIGH",local_value_gap_pct=5,transaction_count_12m=10,prediction_interval_width_pct=50,
              local_gap_temporal_stability="STABLE_POSITIVE",fallback_level=0,comparable_apartment_count=8)
    base.update(changes); return SimpleNamespace(**base)


def test_18_local_gap_confidence_deterministic():
    r=_confidence_row(); assert local_gap_confidence(r,75,100)==local_gap_confidence(r,75,100)=="HIGH"


def test_19_interval_width_downgrades_confidence():
    assert local_gap_confidence(_confidence_row(prediction_interval_width_pct=101),75,100)=="LOW"


def test_20_low_model_confidence_excluded_from_ranking(data):
    candidates=pd.read_csv(ROOT/"reports/phase153_dual_signal_candidates.csv",encoding="utf-8-sig")
    assert candidates.model_confidence.isin(["HIGH","MEDIUM"]).all()


def test_21_school_value_gap_unchanged(data):
    source=pd.read_csv(ROOT/"data/processed/phase149_school_value_master.csv",encoding="utf-8-sig").set_index("apartment_id")
    actual=data.set_index("apartment_id").school_value_gap_pct
    assert np.allclose(actual.dropna(),source.loc[actual.dropna().index,"school_value_gap_pct"])


@pytest.mark.parametrize("school,local,expected",[("POSITIVE","POSITIVE","DOUBLE_POSITIVE"),("NEGATIVE","POSITIVE","LOCAL_ONLY_POSITIVE"),("POSITIVE","NEUTRAL","SCHOOL_ONLY_POSITIVE"),("NEGATIVE","NEGATIVE","DOUBLE_NEGATIVE"),("NEUTRAL","NEUTRAL","MIXED_OR_NEUTRAL")])
def test_22_dual_signal_category(school,local,expected): assert dual_category(school,local)==expected


def test_23_strong_dual_positive_rule(data):
    expected=(data.local_value_gap_pct>0)&data.local_gap_temporal_stability.eq("STABLE_POSITIVE")&data.local_gap_confidence.isin(["HIGH","MEDIUM"])&(data.school_value_gap_pct>0)&data.gap_confidence.isin(["HIGH","MEDIUM"])&data.gap_positive_probability.ge(.75)&data.model_confidence.isin(["HIGH","MEDIUM"])
    assert np.array_equal(data.strong_dual_positive,expected)


def test_24_candidate_class_a_requirements(data):
    a=data[data.combined_candidate_class.eq("ROBUST_DUAL_POSITIVE")]
    assert len(a) and a.strong_dual_positive.all() and (~a.extreme_gap_flag).all() and (~a.dong_bias_flag).all()


def test_25_no_weighted_composite_score(data):
    assert not any("composite" in c.lower() or "weighted_score" in c.lower() for c in data.columns)


def test_26_class_a_ranking_deterministic():
    c=pd.read_csv(ROOT/"reports/phase153_dual_signal_candidates.csv",encoding="utf-8-sig")
    a=c[c.combined_candidate_class.eq("ROBUST_DUAL_POSITIVE")]
    assert np.array_equal(a.class_a_rank,np.arange(1,len(a)+1))


def test_27_extreme_gap_flag_threshold(data):
    official=data[data.model_confidence.isin(["HIGH","MEDIUM"])&data.local_value_gap_pct.notna()]
    threshold=official.local_value_gap_pct.abs().quantile(.9)
    assert data.loc[data.extreme_gap_flag,"local_value_gap_pct"].abs().ge(threshold-1e-10).all()


def test_28_dong_bias_flag_consistent(data):
    assert data.groupby(["gu","legal_dong"]).dong_bias_flag.nunique().le(1).all()


def test_29_phase154_priority_rule(data):
    assert set(data.phase154_audit_priority)<={"HIGH","MEDIUM","LOW"}
    assert data.loc[data.phase154_audit_priority.eq("HIGH"),"extreme_gap_flag"].all()


def test_30_output_apartment_uniqueness(data): assert len(data)==data.apartment_id.nunique()==560


def test_31_missing_price_remains_missing(data):
    assert data.loc[~data.has_12m_market_price,"local_value_gap_pct"].isna().all()


def test_32_finite_critical_output(data):
    d=data.dropna(subset=["local_value_gap_pct"])
    assert np.isfinite(d[["local_value_gap_pct","fair_price_lower_gap_pct","fair_price_upper_gap_pct"]]).all().all()


def test_33_no_arbitrary_gap_imputation(data):
    missing=data.local_fair_total_price.isna()|data.observed_market_price_12m.isna()
    assert data.loc[missing,["local_value_gap_6m_pct","local_value_gap_12m_pct","local_value_gap_pct"]].isna().all().all()


def test_34_protected_overwrite_prevention():
    with pytest.raises(RuntimeError,match="PROTECTED_ARTIFACT_MODIFIED"):
        verify_manifest(pd.DataFrame([{"path":"main.py","sha256_before":"bad"}]),ROOT)


def test_35_total_price_units_are_consistent(data):
    d=data.dropna(subset=["fair_price_lower"])
    assert np.allclose(d.fair_price_lower,d.fair_price_lower_per_m2*d.representative_area_m2)
    assert np.allclose(d.observed_market_price_12m,d.observed_unit_price_12m*d.representative_area_m2)


def test_36_neutral_epsilon_is_fixed(): assert NEUTRAL_EPSILON_PCT==3.0


def test_37_interval_ordering(data):
    d=data.dropna(subset=["local_fair_total_price"])
    assert (d.fair_price_lower<=d.local_fair_total_price).all() and (d.local_fair_total_price<=d.fair_price_upper).all()


def test_38_result_verdict_valid():
    r=json.loads((ROOT/"data/processed/phase153_result.json").read_text(encoding="utf-8"))
    assert r["verdict"] in {"LOCAL_VALUE_GAP_USABLE","LOCAL_VALUE_GAP_USABLE_WITH_CAUTION","LOCAL_VALUE_GAP_NOT_STABLE"}
    assert r["dual_signal_verdict"] in {"DUAL_SIGNAL_COMPLEMENTARY","DUAL_SIGNAL_REDUNDANT","DUAL_SIGNAL_CONFLICTING"}

