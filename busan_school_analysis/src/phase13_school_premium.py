"""Phase 13: evidence-based school premium presentation for 500+ apartments."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .config import ROOT, atomic_bytes, write_csv, write_json
from .phase12_elementary_first import fit_clustered_ols, protected_hashes


def _figures(root: Path, recent: pd.DataFrame, phase13: pd.DataFrame, residual_e, residual_m, residual_em):
    folder=root/"reports/figures"; folder.mkdir(parents=True,exist_ok=True)
    try:
        import plotly.express as px
        base=recent.loc[residual_e.index,["apartment_id","elementary_demand_score","phase7_school_score"]].copy()
        base["residual_E"]=residual_e; base["residual_M"]=residual_m.reindex(base.index); base["residual_E_M"]=residual_em.reindex(base.index)
        apt=base.groupby("apartment_id",as_index=False).agg(elementary_demand_score=("elementary_demand_score","first"),phase7_school_score=("phase7_school_score","first"),
            residual_E=("residual_E","median"),residual_M=("residual_M","median"),residual_E_M=("residual_E_M","median"))
        px.scatter(apt,x="elementary_demand_score",y="residual_E",title="Elementary Demand와 Model E 잔차").write_html(folder/"phase12_elementary_vs_residual.html",include_plotlyjs="cdn")
        px.scatter(apt,x="phase7_school_score",y="residual_M",title="Phase 7 점수와 Model M 잔차").write_html(folder/"phase12_phase7_vs_residual.html",include_plotlyjs="cdn")
        errors=pd.DataFrame({"model":["MODEL_E","MODEL_M"],"mean_absolute_residual":[base.residual_E.abs().mean(),base.residual_M.abs().mean()]})
        px.bar(errors,x="model",y="mean_absolute_residual",title="Model E와 Model M 예측오차").write_html(folder/"phase12_e_vs_m_prediction_error.html",include_plotlyjs="cdn")
        errors2=pd.DataFrame({"model":["MODEL_E","MODEL_E_PLUS_M"],"mean_absolute_residual":[base.residual_E.abs().mean(),base.residual_E_M.abs().mean()]})
        px.bar(errors2,x="model",y="mean_absolute_residual",title="Model E와 E+M 예측오차").write_html(folder/"phase125_e_vs_em_prediction_error.html",include_plotlyjs="cdn")
        apt["E_decile"]=pd.qcut(apt.elementary_demand_score.rank(method="first"),10,labels=[f"D{i}" for i in range(1,11)])
        dec=apt.groupby("E_decile",observed=True).residual_E.mean().reset_index()
        px.bar(dec,x="E_decile",y="residual_E",title="Elementary Demand 분위별 평균 잔차 프리미엄").write_html(folder/"phase12_e_percentile_residual.html",include_plotlyjs="cdn")
        gp=phase13.groupby("has_guaranteed_assignment").agg(apartments=("apartment_id","nunique"),median_recent_price=("recent_price_per_m2","median"),mean_middle_addon_pct=("school_premium_addon_score","mean")).reset_index()
        px.bar(gp,x="has_guaranteed_assignment",y="mean_middle_addon_pct",title="확정 Middle 유무별 추정 add-on").write_html(folder/"phase125_guaranteed_residual_premium.html",include_plotlyjs="cdn")
        temporal=pd.read_csv(root/"reports/phase12_elementary_temporal_stability.csv",encoding="utf-8-sig")
        px.bar(temporal,x="period",y="coefficient",error_y="standard_error",title="기간별 Elementary Demand 계수").write_html(folder/"phase12_temporal_coefficient.html",include_plotlyjs="cdn")
    except Exception as exc:
        atomic_bytes(folder/"phase13_figure_error.txt",str(exc).encode("utf-8"))


def build_phase13(root=ROOT):
    root=Path(root); before=protected_hashes(root)
    phase12=json.loads((root/"data/processed/phase12_result.json").read_text(encoding="utf-8")); phase125=json.loads((root/"data/processed/phase125_result.json").read_text(encoding="utf-8"))
    scores=pd.read_parquet(root/"data/processed/busan_apartment_school_scores_2026.parquet"); scores=scores[scores.households.ge(500)].copy()
    apt_e=pd.read_parquet(root/"data/processed/phase95_apartment_school_features.parquet")[["internal_complex_id","elementary_demand_score","E_mean","phase9_coverage_status","mapped_elementary_school_ids"]]
    options=pd.read_parquet(root/"data/processed/phase125_apartment_middle_options.parquet")
    p=scores.merge(apt_e,on="internal_complex_id",how="left",validate="one_to_one").merge(options,left_on="internal_complex_id",right_on="apartment_id",how="left",validate="one_to_one")
    p["apartment_id"]=p.internal_complex_id; p["apartment_name"]=p.complex_name; p["household_count"]=p.households
    p["phase7_score"]=p.school_zone_score; p["elementary_name"]=p.elementary_school_names.map(lambda x:";".join(x) if isinstance(x,(list,np.ndarray)) else str(x))
    p["elementary_percentile"]=p.elementary_demand_score.rank(pct=True)*100
    demand=pd.read_parquet(root/"data/processed/phase9_elementary_demand_scores.parquet")[["elementary_school_id","demand_score_quality"]]
    detail=pd.read_parquet(root/"data/processed/busan_apartment_school_score_detail_2026.parquet")
    mapping=detail[detail.elementary_school_id.notna()&detail.eligible_for_school_score.fillna(False)].drop_duplicates(["internal_complex_id","elementary_school_id"]).merge(demand,on="elementary_school_id",how="left")
    quality_order={"LOW":0,"MEDIUM":1,"HIGH":2}; mapping["quality_order"]=mapping.demand_score_quality.map(quality_order)
    aq=mapping.groupby("internal_complex_id").quality_order.min().map({v:k for k,v in quality_order.items()}).rename("elementary_demand_quality")
    p=p.merge(aq,left_on="internal_complex_id",right_index=True,how="left")
    coeff=pd.read_csv(root/"reports/phase125_regression_coefficients.csv",encoding="utf-8-sig")
    lookup=coeff[coeff.model.eq("MODEL_E_PLUS_M")].set_index("variable").coefficient
    b_has=float(lookup.get("has_guaranteed_assignment",0)); b_g=float(lookup.get("guaranteed_middle_score_component",0))
    p["school_premium_core_score"]=p.elementary_demand_score
    guaranteed_effect=p.has_guaranteed_assignment.fillna(0)*b_has+p.guaranteed_middle_score_component.fillna(0)*b_g
    p["school_premium_addon_score"]=(np.exp(guaranteed_effect)-1)*100
    # Partial middle evidence is exposed as an add-on estimate but is not forced into the final 0-100 core ranking.
    p["final_school_premium_score"]=p.school_premium_core_score
    p["school_premium_confidence"]=np.select(
        [p.elementary_demand_score.notna()&p.phase9_coverage_status.eq("COMPLETE")&p.elementary_demand_quality.eq("HIGH")&p.all_elementaries_guaranteed.eq(1),
         p.elementary_demand_score.notna()&p.phase9_coverage_status.eq("COMPLETE")&p.eligible_middle_count.gt(0)],
        ["A","B"],default="C")
    p["data_quality_flag"]=np.select([p.elementary_demand_score.isna(),p.phase9_coverage_status.ne("COMPLETE"),p.eligible_middle_count.fillna(0).eq(0),p.middle_score_available_count.fillna(0).lt(p.eligible_middle_count.fillna(0))],
        ["ELEMENTARY_DEMAND_MISSING","ELEMENTARY_MAPPING_PARTIAL","MIDDLE_OPTION_MISSING","MIDDLE_SCORE_PARTIAL"],default="OK")
    # Current price is supplementary context, not an input to either score.
    tx=pd.read_parquet(root/"data/processed/phase12_elementary_first_dataset.parquet"); recent=tx[tx.is_phase10_recent_sample]
    prices=recent.groupby("apartment_id").price_per_sqm.median().rename("recent_price_per_m2"); p=p.merge(prices,left_on="apartment_id",right_index=True,how="left")
    p["unusual_flag"]=p.data_quality_flag.ne("OK")|(p.school_premium_core_score.ge(80)&p.school_premium_confidence.eq("C"))
    p["unusual_reason"]=np.where(p.data_quality_flag.ne("OK"),p.data_quality_flag,np.where(p.unusual_flag,"HIGH_CORE_LOW_CONFIDENCE",""))
    structure="ELEMENTARY_CORE_MODEL_FINAL" if phase125["verdict"]=="MIDDLE_INCREMENTAL_VALUE_NOT_SUPPORTED" else "ELEMENTARY_PLUS_MIDDLE_MODEL_FINAL" if phase125["verdict"]=="MIDDLE_INCREMENTAL_VALUE_SUPPORTED" else "ELEMENTARY_CORE_WITH_MIDDLE_ADDON_FINAL"
    cols=["apartment_id","apartment_name","household_count","sigungu","legal_dong","elementary_name","elementary_demand_score","elementary_percentile","phase7_score",
          "eligible_middle_count","eligible_middle_schools","eligible_middle_score_mean","eligible_middle_score_max","eligible_middle_score_min","eligible_middle_score_range",
          "has_guaranteed_assignment","guaranteed_middle_name","guaranteed_middle_score","guaranteed_middle_is_top_tier","school_premium_core_score","school_premium_addon_score",
          "final_school_premium_score","school_premium_confidence","data_quality_flag","recent_price_per_m2","unusual_flag","unusual_reason"]
    final=p[cols].sort_values(
        ["final_school_premium_score","apartment_id"],
        ascending=[False,True],na_position="last",kind="mergesort",
    ).reset_index(drop=True); write_csv(root/"data/processed/phase13_school_premium_index.csv",final)
    rankings=[]
    for label,col in [("ELEMENTARY_DEMAND","elementary_demand_score"),("CORE_SCHOOL_PREMIUM","school_premium_core_score"),("GUARANTEED_MIDDLE_PREMIUM","school_premium_addon_score"),("FINAL_SCHOOL_PREMIUM","final_school_premium_score")]:
        g=final.dropna(subset=[col]).nlargest(560,col).copy(); g["ranking_type"]=label; g["rank"]=range(1,len(g)+1); rankings.append(g)
    ranking=pd.concat(rankings,ignore_index=True); write_csv(root/"reports/phase13_school_premium_ranking.csv",ranking)
    audit=final.copy(); audit["audit_segment"]=np.select([audit.final_school_premium_score.rank(ascending=False,method="min").le(30),audit.final_school_premium_score.rank(ascending=True,method="min").le(30)],["TOP_30","BOTTOM_30"],default="ALL")
    write_csv(root/"reports/phase13_school_premium_audit.csv",audit)
    # Identical recent rows for residual visual comparisons.
    middle=recent.merge(options,on="apartment_id",how="left",validate="many_to_one").dropna(subset=["elementary_demand_score","phase7_school_score",*list(("eligible_middle_score_mean","eligible_middle_score_range","eligible_middle_count","has_guaranteed_assignment","guaranteed_middle_score_component"))])
    _,_,_,res_e=fit_clustered_ols(middle,["elementary_demand_score"],"MODEL_E")
    _,_,_,res_m=fit_clustered_ols(middle,["phase7_school_score"],"MODEL_M")
    _,_,_,res_em=fit_clustered_ols(middle,["elementary_demand_score","eligible_middle_score_mean","eligible_middle_score_range","eligible_middle_count","has_guaranteed_assignment","guaranteed_middle_score_component"],"MODEL_E_PLUS_M")
    _figures(root,middle,final,res_e,res_m,res_em)
    coverage={"apartments_500plus":len(final),"core_scored":int(final.school_premium_core_score.notna().sum()),"coverage_pct":float(final.school_premium_core_score.notna().mean()*100),
              "guaranteed_middle_apartments":int(final.has_guaranteed_assignment.fillna(0).eq(1).sum()),"confidence_counts":{str(k):int(v) for k,v in final.school_premium_confidence.value_counts().items()},
              "unusual_count":int(final.unusual_flag.sum()),"structure":structure}
    write_json(root/"data/processed/phase13_result.json",coverage)
    p12cmp=pd.read_csv(root/"reports/phase12_elementary_vs_phase7_model_comparison.csv",encoding="utf-8-sig").set_index("model")
    p12coef=pd.read_csv(root/"reports/phase12_regression_coefficients.csv",encoding="utf-8-sig")
    temporal=pd.read_csv(root/"reports/phase12_elementary_temporal_stability.csv",encoding="utf-8-sig")
    e=p12cmp.loc["MODEL_E"]; m=p12cmp.loc["MODEL_M"]; ecoef=p12coef[p12coef.model.eq("MODEL_E")].iloc[0]; mcoef=p12coef[p12coef.model.eq("MODEL_M")].iloc[0]
    rmse_gain=(m.rmse_log_oos-e.rmse_log_oos)/m.rmse_log_oos*100; mae_gain=(m.mae_log_oos-e.mae_log_oos)/m.mae_log_oos*100
    phase12_report=f"""# Phase 12 Elementary-First 검증

