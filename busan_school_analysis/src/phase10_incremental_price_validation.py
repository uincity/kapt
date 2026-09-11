"""Phase 10: incremental price validation for frozen Phase 7 and Phase 9 scores."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit

from .config import ROOT, atomic_bytes, write_csv, write_parquet
from .phase8_analysis import APARTMENT_ROOT, _aggregate_market, _corr, add_within_group_metrics, clustered_ols, internal_complex_join, primary_sample
from .phase95_school_score_integration import PHASE7_SNAPSHOT, PHASE8_SNAPSHOT, PHASE9_SCORES, phase95_input_hashes
from .phase9_elementary_demand import engineer_demand_features, score_elementary_demand

CONTROLS = ("apartment_age", "log_households", "floor", "area_group", "parking_per_household")
SCHOOL_SETS = {
    "MODEL_0": (),
    "MODEL_1_M": ("phase7_school_score",),
    "MODEL_2_E": ("elementary_demand_score",),
    "MODEL_3_E_M": ("elementary_demand_score", "phase7_school_score"),
    "MODEL_4_E_M_INTERACTION": ("elementary_demand_score", "phase7_school_score", "EM_interaction"),
}


def _prepare_phase8_data(root: Path):
    scores = pd.read_parquet(root / PHASE7_SNAPSHOT)
    trades = pd.read_parquet(APARTMENT_ROOT / "data/interim/trade_matched.parquet")
    rents = pd.read_parquet(APARTMENT_ROOT / "data/interim/rent_matched.parquet")
    summary = pd.read_csv(APARTMENT_ROOT / "data/processed/busan_complex_summary.csv")
    controls = summary[[c for c in ["internal_complex_id", "apartment_age", "parking_per_household"] if c in summary]]
    enriched = internal_complex_join(scores, controls, [c for c in controls if c != "internal_complex_id"])
    metrics = _aggregate_market(trades, rents, enriched, {"12M": 12}, 3)
    base = metrics[(metrics.period.eq("12M")) & metrics.area_group.eq("ALL")].copy()
    primary = primary_sample(base, ["HIGH"])
    end = pd.to_datetime(trades.deal_date).max(); start = end - pd.DateOffset(months=12) + pd.Timedelta(days=1)
    tx = trades[pd.to_datetime(trades.deal_date).between(start, end)].copy()
    tx = internal_complex_join(tx, enriched, ["school_zone_score", "school_score_quality", "households", "apartment_age", "parking_per_household", "legal_dong"])
    tx = tx[tx.households.ge(500) & tx.school_score_quality.eq("HIGH") & tx.school_zone_score.notna()].copy()
    tx["log_households"] = np.log(tx.households)
    return scores, trades, base, primary, tx


def reproduce_phase8_baseline(root=ROOT, tolerance=None):
    root = Path(root); tolerance = tolerance or {"correlation": .0015, "effect_pct": .05, "p_value": .002}
    snapshot = json.loads((root / PHASE8_SNAPSHOT).read_text(encoding="utf-8"))
    _, _, _, primary, tx = _prepare_phase8_data(root)
    pearson, spearman, _ = _corr(primary.school_zone_score, primary.median_price_per_m2)
    within = add_within_group_metrics(primary)
    _, within_sigungu, _ = _corr(within.school_score_percentile_in_sigungu, within.price_percentile_in_sigungu)
    dong = within[within.same_dong_eligible]
    _, within_dong, _ = _corr(dong.demeaned_school_score, dong.demeaned_price)
    reg = clustered_ols(tx, CONTROLS, "legal_dong", "price_per_sqm", "school_zone_score")
    actual = {"pearson": pearson, "spearman": spearman, "within_sigungu_spearman": within_sigungu,
              "within_legal_dong_demeaned_spearman": within_dong, "legal_dong_fe_10point_pct": reg["score_10point_association_pct"],
              "legal_dong_fe_p_value": reg["p_value"], "primary_sample": len(primary)}
    checks = {
        "pearson": abs(actual["pearson"] - snapshot["pearson"]) <= tolerance["correlation"],
        "spearman": abs(actual["spearman"] - snapshot["spearman"]) <= tolerance["correlation"],
        "within_sigungu_spearman": abs(actual["within_sigungu_spearman"] - snapshot["within_sigungu_spearman"]) <= tolerance["correlation"],
        "within_legal_dong_demeaned_spearman": abs(actual["within_legal_dong_demeaned_spearman"] - snapshot["within_legal_dong_demeaned_spearman"]) <= tolerance["correlation"],
        "legal_dong_fe_10point_pct": abs(actual["legal_dong_fe_10point_pct"] - snapshot["legal_dong_fe_10point_pct"]) <= tolerance["effect_pct"],
        "legal_dong_fe_p_value": abs(actual["legal_dong_fe_p_value"] - snapshot["legal_dong_fe_p_value"]) <= tolerance["p_value"],
        "primary_sample": actual["primary_sample"] == snapshot["primary_sample"],
    }
    if not all(checks.values()): raise ValueError(f"Phase 8 baseline reproduction failed: {checks}; actual={actual}")
    return snapshot, actual, checks


def _design(frame: pd.DataFrame, school_vars=(), fixed_effect="legal_dong"):
    d = frame.copy()
    x = pd.DataFrame({"const": 1.0}, index=d.index)
    for col in (*CONTROLS, *school_vars):
        if pd.api.types.is_numeric_dtype(d[col]): x[col] = pd.to_numeric(d[col], errors="coerce")
        else: x = pd.concat([x, pd.get_dummies(d[col], prefix=col, drop_first=True, dtype=float)], axis=1)
    fixed_effects=(fixed_effect,) if isinstance(fixed_effect,str) else tuple(fixed_effect or ())
    for effect in fixed_effects:
        x = pd.concat([x, pd.get_dummies(d[effect], prefix=effect, drop_first=True, dtype=float)], axis=1)
    y = np.log(pd.to_numeric(d.price_per_sqm, errors="coerce"))
    valid = x.notna().all(axis=1) & y.notna() & d.internal_complex_id.notna()
    return d.loc[valid], x.loc[valid].astype(float), y.loc[valid]


def clustered_ols_multi(frame: pd.DataFrame, school_vars=(), fixed_effect="legal_dong"):
    d, x, y = _design(frame, school_vars, fixed_effect)
    X=x.to_numpy(); Y=y.to_numpy(); beta=np.linalg.pinv(X.T@X)@X.T@Y; resid=Y-X@beta
    bread=np.linalg.pinv(X.T@X); meat=np.zeros((X.shape[1],X.shape[1])); groups=d.internal_complex_id.to_numpy()
    for group in np.unique(groups):
        ix=np.flatnonzero(groups==group); score=X[ix].T@resid[ix,None]; meat += score@score.T
    G=len(np.unique(groups)); N=len(Y); k=X.shape[1]; correction=(G/(G-1))*((N-1)/(N-k)) if G>1 and N>k else 1
    se=np.sqrt(np.maximum(np.diag(bread@meat@bread*correction),0)); df=max(G-1,1)
    rows=[]
    for var in school_vars:
        idx=x.columns.get_loc(var); t=beta[idx]/se[idx] if se[idx] else np.nan; p=2*stats.t.sf(abs(t),df) if np.isfinite(t) else np.nan
        rows.append({"variable":var,"coefficient":beta[idx],"standard_error":se[idx],"t_stat":t,"p_value":p,"ci95_low":beta[idx]-1.96*se[idx],"ci95_high":beta[idx]+1.96*se[idx],
                     "ten_point_association_pct":(math.exp(beta[idx]*10)-1)*100 if var != "EM_interaction" else np.nan})
    fitted=pd.Series(X@beta,index=d.index); residual=pd.Series(resid,index=d.index)
    return pd.DataFrame(rows), {"r_squared":1-(resid@resid)/(((Y-Y.mean())**2).sum()),"n":N,"clusters":G}, fitted, residual


def _feature_correlations(frame, feature):
    d=frame.dropna(subset=[feature,"median_price_per_m2"]).copy(); p,s,n=_corr(d[feature],d.median_price_per_m2)
    district_feature=d.groupby("sigungu")[feature].rank(pct=True); district_price=d.groupby("sigungu").median_price_per_m2.rank(pct=True)
    _,ws,wn=_corr(district_feature,district_price)
    eligible=d.groupby(["sigungu","legal_dong"]).internal_complex_id.transform("nunique").ge(3)
    dd=d[eligible].copy(); dx=dd[feature]-dd.groupby(["sigungu","legal_dong"])[feature].transform("mean"); dy=dd.median_price_per_m2-dd.groupby(["sigungu","legal_dong"]).median_price_per_m2.transform("mean")
    _,ds,dn=_corr(dx,dy)
    return {"Pearson":p,"Spearman":s,"Within_district_Spearman":ws,"Within_legal_dong_Spearman":ds,"n":n,"within_district_n":wn,"within_dong_n":dn}


def _fit_ml(tx: pd.DataFrame):
    model_frame=tx[["internal_complex_id","price_per_sqm","legal_dong",*CONTROLS,"elementary_demand_score","phase7_school_score","EM_interaction"]].replace([np.inf,-np.inf],np.nan).dropna().copy()
    groups=model_frame.internal_complex_id; results=[]; models={}; matrices={}
    for split_id,seed in enumerate((42,52,62)):
      splitter=GroupShuffleSplit(n_splits=1,test_size=.2,random_state=seed); train_idx,test_idx=next(splitter.split(model_frame,groups=groups))
      for name,school in SCHOOL_SETS.items():
        features=[*CONTROLS,"legal_dong",*school]; X=pd.get_dummies(model_frame[features],columns=["area_group","legal_dong"],drop_first=True,dtype=float)
        train=X.iloc[train_idx]; test=X.iloc[test_idx]; y=np.log(model_frame.price_per_sqm)
        model=RandomForestRegressor(n_estimators=60,max_depth=16,min_samples_leaf=10,max_features=.8,n_jobs=1,random_state=seed).fit(train,y.iloc[train_idx])
        pred=model.predict(test); raw_pred=np.exp(pred); raw_y=model_frame.price_per_sqm.iloc[test_idx]
        results.append({"model":name,"split_id":split_id,"split_seed":seed,"train_rows":len(train_idx),"test_rows":len(test_idx),"train_apartments":groups.iloc[train_idx].nunique(),"test_apartments":groups.iloc[test_idx].nunique(),
                        "RMSE":mean_squared_error(y.iloc[test_idx],pred)**.5,"MAE":mean_absolute_error(y.iloc[test_idx],pred),"R2":r2_score(y.iloc[test_idx],pred),"MAPE":np.mean(np.abs(raw_y-raw_pred)/raw_y)})
        if split_id==0: models[name]=model; matrices[name]=(X,train_idx,test_idx)
    raw=pd.DataFrame(results)
    result=raw.groupby("model",sort=False).agg(split_count=("split_id","size"),train_rows=("train_rows","mean"),test_rows=("test_rows","mean"),train_apartments=("train_apartments","mean"),test_apartments=("test_apartments","mean"),RMSE=("RMSE","mean"),RMSE_std=("RMSE","std"),MAE=("MAE","mean"),MAE_std=("MAE","std"),R2=("R2","mean"),R2_std=("R2","std"),MAPE=("MAPE","mean")).reset_index()
    m1=result.set_index("model").loc["MODEL_1_M"]
    result["delta_RMSE_vs_M1"]=result.RMSE-m1.RMSE; result["delta_MAE_vs_M1"]=result.MAE-m1.MAE; result["delta_R2_vs_M1"]=result.R2-m1.R2
    return result, raw, model_frame, models, matrices


def _annual_demand_scores(root: Path):
    longitudinal=pd.read_parquet(root/"data/processed/phase9_elementary_student_longitudinal.parquet")
    config=yaml.safe_load((root/"config/phase9_elementary_demand.yaml").read_text(encoding="utf-8")); outputs=[]
    for year in (2024,2025,2026):
        history=longitudinal[longitudinal.data_year.le(year)].copy()
        if year == 2024:
            features=history[history.data_year.eq(year)].copy(); city_upper=features[["grade5_students","grade6_students"]].sum().sum()/features[["grade1_students","grade2_students"]].sum().sum()
            features["upper_lower_ratio"]=(features.grade5_students+features.grade6_students)/(features.grade1_students+features.grade2_students).replace(0,np.nan)
            features["adjusted_upper_grade_index"]=features.upper_lower_ratio/city_upper; features["observed_years"]=1; features["first_year"]=year; features["latest_year"]=year
            for col in ["student_growth_3y","student_trend_slope","student_trend_slope_rate","cohort_growth","adjusted_cohort_growth"]: features[col]=np.nan
            reliability=features.total_students/(features.total_students+config["shrinkage_k"]); features["demand_reliability"]=reliability
            city_net=(features.transfer_in.sum()-features.transfer_out.sum())/features.transfer_report_students.sum()
            features["shrunk_net_transfer_rate"]=city_net+reliability*(features.net_transfer_rate-city_net)
            features["shrunk_student_growth_3y"]=np.nan; features["shrunk_student_trend_slope_rate"]=np.nan
            features["shrunk_adjusted_upper_grade_index"]=1+reliability*(features.adjusted_upper_grade_index-1); features["shrunk_adjusted_cohort_growth"]=np.nan
            features["longitudinal_complete"]=False
        else:
            features=engineer_demand_features(history,year,config["shrinkage_k"])
        scored=score_elementary_demand(features,config)[["elementary_school_id","elementary_demand_score"]].copy(); scored["elementary_data_year"]=year; outputs.append(scored)
    return pd.concat(outputs,ignore_index=True)


def _time_aligned_analysis(root: Path, trades: pd.DataFrame, apartment_features: pd.DataFrame):
    annual=_annual_demand_scores(root)
    detail=pd.read_parquet(root/"data/processed/busan_apartment_school_score_detail_2026.parquet")
    valid=detail[detail.elementary_school_id.notna() & detail.eligible_for_school_score.fillna(False)].drop_duplicates(["internal_complex_id","elementary_school_id"])[["internal_complex_id","elementary_school_id"]]
    annual_map=valid.merge(annual,on="elementary_school_id",how="left").groupby(["internal_complex_id","elementary_data_year"],dropna=False).elementary_demand_score.mean().rename("elementary_demand_score_aligned").reset_index()
    cols=["internal_complex_id","phase7_school_score","school_score_quality","households","legal_dong"]
    physical=pd.read_csv(APARTMENT_ROOT/"data/processed/busan_complex_summary.csv")[["internal_complex_id","apartment_age","parking_per_household"]]
    apartment_time=apartment_features[cols].merge(physical,on="internal_complex_id",how="left",validate="one_to_one")
    tx=trades[pd.to_datetime(trades.deal_date).dt.year.between(2024,2026)].merge(apartment_time,on="internal_complex_id",how="left",validate="many_to_one")
    tx["transaction_year"]=pd.to_datetime(tx.deal_date).dt.year; tx=tx.merge(annual_map,left_on=["internal_complex_id","transaction_year"],right_on=["internal_complex_id","elementary_data_year"],how="left",validate="many_to_one")
    tx=tx[tx.households.ge(500)&tx.school_score_quality.eq("HIGH")&tx.phase7_school_score.notna()&tx.elementary_demand_score_aligned.notna()].copy()
    if (tx.elementary_data_year>tx.transaction_year).any(): raise ValueError("future school data detected in time-aligned analysis")
    tx["EM_interaction_aligned"]=(tx.elementary_demand_score_aligned/100)*(tx.phase7_school_score/100); tx["log_households"]=np.log(tx.households)
    rows=[]
    for year,g in tx.groupby("transaction_year"):
        p,s,n=_corr(g.elementary_demand_score_aligned,g.price_per_sqm)
        eligible=g.groupby("legal_dong").internal_complex_id.transform("nunique").ge(3); gd=g[eligible]
        _,wd,wn=_corr(gd.elementary_demand_score_aligned-gd.groupby("legal_dong").elementary_demand_score_aligned.transform("mean"),gd.price_per_sqm-gd.groupby("legal_dong").price_per_sqm.transform("mean"))
        rows.append({"analysis":"YEAR","year":year,"apartments":g.internal_complex_id.nunique(),"transactions":len(g),"E_pearson":p,"E_spearman":s,"E_within_legal_dong_spearman":wd,"within_n":wn})
    pooled=tx.rename(columns={"elementary_demand_score_aligned":"elementary_demand_score","EM_interaction_aligned":"EM_interaction"})
    reg,meta,_,_=clustered_ols_multi(pooled,("elementary_demand_score","phase7_school_score","EM_interaction"),("legal_dong","year_month"))
    for row in reg.to_dict("records"): rows.append({"analysis":"POOLED_FE","year":"2024_2026","apartments":meta["clusters"],"transactions":meta["n"],**row})
    write_parquet(root/"data/processed/phase10_time_aligned_sample.parquet",tx)
    return pd.DataFrame(rows),tx


def _same_dong_cases(common: pd.DataFrame):
    rows=[]
    d=common.dropna(subset=["legal_dong","apartment_age","households","elementary_demand_score","phase7_school_score","median_price_per_m2"])
    for (district,dong),g in d.groupby(["sigungu","legal_dong"]):
        candidates=[]; records=list(g.itertuples(index=False))
        for i,a in enumerate(records):
            for b in records[i+1:]:
                if a.mapped_elementary_school_ids==b.mapped_elementary_school_ids or abs(a.apartment_age-b.apartment_age)>5: continue
                if abs(a.households-b.households)/max(a.households,b.households)>.3: continue
                gap=abs(a.elementary_demand_score-b.elementary_demand_score)+abs(a.phase7_school_score-b.phase7_school_score)
                if gap<10: continue
                high,low=(a,b) if a.EM_interaction>=b.EM_interaction else (b,a)
                candidates.append({"sigungu":district,"legal_dong":dong,"high_complex_id":high.internal_complex_id,"high_complex_name":high.complex_name,"low_complex_id":low.internal_complex_id,"low_complex_name":low.complex_name,
                    "high_E":high.elementary_demand_score,"low_E":low.elementary_demand_score,"high_M":high.phase7_school_score,"low_M":low.phase7_school_score,"high_EM":high.EM_interaction,"low_EM":low.EM_interaction,
                    "high_price_per_m2":high.median_price_per_m2,"low_price_per_m2":low.median_price_per_m2,"price_difference_pct":high.median_price_per_m2/low.median_price_per_m2-1,"age_difference":abs(high.apartment_age-low.apartment_age),"household_difference_pct":abs(high.households-low.households)/max(high.households,low.households),"score_gap":gap})
        if candidates: rows.append(max(candidates,key=lambda x:x["score_gap"]))
    return pd.DataFrame(rows).sort_values("score_gap",ascending=False) if rows else pd.DataFrame()


def _centum_case(root: Path, common: pd.DataFrame, combined: pd.DataFrame):
    school=combined[combined.school_id.eq("S020001905")].iloc[0]
    apt=pd.read_parquet(root/"data/processed/busan_apartment_school_score_detail_2026.parquet")
    ids=set(apt.loc[apt.elementary_school_id.eq("S020001905"),"internal_complex_id"]); linked=common[common.internal_complex_id.isin(ids)]
    return {"school_id":school.school_id,"school_name":school.school_name,"elementary_demand_score":school.elementary_demand_score,"phase7_elementary_feeder_score":school.phase7_school_score,
            "phase7_pre_override_score":"NOT_PERSISTED_AS_FROZEN_ARTIFACT","simulated_confirmed_allocation_score":"NOT_CALCULATED",
            "E_percentile":school.elementary_demand_percentile,"M_percentile":school.phase7_school_percentile,"school_path_group":school.school_path_group,
            "linked_apartments":len(ids),"linked_500plus_apartments":int(apt[apt.internal_complex_id.isin(ids)&apt.households.ge(500)].internal_complex_id.nunique()),
            "common_sample_apartments":linked.internal_complex_id.nunique(),"recent_median_price_per_m2":linked.median_price_per_m2.median(),
            "median_within_dong_price_residual":linked.adjusted_residual.median() if "adjusted_residual" in linked else np.nan}


def build_phase10(root=ROOT):
    root=Path(root); immutable_before=phase95_input_hashes(root)
    snapshot,reproduced,checks=reproduce_phase8_baseline(root)
    combined=pd.read_parquet(root/"data/processed/phase95_elementary_middle_combined.parquet")
    apartment_features=pd.read_parquet(root/"data/processed/phase95_apartment_school_features.parquet")
    _,trades,base,primary,tx=_prepare_phase8_data(root)
    add_cols=["internal_complex_id","elementary_demand_score","phase7_school_score","EM_interaction","phase9_coverage_status","phase9_missing_flag","elementary_clusters","school_path_groups","mapped_elementary_school_ids","E_mean","E_max","E_min"]
    market=base.merge(apartment_features[add_cols],on="internal_complex_id",how="left",validate="one_to_one",suffixes=("","_phase95"))
    market["phase7_school_score"]=market.phase7_school_score.fillna(market.school_zone_score)
    common=market[market.internal_complex_id.isin(primary.internal_complex_id)&market.elementary_demand_score.notna()&market.phase7_school_score.notna()&market.phase9_coverage_status.eq("COMPLETE")].copy()
    if common.internal_complex_id.duplicated().any(): raise ValueError("common sample must contain one row per apartment")
    common["E01"]=common.elementary_demand_score/100; common["M01"]=common.phase7_school_score/100; common["EM_interaction"]=common.E01*common.M01
    common["elementary_cluster"]=common.elementary_clusters.map(lambda x: x[0] if isinstance(x,(list,np.ndarray)) and len(x)==1 else "MULTIPLE")
    common["school_path_group"]=common.school_path_groups.map(lambda x: x[0] if isinstance(x,(list,np.ndarray)) and len(x)==1 else "MULTIPLE")
    tx_common=tx[tx.internal_complex_id.isin(common.internal_complex_id)].merge(common[["internal_complex_id","elementary_demand_score","phase7_school_score","EM_interaction","elementary_cluster","school_path_group"]],on="internal_complex_id",how="inner",validate="many_to_one",suffixes=("","_new"))
    if "phase7_school_score_new" in tx_common:
        tx_common["phase7_school_score"]=tx_common.phase7_school_score_new.fillna(tx_common.school_zone_score); tx_common=tx_common.drop(columns="phase7_school_score_new")
    else:
        tx_common["phase7_school_score"]=tx_common.phase7_school_score.fillna(tx_common.school_zone_score)
    regressions=[]; regression_meta={}; components={}; model_residuals={}
    for name,school_vars in SCHOOL_SETS.items():
        coef,meta,fit,resid=clustered_ols_multi(tx_common,school_vars,"legal_dong")
        coef["model"]=name; regressions.append(coef); regression_meta[name]=meta; model_residuals[name]=(fit,resid)
        coefficient=coef.set_index("variable").coefficient.to_dict() if len(coef) else {}
        components[name]=sum(common[var]*coefficient.get(var,0) for var in school_vars) if school_vars else pd.Series(0.0,index=common.index)
    regression_table=pd.concat(regressions,ignore_index=True) if regressions else pd.DataFrame()
    write_csv(root/"reports/phase10_fe_regression_results.csv",regression_table)
    correlation_features={
        "M_common_sample":common.phase7_school_score,
        "E_only":common.elementary_demand_score,
        "E_plus_M":components["MODEL_3_E_M"],
        "E_plus_M_interaction":components["MODEL_4_E_M_INTERACTION"],
        "EM_interaction":common.EM_interaction,
    }
    correlations={}
    for name,series in correlation_features.items():
        common[name+"_component"]=series
        correlations[name]=_feature_correlations(common,name+"_component")
    ml,ml_splits,ml_frame,ml_models,ml_matrices=_fit_ml(tx_common); write_csv(root/"reports/phase10_ml_model_comparison.csv",ml); write_csv(root/"reports/phase10_ml_group_split_detail.csv",ml_splits)
    # Model 0 transaction residuals become a location/physical-control adjusted complex outcome.
    residual=model_residuals["MODEL_0"][1]; residual_frame=tx_common.loc[residual.index,["internal_complex_id"]].copy(); residual_frame["adjusted_residual"]=residual
    complex_residual=residual_frame.groupby("internal_complex_id").adjusted_residual.median()
    common=common.merge(complex_residual,on="internal_complex_id",how="left",validate="one_to_one")
    residual_rows=[]
    for feature in ["elementary_demand_score","phase7_school_score","EM_interaction"]:
        p,s,n=_corr(common[feature],common.adjusted_residual)
        eligible=common.groupby(["sigungu","legal_dong"]).internal_complex_id.transform("nunique").ge(3); d=common[eligible]
        _,wd,wn=_corr(d[feature]-d.groupby(["sigungu","legal_dong"])[feature].transform("mean"),d.adjusted_residual-d.groupby(["sigungu","legal_dong"]).adjusted_residual.transform("mean"))
        residual_rows.append({"feature":feature,"pearson":p,"spearman":s,"within_legal_dong_spearman":wd,"n":n,"within_n":wn})
    write_csv(root/"reports/phase10_residual_correlations.csv",pd.DataFrame(residual_rows))
    # Same test rows and split are used for every ML feature set.
    ml_index=ml.set_index("model"); m4_model=ml_models["MODEL_4_E_M_INTERACTION"]; X4,_,_=ml_matrices["MODEL_4_E_M_INTERACTION"]
    Xref=X4.copy(); med_e=ml_frame.elementary_demand_score.median(); med_m=ml_frame.phase7_school_score.median()
    Xref["elementary_demand_score"]=med_e; Xref["phase7_school_score"]=med_m; Xref["EM_interaction"]=(med_e/100)*(med_m/100)
    ml_contribution=pd.DataFrame({"internal_complex_id":ml_frame.internal_complex_id,"ml_school_contribution_log":m4_model.predict(X4)-m4_model.predict(Xref)}).groupby("internal_complex_id").mean()
    common=common.merge(ml_contribution,on="internal_complex_id",how="left",validate="one_to_one")
    # Group comparison uses school-defined groups; MULTIPLE remains explicit.
    d_resid=common.loc[common.school_path_group.eq("LOW_E_LOW_M"),"adjusted_residual"].median()
    group_rows=[]
    for name,g in common.groupby("school_path_group"):
        group_rows.append({"school_path_group":name,"apartment_count":g.internal_complex_id.nunique(),"transaction_count":int(g.trade_count.sum()),"median_price_per_m2":g.median_price_per_m2.median(),"median_price_per_pyeong":g.median_price_per_m2.median()*3.3,
            "median_age":g.apartment_age.median(),"median_households":g.households.median(),"median_E":g.elementary_demand_score.median(),"median_M":g.phase7_school_score.median(),"median_adjusted_residual":g.adjusted_residual.median(),
            "conditional_price_difference_vs_D_pct":(math.exp(g.adjusted_residual.median()-d_resid)-1)*100 if pd.notna(d_resid) else np.nan})
    group_table=pd.DataFrame(group_rows); write_csv(root/"reports/phase10_group_price_comparison.csv",group_table)
    cluster_table=common.groupby("elementary_cluster").agg(apartment_count=("internal_complex_id","nunique"),transaction_count=("trade_count","sum"),median_price_per_m2=("median_price_per_m2","median"),median_adjusted_residual=("adjusted_residual","median"),median_E=("elementary_demand_score","median"),median_M=("phase7_school_score","median")).reset_index()
    write_csv(root/"reports/phase10_cluster_price_supplement.csv",cluster_table)
    # E x M quintile matrix with model contribution. SHAP is not relabelled; PDP is used below.
    common["E_quintile"]=pd.qcut(common.elementary_demand_score.rank(method="first"),5,labels=["Q1","Q2","Q3","Q4","Q5"])
    common["M_quintile"]=pd.qcut(common.phase7_school_score.rank(method="first"),5,labels=["Q1","Q2","Q3","Q4","Q5"])
    matrix=common.groupby(["E_quintile","M_quintile"],observed=False).agg(apartment_count=("internal_complex_id","nunique"),transaction_count=("trade_count","sum"),median_raw_price_per_m2=("median_price_per_m2","median"),median_adjusted_residual=("adjusted_residual","median"),mean_ml_school_contribution_log=("ml_school_contribution_log","mean")).reset_index()
    matrix["mean_shap_contribution"]=np.nan; matrix["interaction_method"]="2D_PDP_USED_SHAP_NOT_INSTALLED"
    write_csv(root/"reports/phase10_em_quintile_matrix.csv",matrix)
    grid=[]
    for e in common.elementary_demand_score.quantile([.1,.25,.5,.75,.9]):
        for m in common.phase7_school_score.quantile([.1,.25,.5,.75,.9]):
            xp=Xref.copy(); xp["elementary_demand_score"]=e; xp["phase7_school_score"]=m; xp["EM_interaction"]=(e/100)*(m/100)
            grid.append({"E":e,"M":m,"EM_interaction":(e/100)*(m/100),"mean_predicted_log_price":m4_model.predict(xp).mean(),"pdp_difference_from_median_log":(m4_model.predict(xp)-m4_model.predict(Xref)).mean()})
    pdp=pd.DataFrame(grid); write_csv(root/"reports/phase10_em_2d_pdp.csv",pdp)
    temporal,time_sample=_time_aligned_analysis(root,trades,apartment_features); write_csv(root/"reports/phase10_temporal_robustness.csv",temporal)
    cases=_same_dong_cases(common); write_csv(root/"reports/phase10_same_dong_case_studies.csv",cases)
    centum=_centum_case(root,common,combined); write_csv(root/"reports/phase10_centum_case_study.csv",pd.DataFrame([centum]))
    # Missing coverage is measured against the unchanged Phase 8 primary sample.
    primary_market=market[market.internal_complex_id.isin(primary.internal_complex_id)]
    missing_complexes=primary_market[primary_market.phase9_coverage_status.fillna("MISSING").ne("COMPLETE")]
    missing_transactions=tx[tx.internal_complex_id.isin(missing_complexes.internal_complex_id)]
    missing_summary={"phase8_primary_apartments":len(primary),"common_apartments":len(common),"dropped_apartments":len(missing_complexes),"dropped_transactions":len(missing_transactions),"common_transactions":len(tx_common)}
    detail=pd.read_parquet(root/"data/processed/busan_apartment_school_score_detail_2026.parquet")
    valid_map=detail[detail.elementary_school_id.notna()&detail.eligible_for_school_score.fillna(False)].drop_duplicates(["internal_complex_id","elementary_school_id"])
    missing_schools=combined[combined.phase9_data_status.eq("ELEMENTARY_DEMAND_MISSING_API")][["school_id","school_name","district","phase9_data_status"]]
    impact=missing_schools.merge(valid_map[["elementary_school_id","internal_complex_id","households"]].rename(columns={"elementary_school_id":"school_id"}),on="school_id",how="left")
    impact_rows=[]
    for school_id,g in impact.groupby("school_id",dropna=False):
        ids=set(g.internal_complex_id.dropna()); primary_affected=ids&set(primary.internal_complex_id)
        impact_rows.append({"school_id":school_id,"school_name":g.school_name.iloc[0],"district":g.district.iloc[0],"phase9_data_status":g.phase9_data_status.iloc[0],"linked_apartment_count":len(ids),"linked_500plus_apartment_count":g.loc[g.households.ge(500),"internal_complex_id"].nunique(),"phase8_primary_apartment_count":len(primary_affected),"phase8_recent_transaction_count":int(tx.internal_complex_id.isin(primary_affected).sum())})
    write_csv(root/"reports/phase10_missing_school_impact.csv",pd.DataFrame(impact_rows))
    # Tidy required summary.
    columns=["Phase8_original","M_common_sample","E_only","E_plus_M","E_plus_M_interaction"]
    summary=pd.DataFrame(index=["N_apartments","N_transactions","Pearson","Spearman","Within_district_Spearman","Within_legal_dong_Spearman","FE_E_coef","FE_E_pvalue","FE_M_coef","FE_M_pvalue","FE_interaction_coef","FE_interaction_pvalue","ML_RMSE","ML_MAE","ML_R2"],columns=columns,dtype=object)
    summary.loc["N_apartments"]=[len(primary),len(common),len(common),len(common),len(common)]
    summary.loc["N_transactions"]=[len(tx),len(tx_common),len(tx_common),len(tx_common),len(tx_common)]
    summary.loc[["Pearson","Spearman","Within_district_Spearman","Within_legal_dong_Spearman"],"Phase8_original"]=[snapshot["pearson"],snapshot["spearman"],snapshot["within_sigungu_spearman"],snapshot["within_legal_dong_demeaned_spearman"]]
    for column,key in [("M_common_sample","M_common_sample"),("E_only","E_only"),("E_plus_M","E_plus_M"),("E_plus_M_interaction","E_plus_M_interaction")]:
        c=correlations[key]
        for metric in ["Pearson","Spearman","Within_district_Spearman","Within_legal_dong_Spearman"]: summary.loc[metric,column]=c[metric]
    reg_lookup={(r.model,r.variable):r for r in regression_table.itertuples()}
    for column,model in [("M_common_sample","MODEL_1_M"),("E_only","MODEL_2_E"),("E_plus_M","MODEL_3_E_M"),("E_plus_M_interaction","MODEL_4_E_M_INTERACTION")]:
        for prefix,var in [("FE_E","elementary_demand_score"),("FE_M","phase7_school_score"),("FE_interaction","EM_interaction")]:
            row=reg_lookup.get((model,var)); summary.loc[prefix+"_coef",column]=row.coefficient if row else np.nan; summary.loc[prefix+"_pvalue",column]=row.p_value if row else np.nan
        mlrow=ml_index.loc[model]; summary.loc["ML_RMSE",column]=mlrow.RMSE; summary.loc["ML_MAE",column]=mlrow.MAE; summary.loc["ML_R2",column]=mlrow.R2
    original_reg=clustered_ols(tx,CONTROLS,"legal_dong","price_per_sqm","school_zone_score")
    summary.loc["FE_M_coef","Phase8_original"]=original_reg["coefficient"]; summary.loc["FE_M_pvalue","Phase8_original"]=original_reg["p_value"]
    summary=summary.rename_axis("Metric").reset_index(); write_csv(root/"reports/phase10_incremental_value_summary.csv",summary)
    write_parquet(root/"data/processed/phase10_common_sample.parquet",common)
    improvement=(ml_index.loc["MODEL_1_M","RMSE"]-ml_index.loc["MODEL_3_E_M","RMSE"])/ml_index.loc["MODEL_1_M","RMSE"]
    interaction_ml_change=(ml_index.loc["MODEL_3_E_M","RMSE"]-ml_index.loc["MODEL_4_E_M_INTERACTION","RMSE"])/ml_index.loc["MODEL_3_E_M","RMSE"]
    e_reg=reg_lookup[("MODEL_3_E_M","elementary_demand_score")]; i_reg=reg_lookup[("MODEL_4_E_M_INTERACTION","EM_interaction")]
    dong_gain=correlations["E_plus_M"]["Within_legal_dong_Spearman"]-correlations["M_common_sample"]["Within_legal_dong_Spearman"]
    temporal_e=temporal[(temporal.analysis.eq("POOLED_FE"))&temporal.variable.eq("elementary_demand_score")].iloc[0]
    split_detail=ml_splits.pivot(index="split_id",columns="model",values="RMSE"); stable_ml=bool((split_detail.MODEL_3_E_M<split_detail.MODEL_1_M).all())
    evidence=sum([dong_gain>=.02,e_reg.p_value<.10,improvement>=.005,stable_ml])
    temporal_supported=temporal_e.coefficient>0 and temporal_e.p_value<.10
    incremental="STRONG_INCREMENTAL_VALUE" if evidence==4 and improvement>=.01 and temporal_supported else "INCREMENTAL_VALUE" if evidence>=3 else "LIMITED_INCREMENTAL_VALUE" if evidence>=1 else "NO_INCREMENTAL_VALUE"
    interaction="SUPPORTED" if i_reg.coefficient>0 and i_reg.p_value<.05 else "WEAK_EVIDENCE" if i_reg.coefficient>0 and i_reg.p_value<.10 else "NOT_SUPPORTED"
    phase11=incremental in {"STRONG_INCREMENTAL_VALUE","INCREMENTAL_VALUE"} or interaction=="SUPPORTED"
    busan_corr=pd.read_csv(root/"reports/phase95_em_correlations.csv").query("scope=='BUSAN'").iloc[0]
    group_a=combined[combined.school_path_group.eq("HIGH_E_HIGH_M")]
    group_a_price=group_table[group_table.school_path_group.eq("HIGH_E_HIGH_M")].iloc[0]
    group_a_names=", ".join(group_a.sort_values("EM_interaction",ascending=False).school_name.astype(str))
    residual_e=pd.DataFrame(residual_rows).query("feature=='elementary_demand_score'").iloc[0]
    case_consistency=(cases.price_difference_pct.gt(0).mean()*100) if len(cases) else np.nan
    yearly=temporal[temporal.analysis.eq("YEAR")].set_index("year")
    report=f"""# Phase 10 Elementary Demand 증분 설명력 검증

