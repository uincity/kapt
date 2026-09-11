"""Phase 11.5: test migration mechanisms and Phase 7 assignment measurement error."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .config import ROOT, atomic_bytes, write_csv, write_parquet
from .phase11_middle_catchment_demand import build_phase11, phase11_input_hashes
from .phase9_elementary_demand import engineer_demand_features


OUTCOMES = ("adjusted_upper_grade_index", "adjusted_cohort_growth", "net_transfer_rate")
CONTROLS = ("log_total_students", "students_per_class", "student_growth_3y")


def _ols(frame: pd.DataFrame, outcome: str, predictor: str, district_fe=True, cluster=False) -> dict:
    cols = [outcome, predictor, *CONTROLS, "district"]
    if cluster: cols.append("demand_cluster_name")
    d = frame[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if len(d) < 12:
        return {"n": len(d), "coefficient": np.nan, "standard_error": np.nan, "t_stat": np.nan,
                "p_value": np.nan, "ci95_low": np.nan, "ci95_high": np.nan, "r_squared": np.nan}
    x = pd.DataFrame({"const": 1.0}, index=d.index)
    for col in (predictor, *CONTROLS): x[col] = pd.to_numeric(d[col], errors="coerce")
    if district_fe: x = pd.concat([x, pd.get_dummies(d.district, prefix="district", drop_first=True, dtype=float)], axis=1)
    if cluster: x = pd.concat([x, pd.get_dummies(d.demand_cluster_name, prefix="cluster", drop_first=True, dtype=float)], axis=1)
    X=x.to_numpy(float); y=d[outcome].to_numpy(float); inv=np.linalg.pinv(X.T@X); beta=inv@X.T@y; resid=y-X@beta
    n,k=X.shape; sigma2=(resid@resid)/max(n-k,1); se=np.sqrt(np.maximum(np.diag(inv*sigma2),0)); idx=x.columns.get_loc(predictor)
    t=beta[idx]/se[idx] if se[idx] else np.nan; p=2*stats.t.sf(abs(t),max(n-k,1)) if np.isfinite(t) else np.nan
    return {"n": n, "coefficient": beta[idx], "standard_error": se[idx], "t_stat": t, "p_value": p,
            "ci95_low": beta[idx]-1.96*se[idx], "ci95_high": beta[idx]+1.96*se[idx],
            "r_squared": 1-(resid@resid)/((y-y.mean())@(y-y.mean()))}


def _elementary_middle_features(root: Path):
    edges = pd.read_parquet(root/"data/processed/phase11_assignment_edges_audit.parquet")
    quality = pd.read_parquet(root/"data/processed/middle_school_scores.parquet")[["middle_school_id", "middle_school_score"]]
    active = edges[edges.used_in_broad_aggregate].drop_duplicates(["elementary_school_id", "middle_school_id"]).merge(quality, on="middle_school_id", how="left", validate="many_to_one")
    rows=[]
    for school_id,g in active.groupby("elementary_school_id"):
        record={"elementary_school_id":school_id,
                "elementary_school_name":g.elementary_school_name.iloc[0], "education_office":g.education_office.iloc[0],
                "candidate_middle_count":g.middle_school_id.nunique(),
                "confirmed_middle_count":g.loc[g.phase11_edge_class.eq("CONFIRMED"),"middle_school_id"].nunique(),
                "possible_middle_count":g.loc[g.phase11_edge_class.eq("POSSIBLE"),"middle_school_id"].nunique()}
        for label,mask in [("confirmed",g.phase11_edge_class.eq("CONFIRMED")),("broad",g.phase11_edge_class.isin(["CONFIRMED","POSSIBLE"]))]:
            values=g.loc[mask,"middle_school_score"].dropna()
            for stat in ("mean","median","max","min"):
                record[f"{label}_middle_quality_{stat}"]=getattr(values,stat)() if len(values) else np.nan
        rows.append(record)
    return pd.DataFrame(rows)


def _current_migration(root: Path, elementary_middle: pd.DataFrame):
    e=pd.read_parquet(root/"data/processed/phase9_elementary_demand_scores.parquet").copy()
    middle_join=elementary_middle.drop(columns=["elementary_school_name"],errors="ignore")
    e=e.rename(columns={"sigungu_requested":"district"}).merge(middle_join,on="elementary_school_id",how="left",validate="one_to_one")
    e["log_total_students"]=np.log(e.total_students.replace(0,np.nan))
    e["transfer_in_rate"]=e.transfer_in/e.transfer_report_students.replace(0,np.nan)
    e["assignment_uncertainty_index"]=e.possible_middle_count.fillna(0)+np.maximum(e.candidate_middle_count.fillna(0)-e.confirmed_middle_count.fillna(0),0)
    valid=e.assignment_uncertainty_index.notna()
    if valid.sum():
        ranks=e.loc[valid,"assignment_uncertainty_index"].rank(method="average",pct=True)
        e.loc[valid,"assignment_ambiguity_grade"]=pd.cut(ranks,[0,.33,.67,1],labels=["LOW","MEDIUM","HIGH"],include_lowest=True).astype(str)
    e["assignment_ambiguity_grade"]=e.assignment_ambiguity_grade.fillna("MISSING_RELATION")
    return e


def _migration_models(frame: pd.DataFrame):
    rows=[]
    schemes={"CONFIRMED":"confirmed_middle_quality_median","BROAD":"broad_middle_quality_median"}
    for scheme,predictor in schemes.items():
      for outcome in OUTCOMES:
       for model,cluster,exclude_growth in [("MAIN",False,False),("PLUS_CLUSTER",True,False),("EXCLUDE_GROWTH_CLUSTER",False,True)]:
        d=frame.copy()
        if exclude_growth: d=d[~d.demand_cluster_name.astype(str).str.contains("급성장",na=False)]
        result=_ols(d,outcome,predictor,True,cluster); result.update({"analysis":"CURRENT_2026","edge_scheme":scheme,"model":model,"outcome":outcome,"predictor":predictor})
        rows.append(result)
    return pd.DataFrame(rows)


def _regional_correlations(frame: pd.DataFrame):
    rows=[]
    for scope,groups in [("BUSAN",[("ALL",frame)]),("EDUCATION_OFFICE",list(frame.groupby("education_office"))),("DISTRICT",list(frame.groupby("district")))]:
      for name,g in groups:
       for predictor in ("confirmed_middle_quality_median","broad_middle_quality_median"):
        for outcome in OUTCOMES:
         d=g[[predictor,outcome]].dropna(); rows.append({"scope":scope,"group":name,"predictor":predictor,"outcome":outcome,"n":len(d),
             "pearson":d[predictor].corr(d[outcome]) if len(d)>1 else np.nan,"spearman":d[predictor].corr(d[outcome],method="spearman") if len(d)>1 else np.nan})
    return pd.DataFrame(rows)


def _district_sensitivity(frame: pd.DataFrame):
    districts=sorted(frame.district.dropna().astype(str).unique())
    scenarios=[("ALL",set()),*[("LEAVE_ONE_OUT_"+d,{d}) for d in districts]]
    for label,names in [("EXCLUDE_HAEUNDAE",{"해운대구"}),("EXCLUDE_SUYEONG",{"수영구"}),("EXCLUDE_NAM",{"남구"}),
                        ("EXCLUDE_HAEUNDAE_SUYEONG",{"해운대구","수영구"}),("EXCLUDE_HAEUNDAE_SUYEONG_NAM",{"해운대구","수영구","남구"})]: scenarios.append((label,names))
    rows=[]
    for scenario,excluded in scenarios:
      d=frame[~frame.district.isin(excluded)]
      for predictor in ("confirmed_middle_quality_median","broad_middle_quality_median"):
       for outcome in OUTCOMES:
        result=_ols(d,outcome,predictor,True,False); result.update({"scenario":scenario,"excluded_districts":";".join(sorted(excluded)),"predictor":predictor,"outcome":outcome}); rows.append(result)
    return pd.DataFrame(rows)


def _annual_features(root: Path, elementary_middle: pd.DataFrame):
    raw=pd.read_parquet(root/"data/processed/phase9_elementary_student_longitudinal.parquet")
    output=[]
    for year in (2024,2025,2026):
        history=raw[raw.data_year.le(year)].copy()
        current=history[history.data_year.eq(year)].copy()
        city=(current.grade5_students.sum()+current.grade6_students.sum())/(current.grade1_students.sum()+current.grade2_students.sum())
        current["adjusted_upper_grade_index"]=((current.grade5_students+current.grade6_students)/(current.grade1_students+current.grade2_students).replace(0,np.nan))/city
        if year>2024:
            engineered=engineer_demand_features(history,year,100)
            additions=engineered[["elementary_school_id","student_growth_3y","student_trend_slope","student_trend_slope_rate","cohort_growth","adjusted_cohort_growth"]]
            current=current.drop(columns=[c for c in additions if c!="elementary_school_id" and c in current]).merge(additions,on="elementary_school_id",how="left",validate="one_to_one")
        else:
            for c in ["student_growth_3y","student_trend_slope","student_trend_slope_rate","cohort_growth","adjusted_cohort_growth"]: current[c]=np.nan
        current=current.rename(columns={"sigungu_requested":"district"}).merge(elementary_middle,on="elementary_school_id",how="left",validate="one_to_one")
        current["log_total_students"]=np.log(current.total_students.replace(0,np.nan)); output.append(current)
    annual=pd.concat(output,ignore_index=True)
    rows=[]
    for year,g in annual.groupby("data_year"):
      for predictor in ("confirmed_middle_quality_median","broad_middle_quality_median"):
       for outcome in OUTCOMES:
        result=_ols(g,outcome,predictor,True,False); result.update({"analysis":"YEAR_MATCHED_STRUCTURAL","school_data_year":year,"middle_quality_reference_year":2025,"predictor":predictor,"outcome":outcome,"temporal_note":"Middle quality is a 2023-2025 aggregate; association is structural, not predictive or causal."}); rows.append(result)
    # Lag outcome is observed at t+1; middle quality stays the documented 2025 structural measure.
    lag=[]
    for outcome in ("net_transfer_rate","adjusted_upper_grade_index"):
        future=annual[["elementary_school_id","data_year",outcome]].copy(); future.data_year=future.data_year-1; future=future.rename(columns={outcome:"future_outcome"})
        joined=annual.merge(future,on=["elementary_school_id","data_year"],how="inner")
        for predictor in ("confirmed_middle_quality_median","broad_middle_quality_median"):
            d=joined[[predictor,"future_outcome"]].dropna(); lag.append({"analysis":"T_TO_T_PLUS_1_EXPLORATORY","school_data_year_t":int(joined.data_year.min()) if len(joined) else np.nan,"outcome":outcome,"predictor":predictor,"n":len(d),"pearson":d[predictor].corr(d.future_outcome),"spearman":d[predictor].corr(d.future_outcome,method="spearman"),"temporal_note":"Descriptive lag association; current middle-quality series is unavailable by historical year."})
    return annual,pd.DataFrame(rows),pd.DataFrame(lag)


def _within_dong_corr(d: pd.DataFrame, feature: str):
    valid=d.dropna(subset=[feature,"median_price_per_m2","sigungu","legal_dong"]).copy()
    eligible=valid.groupby(["sigungu","legal_dong"]).internal_complex_id.transform("nunique").ge(3); valid=valid[eligible]
    x=valid[feature]-valid.groupby(["sigungu","legal_dong"])[feature].transform("mean")
    y=valid.median_price_per_m2-valid.groupby(["sigungu","legal_dong"]).median_price_per_m2.transform("mean")
    return x.corr(y,method="spearman"),len(valid)


def _assignment_ambiguity_price(root: Path, elementary: pd.DataFrame):
    common=pd.read_parquet(root/"data/processed/phase10_common_sample.parquet")
    detail=pd.read_parquet(root/"data/processed/busan_apartment_school_score_detail_2026.parquet")
    mapping=detail[detail.elementary_school_id.notna()&detail.eligible_for_school_score.fillna(False)].drop_duplicates(["internal_complex_id","elementary_school_id"])
    em=elementary[["elementary_school_id","candidate_middle_count","confirmed_middle_count","possible_middle_count","assignment_uncertainty_index","assignment_ambiguity_grade"]]
    linked=mapping[["internal_complex_id","elementary_school_id"]].merge(em,on="elementary_school_id",how="left",validate="many_to_one")
    order={"LOW":0,"MEDIUM":1,"HIGH":2,"MISSING_RELATION":3}
    linked["ambiguity_order"]=linked.assignment_ambiguity_grade.map(order)
    agg=linked.groupby("internal_complex_id").agg(candidate_middle_count=("candidate_middle_count","max"),confirmed_middle_count=("confirmed_middle_count","min"),possible_middle_count=("possible_middle_count","max"),assignment_uncertainty_index=("assignment_uncertainty_index","max"),ambiguity_order=("ambiguity_order","max"),mapped_school_count=("elementary_school_id","nunique")).reset_index()
    agg["assignment_ambiguity_grade"]=agg.ambiguity_order.map({v:k for k,v in order.items()})
    d=common.merge(agg,on="internal_complex_id",how="left",validate="one_to_one")
    rows=[]
    groups=[("ALL",d)]+[(str(name),g) for name,g in d.groupby("assignment_ambiguity_grade")]
    d["candidate_middle_bin"]=pd.cut(d.candidate_middle_count,[-np.inf,1,3,5,np.inf],labels=["1","2-3","4-5","6+"])
    groups += [("CANDIDATE_"+str(name),g) for name,g in d.groupby("candidate_middle_bin",observed=True)]
    for name,g in groups:
      for feature in ("phase7_school_score","elementary_demand_score"):
       corr,n=_within_dong_corr(g,feature); rows.append({"ambiguity_group":name,"feature":feature,"apartment_count":g.internal_complex_id.nunique(),"transaction_count":int(g.trade_count.sum()),"within_legal_dong_spearman":corr,"within_n":n})
    strict=d[(d.confirmed_middle_count.ge(1))&d.possible_middle_count.eq(0)].copy()
    confirmed=[]
    for label,g in [("COMMON_ALL",d),("STRICT_CONFIRMED_ONLY",strict)]:
      for feature in ("phase7_school_score","elementary_demand_score"):
       corr,n=_within_dong_corr(g,feature); confirmed.append({"sample":label,"feature":feature,"apartment_count":g.internal_complex_id.nunique(),"transaction_count":int(g.trade_count.sum()),"within_legal_dong_spearman":corr,"within_n":n,"power_warning":len(g)<30})
    return d,pd.DataFrame(rows),pd.DataFrame(confirmed)


def _plots(root: Path, elementary: pd.DataFrame, ambiguity: pd.DataFrame):
    try:
        import plotly.express as px
        for outcome,name in [("adjusted_upper_grade_index","upper"),("adjusted_cohort_growth","cohort")]:
            px.scatter(elementary,x="broad_middle_quality_median",y=outcome,color="education_office",hover_name="elementary_school_name",title=f"중학교 품질 × {outcome}").write_html(root/f"reports/phase115_quality_vs_{name}.html",include_plotlyjs="cdn")
        p=ambiguity[ambiguity.feature.eq("phase7_school_score")]
        px.bar(p,x="ambiguity_group",y="within_legal_dong_spearman",title="배정 모호성별 Phase 7 법정동 내 가격순위 설명력").write_html(root/"reports/phase115_ambiguity_vs_phase7.html",include_plotlyjs="cdn")
    except Exception:
        pass


def _judgements(phase11_corr: pd.DataFrame, migration_corr: pd.DataFrame, models: pd.DataFrame, sensitivity: pd.DataFrame, ambiguity: pd.DataFrame, confirmed: pd.DataFrame):
    q=phase11_corr[(phase11_corr.scope.eq("BUSAN"))&(phase11_corr.catchment_feature.eq("broad_E_median"))]
    catchment_r=abs(q.spearman.iloc[0]) if len(q) else np.nan
    confirmed_n=phase11_corr[(phase11_corr.scope.eq("BUSAN"))&(phase11_corr.catchment_feature.eq("confirmed_E_median"))].n.max()
    # A broad-set correlation cannot earn STRONG while confirmed-edge validation has no power.
    catchment="STRONG" if catchment_r>=.30 and confirmed_n>=30 else "MEANINGFUL" if catchment_r>=.15 else "WEAK" if catchment_r>=.05 else "NO_SIGNAL"
    main=models[(models.edge_scheme.eq("BROAD"))&(models.model.eq("MAIN"))]
    strong_sig=int((main.p_value<.05).sum()); marginal_sig=int((main.p_value<.10).sum())
    migration="SUPPORTED" if strong_sig>=2 else "PARTIALLY_SUPPORTED" if strong_sig>=1 or marginal_sig>=1 else "NOT_SUPPORTED"
    all_m=ambiguity[(ambiguity.ambiguity_group.eq("ALL"))&(ambiguity.feature.eq("phase7_school_score"))].within_legal_dong_spearman
    low_m=ambiguity[(ambiguity.ambiguity_group.eq("LOW"))&(ambiguity.feature.eq("phase7_school_score"))].within_legal_dong_spearman
    strict=confirmed[(confirmed["sample"].eq("STRICT_CONFIRMED_ONLY"))&(confirmed.feature.eq("phase7_school_score"))]
    measurement="SUPPORTED" if len(low_m) and len(all_m) and low_m.iloc[0]>all_m.iloc[0]+.03 else "PARTIALLY_SUPPORTED" if len(strict) and strict.within_n.iloc[0]>=20 and strict.within_legal_dong_spearman.iloc[0]>all_m.iloc[0] else "NOT_SUPPORTED"
    return catchment,migration,measurement


def build_phase115(root=ROOT):
    root=Path(root)
    if not (root/"data/processed/phase11_middle_catchment_demand.parquet").exists(): build_phase11(root)
    before=phase11_input_hashes(root)
    elementary_middle=_elementary_middle_features(root)
    elementary=_current_migration(root,elementary_middle)
    models=_migration_models(elementary); regional=_regional_correlations(elementary); sensitivity=_district_sensitivity(elementary)
    annual,annual_models,lag=_annual_features(root,elementary_middle)
    apartment,ambiguity,confirmed=_assignment_ambiguity_price(root,elementary)
    write_parquet(root/"data/processed/phase115_elementary_migration_features.parquet",elementary)
    write_parquet(root/"data/processed/phase115_annual_migration_features.parquet",annual)
    write_csv(root/"reports/phase115_migration_analysis.csv",pd.concat([models,annual_models],ignore_index=True,sort=False))
    write_csv(root/"reports/phase115_migration_correlations.csv",regional)
    write_csv(root/"reports/phase115_district_sensitivity.csv",sensitivity)
    write_csv(root/"reports/phase115_temporal_lag_analysis.csv",lag)
    write_csv(root/"reports/phase115_assignment_ambiguity_vs_phase7.csv",ambiguity)
    write_csv(root/"reports/phase115_confirmed_only_validation.csv",confirmed)
    _plots(root,elementary,ambiguity)
    phase11_corr=pd.read_csv(root/"reports/phase11_quality_demand_correlations.csv",encoding="utf-8-sig")
    catchment,migration,measurement=_judgements(phase11_corr,regional,models,sensitivity,ambiguity,confirmed)
    middle=pd.read_parquet(root/"data/processed/phase11_middle_catchment_demand.parquet")
    matrix=pd.read_csv(root/"reports/phase11_middle_quality_demand_matrix.csv",encoding="utf-8-sig")
    broad=phase11_corr[(phase11_corr.scope.eq("BUSAN"))&(phase11_corr.catchment_feature.eq("broad_E_median"))].iloc[0]
    high=matrix[matrix.quality_demand_group.eq("HIGH_QUALITY_HIGH_DEMAND")]
    centum=middle[middle.middle_school_name.astype(str).str.contains("센텀",na=False)]
    centum_text=("```csv\n"+centum[["middle_school_name","middle_school_score","confirmed_E_median","broad_E_median","representative_basis","assignment_uncertainty_grade"]].to_csv(index=False)+"```" if len(centum) else "센텀중 ID/명칭 행을 찾지 못했다.")
    report=f"""# Phase 11 / 11.5 검증 보고서

