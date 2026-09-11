"""Phase 12: elementary-first comparison on the frozen Phase 10 common sample."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .config import ROOT, atomic_bytes, write_csv, write_json, write_parquet

APARTMENT_ROOT=ROOT.parent/"busan_apartment_analysis"
CONTROLS=("apartment_age","log_households","floor","area_group","parking_per_household")
PROTECTED=(
 "data/snapshots/school_scores_2026_phase7_final.parquet","data/snapshots/phase8_baseline_benchmark.json",
 "data/processed/busan_apartment_school_scores_2026.parquet","data/processed/elementary_feeder_scores_2026.parquet",
 "data/processed/elementary_middle_score_detail_2026.parquet",
 "data/processed/phase9_elementary_demand_scores.parquet","data/processed/phase95_elementary_middle_combined.parquet",
 "data/processed/phase10_common_sample.parquet","data/processed/phase11_middle_catchment_demand.parquet",
 "data/processed/phase11_school_network.parquet","data/processed/phase115_elementary_migration_features.parquet",
 "data/processed/busan_elementary_middle_relation_2026.parquet","config/manual_elementary_middle_overrides.csv",
)


def protected_hashes(root=ROOT):
    root=Path(root); return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in PROTECTED}


def build_phase12_dataset(root=ROOT):
    root=Path(root); common=pd.read_parquet(root/"data/processed/phase10_common_sample.parquet")
    trades=pd.read_parquet(APARTMENT_ROOT/"data/interim/trade_matched.parquet")
    detail=pd.read_parquet(root/"data/processed/busan_apartment_school_score_detail_2026.parquet")
    mapping=detail[detail.elementary_school_id.notna()&detail.eligible_for_school_score.fillna(False)].drop_duplicates(["internal_complex_id","elementary_school_id"])
    school_map=mapping.groupby("internal_complex_id").agg(
        elementary_school_id=("elementary_school_id",lambda x:";".join(sorted(set(x.astype(str))))),
        elementary_school_name=("elementary_school_name",lambda x:";".join(sorted(set(x.astype(str)))))).reset_index()
    keep=["internal_complex_id","complex_name","legal_dong","sigungu","households","apartment_age","parking_per_household",
          "elementary_demand_score","phase7_school_score","phase9_coverage_status"]
    apartment=common[keep].merge(school_map,on="internal_complex_id",how="left",validate="one_to_one")
    tx=trades[trades.internal_complex_id.isin(apartment.internal_complex_id)&~trades.is_cancelled.fillna(False)].copy()
    tx=tx.merge(apartment,on="internal_complex_id",how="inner",validate="many_to_one",suffixes=("","_apartment"))
    tx["log_households"]=np.log(tx.households.replace(0,np.nan)); tx["transaction_date"]=pd.to_datetime(tx.deal_date)
    tx["transaction_price"]=tx.deal_amount_krw; tx["exclusive_area"]=tx.area_sqm
    end=tx.transaction_date.max(); start=end-pd.DateOffset(months=12)+pd.Timedelta(days=1)
    tx["is_phase10_recent_sample"]=tx.transaction_date.between(start,end)
    tx["period_group"]=pd.cut(tx.transaction_date.dt.year,[2019,2022,2024,9999],labels=["A_2020_2022","B_2023_2024","C_2025_CURRENT"])
    cols=["internal_complex_id","complex_name","legal_dong","sigungu","elementary_school_id","elementary_school_name",
          "elementary_demand_score","phase7_school_score","households","transaction_price","price_per_sqm","exclusive_area",
          "floor","apartment_age","parking_per_household","area_group","transaction_date","year_month","period_group","is_phase10_recent_sample","phase9_coverage_status"]
    out=tx[cols].rename(columns={"internal_complex_id":"apartment_id","complex_name":"apartment_name","sigungu":"district","households":"household_count"})
    return out.sort_values(["transaction_date","apartment_id"]).reset_index(drop=True)


def _design(frame, features):
    d=frame.copy(); x=pd.DataFrame({"const":1.0},index=d.index)
    for col in (*CONTROLS,*features):
        if col=="log_households": x[col]=np.log(pd.to_numeric(d.household_count,errors="coerce").replace(0,np.nan))
        elif col=="area_group": x=pd.concat([x,pd.get_dummies(d[col],prefix=col,drop_first=True,dtype=float)],axis=1)
        else: x[col]=pd.to_numeric(d[col],errors="coerce")
    x=pd.concat([x,pd.get_dummies(d.legal_dong,prefix="legal_dong",drop_first=True,dtype=float)],axis=1)
    y=np.log(pd.to_numeric(d.price_per_sqm,errors="coerce")); valid=x.notna().all(axis=1)&y.notna()&np.isfinite(y)&d.apartment_id.notna()
    return d.loc[valid],x.loc[valid].astype(float),y.loc[valid]


def fit_clustered_ols(frame, features, model_name):
    d,x,y=_design(frame,features); X=x.to_numpy(); Y=y.to_numpy(); beta=np.linalg.pinv(X.T@X)@X.T@Y; resid=Y-X@beta
    inv=np.linalg.pinv(X.T@X); meat=np.zeros_like(inv); groups=d.apartment_id.to_numpy()
    for group in np.unique(groups):
        ix=np.flatnonzero(groups==group); score=X[ix].T@resid[ix,None]; meat+=score@score.T
    n=len(Y); k=X.shape[1]; G=len(np.unique(groups)); correction=(G/(G-1))*((n-1)/(n-k)) if G>1 and n>k else 1
    se=np.sqrt(np.maximum(np.diag(inv@meat@inv*correction),0)); sse=float(resid@resid); sigma=max(sse/n,1e-15)
    ll=-n/2*(math.log(2*math.pi)+1+math.log(sigma)); r2=1-sse/float(((Y-Y.mean())**2).sum()); adj=1-(1-r2)*(n-1)/max(n-k,1)
    rows=[]
    for feature in features:
        idx=x.columns.get_loc(feature); t=beta[idx]/se[idx] if se[idx] else np.nan; p=2*stats.t.sf(abs(t),max(G-1,1)) if np.isfinite(t) else np.nan
        rows.append({"model":model_name,"variable":feature,"coefficient":beta[idx],"standard_error":se[idx],"t_stat":t,"p_value":p,
                     "ci95_low":beta[idx]-1.96*se[idx],"ci95_high":beta[idx]+1.96*se[idx],"ten_point_price_pct":(math.exp(beta[idx]*10)-1)*100 if feature in ["elementary_demand_score","phase7_school_score"] else np.nan})
    pred=X@beta
    metrics={"model":model_name,"n_transactions":n,"n_apartments":G,"n_schools":d.elementary_school_id.nunique(),"r_squared":r2,
             "adjusted_r_squared":adj,"aic":2*k-2*ll,"bic":k*math.log(n)-2*ll,"rmse_log":float(np.sqrt(np.mean(resid**2))),
             "mae_log":float(np.mean(np.abs(resid))),"parameter_count":k,"sse":sse}
    return pd.DataFrame(rows),metrics,pd.Series(pred,index=d.index),pd.Series(resid,index=d.index)


def within_dong_spearman(frame, feature):
    a=frame.groupby(["apartment_id","district","legal_dong"],as_index=False).agg(feature=(feature,"first"),price_per_sqm=("price_per_sqm","median"))
    eligible=a.groupby(["district","legal_dong"]).apartment_id.transform("nunique").ge(3); a=a[eligible]
    x=a.feature-a.groupby(["district","legal_dong"]).feature.transform("mean"); y=a.price_per_sqm-a.groupby(["district","legal_dong"]).price_per_sqm.transform("mean")
    return x.corr(y,method="spearman"),len(a)


def temporal_split_compare(frame, model_sets):
    d=frame.sort_values("transaction_date").copy(); cutoff=d.transaction_date.quantile(.75); train_mask=d.transaction_date.le(cutoff)
    all_features=sorted(set().union(*model_sets.values())); base,x_all,y=_design(d,all_features); train=base.transaction_date.le(cutoff).to_numpy(); rows=[]
    # Rebuild per feature set on the identical valid base, preserving the same chronological split.
    for name,features in model_sets.items():
        dd,x,y2=_design(base,features); assert dd.index.equals(base.index)
        beta=np.linalg.pinv(x.loc[train].T@x.loc[train])@x.loc[train].T@y2.loc[train]; pred=x.loc[~train].to_numpy()@beta; actual=y2.loc[~train].to_numpy(); err=actual-pred
        rows.append({"model":name,"train_end":cutoff,"train_transactions":int(train.sum()),"test_transactions":int((~train).sum()),
                     "train_apartments":base.loc[train,"apartment_id"].nunique(),"test_apartments":base.loc[~train,"apartment_id"].nunique(),
                     "rmse_log":float(np.sqrt(np.mean(err**2))),"mae_log":float(np.mean(np.abs(err))),
                     "mape":float(np.mean(np.abs(np.exp(actual)-np.exp(pred))/np.exp(actual))),
                     "r_squared":1-float(err@err)/float(((actual-actual.mean())**2).sum())})
    return pd.DataFrame(rows)


def build_phase12(root=ROOT):
    root=Path(root); before=protected_hashes(root); dataset=build_phase12_dataset(root)
    write_parquet(root/"data/processed/phase12_elementary_first_dataset.parquet",dataset)
    write_csv(root/"data/processed/phase12_elementary_first_dataset.csv",dataset)
    recent=dataset[dataset.is_phase10_recent_sample].dropna(subset=["elementary_demand_score","phase7_school_score"]).copy()
    results=[]; metrics=[]
    for name,features in {"MODEL_E":["elementary_demand_score"],"MODEL_M":["phase7_school_score"]}.items():
        coef,meta,_,_=fit_clustered_ols(recent,features,name); results.append(coef); metrics.append(meta)
    coefficients=pd.concat(results,ignore_index=True); comparison=pd.DataFrame(metrics)
    for feature,name in [("elementary_demand_score","MODEL_E"),("phase7_school_score","MODEL_M")]:
        corr,n=within_dong_spearman(recent,feature); comparison.loc[comparison.model.eq(name),"within_legal_dong_spearman"]=corr; comparison.loc[comparison.model.eq(name),"within_dong_n"]=n
    oos=temporal_split_compare(dataset.dropna(subset=["elementary_demand_score","phase7_school_score"]),{"MODEL_E":["elementary_demand_score"],"MODEL_M":["phase7_school_score"]})
    comparison=comparison.merge(oos,on="model",how="left",suffixes=("_insample","_oos"))
    comparison=comparison.merge(coefficients[["model","variable","coefficient","standard_error","p_value","ci95_low","ci95_high","ten_point_price_pct"]],on="model",how="left")
    periods=[]
    for period,g in dataset.dropna(subset=["elementary_demand_score","phase7_school_score"]).groupby("period_group",observed=True):
        coef,meta,_,_=fit_clustered_ols(g,["elementary_demand_score"],"MODEL_E")
        row={**meta,**coef.iloc[0].to_dict(),"period":str(period),"start_date":g.transaction_date.min(),"end_date":g.transaction_date.max()}
        row["within_legal_dong_spearman"],row["within_dong_n"]=within_dong_spearman(g,"elementary_demand_score"); periods.append(row)
    temporal=pd.DataFrame(periods); directions="".join("+" if x>0 else "-" for x in temporal.coefficient)
    e=comparison.set_index("model").loc["MODEL_E"]; m=comparison.set_index("model").loc["MODEL_M"]
    criteria={"positive_coefficient":bool(e.coefficient>0),"within_dong_better":bool(e.within_legal_dong_spearman>m.within_legal_dong_spearman),
              "oos_rmse_not_worse":bool(e.rmse_log_oos<=m.rmse_log_oos*1.005),"temporal_direction_stable":bool(sum(temporal.coefficient>0)>=2)}
    score=sum(criteria.values()); verdict="ELEMENTARY_CORE_SUPPORTED" if score>=3 else "ELEMENTARY_CORE_PARTIALLY_SUPPORTED" if score>=2 else "ELEMENTARY_CORE_NOT_SUPPORTED"
    write_csv(root/"reports/phase12_elementary_vs_phase7_model_comparison.csv",comparison); write_csv(root/"reports/phase12_elementary_temporal_stability.csv",temporal)
    write_csv(root/"reports/phase12_regression_coefficients.csv",coefficients)
    summary={"verdict":verdict,"criteria":criteria,"temporal_directions":directions,"recent_transactions":int(len(recent)),"recent_apartments":int(recent.apartment_id.nunique()),"all_transactions":int(len(dataset)),"all_apartments":int(dataset.apartment_id.nunique())}
    write_json(root/"data/processed/phase12_result.json",summary)
    after=protected_hashes(root)
    if before!=after: raise RuntimeError("Protected Phase 7-11 input changed during Phase 12")
    write_json(root/"data/snapshots/phase12_input_hashes.json",{"input_hashes":before})
    return summary