- 주 표본: 최근 12개월 공통표본 {int(e.n_transactions):,}건, {int(e.n_apartments):,}개 단지, {int(e.n_schools):,}개 초등학교
- E 10점 증가 연관: {ecoef.ten_point_price_pct:.2f}% (p={ecoef.p_value:.4g}, 95% CI 계수 {ecoef.ci95_low:.6f}~{ecoef.ci95_high:.6f})
- M 10점 증가 연관: {mcoef.ten_point_price_pct:.2f}% (p={mcoef.p_value:.4g})
- 법정동 내 Spearman: E {e.within_legal_dong_spearman:.3f}, M {m.within_legal_dong_spearman:.3f}
- 조정 R²: E {e.adjusted_r_squared:.4f}, M {m.adjusted_r_squared:.4f}
- 시간분할 OOS RMSE: E {e.rmse_log_oos:.5f}, M {m.rmse_log_oos:.5f}; E가 {rmse_gain:.2f}% 낮음
- 시간분할 OOS MAE: E {e.mae_log_oos:.5f}, M {m.mae_log_oos:.5f}; E가 {mae_gain:.2f}% 낮음
- 기간별 E 계수 방향: {phase12['temporal_directions']} ({', '.join(f'{r.period}={r.coefficient:.6f}' for r in temporal.itertuples())})
- 판정: **{phase12['verdict']}**

