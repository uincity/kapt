from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config import ROOT
from src.phase152_local_comparable import (
    CATEGORICAL_FEATURES,
    FORBIDDEN_MODEL_FEATURES,
    MATCHING_FEATURES,
    MIN_APARTMENTS,
    MIN_RECENT_TRANSACTIONS,
    NUMERIC_FEATURES,
    SCHOOL_FEATURE,
    build_fallback_map,
    discover_protected,
    make_pipeline,
    recent_market_counts,
    temporal_split,
    verify_manifest,
)


FAIR_PATH = ROOT / "data/processed/phase152_local_fair_price.csv"
COMPARE_PATH = ROOT / "reports/phase152_model_comparison.csv"
DETAIL_PATH = ROOT / "reports/phase152_comparable_details.csv"
FALLBACK_PATH = ROOT / "reports/phase152_low_sample_fallback_audit.csv"


@pytest.fixture(scope="module")
def fair():
    return pd.read_csv(FAIR_PATH, encoding="utf-8-sig")


@pytest.fixture(scope="module")
def compare():
    return pd.read_csv(COMPARE_PATH, encoding="utf-8-sig")


@pytest.fixture(scope="module")
def details():
    return pd.read_csv(DETAIL_PATH, encoding="utf-8-sig")


def test_01_phase7_to_phase151_hashes_unchanged():
    manifest=pd.read_csv(ROOT/"reports/phase152_protected_manifest.csv",encoding="utf-8-sig")
    assert len(manifest)>=233 and manifest.unchanged.all()


def test_02_phase149_master_unchanged():
    m=pd.read_csv(ROOT/"reports/phase152_protected_manifest.csv",encoding="utf-8-sig")
    row=m[m.path.eq("data/processed/phase149_school_value_master.csv")]
    assert len(row)==1 and bool(row.unchanged.iloc[0])


def test_03_phase151_mapping_unchanged():
    m=pd.read_csv(ROOT/"reports/phase152_protected_manifest.csv",encoding="utf-8-sig")
    row=m[m.path.eq("data/processed/phase151_local_market_mapping.csv")]
    assert len(row)==1 and bool(row.unchanged.iloc[0])


def test_04_legal_dong_is_default_market(fair):
    assert (fair.primary_market==fair.gu.astype(str)+"|"+fair.legal_dong.astype(str)).all()


def test_05_no_algorithm_cluster_as_primary(fair):
    assert ~fair.primary_market.str.contains("ALG|KMEANS",case=False,regex=True).any()


def test_06_fallback_only_if_minimum_fails(fair):
    assert fair.loc[~fair.low_sample_flag,"fallback_level"].eq(0).all()
    assert fair.loc[fair.fallback_level.gt(0),"low_sample_flag"].all()


def test_07_fallback_hierarchy_deterministic():
    tx=pd.read_parquet(ROOT/"data/processed/phase135_transaction_sample.parquet")
    features=pd.read_csv(ROOT/"data/processed/phase151_apartment_market_features.csv",encoding="utf-8-sig")
    a=build_fallback_map(tx,features); b=build_fallback_map(tx,features)
    assert a[["market_key","fallback_level","fallback_market_name"]].equals(b[["market_key","fallback_level","fallback_market_name"]])


def test_08_no_target_current_price_in_matching():
    assert "target_current_price" not in MATCHING_FEATURES
    assert not {"recent_6m_price_per_m2","recent_12m_price_per_m2"}&set(MATCHING_FEATURES)


def test_09_no_school_value_gap_in_model():
    used=set(NUMERIC_FEATURES)|set(CATEGORICAL_FEATURES)|{SCHOOL_FEATURE}
    assert "school_value_gap_pct" not in used and not set(FORBIDDEN_MODEL_FEATURES)&used


def test_10_no_future_transactions_in_training():
    tx=pd.read_parquet(ROOT/"data/processed/phase135_transaction_sample.parquet").sort_values("transaction_date")
    train,test,_=temporal_split(tx)
    assert tx.loc[train,"transaction_date"].max()<tx.loc[test,"transaction_date"].min()


def test_11_temporal_split_is_exhaustive():
    tx=pd.read_parquet(ROOT/"data/processed/phase135_transaction_sample.parquet").sort_values("transaction_date")
    train,test,_=temporal_split(tx)
    assert not (train&test).any() and (train|test).all()


def test_12_comparable_excludes_target(details):
    assert details.target_apartment_id.ne(details.comparable_apartment_id).all()


def test_13_comparable_count_correct(details):
    assert details.groupby("target_apartment_id").comparable_rank.max().le(5).all()
    assert details.groupby("target_apartment_id").comparable_apartment_id.nunique().equals(details.groupby("target_apartment_id").size())


def test_14_same_legal_dong_priority(details):
    level0=details[details.fallback_level.eq(0)]
    assert len(level0) and level0.same_legal_dong.all()


def test_15_low_sample_fallback_correct():
    audit=pd.read_csv(FALLBACK_PATH,encoding="utf-8-sig")
    assert (~audit.original_sufficient).all() and audit.fallback_level.ge(1).all()


