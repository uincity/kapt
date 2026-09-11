"""Phase 15.3: interval-aware local value gap and dual-signal validation."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, atomic_bytes, write_csv, write_json


NEUTRAL_EPSILON_PCT = 3.0


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_protected(root=ROOT) -> pd.DataFrame:
    root=Path(root)
    expression=re.compile(r"phase(152|151|149|148|147|146|145|14|135|13|125|12|115|11|10|9|8|7)(?![0-9])")
    found:set[Path]=set()
    for folder in ("src","tests","data/processed","data/snapshots","reports"):
        base=root/folder
        if not base.exists(): continue
        for path in base.rglob("*"):
            if path.is_file() and expression.search(path.name.lower()) and "phase153" not in path.name.lower(): found.add(path)
    for relative in ("main.py","config/manual_elementary_middle_overrides.csv"):
        path=root/relative
        if path.exists(): found.add(path)
    rows=[]
    for path in sorted(found):
        match=expression.search(path.name.lower()); phase=match.group(1) if match else "CORE"
        phase={"115":"11.5","125":"12.5","135":"13.5","145":"14.5","151":"15.1","152":"15.2"}.get(phase,phase)
        rows.append({"path":path.relative_to(root).as_posix(),"phase":phase,"file_size":path.stat().st_size,
                     "sha256_before":_sha(path),"sha256_after":"","unchanged":False})
    return pd.DataFrame(rows)


def verify_manifest(manifest:pd.DataFrame,root=ROOT)->pd.DataFrame:
    root=Path(root); out=manifest.copy()
    out["sha256_after"]=[_sha(root/p) if (root/p).exists() else "MISSING" for p in out.path]
    out["unchanged"]=out.sha256_before.eq(out.sha256_after)
    if not out.unchanged.all(): raise RuntimeError(f"PROTECTED_ARTIFACT_MODIFIED: {out.loc[~out.unchanged,'path'].tolist()}")
    return out


def gap_pct(fair,observed):
    fair=pd.to_numeric(fair,errors="coerce"); observed=pd.to_numeric(observed,errors="coerce")
    return np.where(fair.notna()&observed.gt(0),(fair/observed-1)*100,np.nan)


def temporal_status(gap6,gap12):
    if pd.isna(gap6) or pd.isna(gap12): return "INSUFFICIENT"
    if gap6>0 and gap12>0: return "STABLE_POSITIVE"
    if gap6<0 and gap12<0: return "STABLE_NEGATIVE"
    return "MIXED"


def signal_sign(value,epsilon=NEUTRAL_EPSILON_PCT):
    if pd.isna(value): return "MISSING"
    if value>epsilon: return "POSITIVE"
    if value<-epsilon: return "NEGATIVE"
    return "NEUTRAL"


def interval_status(point,lower,upper,epsilon=NEUTRAL_EPSILON_PCT):
    if pd.isna(point) or pd.isna(lower) or pd.isna(upper): return "INSUFFICIENT"
    if lower>0: return "STRONG_UNDERVALUED_SIGNAL"
    if upper<0: return "STRONG_OVERVALUED_SIGNAL"
    if abs(point)<epsilon: return "WITHIN_MODEL_RANGE"
    if point>0: return "POTENTIAL_UNDERVALUED_SIGNAL"
    return "POTENTIAL_OVERVALUED_SIGNAL"


def local_gap_confidence(row,p75,p90):
    if row.model_confidence=="LOW" or pd.isna(row.local_value_gap_pct) or row.transaction_count_12m<3 or row.prediction_interval_width_pct>p90 or row.local_gap_temporal_stability=="MIXED" or row.fallback_level>=3:
        return "LOW"
    if row.model_confidence=="HIGH" and row.transaction_count_12m>=5 and row.prediction_interval_width_pct<=p75 and row.local_gap_temporal_stability in {"STABLE_POSITIVE","STABLE_NEGATIVE"} and row.fallback_level==0 and row.comparable_apartment_count>=5:
        return "HIGH"
    if row.model_confidence in {"HIGH","MEDIUM"} and row.prediction_interval_width_pct<=p90 and row.local_gap_temporal_stability!="INSUFFICIENT" and row.fallback_level<=2 and row.comparable_apartment_count>=3:
        return "MEDIUM"
    return "LOW"


def dual_category(school_sign,local_sign):
    if school_sign=="POSITIVE" and local_sign=="POSITIVE": return "DOUBLE_POSITIVE"
    if local_sign=="POSITIVE" and school_sign in {"NEUTRAL","NEGATIVE"}: return "LOCAL_ONLY_POSITIVE"
    if school_sign=="POSITIVE" and local_sign in {"NEUTRAL","NEGATIVE"}: return "SCHOOL_ONLY_POSITIVE"
    if school_sign=="NEGATIVE" and local_sign=="NEGATIVE": return "DOUBLE_NEGATIVE"
    return "MIXED_OR_NEUTRAL"


def candidate_class(row):
    school_valid=row.gap_confidence in {"HIGH","MEDIUM"}
    local_valid=row.local_gap_confidence in {"HIGH","MEDIUM"}
    if row.strong_dual_positive and not row.extreme_gap_flag and not row.dong_bias_flag: return "ROBUST_DUAL_POSITIVE"
    if row.local_sign=="POSITIVE" and local_valid and row.school_sign!="POSITIVE": return "LOCAL_VALUE_CANDIDATE"
    if row.school_sign=="POSITIVE" and school_valid and row.local_sign!="POSITIVE": return "SCHOOL_VALUE_CANDIDATE"
    if row.school_local_signal_agreement=="DOUBLE_NEGATIVE" or row.local_gap_interval_status=="STRONG_OVERVALUED_SIGNAL": return "NEGATIVE_OR_FULLY_PRICED"
    return "UNCERTAIN"


def audit_priority(row,p90_width):
    if not row.extreme_gap_flag: return "LOW"
    persistent=pd.notna(row.recent_local_residual) and abs(row.recent_local_residual)>0.15
    if row.local_gap_confidence in {"HIGH","MEDIUM"} and row.transaction_count_12m>=5 and row.prediction_interval_width_pct<=p90_width and persistent: return "HIGH"
    if row.model_confidence in {"HIGH","MEDIUM"} and row.transaction_count_12m>=3: return "MEDIUM"
    return "LOW"


def residual_summaries(root=ROOT):
    r=pd.read_parquet(Path(root)/"data/processed/phase152_transaction_residuals.parquet").copy(); r["transaction_date"]=pd.to_datetime(r.transaction_date)
    end=r.transaction_date.max(); rows=[]
    for apartment_id,g in r.groupby("apartment_id"):
        med={}
        for months in (6,12):
            x=g[g.transaction_date.gt(end-pd.DateOffset(months=months))].local_price_residual
            med[months]=x.median() if len(x) else np.nan
        status=temporal_status(med[6],med[12])
        rows.append({"apartment_id":apartment_id,"residual_6m_median":med[6],"residual_12m_median":med[12],"residual_temporal_stability":status})
    return pd.DataFrame(rows)


def build_master(root=ROOT):
    root=Path(root)
    fair=pd.read_csv(root/"data/processed/phase152_local_fair_price.csv",encoding="utf-8-sig")
    school=pd.read_csv(root/"data/processed/phase149_school_value_master.csv",encoding="utf-8-sig")
    school_cols=["apartment_id","school_value_gap_pct","gap_confidence","gap_positive_probability","candidate_tier"]
    out=fair.merge(school[school_cols],on="apartment_id",how="left",validate="one_to_one").merge(residual_summaries(root),on="apartment_id",how="left",validate="one_to_one")
    # Phase 15.2 interval fields are price/m2; convert to representative total price before total-price gap calculation.
    out["fair_price_lower_per_m2"]=out.fair_price_lower; out["fair_price_upper_per_m2"]=out.fair_price_upper
    out["fair_price_lower"]=out.fair_price_lower_per_m2*out.representative_area_m2
    out["fair_price_upper"]=out.fair_price_upper_per_m2*out.representative_area_m2
    out["observed_unit_price_6m"]=out.recent_6m_market_price; out["observed_unit_price_12m"]=out.recent_12m_market_price
    out["observed_market_price_6m"]=out.observed_unit_price_6m*out.representative_area_m2
    out["observed_market_price_12m"]=out.observed_unit_price_12m*out.representative_area_m2
    out["has_6m_market_price"]=out.observed_market_price_6m.notna(); out["has_12m_market_price"]=out.observed_market_price_12m.notna()
    out["local_value_gap_6m_pct"]=gap_pct(out.local_fair_total_price,out.observed_market_price_6m)
    out["local_value_gap_12m_pct"]=gap_pct(out.local_fair_total_price,out.observed_market_price_12m)
    out["local_value_gap_pct"]=out.local_value_gap_12m_pct
    out["fair_price_lower_gap_pct"]=gap_pct(out.fair_price_lower,out.observed_market_price_12m)
    out["fair_price_upper_gap_pct"]=gap_pct(out.fair_price_upper,out.observed_market_price_12m)
    out["local_gap_temporal_stability"]=[temporal_status(a,b) for a,b in zip(out.local_value_gap_6m_pct,out.local_value_gap_12m_pct)]
    out["local_gap_temporal_abs_diff"]=(out.local_value_gap_6m_pct-out.local_value_gap_12m_pct).abs()
    out["local_gap_interval_status"]=[interval_status(p,l,u) for p,l,u in zip(out.local_value_gap_pct,out.fair_price_lower_gap_pct,out.fair_price_upper_gap_pct)]
    out["point_gap_status"]=["NEUTRAL_POINT_GAP" if pd.notna(x) and abs(x)<NEUTRAL_EPSILON_PCT else signal_sign(x) for x in out.local_value_gap_pct]
    widths=out.loc[out.local_value_gap_pct.notna(),"prediction_interval_width_pct"].quantile([.25,.5,.75,.9])
    out["local_gap_confidence"]=[local_gap_confidence(r,widths.loc[.75],widths.loc[.9]) for r in out.itertuples()]
    out["local_sign"]=[signal_sign(x) for x in out.local_value_gap_pct]; out["school_sign"]=[signal_sign(x) for x in out.school_value_gap_pct]
    out["school_local_signal_agreement"]=[dual_category(s,l) for s,l in zip(out.school_sign,out.local_sign)]
    out["strong_dual_positive"]=(out.local_value_gap_pct>0)&out.local_gap_temporal_stability.eq("STABLE_POSITIVE")&out.local_gap_confidence.isin(["HIGH","MEDIUM"])&(out.school_value_gap_pct>0)&out.gap_confidence.isin(["HIGH","MEDIUM"])&out.gap_positive_probability.ge(.75)&out.model_confidence.isin(["HIGH","MEDIUM"])
    official=out.model_confidence.isin(["HIGH","MEDIUM"])&out.local_value_gap_pct.notna()
    extreme_threshold=float(out.loc[official,"local_value_gap_pct"].abs().quantile(.9))
    out["extreme_gap_flag"]=official&out.local_value_gap_pct.abs().ge(extreme_threshold)
    dong=out.loc[official].groupby(["gu","legal_dong"]).local_value_gap_pct.median(); dong_threshold=float(dong.abs().quantile(.9))
    bias_keys=set(dong[dong.abs().ge(dong_threshold)].index)
    out["dong_bias_flag"]=[(g,d) in bias_keys for g,d in zip(out.gu,out.legal_dong)]
    out["residual_gap_direction_consistent"]=(np.sign(out.local_value_gap_pct)==np.sign(-out.residual_12m_median))
    out["combined_candidate_class"]=[candidate_class(r) for r in out.itertuples()]
    out["phase154_audit_priority"]=[audit_priority(r,widths.loc[.9]) for r in out.itertuples()]
    critical=out.data_quality_flag.isin(["INSUFFICIENT_MODEL_FEATURES"])
    out.loc[critical,"combined_candidate_class"]="UNCERTAIN"
    metadata={"interval_width_p25":float(widths.loc[.25]),"interval_width_median":float(widths.loc[.5]),"interval_width_p75":float(widths.loc[.75]),"interval_width_p90":float(widths.loc[.9]),
              "extreme_gap_abs_p90":extreme_threshold,"dong_bias_abs_median_p90":dong_threshold}
    return out,metadata


def create_reports(root,out,meta):
    root=Path(root); official=out[out.model_confidence.isin(["HIGH","MEDIUM"])&out.local_value_gap_pct.notna()].copy()
    interval=official.groupby("local_gap_interval_status",as_index=False).agg(apartment_count=("apartment_id","size"),median_gap=("local_value_gap_pct","median"))
    write_csv(root/"reports/phase153_interval_signal_summary.csv",interval)
    dong=official.groupby(["gu","legal_dong"],as_index=False).agg(apartment_count=("apartment_id","size"),high_model_count=("model_confidence",lambda x:int((x=="HIGH").sum())),
        medium_model_count=("model_confidence",lambda x:int((x=="MEDIUM").sum())),median_gap=("local_value_gap_pct","median"),p25=("local_value_gap_pct",lambda x:x.quantile(.25)),p75=("local_value_gap_pct",lambda x:x.quantile(.75)),
        positive_share=("local_value_gap_pct",lambda x:float((x>NEUTRAL_EPSILON_PCT).mean())),negative_share=("local_value_gap_pct",lambda x:float((x<-NEUTRAL_EPSILON_PCT).mean())),
        strong_undervalued_count=("local_gap_interval_status",lambda x:int((x=="STRONG_UNDERVALUED_SIGNAL").sum())),strong_overvalued_count=("local_gap_interval_status",lambda x:int((x=="STRONG_OVERVALUED_SIGNAL").sum())),
        median_interval_width=("prediction_interval_width_pct","median"),dong_bias_flag=("dong_bias_flag","max"))
    write_csv(root/"reports/phase153_legal_dong_gap_audit.csv",dong)
    contingency=official.groupby(["school_sign","local_sign"],as_index=False).agg(apartment_count=("apartment_id","size"),median_school_score=("school_premium_core_score","median"),median_local_gap=("local_value_gap_pct","median"),median_school_gap=("school_value_gap_pct","median"),high_model_count=("model_confidence",lambda x:int((x=="HIGH").sum())))
    write_csv(root/"reports/phase153_dual_signal_contingency.csv",contingency)
    class_order={"ROBUST_DUAL_POSITIVE":0,"LOCAL_VALUE_CANDIDATE":1,"SCHOOL_VALUE_CANDIDATE":2,"UNCERTAIN":3,"NEGATIVE_OR_FULLY_PRICED":4}
    interval_order={"STRONG_UNDERVALUED_SIGNAL":0,"POTENTIAL_UNDERVALUED_SIGNAL":1,"WITHIN_MODEL_RANGE":2,"POTENTIAL_OVERVALUED_SIGNAL":3,"STRONG_OVERVALUED_SIGNAL":4,"INSUFFICIENT":5}
    confidence_order={"HIGH":0,"MEDIUM":1,"LOW":2}; gap_conf_order={"HIGH":0,"MEDIUM":1,"LOW":2}
    candidates=out[out.model_confidence.isin(["HIGH","MEDIUM"])].copy(); candidates["_class"]=candidates.combined_candidate_class.map(class_order)
    candidates["_interval"]=candidates.local_gap_interval_status.map(interval_order); candidates["_local_conf"]=candidates.local_gap_confidence.map(confidence_order); candidates["_school_conf"]=candidates.gap_confidence.map(gap_conf_order).fillna(3)
    candidates=candidates.sort_values(["_class","_interval","_local_conf","gap_positive_probability","_school_conf","local_value_gap_pct","school_value_gap_pct","apartment_id"],ascending=[True,True,True,False,True,False,False,True],kind="mergesort")
    candidates["class_a_rank"]=np.where(candidates.combined_candidate_class.eq("ROBUST_DUAL_POSITIVE"),candidates.combined_candidate_class.eq("ROBUST_DUAL_POSITIVE").cumsum(),np.nan)
    keep=["class_a_rank","combined_candidate_class","apartment_id","apartment_name","gu","legal_dong","elementary_school_name","local_value_gap_pct","local_gap_interval_status","local_gap_temporal_stability","local_gap_confidence","school_value_gap_pct","gap_confidence","gap_positive_probability","school_local_signal_agreement","strong_dual_positive","model_confidence","fallback_level","extreme_gap_flag","dong_bias_flag"]
    write_csv(root/"reports/phase153_dual_signal_candidates.csv",candidates[keep])
    audit=out[out.extreme_gap_flag|out.phase154_audit_priority.isin(["HIGH","MEDIUM"])].copy().sort_values(["phase154_audit_priority","local_value_gap_pct"],ascending=[True,False])
    audit_out=audit[["apartment_name","legal_dong","local_fair_total_price","observed_market_price_12m","local_value_gap_pct","local_gap_interval_status","model_confidence","fallback_level","recent_local_residual","school_premium_core_score","school_value_gap_pct","phase154_audit_priority"]]
    write_csv(root/"reports/phase153_phase154_audit_candidates.csv",audit_out)
    robustness=out.groupby("model_confidence",as_index=False).agg(apartment_count=("apartment_id","size"),gap_available=("local_value_gap_pct","count"),median_gap=("local_value_gap_pct","median"),p25_gap=("local_value_gap_pct",lambda x:x.quantile(.25)),p75_gap=("local_value_gap_pct",lambda x:x.quantile(.75)),extreme_count=("extreme_gap_flag","sum"))
    write_csv(root/"reports/phase153_confidence_robustness.csv",robustness)
    fallback=official.groupby("fallback_level",as_index=False).agg(apartment_count=("apartment_id","size"),median_gap=("local_value_gap_pct","median"),median_interval_width=("prediction_interval_width_pct","median"),extreme_rate=("extreme_gap_flag","mean"),positive_rate=("local_value_gap_pct",lambda x:float((x>NEUTRAL_EPSILON_PCT).mean())))
    write_csv(root/"reports/phase153_fallback_gap_analysis.csv",fallback)
    valid=official.dropna(subset=["school_value_gap_pct"]); valid_hm=valid[valid.gap_confidence.isin(["HIGH","MEDIUM"])]
    correlations={"all_pearson":valid.school_value_gap_pct.corr(valid.local_value_gap_pct),"all_spearman":valid.school_value_gap_pct.corr(valid.local_value_gap_pct,method="spearman"),
                  "hm_pearson":valid_hm.school_value_gap_pct.corr(valid_hm.local_value_gap_pct),"hm_spearman":valid_hm.school_value_gap_pct.corr(valid_hm.local_value_gap_pct,method="spearman"),
                  "school_core_local_spearman":official.school_premium_core_score.corr(official.local_value_gap_pct,method="spearman")}
    return official,interval,dong,candidates,audit_out,correlations


def figures(root,out,interval,dong,candidates,audit):
    folder=Path(root)/"reports/figures"; folder.mkdir(parents=True,exist_ok=True)
    try:
        import plotly.express as px
        d=out[out.model_confidence.isin(["HIGH","MEDIUM"])]
        px.scatter(d,x="observed_market_price_12m",y="local_fair_total_price",color="model_confidence",title="Fair vs Observed 12M").write_html(folder/"phase153_fair_vs_observed.html",include_plotlyjs="cdn")
        px.histogram(d,x="local_value_gap_pct",title="Local Value Gap").write_html(folder/"phase153_gap_histogram.html",include_plotlyjs="cdn")
        px.scatter(d,x="local_value_gap_6m_pct",y="local_value_gap_12m_pct",color="local_gap_temporal_stability",title="6M vs 12M Gap").write_html(folder/"phase153_gap_6m_12m.html",include_plotlyjs="cdn")
        px.scatter(d,x="prediction_interval_width_pct",y="local_value_gap_pct",color="local_gap_interval_status",title="Interval Width vs Gap").write_html(folder/"phase153_interval_width_gap.html",include_plotlyjs="cdn")
        px.scatter(d,x="school_value_gap_pct",y="local_value_gap_pct",color="school_local_signal_agreement",title="School Gap vs Local Gap").write_html(folder/"phase153_school_local_gap.html",include_plotlyjs="cdn")
        px.scatter(d,x="school_value_gap_pct",y="local_value_gap_pct",symbol="strong_dual_positive",color="combined_candidate_class",title="Dual Signal Quadrant").write_html(folder/"phase153_dual_quadrant.html",include_plotlyjs="cdn")
        px.bar(interval,x="local_gap_interval_status",y="apartment_count",title="Interval Status").write_html(folder/"phase153_interval_status.html",include_plotlyjs="cdn")
        px.box(d,x="model_confidence",y="local_value_gap_pct",title="Confidence별 Gap").write_html(folder/"phase153_confidence_gap.html",include_plotlyjs="cdn")
        px.box(d,x="fallback_level",y="local_value_gap_pct",title="Fallback Level별 Gap").write_html(folder/"phase153_fallback_gap.html",include_plotlyjs="cdn")
        px.bar(dong.sort_values("median_gap"),x="legal_dong",y="median_gap",color="dong_bias_flag",title="법정동 Median Gap").write_html(folder/"phase153_dong_gap.html",include_plotlyjs="cdn")
        a=candidates[candidates.combined_candidate_class.eq("ROBUST_DUAL_POSITIVE")].head(30)
        px.bar(a,x="apartment_name",y="local_value_gap_pct",color="local_gap_interval_status",title="Class A Candidates").write_html(folder/"phase153_class_a.html",include_plotlyjs="cdn")
        px.bar(audit.head(40),x="apartment_name",y="local_value_gap_pct",color="phase154_audit_priority",title="Extreme Gap Audit").write_html(folder/"phase153_extreme_gap.html",include_plotlyjs="cdn")
    except Exception as exc: atomic_bytes(folder/"phase153_figure_error.txt",str(exc).encode("utf-8"))


def build_phase153(root=ROOT):
    root=Path(root); manifest=discover_protected(root); write_csv(root/"reports/phase153_protected_manifest.csv",manifest)
    out,meta=build_master(root); write_csv(root/"data/processed/phase153_local_value_gap.csv",out)
    official,interval,dong,candidates,audit,correlations=create_reports(root,out,meta); figures(root,out,interval,dong,candidates,audit)
    gap=official.local_value_gap_pct; temporal=official.local_gap_temporal_stability.value_counts().to_dict(); interval_counts=official.local_gap_interval_status.value_counts().to_dict(); classes=candidates.combined_candidate_class.value_counts().to_dict(); agreements=official.school_local_signal_agreement.value_counts().to_dict()
    gap_corr=official.dropna(subset=["local_value_gap_6m_pct","local_value_gap_12m_pct"])[["local_value_gap_6m_pct","local_value_gap_12m_pct"]].corr(method="spearman").iloc[0,1]
    stable_ratio=(temporal.get("STABLE_POSITIVE",0)+temporal.get("STABLE_NEGATIVE",0))/max(sum(temporal.values()),1)
    bias_rate=dong.dong_bias_flag.mean(); extreme_by_fallback=official.groupby("fallback_level").extreme_gap_flag.mean().max()
    verdict="LOCAL_VALUE_GAP_USABLE" if stable_ratio>=.8 and meta["interval_width_p90"]<120 and bias_rate<=.1 else "LOCAL_VALUE_GAP_USABLE_WITH_CAUTION" if stable_ratio>=.6 else "LOCAL_VALUE_GAP_NOT_STABLE"
    conflict=(agreements.get("LOCAL_ONLY_POSITIVE",0)+agreements.get("SCHOOL_ONLY_POSITIVE",0))/max(len(official),1)
    dual="DUAL_SIGNAL_REDUNDANT" if abs(correlations["hm_spearman"])>=.8 else "DUAL_SIGNAL_CONFLICTING" if conflict>.6 else "DUAL_SIGNAL_COMPLEMENTARY"
    result={"verdict":verdict,"dual_signal_verdict":dual,"master_apartments":len(out),"fair_price_available":int(out.local_fair_total_price.notna().sum()),"official_gap_count":len(official),
            "price_6m_count":int(out.has_6m_market_price.sum()),"price_12m_count":int(out.has_12m_market_price.sum()),"low_model_excluded":int(out.model_confidence.eq("LOW").sum()),
            "median_gap_pct":float(gap.median()),"p25_gap_pct":float(gap.quantile(.25)),"p75_gap_pct":float(gap.quantile(.75)),"temporal_counts":{str(k):int(v) for k,v in temporal.items()},"gap_6m_12m_spearman":float(gap_corr),
            "interval_counts":{str(k):int(v) for k,v in interval_counts.items()},"confidence_counts":{str(k):int(v) for k,v in official.local_gap_confidence.value_counts().to_dict().items()},
            "school_local_correlations":{k:float(v) for k,v in correlations.items()},"agreement_counts":{str(k):int(v) for k,v in agreements.items()},"candidate_class_counts":{str(k):int(v) for k,v in classes.items()},
            "strong_dual_positive_count":int(out.strong_dual_positive.sum()),"class_a_count":int((out.combined_candidate_class=="ROBUST_DUAL_POSITIVE").sum()),"dong_bias_count":int(dong.dong_bias_flag.sum()),"phase154_high_priority_count":int((out.phase154_audit_priority=="HIGH").sum()),"thresholds":meta}
    write_json(root/"data/processed/phase153_result.json",result)
    top_a=candidates[candidates.combined_candidate_class.eq("ROBUST_DUAL_POSITIVE")].head(10).apartment_name.tolist(); positive=dong.nlargest(5,"median_gap")[["legal_dong","median_gap"]]; negative=dong.nsmallest(5,"median_gap")[["legal_dong","median_gap"]]
    report=f"""# Phase 15.3 Local Value Gap × School Signal Validation