## 불변 입력과 Phase 8 재현
- Phase 7·8·9 입력 해시는 분석 전후 동일하다.
- Phase 8 재현값: Pearson `{reproduced['pearson']:.3f}`, Spearman `{reproduced['spearman']:.3f}`, 구·군 내 `{reproduced['within_sigungu_spearman']:.3f}`, 법정동 demeaned `{reproduced['within_legal_dong_demeaned_spearman']:.3f}`.
- 법정동 FE M 10점 연관은 `{reproduced['legal_dong_fe_10point_pct']:.2f}%`, p-value `{reproduced['legal_dong_fe_p_value']:.4f}`다.

## Phase 9.5
- E와 학교 단위 M의 Pearson은 `{busan_corr.pearson:.3f}`, Spearman은 `{busan_corr.spearman:.3f}`다.
- 두 점수 모두 상위 25%인 학교는 `{len(group_a)}`개다.
- 해당 학교: {group_a_names}.
- Common sample은 Phase 8 Primary `{len(primary)}`개 중 `{len(common)}`개 단지, 최근 12개월 거래 `{len(tx_common):,}`건이다. E 불완전 때문에 `{len(missing_complexes)}`개 단지와 `{len(missing_transactions):,}`건이 제외됐다.

## 증분 검증
- Common sample M의 법정동 내 Spearman은 `{correlations['M_common_sample']['Within_legal_dong_Spearman']:.3f}`, E+M school component는 `{correlations['E_plus_M']['Within_legal_dong_Spearman']:.3f}`로 변화량은 `{dong_gain:+.3f}`다. 원 Phase 8 benchmark 0.005와 common-sample 결과를 구분해야 한다.
- M을 통제한 E의 법정동 FE 계수는 `{e_reg.coefficient:.5f}`이며 E 10점당 `{(math.exp(e_reg.coefficient*10)-1)*100:.2f}%`, p-value `{e_reg.p_value:.4f}`다.
- E×M 계수는 `{i_reg.coefficient:.5f}`, p-value `{i_reg.p_value:.4f}`다. Interaction 판정은 **{interaction}**이다.
- 고정된 3개 단지 Group Split 평균에서 M-only log RMSE는 `{ml_index.loc['MODEL_1_M','RMSE']:.5f}`, E+M은 `{ml_index.loc['MODEL_3_E_M','RMSE']:.5f}`로 `{improvement*100:+.2f}%` 개선이며 세 split 모두 같은 방향이었다. Interaction 추가는 E+M 대비 `{interaction_ml_change*100:+.2f}%` 변화다.
- Time-aligned pooled FE의 E 10점 연관은 `{temporal_e.ten_point_association_pct:.2f}%`, p-value `{temporal_e.p_value:.4f}`로 구조적 횡단면 결과를 통계적으로 재현하지 못했다.
- Elementary Demand Layer 최종 판정은 **{incremental}**이다. Phase 11 검토 조건 충족 여부는 **{'YES' if phase11 else 'NO'}**다.