2020~2024 구간은 2026 Elementary Demand를 현재 구조의 proxy로 연결한 분석이다. 당시 알려진 정보나 인과효과로 해석하지 않는다.
"""
    atomic_bytes(root/"reports/phase12_elementary_first_validation.md",phase12_report.encode("utf-8"))
    p125cmp=pd.read_csv(root/"reports/phase125_nested_model_comparison.csv",encoding="utf-8-sig").set_index("model"); pe=p125cmp.loc["MODEL_E"]; pem=p125cmp.loc["MODEL_E_PLUS_M"]
    pc=pd.read_csv(root/"reports/phase125_regression_coefficients.csv",encoding="utf-8-sig"); gold=pd.read_csv(root/"reports/phase125_guaranteed_gold_validation.csv",encoding="utf-8-sig")
    eligible=pc[(pc.model.eq("MODEL_E_PLUS_M"))&pc.variable.eq("eligible_middle_score_mean")].iloc[0]; guaranteed=gold[(gold.model.eq("GOLD_E_G"))&gold.variable.eq("guaranteed_middle_score")].iloc[0]
    interaction=gold[(gold.model.eq("GOLD_E_G_INTERACTION"))&gold.variable.eq("E_G_interaction")].iloc[0]
    p125_rmse=(pe.rmse_log_oos-pem.rmse_log_oos)/pe.rmse_log_oos*100; p125_mae=(pe.mae_log_oos-pem.mae_log_oos)/pe.mae_log_oos*100
    phase125_report=f"""# Phase 12.5 Middle Incremental Value 검증

