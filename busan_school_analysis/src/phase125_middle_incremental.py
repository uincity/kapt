"""Phase 12.5: incremental middle-option value after elementary demand."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .config import ROOT, write_csv, write_json, write_parquet
from .phase12_elementary_first import fit_clustered_ols, protected_hashes, temporal_split_compare

MIDDLE_FEATURES=("eligible_middle_score_mean","eligible_middle_score_range","eligible_middle_count",
                 "has_guaranteed_assignment","guaranteed_middle_score_component")


def build_apartment_middle_options(root=ROOT):
    root=Path(root); detail=pd.read_parquet(root/"data/processed/busan_apartment_school_score_detail_2026.parquet")
    mapping=detail[detail.elementary_school_id.notna()&detail.eligible_for_school_score.fillna(False)].drop_duplicates(["internal_complex_id","elementary_school_id"])
    rel=pd.read_parquet(root/"data/processed/busan_elementary_middle_relation_2026.parquet")
    quality=pd.read_parquet(root/"data/processed/middle_school_scores.parquet")[["middle_school_id","middle_school_score"]]
    active=rel[rel.relation_status.eq("ACTIVE")&rel.middle_school_id.notna()].copy().merge(quality,on="middle_school_id",how="left",validate="many_to_one")
    rows=[]
    for apartment_id,gmap in mapping.groupby("internal_complex_id"):
        school_ids=set(gmap.elementary_school_id); g=active[active.elementary_school_id.isin(school_ids)].drop_duplicates(["elementary_school_id","middle_school_id"])
        option=g.drop_duplicates("middle_school_id"); q=option.middle_school_score.dropna().astype(float)
        guaranteed=g[g.guaranteed_assignment.fillna(False)].drop_duplicates("middle_school_id"); gq=guaranteed.middle_school_score.dropna().astype(float)
        confirmed_elementaries=set(g.loc[g.guaranteed_assignment.fillna(False),"elementary_school_id"])
        rows.append({"apartment_id":apartment_id,"mapped_elementary_count":len(school_ids),
            "eligible_middle_count":option.middle_school_id.nunique(),"eligible_middle_score_mean":q.mean(),
            "eligible_middle_score_max":q.max(),"eligible_middle_score_min":q.min(),"eligible_middle_score_range":q.max()-q.min() if len(q) else np.nan,
            "best_middle_option_score":q.max(),"worst_middle_option_score":q.min(),
            "eligible_middle_schools":";".join(sorted(set(option.middle_school_name_current.dropna().astype(str)))),
            "has_guaranteed_assignment":int(len(guaranteed)>0),"all_elementaries_guaranteed":int(len(school_ids)>0 and school_ids.issubset(confirmed_elementaries)),
            "guaranteed_middle_count":guaranteed.middle_school_id.nunique(),"guaranteed_middle_name":";".join(sorted(set(guaranteed.middle_school_name_current.dropna().astype(str)))),
            "guaranteed_middle_score":gq.mean(),"guaranteed_middle_score_max":gq.max(),
            "guaranteed_middle_is_top_tier":int(len(gq)>0 and gq.max()>=quality.middle_school_score.quantile(.75)),
            "middle_score_available_count":int(q.size),"assignment_probability_used":False})
    out=pd.DataFrame(rows)
    # Zero is a structural interaction value when no guaranteed edge exists;
    # the separate flag prevents it from being interpreted as a zero-quality school.
    out["guaranteed_middle_score_component"]=np.where(out.has_guaranteed_assignment.eq(1),out.guaranteed_middle_score/100,0.0)
    return out


def _nested_lr(reduced,full):
    r=math.log(max(reduced["sse"],1e-15)/max(full["sse"],1e-15))*full["n_transactions"]
    df=int(full["parameter_count"]-reduced["parameter_count"])
    return {"lr_stat":r,"lr_df":df,"lr_p_value":stats.chi2.sf(r,df) if df>0 else np.nan}


def build_phase125(root=ROOT):
    root=Path(root); before=protected_hashes(root)
    options=build_apartment_middle_options(root); write_parquet(root/"data/processed/phase125_apartment_middle_options.parquet",options)
    tx=pd.read_parquet(root/"data/processed/phase12_elementary_first_dataset.parquet").merge(options,on="apartment_id",how="left",validate="many_to_one")
    recent=tx[tx.is_phase10_recent_sample].dropna(subset=["elementary_demand_score",*MIDDLE_FEATURES]).copy()
    model_sets={"MODEL_E":["elementary_demand_score"],"MODEL_E_PLUS_M":["elementary_demand_score",*MIDDLE_FEATURES]}
    coefs=[]; metrics=[]
    for name,features in model_sets.items():
        coef,meta,_,_=fit_clustered_ols(recent,features,name); coefs.append(coef); metrics.append(meta)
    coefficients=pd.concat(coefs,ignore_index=True); comparison=pd.DataFrame(metrics); lookup=comparison.set_index("model")
    reduced=lookup.loc["MODEL_E"].to_dict(); full=lookup.loc["MODEL_E_PLUS_M"].to_dict(); lr=_nested_lr(reduced,full)
    oos=temporal_split_compare(tx.dropna(subset=["elementary_demand_score",*MIDDLE_FEATURES]),model_sets)
    comparison=comparison.merge(oos,on="model",how="left",suffixes=("_insample","_oos"))
    comparison["delta_adjusted_r2_vs_E"]=comparison.adjusted_r_squared-comparison.loc[comparison.model.eq("MODEL_E"),"adjusted_r_squared"].iloc[0]
    comparison["delta_aic_vs_E"]=comparison.aic-comparison.loc[comparison.model.eq("MODEL_E"),"aic"].iloc[0]
    comparison["delta_bic_vs_E"]=comparison.bic-comparison.loc[comparison.model.eq("MODEL_E"),"bic"].iloc[0]
    comparison["delta_rmse_vs_E"]=comparison.rmse_log_oos-comparison.loc[comparison.model.eq("MODEL_E"),"rmse_log_oos"].iloc[0]
    comparison["delta_mae_vs_E"]=comparison.mae_log_oos-comparison.loc[comparison.model.eq("MODEL_E"),"mae_log_oos"].iloc[0]
    for key,value in lr.items(): comparison.loc[comparison.model.eq("MODEL_E_PLUS_M"),key]=value
    # Strict gold sample: every mapped elementary has a confirmed edge and there is one unique guaranteed middle.
    gold=tx[tx.is_phase10_recent_sample&tx.all_elementaries_guaranteed.eq(1)&tx.guaranteed_middle_count.eq(1)].dropna(subset=["elementary_demand_score","guaranteed_middle_score"]).copy()
    gold["E_G_interaction"]=(gold.elementary_demand_score/100)*(gold.guaranteed_middle_score/100)
    gold_sets={"GOLD_E":["elementary_demand_score"],"GOLD_E_G":["elementary_demand_score","guaranteed_middle_score"],
               "GOLD_E_G_INTERACTION":["elementary_demand_score","guaranteed_middle_score","E_G_interaction"]}
    gold_coefs=[]; gold_metrics=[]
    for name,features in gold_sets.items():
        coef,meta,_,_=fit_clustered_ols(gold,features,name); gold_coefs.append(coef); gold_metrics.append(meta)
    gold_table=pd.DataFrame(gold_metrics).merge(pd.concat(gold_coefs,ignore_index=True),on="model",how="left")
    e=comparison.set_index("model").loc["MODEL_E"]; em=comparison.set_index("model").loc["MODEL_E_PLUS_M"]
    quality_coef=coefficients[(coefficients.model.eq("MODEL_E_PLUS_M"))&coefficients.variable.eq("eligible_middle_score_mean")].iloc[0]
    gold_quality=gold_table[(gold_table.model.eq("GOLD_E_G"))&gold_table.variable.eq("guaranteed_middle_score")]
    guaranteed_component=coefficients[(coefficients.model.eq("MODEL_E_PLUS_M"))&coefficients.variable.eq("guaranteed_middle_score_component")].iloc[0]
    criteria={"adjusted_r2_gain":bool(em.adjusted_r_squared-e.adjusted_r_squared>=.001),"aic_improves":bool(em.aic<=e.aic-2),
              "bic_improves":bool(em.bic<=e.bic-2),"oos_rmse_improves_0_5pct":bool(em.rmse_log_oos<=e.rmse_log_oos*.995),
              "oos_mae_improves_0_5pct":bool(em.mae_log_oos<=e.mae_log_oos*.995),"eligible_quality_positive":bool(quality_coef.coefficient>0),
              "eligible_quality_significant":bool(quality_coef.coefficient>0 and quality_coef.p_value<.10),
              "guaranteed_quality_component_positive_significant":bool(guaranteed_component.coefficient>0 and guaranteed_component.p_value<.10),
              "gold_guaranteed_positive":bool(len(gold_quality) and gold_quality.coefficient.iloc[0]>0),
              "middle_joint_lr_significant":bool(lr["lr_p_value"]<.05)}
    strong=(criteria["oos_rmse_improves_0_5pct"] and criteria["oos_mae_improves_0_5pct"] and criteria["middle_joint_lr_significant"]
            and (criteria["eligible_quality_significant"] or criteria["guaranteed_quality_component_positive_significant"])
            and criteria["gold_guaranteed_positive"])
    partial=(criteria["middle_joint_lr_significant"] and (em.rmse_log_oos<e.rmse_log_oos or em.mae_log_oos<e.mae_log_oos))
    verdict="MIDDLE_INCREMENTAL_VALUE_SUPPORTED" if strong else "MIDDLE_INCREMENTAL_VALUE_PARTIALLY_SUPPORTED" if partial else "MIDDLE_INCREMENTAL_VALUE_NOT_SUPPORTED"
    write_csv(root/"reports/phase125_middle_feature_definition.csv",options)
    write_csv(root/"reports/phase125_nested_model_comparison.csv",comparison)
    write_csv(root/"reports/phase125_regression_coefficients.csv",coefficients)
    write_csv(root/"reports/phase125_guaranteed_gold_validation.csv",gold_table)
    result={"verdict":verdict,"criteria":criteria,"recent_transactions":int(len(recent)),"recent_apartments":int(recent.apartment_id.nunique()),
            "gold_transactions":int(len(gold)),"gold_apartments":int(gold.apartment_id.nunique()),"gold_schools":int(gold.elementary_school_id.nunique()),**{k:(float(v) if pd.notna(v) else None) for k,v in lr.items()}}
    write_json(root/"data/processed/phase125_result.json",result)
    if before!=protected_hashes(root): raise RuntimeError("Protected Phase 7-11 input changed during Phase 12.5")
    return result