## 데이터와 방법

- 배정관계 원행: 811건. 원래 상태·유형·override 필드를 보존했다.
- 분석 분류: 확정 {int((pd.read_parquet(root/'data/processed/phase11_assignment_edges_audit.parquet').phase11_edge_class=='CONFIRMED').sum())}건, 배정가능 {int((pd.read_parquet(root/'data/processed/phase11_assignment_edges_audit.parquet').phase11_edge_class=='POSSIBLE').sum())}건. 제외·모호 관계는 집계에서 사용하지 않았다.
- 배정확률을 생성하거나 `assignment_share`로 가중하지 않았다. 모든 통학권 지표는 고유 연결 초등학교 집합의 비가중 통계다.
- 대표값은 확정 연결 중앙값이며, 확정 연결이 없을 때만 `BROAD_MEDIAN_FALLBACK`을 명시한 광의 중앙값을 사용했다.
- 상위 25% 평균은 각 중학교의 연결 초등학교 집합 내부 75백분위 이상 E 값의 산술평균이다.

## 핵심 결과

- 중학교 {len(middle)}개 중 품질점수 관측은 {middle.middle_school_score.notna().sum()}개다.
- 중학교 품질과 광의 통학권 E 중앙값의 Pearson은 {broad.pearson:.3f}, Spearman은 {broad.spearman:.3f} (n={int(broad.n)})다.
- 품질·수요 모두 상위 25%인 중학교는 {len(high)}개다.
- 통학권 수요 신호: **{catchment}**
- 학생 이동 메커니즘: **{migration}**
- Phase 7 배정 측정오차 가설: **{measurement}**

