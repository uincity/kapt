"""Phase 8: validate the association between school scores and apartment markets."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import stats

from .config import ROOT, atomic_bytes, write_csv, write_parquet

APARTMENT_ROOT = ROOT.parent / "busan_apartment_analysis"


def internal_complex_join(left: pd.DataFrame, right: pd.DataFrame, columns=None) -> pd.DataFrame:
    if left.internal_complex_id.isna().any() or right.internal_complex_id.isna().any():
        raise ValueError("internal_complex_id cannot be null for Phase 8 joins")
    use = right if columns is None else right[["internal_complex_id", *columns]]
    if use.internal_complex_id.duplicated().any():
        raise ValueError("right side of complex join must contain one row per complex")
    return left.merge(use, on="internal_complex_id", how="left", validate="many_to_one")


def primary_sample(frame: pd.DataFrame, quality=("HIGH",), min_trades=1) -> pd.DataFrame:
    mask = frame.households.ge(500) & frame.school_zone_score.notna()
    if "school_score_quality" in frame:
        mask &= frame.school_score_quality.isin(quality)
    if "trade_count" in frame:
        mask &= frame.trade_count.ge(min_trades)
    return frame.loc[mask].copy()


def add_low_sample_flag(frame: pd.DataFrame, threshold=3) -> pd.DataFrame:
    out = frame.copy()
    out["low_sample_flag"] = out["trade_count"].fillna(0).lt(threshold)
    return out


def add_quintile(frame: pd.DataFrame, score="school_zone_score") -> pd.DataFrame:
    out = frame.copy(); valid = out[score].notna()
    ranked = out.loc[valid, score].rank(method="average", pct=True)
    out.loc[valid, "school_quintile"] = pd.cut(ranked, [0, .2, .4, .6, .8, 1], labels=["Q1", "Q2", "Q3", "Q4", "Q5"], include_lowest=True).astype(str)
    return out


def add_within_group_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["school_score_percentile_in_sigungu"] = out.groupby("sigungu")["school_zone_score"].rank(pct=True) * 100
    out["price_percentile_in_sigungu"] = out.groupby("sigungu")["median_price_per_m2"].rank(pct=True) * 100
    eligible = out.groupby(["sigungu", "legal_dong"])["internal_complex_id"].transform("nunique").ge(3)
    out["same_dong_eligible"] = eligible
    out["demeaned_price"] = np.where(eligible, out.median_price_per_m2 - out.groupby(["sigungu", "legal_dong"]).median_price_per_m2.transform("mean"), np.nan)
    out["demeaned_school_score"] = np.where(eligible, out.school_zone_score - out.groupby(["sigungu", "legal_dong"]).school_zone_score.transform("mean"), np.nan)
    return out


def winsorize_series(series: pd.Series, limits=(.01, .99)) -> pd.Series:
    lo, hi = series.quantile(list(limits))
    return series.clip(lo, hi)


def _corr(x, y):
    valid = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(valid) < 3 or valid.x.nunique() < 2 or valid.y.nunique() < 2:
        return np.nan, np.nan, len(valid)
    return valid.x.corr(valid.y, method="pearson"), valid.x.corr(valid.y, method="spearman"), len(valid)


def _aggregate_market(trades, rents, scores, periods, low_threshold):
    max_date = pd.to_datetime(trades.deal_date).max()
    outputs = []
    for period, months in periods.items():
        start = pd.Timestamp("2020-01-01") if months is None else max_date - pd.DateOffset(months=months) + pd.Timedelta(days=1)
        sale = trades[pd.to_datetime(trades.deal_date).between(start, max_date)].copy()
        rent = rents[pd.to_datetime(rents.deal_date).between(start, max_date) & rents.rent_type.eq("전세")].copy()
        for scope in ("ALL", "80_90", "55_65"):
            s = sale if scope == "ALL" else sale[sale.area_group.eq(scope)]
            r = rent if scope == "ALL" else rent[rent.area_group.eq(scope)]
            agg = s.groupby("internal_complex_id").agg(
                median_price_per_m2=("price_per_sqm", "median"), mean_price_per_m2=("price_per_sqm", "mean"),
                median_sale_price=("deal_amount_krw", "median"), trade_count=("deal_amount_krw", "size"),
                median_floor=("floor", "median"), median_area_sqm=("area_sqm", "median"),
                first_trade_date=("deal_date", "min"), last_trade_date=("deal_date", "max")
            ).reset_index()
            monthly = s.groupby(["internal_complex_id", "year_month"]).price_per_sqm.median().reset_index()
            monthly["seq"] = monthly.groupby("internal_complex_id").cumcount()
            ret = monthly.groupby("internal_complex_id").price_per_sqm.agg(["first", "last"])
            ret["recent_return"] = ret["last"] / ret["first"] - 1
            agg = agg.merge(ret[["recent_return"]], on="internal_complex_id", how="left")
            dep = r.groupby("internal_complex_id").agg(median_jeonse_deposit=("deposit_krw", "median"), jeonse_count=("deposit_krw", "size")).reset_index()
            agg = agg.merge(dep, on="internal_complex_id", how="left")
            agg["jeonse_ratio"] = agg.median_jeonse_deposit / agg.median_sale_price
            agg = internal_complex_join(agg, scores, [c for c in scores.columns if c != "internal_complex_id"])
            agg["period"] = period; agg["area_group"] = scope
            agg["turnover"] = agg.trade_count / agg.households
            agg = add_low_sample_flag(agg, low_threshold)
            outputs.append(agg)
    return pd.concat(outputs, ignore_index=True)


def create_pairs(frame: pd.DataFrame, min_pairs=20, score_gap=10, household_tolerance=.30, age_tolerance=5):
    rows = []
    d = frame.dropna(subset=["school_zone_score", "median_price_per_m2", "households", "apartment_age"]).copy()
    for level in ("legal_dong", "sigungu"):
        for _, group in d.groupby(["sigungu", level] if level == "legal_dong" else ["sigungu"]):
            vals = list(group.itertuples(index=False))
            for i, a in enumerate(vals):
                for b in vals[i + 1:]:
                    if abs(a.households-b.households)/max(a.households,b.households) > household_tolerance: continue
                    if abs(a.apartment_age-b.apartment_age) > age_tolerance: continue
                    gap = abs(a.school_zone_score-b.school_zone_score)
                    if gap < score_gap: continue
                    high, low = (a,b) if a.school_zone_score >= b.school_zone_score else (b,a)
                    rows.append({"match_level": level, "area_group": a.area_group,
                        "high_complex_id": high.internal_complex_id, "high_complex_name": high.complex_name,
                        "low_complex_id": low.internal_complex_id, "low_complex_name": low.complex_name,
                        "sigungu": high.sigungu, "legal_dong": high.legal_dong if high.legal_dong == low.legal_dong else pd.NA,
                        "high_score": high.school_zone_score, "low_score": low.school_zone_score, "score_gap": gap,
                        "high_price_per_m2": high.median_price_per_m2, "low_price_per_m2": low.median_price_per_m2,
                        "price_difference_pct": high.median_price_per_m2/low.median_price_per_m2-1,
                        "household_difference_pct": abs(high.households-low.households)/max(high.households,low.households),
                        "age_difference_years": abs(high.apartment_age-low.apartment_age)})
        if len(rows) >= min_pairs: break
    if not rows: return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values(["match_level", "score_gap"], ascending=[True, False])
    return out.drop_duplicates(["high_complex_id", "low_complex_id"]).head(max(min_pairs, 100))


def clustered_ols(frame, controls=(), fixed_effect=None, price_column="price_per_sqm", score_column="school_zone_score"):
    cols = [price_column, score_column, "internal_complex_id", *controls]
    if fixed_effect: cols.append(fixed_effect)
    d = frame[cols].replace([np.inf, -np.inf], np.nan).dropna(subset=[price_column, score_column, "internal_complex_id"]).copy()
    x = pd.DataFrame({"const": 1., "school_zone_score": d[score_column].astype(float)}, index=d.index)
    for col in controls:
        if col in d and pd.api.types.is_numeric_dtype(d[col]): x[col] = pd.to_numeric(d[col], errors="coerce")
        elif col in d: x = pd.concat([x, pd.get_dummies(d[col], prefix=col, drop_first=True, dtype=float)], axis=1)
    if fixed_effect:
        x = pd.concat([x, pd.get_dummies(d[fixed_effect], prefix=fixed_effect, drop_first=True, dtype=float)], axis=1)
    y = np.log(pd.to_numeric(d[price_column], errors="coerce"))
    valid = x.notna().all(axis=1) & y.notna(); x=x.loc[valid].astype(float); y=y.loc[valid]; groups=d.loc[valid,"internal_complex_id"]
    X=x.to_numpy(); Y=y.to_numpy(); beta=np.linalg.pinv(X.T@X)@X.T@Y; resid=Y-X@beta
    bread=np.linalg.pinv(X.T@X); meat=np.zeros((X.shape[1],X.shape[1]));
    for g in groups.unique():
        ix=np.flatnonzero(groups.to_numpy()==g); xu=X[ix]; ug=resid[ix,None]; s=xu.T@ug; meat += s@s.T
    G=groups.nunique(); N=len(y); k=X.shape[1]; correction=(G/(G-1))*((N-1)/(N-k)) if G>1 and N>k else 1
    se=np.sqrt(np.maximum(np.diag(bread@meat@bread*correction),0)); idx=list(x.columns).index("school_zone_score")
    tval=beta[idx]/se[idx] if se[idx] else np.nan; p=2*stats.t.sf(abs(tval), max(G-1,1)) if np.isfinite(tval) else np.nan
    r2=1-(resid@resid)/(((Y-Y.mean())**2).sum())
    return {"coefficient": beta[idx], "standard_error": se[idx], "p_value": p, "r_squared": r2, "n": N, "clusters": G, "score_10point_association_pct": (math.exp(beta[idx]*10)-1)*100}


def _relation_source(scores, relations):
    active = relations[relations.relation_status.eq("ACTIVE") & relations.middle_school_id.notna()]
    official=set(active.loc[~active.manual_review,"elementary_school_id"].dropna()); manual=set(active.loc[active.manual_review,"elementary_school_id"].dropna())
    def classify(ids):
        ids=set(ids) if isinstance(ids,(list,tuple,np.ndarray)) else set(); a=bool(ids&official); m=bool(ids&manual)
        return "MIXED" if a and m else "OFFICIAL" if a else "MANUAL_VERIFIED" if m else "NONE"
    out=scores.copy(); out["relation_source_group"]=out.elementary_school_ids.map(classify); return out


def _write_visuals(metrics, correlations, quintiles, regressions, top30, reports):
    import plotly.express as px
    base=metrics[(metrics.period.eq("12M"))&(metrics.area_group.eq("ALL"))&metrics.households.ge(500)&metrics.school_zone_score.notna()]
    figs={
      "score_price_scatter": px.scatter(base,x="school_zone_score",y="median_price_per_m2",color="sigungu",hover_name="complex_name",trendline=None),
      "quintile_price": px.bar(quintiles[quintiles.analysis.eq("QUINTILE")],x="group",y="median_price_per_m2",color="quality_scope",barmode="group"),
      "sigungu_relation": px.scatter(base,x="school_zone_score",y="median_price_per_m2",facet_col="sigungu",facet_col_wrap=4),
      "percentile_relation": px.scatter(add_within_group_metrics(base),x="school_score_percentile_in_sigungu",y="price_percentile_in_sigungu",color="sigungu"),
      "regression_coefficients": px.bar(regressions,x="model",y="score_10point_association_pct",color="price_variant",error_y="score_10point_se_pct"),
      "top30_score_price": px.scatter(top30,x="school_zone_score",y="median_price_per_m2",color="sigungu",hover_name="complex_name",size="households")}
    for name,fig in figs.items(): fig.write_html(reports/f"phase8_{name}.html",include_plotlyjs="cdn")


def build_phase8(root=ROOT):
    root=Path(root); reports=root/"reports"; processed=root/"data/processed"; snapshots=root/"data/snapshots"; snapshots.mkdir(parents=True,exist_ok=True)
    cfg=yaml.safe_load((root/"config/phase8_analysis.yaml").read_text(encoding="utf-8"))
    score_path=processed/"busan_apartment_school_scores_2026.parquet"; relation_path=processed/"busan_elementary_middle_relation_2026.parquet"
    scores=pd.read_parquet(score_path); relations=pd.read_parquet(relation_path)
    required={"relation_status","raw_middle_school_name","source_page","source_text"}
    if not required.issubset(relations.columns): raise ValueError("Phase 7 관계 상태를 먼저 재생성하세요: python main.py phase7-build --assignment-year 2026")
    scores=_relation_source(scores,relations)
    sensitivity=pd.read_parquet(processed/"busan_school_score_sensitivity_2026.parquet")
    metadata={"assignment_school_year":2026,"school_zone_reference_date":"2025-09-22","score_version":cfg["score_version"],"relation_count":len(relations),
      "500plus_coverage":f"{scores.loc[scores.households.ge(500),'school_zone_score'].notna().sum()}/{scores.households.ge(500).sum()}","created_at":datetime.now().astimezone().isoformat(),
      "source_hashes":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [score_path,relation_path]}}
    write_parquet(snapshots/"school_scores_2026_phase7_final.parquet",scores)
    atomic_bytes(snapshots/"school_scores_2026_phase7_final.metadata.json",json.dumps(metadata,ensure_ascii=False,indent=2).encode("utf-8"))
    monthly=pd.read_parquet(APARTMENT_ROOT/"data/processed/busan_apartment_monthly.parquet")
    rent_monthly=pd.read_parquet(APARTMENT_ROOT/"data/processed/busan_apartment_rent_monthly.parquet")
    trades=pd.read_parquet(APARTMENT_ROOT/"data/interim/trade_matched.parquet")
    rents=pd.read_parquet(APARTMENT_ROOT/"data/interim/rent_matched.parquet")
    complex_summary=pd.read_csv(APARTMENT_ROOT/"data/processed/busan_complex_summary.csv")
    panel=internal_complex_join(monthly,scores,[c for c in scores.columns if c not in {"internal_complex_id","complex_name","sigungu","households"}])
    rent_cols=[c for c in ["internal_complex_id","year_month","area_group","jeonse_count_12m","median_jeonse_deposit_12m","jeonse_ratio_12m"] if c in rent_monthly]
    panel=panel.merge(rent_monthly[rent_cols],on=["internal_complex_id","year_month","area_group"],how="left",validate="one_to_one")
    panel["price_per_m2"]=panel.median_price_per_sqm
    write_parquet(processed/"phase8_apartment_school_price_panel.parquet",panel)
    controls=complex_summary[[c for c in ["internal_complex_id","apartment_age","parking_per_household"] if c in complex_summary]]
    score_enriched=internal_complex_join(scores,controls,[c for c in controls if c!="internal_complex_id"])
    metrics=_aggregate_market(trades,rents,score_enriched,cfg["periods"],cfg["low_sample_trade_count"])
    metrics=metrics.merge(sensitivity[["internal_complex_id","score_quality_focused","score_stability_focused"]],on="internal_complex_id",how="left",suffixes=("","_sens"))
    for c in ["score_quality_focused","score_stability_focused"]:
        if c+"_sens" in metrics: metrics[c]=metrics[c].fillna(metrics[c+"_sens"]); metrics.drop(columns=[c+"_sens"],inplace=True)
    corr=[]
    for quality_name,quals in [("HIGH",["HIGH"]),("HIGH_MEDIUM",["HIGH","MEDIUM"])]:
      for period in cfg["periods"]:
       for area in cfg["area_scopes"]:
        d=primary_sample(metrics[(metrics.period.eq(period))&metrics.area_group.eq(area)],quals)
        for variant,col in [("BASE","school_zone_score"),("QUALITY_FOCUSED","score_quality_focused"),("STABILITY_FOCUSED","score_stability_focused")]:
          p,s,n=_corr(d[col],d.median_price_per_m2); corr.append({"scope":"BUSAN","group":"ALL","period":period,"area_group":area,"quality_scope":quality_name,"score_variant":variant,"pearson":p,"spearman":s,"n":n})
        if period=="12M" and area=="ALL":
          for name,g in d.groupby("sigungu"):
            p,s,n=_corr(g.school_zone_score,g.median_price_per_m2); corr.append({"scope":"SIGUNGU","group":name,"period":period,"area_group":area,"quality_scope":quality_name,"score_variant":"BASE","pearson":p,"spearman":s,"n":n})
          w=add_within_group_metrics(d); p,s,n=_corr(w.school_score_percentile_in_sigungu,w.price_percentile_in_sigungu); corr.append({"scope":"WITHIN_SIGUNGU_PERCENTILE","group":"ALL","period":period,"area_group":area,"quality_scope":quality_name,"score_variant":"BASE","pearson":p,"spearman":s,"n":n})
          wd=w[w.same_dong_eligible]; p,s,n=_corr(wd.demeaned_school_score,wd.demeaned_price); corr.append({"scope":"WITHIN_LEGAL_DONG_DEMEANED","group":"ALL","period":period,"area_group":area,"quality_scope":quality_name,"score_variant":"BASE","pearson":p,"spearman":s,"n":n})
    base=metrics[(metrics.period.eq("12M"))&metrics.area_group.eq("ALL")]
    # Component, source, age and trade-count sensitivity rows share one tidy
    # result file so every robustness result can be filtered reproducibly.
    high=primary_sample(base,["HIGH"])
    components=["mean_middle_score","worst_middle_score","feeder_exclusivity","assignment_data_quality","elementary_accessibility_score","nearest_elementary_distance_m"]
    for col in components:
      p,s,n=_corr(high[col],high.median_price_per_m2); corr.append({"scope":"COMPONENT","group":col,"period":"12M","area_group":"ALL","quality_scope":"HIGH","score_variant":col,"pearson":p,"spearman":s,"n":n})
    for threshold in (1,3,5):
      g=primary_sample(base,["HIGH"],threshold); p,s,n=_corr(g.school_zone_score,g.median_price_per_m2); corr.append({"scope":"TRADE_COUNT_SENSITIVITY","group":f">={threshold}","period":"12M","area_group":"ALL","quality_scope":"HIGH","score_variant":"BASE","pearson":p,"spearman":s,"n":n})
    high["age_group"]=pd.cut(high.apartment_age,[-1,5,10,20,np.inf],labels=["0_5","6_10","11_20","20_PLUS"])
    for name,g in high.groupby("age_group",observed=True):
      p,s,n=_corr(g.school_zone_score,g.median_price_per_m2); corr.append({"scope":"AGE_GROUP","group":name,"period":"12M","area_group":"ALL","quality_scope":"HIGH","score_variant":"BASE","pearson":p,"spearman":s,"n":n})
    for name,g in high.groupby("relation_source_group"):
      p,s,n=_corr(g.school_zone_score,g.median_price_per_m2); corr.append({"scope":"RELATION_SOURCE","group":name,"period":"12M","area_group":"ALL","quality_scope":"HIGH","score_variant":"BASE","pearson":p,"spearman":s,"n":n})
    # Coverage-bias audit includes all 500+ complexes; missing price remains NA.
    all500=scores[scores.households.ge(500)].copy().merge(base[["internal_complex_id","median_price_per_m2","trade_count","apartment_age"]],on="internal_complex_id",how="left",suffixes=("","_market"))
    office_map={"중구":"seobu","서구":"seobu","영도구":"seobu","사하구":"seobu","남구":"nambu","동구":"nambu","부산진구":"nambu","북구":"bukbu","사상구":"bukbu","강서구":"bukbu","동래구":"dongnae","금정구":"dongnae","연제구":"dongnae","해운대구":"haeundae","수영구":"haeundae","기장군":"haeundae"}
    all500["education_office"]=all500.sigungu.map(office_map); all500["score_status"]=np.where(all500.school_zone_score.notna(),"SCORED","UNSCORED")
    for (office,status),g in all500.groupby(["education_office","score_status"]):
      corr.append({"scope":"COVERAGE_BIAS","group":f"{office}:{status}","period":"12M","area_group":"ALL","quality_scope":"ALL","score_variant":"BASE","pearson":np.nan,"spearman":np.nan,"n":len(g),"median_households":g.households.median(),"median_price_per_m2":g.median_price_per_m2.median(),"median_apartment_age":g.apartment_age.median(),"unique_legal_dong":g.legal_dong.nunique()})
    correlations=pd.DataFrame(corr); write_csv(reports/"phase8_school_price_correlation.csv",correlations)
    quint=[]
    for qname,quals in [("HIGH",["HIGH"]),("HIGH_MEDIUM",["HIGH","MEDIUM"])]:
      d=add_quintile(primary_sample(base,quals))
      for name,g in d.groupby("school_quintile",observed=True):
       quint.append({"analysis":"QUINTILE","quality_scope":qname,"group":name,"complex_count":g.internal_complex_id.nunique(),"median_price_per_m2":g.median_price_per_m2.median(),"median_trade_count":g.trade_count.median(),"median_turnover":g.turnover.median(),"median_jeonse_ratio":g.jeonse_ratio.median(),"median_apartment_age":g.apartment_age.median()})
      cutoff=d.school_zone_score.quantile(.9); d["top10_group"]=np.where(d.school_zone_score.ge(cutoff),"TOP10","REMAINING90")
      for name,g in d.groupby("top10_group"):
       quint.append({"analysis":"TOP10","quality_scope":qname,"group":name,"complex_count":g.internal_complex_id.nunique(),"median_price_per_m2":g.median_price_per_m2.median(),"median_trade_count":g.trade_count.median(),"median_turnover":g.turnover.median(),"median_jeonse_ratio":g.jeonse_ratio.median(),"median_recent_return":g.recent_return.median(),"median_apartment_age":g.apartment_age.median()})
      qmed=d.groupby("school_quintile",observed=True).median_price_per_m2.median()
      if {"Q1","Q5"}.issubset(qmed.index):
       quint.append({"analysis":"Q5_MINUS_Q1","quality_scope":qname,"group":"Q5-Q1","complex_count":len(d),"median_price_per_m2":qmed["Q5"]-qmed["Q1"],"price_difference_pct":qmed["Q5"]/qmed["Q1"]-1})
    score_band=add_quintile(primary_sample(base,["HIGH"]))[["internal_complex_id","school_quintile"]]
    phase_panel=panel[panel.area_group.eq("80_90")&panel.households.ge(500)&panel.school_score_quality.eq("HIGH")].merge(score_band,on="internal_complex_id",how="inner")
    market=phase_panel.groupby("year_month").median_price_per_sqm.median().sort_index().pct_change().rename("market_return")
    band=phase_panel[phase_panel.school_quintile.isin(["Q1","Q5"])].groupby(["year_month","school_quintile"],observed=True).median_price_per_sqm.median().unstack().sort_index().pct_change()
    phases=band.join(market).dropna(subset=["market_return"]); phases["market_phase"]=np.where(phases.market_return.lt(0),"DECLINE","RISE")
    phase_summary={}
    for phase,g in phases.groupby("market_phase"):
      for band_name in ("Q1","Q5"):
       value=g[band_name].median() if band_name in g else np.nan; phase_summary[(phase,band_name)]=value
       quint.append({"analysis":"MARKET_PHASE","quality_scope":"HIGH","group":f"{phase}_{band_name}","complex_count":g[band_name].notna().sum() if band_name in g else 0,"median_recent_return":value})
    quintiles=pd.DataFrame(quint); write_csv(reports/"phase8_school_quintile_analysis.csv",quintiles)
    pair_base=primary_sample(metrics[(metrics.period.eq("12M"))&metrics.area_group.isin(["80_90","55_65"])],["HIGH","MEDIUM"])
    pairs=create_pairs(pair_base); write_csv(reports/"phase8_comparable_pairs.csv",pairs)
    tx=trades[pd.to_datetime(trades.deal_date).ge(pd.to_datetime(trades.deal_date).max()-pd.DateOffset(months=12)+pd.Timedelta(days=1))]
    tx=internal_complex_join(tx,score_enriched,["school_zone_score","score_quality_focused","score_stability_focused","school_score_quality","households","apartment_age","parking_per_household","legal_dong"])
    tx=tx[tx.households.ge(500)&tx.school_score_quality.eq("HIGH")&tx.school_zone_score.notna()]
    tx["log_households"]=np.log(tx.households); tx["price_per_sqm_winsorized"]=winsorize_series(tx.price_per_sqm)
    models=[("MODEL1",(),None),("MODEL2",("apartment_age","log_households","floor","area_group","parking_per_household"),None),("MODEL3",("apartment_age","log_households","floor","area_group","parking_per_household"),"sigungu"),("MODEL4",("apartment_age","log_households","floor","area_group","parking_per_household"),"legal_dong")]
    regs=[]
    for variant,col in [("RAW","price_per_sqm"),("WINSORIZED_1_99","price_per_sqm_winsorized")]:
      for name,ctrl,fe in models:
       result=clustered_ols(tx,ctrl,fe,col); result.update({"model":name,"price_variant":variant,"fixed_effect":fe or "NONE","score_10point_se_pct":result["standard_error"]*10*100}); regs.append(result)
    for label,score_col in [("QUALITY_FOCUSED","score_quality_focused"),("STABILITY_FOCUSED","score_stability_focused")]:
      result=clustered_ols(tx,models[-1][1],"legal_dong","price_per_sqm",score_col); result.update({"model":"MODEL4","price_variant":label,"fixed_effect":"legal_dong","score_10point_se_pct":result["standard_error"]*10*100}); regs.append(result)
    regressions=pd.DataFrame(regs); write_csv(reports/"phase8_regression_results.csv",regressions)
    missing=scores[scores.households.ge(500)&scores.school_zone_score.isna()].copy()
    missing=missing.merge(base[["internal_complex_id","median_price_per_m2","trade_count"]],on="internal_complex_id",how="left")
    audit_path=reports/"phase7_missing_500plus_apartments.csv"
    if audit_path.exists():
      audit=pd.read_csv(audit_path); audit=audit.groupby("internal_complex_id").agg(elementary_school=("elementary_school_name",lambda x:"; ".join(sorted(set(x.dropna().astype(str))))),missing_reason=("missing_reason",lambda x:"; ".join(sorted(set(x.dropna().astype(str)))))).reset_index(); missing=missing.merge(audit,on="internal_complex_id",how="left")
    write_csv(reports/"phase8_unscored_500plus.csv",missing[[c for c in ["internal_complex_id","complex_name","sigungu","legal_dong","households","elementary_school","missing_reason","median_price_per_m2","trade_count"] if c in missing]])
    top=scores[scores.households.ge(500)&scores.school_zone_score.notna()].nsmallest(30,"busan_school_rank").copy(); top.insert(0,"rank",range(1,len(top)+1)); top=top.merge(base[["internal_complex_id","median_price_per_m2","trade_count"]],on="internal_complex_id",how="left")
    top["price_rank_in_dong"]=top.groupby(["sigungu","legal_dong"]).median_price_per_m2.rank(ascending=False,method="min")
    detail=pd.read_parquet(processed/"elementary_middle_score_detail_2026.parquet")
    mids=detail.groupby("elementary_school_id").middle_school_name.agg(lambda x:"; ".join(sorted(set(x.dropna().astype(str))))).to_dict()
    top["middle_school_candidates"]=top.elementary_school_ids.map(lambda ids:"; ".join(sorted({mids.get(i,"") for i in ids if mids.get(i,"")})) if isinstance(ids,(list,tuple,np.ndarray)) else "")
    write_csv(reports/"phase8_top30_school_price.csv",top[["rank","internal_complex_id","complex_name","sigungu","legal_dong","households","elementary_school_names","middle_school_candidates","school_zone_score","school_score_quality","median_price_per_m2","price_rank_in_dong","trade_count"]])
    primary=primary_sample(base,["HIGH"]); main=correlations.query("scope=='BUSAN' and period=='12M' and area_group=='ALL' and quality_scope=='HIGH' and score_variant=='BASE'").iloc[0]; within=correlations.query("scope=='WITHIN_SIGUNGU_PERCENTILE' and quality_scope=='HIGH'").iloc[0]; dong=correlations.query("scope=='WITHIN_LEGAL_DONG_DEMEANED' and quality_scope=='HIGH'").iloc[0]; m4=regressions.query("model=='MODEL4' and price_variant=='RAW'").iloc[0]
    feature="STRONG_FEATURE" if m4.p_value<.05 and m4.coefficient>0 and main.spearman>0 else "USEFUL_FEATURE" if m4.coefficient>0 or main.spearman>0 else "WEAK_FEATURE" if abs(main.spearman)<.1 else "NOT_SUPPORTED"
    component_rows=correlations[correlations.scope.eq("COMPONENT")].dropna(subset=["spearman"]); strongest=component_rows.loc[component_rows.spearman.abs().idxmax()]
    decline_q1=phase_summary.get(("DECLINE","Q1"),np.nan); decline_q5=phase_summary.get(("DECLINE","Q5"),np.nan)
    rise_q1=phase_summary.get(("RISE","Q1"),np.nan); rise_q5=phase_summary.get(("RISE","Q5"),np.nan)
    report=f"""# Phase 8 학군점수–가격 검증 보고서\n\n## 분석 범위와 품질\n- 가격 원천: 개별 실거래 `{len(trades):,}`건, 기간 {pd.to_datetime(trades.deal_date).min():%Y-%m}~{pd.to_datetime(trades.deal_date).max():%Y-%m}\n- Primary sample: 500세대 이상·HIGH 품질·최근 12개월 거래 존재 `{len(primary):,}`단지\n- 점수 coverage: {metadata['500plus_coverage']}; 미점수 단지 `{len(missing):,}`개\n- 84㎡ 그룹은 실제 80~90㎡, 59㎡ 그룹은 실제 55~65㎡ 거래만 사용했다.\n- 가격은 ㎡당 실거래가 중앙값이며, low_sample_flag는 기간 내 3건 미만이다.\n\n## 핵심 질문\n1. **Q1 부산 전체**: Pearson `{main.pearson:.3f}`, Spearman `{main.spearman:.3f}`로 {'양의' if main.spearman>0 else '음의'} 관계다.\n2. **Q2 같은 구군**: 구군 내 percentile Spearman `{within.spearman:.3f}`다.\n3. **Q3 같은 법정동**: 500세대 이상 단지가 3개 이상인 동의 demeaned Spearman `{dong.spearman:.3f}`다.\n4. **Q4 통제 회귀**: 법정동 FE Model 4의 계수 `{m4.coefficient:.5f}`, 군집 SE `{m4.standard_error:.5f}`, p-value `{m4.p_value:.4f}`, R² `{m4.r_squared:.3f}`다.\n5. **Q5 10점 차이**: 관측 특성과 법정동을 통제한 모형에서 `{m4.score_10point_association_pct:.2f}%`의 가격 차이와 연관된다. 인과효과가 아니다.\n6. **Q6 가격 방어력**: 80~90㎡ 부산 중앙가격이 전월보다 하락한 모든 달에서 Q1/Q5의 월간 중앙 수익률은 각각 `{decline_q1:.2%}`/`{decline_q5:.2%}`였다. 상승한 모든 달은 각각 `{rise_q1:.2%}`/`{rise_q5:.2%}`였다. 기간을 임의 선택하지 않았다.\n7. **Q7 구성요소**: 절대 Spearman이 가장 큰 항목은 `{strongest['group']}`이며 계수는 `{strongest.spearman:.3f}`다. 단일 구성요소 결과로 점수를 재조정하지 않았다.\n\n## 강건성 및 해석 한계\n- HIGH를 주 분석, HIGH+MEDIUM을 보조 분석으로 구분했다. BASE/QUALITY_FOCUSED/STABILITY_FOCUSED, 거래 1·3·5건, 1/99 winsorized 결과를 비교할 수 있게 산출했다.\n- 2026학년도 점수와 과거 가격의 분석은 현재 학군 구조와 과거 가격 패턴의 연관성이다. 당시 학군이 같았다는 뜻이 아니다.\n- 전세가율은 같은 기간·면적 범위의 전세 보증금 중앙값/매매가격 중앙값이다. 초등학교 거리는 직선거리다.\n- 수작업 미확정 11건은 `EXCLUDED_AMBIGUOUS_SCHOOL`로 보존하고 점수 입력에서 제외했다.\n\n## Phase 9 readiness\n판정: **{feature}**. 이 판정은 통계적 연관성과 통제 회귀의 방향을 기준으로 하며 인과성을 뜻하지 않는다. Phase 9는 시작하지 않았다.\n"""
    atomic_bytes(reports/"phase8_validation.md",report.encode("utf-8")); _write_visuals(metrics,correlations,quintiles,regressions,top,reports)
    return {"pytest_required":True,"primary_sample":len(primary),"unscored_500plus":len(missing),"pearson":main.pearson,"spearman":main.spearman,"model4_10point_pct":m4.score_10point_association_pct,"feature_status":feature,"panel_rows":len(panel)}