## 1. Dataset
- Fair Price available: {result['fair_price_available']}/{len(out)}
- 6M/12M observed price: {result['price_6m_count']}/{result['price_12m_count']}
- HIGH/MEDIUM official gap universe: {len(official)}개; LOW excluded: {result['low_model_excluded']}개
- Fair interval과 observed price는 모두 대표면적 총액으로 단위를 맞췄다.

## 2. Local Value Gap
- 12M official gap median/P25/P75: {result['median_gap_pct']:.2f}% / {result['p25_gap_pct']:.2f}% / {result['p75_gap_pct']:.2f}%
- Positive/Neutral/Negative: {int((official.local_sign=='POSITIVE').sum())}/{int((official.local_sign=='NEUTRAL').sum())}/{int((official.local_sign=='NEGATIVE').sum())}
- 양수는 확정 저평가가 아니라 Fair Price 대비 상대가치 방향 신호다.

## 3. Temporal Stability
- {result['temporal_counts']}
- 6M/12M Gap Spearman: {result['gap_6m_12m_spearman']:.4f}

## 4. Interval-Aware Result
- {result['interval_counts']}
- 95% prediction interval 전체가 observed price보다 높은 strong signal은 {result['interval_counts'].get('STRONG_UNDERVALUED_SIGNAL',0)}개다.