## 센텀중 사례

{centum_text}

센텀초의 기존 확정배정 override는 원본 관계에서 그대로 유지했으며 결과에 맞춘 조정은 하지 않았다.

## 시간 해석 제한

초등 학생자료는 2024~2026년이다. 연도별 표는 해당 연도 학생자료만 사용했다. 중학교 품질은 실제 제공된 2023~2025 관측의 2025 기준 집계이므로 과거 시점 예측변수처럼 해석하지 않고 구조적·기술적 연관으로만 보고한다. 장기 추세나 인과효과를 주장하지 않는다.

## 중학교 품질자료 품질

- 기준연도: 2025, 실제 관측연도는 주로 2023~2025
- 점수 관측: {middle.middle_school_score.notna().sum()}개, 결측: {middle.middle_school_score.isna().sum()}개
- `sample_warning`: {middle.sample_warning.fillna(False).sum()}개
- 졸업자 합계 중앙값: {middle.graduates_total.median():.1f}, 가중 졸업자 중앙값: {middle.weighted_graduates.median():.1f}
- 진학성과 분모·선택계열 목적지 범위는 기존 Phase 7 중학교 품질 산출물의 정의를 그대로 사용했다.

## Phase 12 판단

Phase 12 통합점수는 생성하지 않았다. 통학권 수요가 `{catchment}`, 이동 메커니즘이 `{migration}`이므로 후속 설계에서는 지역 민감도와 확정관계 표본 부족을 먼저 반영해야 한다.
"""
    atomic_bytes(root/"reports/phase11_validation.md",report.encode("utf-8"))
    after=phase11_input_hashes(root)
    if before!=after: raise RuntimeError("An immutable Phase 7-10 input changed during Phase 11.5")
    return {"middle_schools":len(middle),"elementary_schools":len(elementary),"catchment_signal":catchment,"migration_mechanism":migration,"measurement_error":measurement,"high_quality_high_demand":len(high),"immutable_inputs_unchanged":True}