- Middle은 활성 후보집합의 개수·평균·범위·최선·최악 및 확정관계로 표현했다. `assignment_share`와 ELIGIBLE weight는 확률로 사용하지 않았다.
- 공통표본: {int(pem.n_transactions):,}건, {int(pem.n_apartments):,}개 단지
- Δ조정 R²: {pem.delta_adjusted_r2_vs_E:+.4f}; ΔAIC {pem.delta_aic_vs_E:+.2f}; ΔBIC {pem.delta_bic_vs_E:+.2f}
- OOS RMSE: {pe.rmse_log_oos:.5f} → {pem.rmse_log_oos:.5f} ({p125_rmse:.2f}% 개선)
- OOS MAE: {pe.mae_log_oos:.5f} → {pem.mae_log_oos:.5f} ({p125_mae:.2f}% 개선)
- 후보 중학교 평균점수 계수: {eligible.coefficient:.6f}, p={eligible.p_value:.4f}
- Gold 표본: {phase125['gold_apartments']}개 단지, {phase125['gold_transactions']:,}건; 확정 중학교 점수 계수 {guaranteed.coefficient:.6f}, p={guaranteed.p_value:.4f}
- Gold interaction 계수: {interaction.coefficient:.6f}, p={interaction.p_value:.4f}
- 판정: **{phase125['verdict']}**