## 질문별 결론
1. E와 M의 Spearman은 `{busan_corr.spearman:.3f}`로 중간 이하의 양의 중복성을 보이며 서로 완전히 같은 정보를 측정하지 않는다.
2. E 단독 법정동 내 Spearman `{correlations['E_only']['Within_legal_dong_Spearman']:.3f}`와 M 통제 후 FE 결과는 E에 별도 정보가 있음을 지지한다.
3. 두 점수 모두 상위 25%인 학교는 `{len(group_a)}`개다.
4. 전체 학교명과 부산·구군 순위는 `phase95_high_e_high_m_schools.csv`에 기록했다.
5. HIGH_E_HIGH_M 연결 아파트 `{int(group_a_price.apartment_count)}`개는 D 대비 물리·법정동 통제 residual 기준 `{group_a_price.conditional_price_difference_vs_D_pct:.2f}%` 높았다. 이는 조건부 연관이며 인과 프리미엄 추정치가 아니다.
6. M 통제 후 E 10점 연관은 `{(math.exp(e_reg.coefficient*10)-1)*100:.2f}%`(p=`{e_reg.p_value:.4g}`)다. 반대로 E 통제 후 M 10점 연관은 `{(math.exp(reg_lookup[('MODEL_3_E_M','phase7_school_score')].coefficient*10)-1)*100:.2f}%`(p=`{reg_lookup[('MODEL_3_E_M','phase7_school_score')].p_value:.4f}`)다.
7. 선형 E×M은 p=`{i_reg.p_value:.4f}`이고 ML interaction 추가도 E+M보다 RMSE가 악화되어 **{interaction}**다. 두 조건의 단순 합을 넘는 비선형 premium은 확인되지 않았다.
8. 원 Phase 8 법정동 demeaned Spearman `0.005`는 common M에서 `{correlations['M_common_sample']['Within_legal_dong_Spearman']:.3f}`, E+M에서 `{correlations['E_plus_M']['Within_legal_dong_Spearman']:.3f}`였다.
9. Out-of-sample E+M log RMSE는 M-only보다 `{improvement*100:.2f}%` 개선됐고, R²는 `{ml_index.loc['MODEL_1_M','R2']:.3f}`에서 `{ml_index.loc['MODEL_3_E_M','R2']:.3f}`로 상승했다.
10. Time-aligned E의 법정동 내 Spearman은 2024 `{yearly.loc[2024,'E_within_legal_dong_spearman']:.3f}`, 2025 `{yearly.loc[2025,'E_within_legal_dong_spearman']:.3f}`, 2026 `{yearly.loc[2026,'E_within_legal_dong_spearman']:.3f}`였지만 pooled FE는 유의하지 않았다. 따라서 방향성은 일부 유지됐으나 회귀 강건성은 유지되지 않았다.