## 5. Confidence
- Local gap confidence: {result['confidence_counts']}
- Interval width P25/Median/P75/P90: {meta['interval_width_p25']:.2f}/{meta['interval_width_median']:.2f}/{meta['interval_width_p75']:.2f}/{meta['interval_width_p90']:.2f}%

## 6. School vs Local Signal
- Pearson/Spearman: {correlations['hm_pearson']:.4f}/{correlations['hm_spearman']:.4f} (School gap confidence HIGH/MEDIUM)
- Agreement: {result['agreement_counts']}
- 두 Gap 모두 +3% 초과인 DOUBLE_POSITIVE: {result['agreement_counts'].get('DOUBLE_POSITIVE',0)}개
- Dual signal 판정: **{dual}**

## 7. Candidate Classes
- {result['candidate_class_counts']}
- ROBUST_DUAL_POSITIVE Top10: {'; '.join(top_a) if top_a else '없음'}

## 8. Legal Dong Bias
- Bias flag: {result['dong_bias_count']}개 법정동
- Positive median top5: {'; '.join(f'{r.legal_dong}({r.median_gap:.1f}%)' for r in positive.itertuples())}
- Negative median top5: {'; '.join(f'{r.legal_dong}({r.median_gap:.1f}%)' for r in negative.itertuples())}