적합도와 RMSE는 소폭 개선됐지만 MAE 사전기준을 충족하지 않았고, 후보 평균점수는 유의하지 않으며 Gold 표본 방향이 반대다. 현재 자료로는 추가 신호를 guaranteed 또는 eligible quality 한쪽에 안정적으로 귀속할 수 없다.
"""
    atomic_bytes(root/"reports/phase125_middle_incremental_validation.md",phase125_report.encode("utf-8"))
    top20=final.dropna(subset=["final_school_premium_score"]).head(20)[["apartment_name","household_count","sigungu","legal_dong","elementary_name","elementary_demand_score","eligible_middle_schools","guaranteed_middle_name","school_premium_confidence","recent_price_per_m2"]]
    phase13_report=f"""# Phase 13 School Premium Index 검증

## 결론

- Elementary Demand는 기존 Phase 7보다 법정동 내부 순위와 OOS 오차 모두에서 우수했다.
- Middle 옵션집합은 E 이후 RMSE를 {p125_rmse:.2f}% 개선했지만 Gold 결과와 개별계수가 안정적이지 않아 부분 지지로 판정했다.
- 최종 구조: **{structure}**
- 최종 0~100 순위는 E Core를 유지한다. 회귀계수 기반 guaranteed Middle 효과는 `school_premium_addon_score`에 분리했으며 최종점수에 강제 합산하지 않았다.

## Coverage와 신뢰도

- 500세대 이상: {len(final)}개
- Core 생성: {coverage['core_scored']}개 ({coverage['coverage_pct']:.2f}%)
- 확정 Middle 연결: {coverage['guaranteed_middle_apartments']}개
- Confidence A/B/C: {coverage['confidence_counts'].get('A',0)}/{coverage['confidence_counts'].get('B',0)}/{coverage['confidence_counts'].get('C',0)}
- 감사 플래그: {coverage['unusual_count']}개 — E 결측 {int(final.data_quality_flag.eq('ELEMENTARY_DEMAND_MISSING').sum())}, Middle 미연결 {int(final.data_quality_flag.eq('MIDDLE_OPTION_MISSING').sum())}, Middle 점수 일부 결측 {int(final.data_quality_flag.eq('MIDDLE_SCORE_PARTIAL').sum())}

## 상위 20개 단지

```csv
{top20.to_csv(index=False)}```

가격은 점수 산식에 사용하지 않았으며 최근 가격은 감사용 문맥 정보다. Confidence는 점수와 별도로 유지한다.
"""
    atomic_bytes(root/"reports/phase13_school_premium_validation.md",phase13_report.encode("utf-8"))
    if before!=protected_hashes(root): raise RuntimeError("Protected Phase 7-11 input changed during Phase 13")
    return coverage