def test_16_selected_fallback_pool_nonempty():
    audit=pd.read_csv(FALLBACK_PATH,encoding="utf-8-sig")
    assert audit.fallback_pool_apartments.gt(0).all() and audit.fallback_pool_transactions.gt(0).all()


@pytest.mark.parametrize("model",["G","D","L","F"])
def test_17_20_model_output_present_and_finite(compare,model):
    rows=compare[compare.model.eq(model)]
    assert set(rows.school_variant)=={"NO_SCHOOL","SCHOOL"}
    assert np.isfinite(rows[["rmse","mae","r2"]]).all().all()


def test_21_no_school_and_school_common_sample(compare):
    sizes=compare.groupby("school_variant")[["test_transactions","test_apartments"]].first()
    assert sizes.nunique().eq(1).all()


def test_22_prediction_output_finite(fair):
    assert np.isfinite(fair.local_fair_price_per_m2.dropna()).all()


def test_23_fair_price_positive(fair):
    assert fair.local_fair_price_per_m2.dropna().gt(0).all()


def test_24_interval_contains_fair_price(fair):
    d=fair.dropna(subset=["local_fair_price_per_m2"])
    assert (d.fair_price_lower<=d.local_fair_price_per_m2).all()
    assert (d.local_fair_price_per_m2<=d.fair_price_upper).all()


def test_25_representative_area_correct(fair):
    source=pd.read_csv(ROOT/"data/processed/phase151_apartment_market_features.csv",encoding="utf-8-sig").set_index("apartment_id")
    actual=fair.set_index("apartment_id").representative_area_m2
    assert np.allclose(actual.dropna(),source.loc[actual.dropna().index,"representative_area_m2"])


def test_26_fair_total_price_identity(fair):
    d=fair.dropna(subset=["local_fair_total_price"])
    assert np.allclose(d.local_fair_total_price,d.local_fair_price_per_m2*d.representative_area_m2)


def test_27_model_confidence_rule(fair):
    assert set(fair.model_confidence)=={"HIGH","MEDIUM","LOW"}
    assert fair.loc[fair.local_fair_price_per_m2.isna(),"model_confidence"].eq("LOW").all()


def test_28_fallback_confidence_downgrade(fair):
    assert ~fair.loc[fair.fallback_level.ge(3),"model_confidence"].eq("HIGH").any()


def test_29_top_comparable_unique(details):
    assert ~details.duplicated(["target_apartment_id","comparable_apartment_id"]).any()


def test_30_similarity_distance_ordering(details):
    ordered=details.sort_values(["target_apartment_id","comparable_rank"])
    assert ordered.groupby("target_apartment_id").similarity_distance.apply(lambda x:x.is_monotonic_increasing).all()


def test_31_transaction_count_consistency(fair):
    features=pd.read_csv(ROOT/"data/processed/phase151_apartment_market_features.csv",encoding="utf-8-sig").set_index("apartment_id")
    a=fair.set_index("apartment_id")
    assert np.allclose(a.transaction_count_12m,features.transaction_count_12m.fillna(0))


def test_32_apartment_output_unique(fair):
    assert len(fair)==fair.apartment_id.nunique()==560


def test_33_residual_identity():
    r=pd.read_parquet(ROOT/"data/processed/phase152_transaction_residuals.parquet")
    assert np.allclose(r.local_price_residual,r.log_price-r.predicted_log_price)


def test_34_no_official_local_value_gap(fair):
    assert "local_value_gap_pct" not in fair.columns
    result=json.loads((ROOT/"data/processed/phase152_result.json").read_text(encoding="utf-8"))
    assert result["official_local_value_gap_created"] is False


def test_35_protected_overwrite_prevention():
    bad=pd.DataFrame([{"path":"main.py","sha256_before":"bad"}])
    with pytest.raises(RuntimeError,match="PROTECTED_ARTIFACT_MODIFIED"):
        verify_manifest(bad,ROOT)


def test_36_primary_mapping_type_is_legal_dong(fair):
    mapping=pd.read_csv(ROOT/"data/processed/phase151_local_market_mapping.csv",encoding="utf-8-sig")
    assert set(mapping.market_definition_type.dropna())=={"LEGAL_DONG"}


def test_37_fallback_levels_valid(fair):
    assert fair.fallback_level.between(0,4).all()


def test_38_recent_count_threshold_constants():
    assert MIN_APARTMENTS==5 and MIN_RECENT_TRANSACTIONS==100


def test_39_school_core_frozen_values(fair):
    master=pd.read_csv(ROOT/"data/processed/phase149_school_value_master.csv",encoding="utf-8-sig").set_index("apartment_id")
    actual=fair.set_index("apartment_id").school_premium_core_score
    assert np.allclose(actual.dropna(),master.loc[actual.dropna().index,"school_premium_core_score"])


def test_40_all_models_share_temporal_test(compare):
    assert compare.test_transactions.nunique()==1 and compare.test_apartments.nunique()==1