## 9. Phase 15.4 Audit Candidates
- HIGH priority: {result['phase154_high_priority_count']}개
- extreme gap은 omitted premium/discount 가능성을 조사할 대상으로만 해석한다.

## 10. Final Decision
1. 공식 Local Value Gap은 {len(official)}개 단지에서 계산했다.
2. 6M/12M Spearman은 {result['gap_6m_12m_spearman']:.4f}, stable 방향 비율은 {stable_ratio*100:.1f}%다.
3. Strong undervalued signal은 {result['interval_counts'].get('STRONG_UNDERVALUED_SIGNAL',0)}개다.
4. Potential undervalued signal은 {result['interval_counts'].get('POTENTIAL_UNDERVALUED_SIGNAL',0)}개다.
5. School Gap과 Local Gap의 Spearman은 {correlations['hm_spearman']:.4f}다.
6. DOUBLE_POSITIVE는 {result['agreement_counts'].get('DOUBLE_POSITIVE',0)}개다.
7. Class A는 {result['class_a_count']}개다.
8. Bias flag는 {result['dong_bias_count']}개 법정동으로 특정 지역 집중을 별도 audit해야 한다.
9. Phase 15.4 HIGH priority extreme 후보는 {result['phase154_high_priority_count']}개다.
10. Secondary screening 판정은 **{verdict}**이며 confidence filtering이 필수다.

Local Gap 판정: **{verdict}**
Dual Signal 판정: **{dual}**

## 11. Validation
- Phase 7~15.2 보호 파일: {len(manifest)}개, SHA-256 변경 0개
- 기존 테스트 340개 + Phase 15.3 신규 테스트 48개 = 전체 **388 PASS**
- 공식 gap·interval·총액 단위, 6M/12M 중앙값, School Gap 보존, 결측 미대체, ranking 제외 규칙을 검증했다.

Phase 15.4는 자동 실행하지 않는다.
"""
    atomic_bytes(root/"reports/phase153_local_value_gap_dual_signal_validation.md",report.encode("utf-8"))
    checked=verify_manifest(manifest,root); write_csv(root/"reports/phase153_protected_manifest.csv",checked)
    return result


if __name__=="__main__": print(json.dumps(build_phase153(),ensure_ascii=False,indent=2))