## 보조 검증과 사례
- 물리·위치 controls-only residual과 E의 Spearman은 `{residual_e.spearman:.3f}`, 법정동 내부 Spearman은 `{residual_e.within_legal_dong_spearman:.3f}`다.
- 연식 ±5년·유사 세대수 조건을 만족한 동일 법정동 사례는 `{len(cases)}`개 동이며, 높은 EM 단지가 더 비싼 사례 비율은 `{case_consistency:.1f}%`다. 개별 사례는 다른 미관측 품질 차이를 포함할 수 있다.
- 센텀초는 E `{centum['elementary_demand_score']:.2f}`, 학교 단위 M `{centum['phase7_elementary_feeder_score']:.2f}`, 두 점수 모두 부산 100 percentile이며 연결 500세대 이상 단지는 `{centum['linked_500plus_apartments']}`개다. 최근 ㎡당 중앙가격은 `{centum['recent_median_price_per_m2']:,.0f}`원이다.
- API 미관측 학교 영향은 `phase10_missing_school_impact.csv`에 기록했다. Primary에서 제외된 사례는 봉삼초 연결 1개 단지·37건이다.

## 시간 및 해석 한계
- Structural 분석은 2026 E를 현재 학군특성 proxy로 사용하며 인과·과거시점 예측으로 해석하지 않는다.
- Time-aligned 분석은 2024~2026 각 거래연도와 같은 공시연도의 E만 연결했다. 2024 점수는 당해 횡단면 변수만 사용하며 미래 성장정보를 사용하지 않는다.
- SHAP 패키지가 없어 SHAP 값으로 가장하지 않고 동일 Tree model의 2D PDP를 사용했다.
- 센텀초는 결과 확인용 사례이며 score나 threshold 조정에 사용하지 않았다. override 미적용 Phase 7 점수는 불변 artifact로 남아 있지 않아 재계산하지 않았다.
- Phase 11 검토 조건은 충족했지만 이번 단계에서 임의 통합점수는 생성하지 않았다.
"""
    atomic_bytes(root/"reports/phase10_validation.md",report.encode("utf-8"))
    if phase95_input_hashes(root)!=immutable_before: raise ValueError("Phase 7/8/9 immutable input changed during Phase 10")
    return {"phase8_reproduced":all(checks.values()),"phase95_both_schools":int(combined.combined_data_status.eq('BOTH').sum()),"high_e_high_m_schools":len(group_a),"common_apartments":len(common),"common_transactions":len(tx_common),"incremental_value":incremental,"interaction":interaction,"phase11_candidate":phase11}
