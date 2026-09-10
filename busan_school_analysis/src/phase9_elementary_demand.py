"""Phase 9 elementary demand collection and scoring, independent of Phase 7/8."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))
from sklearn.cluster import KMeans
from sklearn.mixture import GaussianMixture
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from .config import ROOT, api_key, atomic_bytes, now, write_csv, write_json, write_parquet

ENDPOINT = "https://www.schoolinfo.go.kr/openApi.do"
PARSER_VERSION = "phase9-schoolinfo-1.0"
COMMON = ["SCHUL_CODE", "SCHUL_NM", "SCHUL_KND_SC_CODE", "ADRCD_CD", "ADRCD_NM",
          "JU_ORG_CODE", "JU_ORG_NM", "PBAN_EXCP_YN", "BNHH_YN"]
GRADE_FIELDS = [*[f"COL_S{i}" for i in range(1, 9)], *[f"COL_C{i}" for i in range(1, 9)],
                "COL_S_SUM", "COL_C_SUM", "COL_SUM"]
TRANSFER_FIELDS = [*[f"COL_2{i}1" for i in range(1, 7)], *[f"COL_2{i}2" for i in range(1, 7)],
                   "MVIN_SUM", "MVT_SUM", "STDNT_SUM"]


def _download(session, params, timeout=30, retries=3):
    for attempt in range(retries + 1):
        try:
            response = session.get(ENDPOINT, params=params, timeout=timeout, allow_redirects=False)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < retries: time.sleep(.5 * 2 ** attempt); continue
            if response.status_code != 200: raise ValueError(f"Schoolinfo HTTP {response.status_code}")
            return response.content
        except requests.RequestException:
            if attempt >= retries: raise ValueError("Schoolinfo connection failed") from None
            time.sleep(.5 * 2 ** attempt)
    raise ValueError("Schoolinfo retry limit reached")


def _validate_payload(content, api_type, district_code):
    payload=json.loads(content)
    if payload.get("resultCode") != "success" or not isinstance(payload.get("list"),list):
        raise ValueError("Schoolinfo result or schema invalid")
    rows=payload["list"]; required=set(COMMON + (GRADE_FIELDS if api_type=="09" else TRANSFER_FIELDS))
    if rows and not required.issubset(rows[0]): raise ValueError("Schoolinfo required fields missing")
    for row in rows:
        if str(row.get("SCHUL_KND_SC_CODE")) != "02" or not str(row.get("ADRCD_CD","")).startswith(district_code):
            raise ValueError("Schoolinfo scope mismatch")
    ids=[row["SCHUL_CODE"] for row in rows]
    if any(not x for x in ids) or len(ids)!=len(set(ids)): raise ValueError("Schoolinfo school ID invalid or duplicated")
    return rows


def collect_phase9_schoolinfo(years=(2024,2025,2026), *, force=False, root=ROOT, session=None):
    root=Path(root); cfg=yaml.safe_load((root/"config/phase9_elementary_demand.yaml").read_text(encoding="utf-8"))
    allowed=set(cfg["years"]); years=tuple(int(y) for y in years)
    if not set(years).issubset(allowed): raise ValueError(f"Phase 9 공식 수집 가능 연도는 {sorted(allowed)}입니다.")
    regions=pd.read_csv(root/"config/schoolinfo_codes.csv",dtype=str)
    if len(regions)!=16 or regions.sgg_code.nunique()!=16: raise ValueError("부산 16개 구·군 코드가 필요합니다.")
    key=api_key("SCHOOLINFO_API_KEY",root)
    if not key: raise ValueError("SCHOOLINFO_API_KEY가 설정되지 않았습니다.")
    session=session or requests.Session(); statuses=[]
    for year in years:
      for region in regions.to_dict("records"):
       for label,api_type in cfg["api_types"].items():
        path=root/f"data/raw/phase9_schoolinfo/{year}/{region['sgg_code']}_{api_type}.json"; meta_path=path.with_suffix(".meta.json")
        reused=path.exists() and meta_path.exists() and not force
        status={"data_year":year,"sigungu":region["sigungu"],"sgg_code":region["sgg_code"],"api_type":api_type,"dataset":label,"status":"failed","rows":0,"reused":reused,"reason":""}
        try:
          if reused:
            content=path.read_bytes(); meta=json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("sha256")!=hashlib.sha256(content).hexdigest() or meta.get("data_year")!=year or meta.get("api_type")!=api_type: raise ValueError("cache provenance mismatch")
          else:
            params={"apiKey":key,"apiType":api_type,"sidoCode":"26","sggCode":region["sgg_code"],"schulKndCode":"02","pbanYr":str(year)}
            content=_download(session,params)
            if key.encode() in content: raise ValueError("response echoed credential")
            _validate_payload(content,api_type,region["sgg_code"])
            if path.exists():
              digest=hashlib.sha256(path.read_bytes()).hexdigest()[:16]; atomic_bytes(path.parent/"history"/f"{path.stem}_{digest}.json",path.read_bytes())
              if meta_path.exists(): atomic_bytes(path.parent/"history"/f"{path.stem}_{digest}.meta.json",meta_path.read_bytes())
            atomic_bytes(path,content); meta={"data_year":year,"api_type":api_type,"collected_at":now(),"sha256":hashlib.sha256(content).hexdigest(),"source_url":ENDPOINT,"params":{"apiType":api_type,"sidoCode":"26","sggCode":region["sgg_code"],"schulKndCode":"02","pbanYr":str(year)}}; write_json(meta_path,meta); time.sleep(.1)
          rows=_validate_payload(content,api_type,region["sgg_code"]); status.update(status="ok",rows=len(rows))
        except (ValueError,KeyError,TypeError,json.JSONDecodeError): status["reason"]="request_or_schema_or_cache_validation_failed"
        statuses.append(status)
    report=pd.DataFrame(statuses); write_csv(root/"reports/phase9_collection_status.csv",report)
    if report.status.ne("ok").any(): raise ValueError(f"Phase 9 학교알리미 {report.status.ne('ok').sum()}/{len(report)} 배치 실패; 기존 산출물은 보존했습니다.")
    longitudinal=build_longitudinal_from_raw(years,root)
    write_parquet(root/"data/processed/phase9_elementary_student_longitudinal.parquet",longitudinal)
    return {"batches":len(report),"years":list(years),"school_year_rows":len(longitudinal),"schools":int(longitudinal.elementary_school_id.nunique())}


def _numeric(frame, fields):
    for col in fields: frame[col]=pd.to_numeric(frame.get(col),errors="coerce")
    return frame


def build_longitudinal_from_raw(years, root=ROOT):
    root=Path(root); regions=pd.read_csv(root/"config/schoolinfo_codes.csv",dtype=str); outputs=[]
    for year in years:
      grades=[]; transfers=[]
      for region in regions.to_dict("records"):
        for api_type,target in [("09",grades),("10",transfers)]:
          path=root/f"data/raw/phase9_schoolinfo/{year}/{region['sgg_code']}_{api_type}.json"; rows=json.loads(path.read_text(encoding="utf-8"))["list"]
          f=pd.DataFrame(rows); f["sigungu_requested"]=region["sigungu"]
          f["source_document"]=path.relative_to(root).as_posix()
          f["source_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
          target.append(f)
      g=pd.concat(grades,ignore_index=True); t=pd.concat(transfers,ignore_index=True)
      g=_numeric(g,GRADE_FIELDS); t=_numeric(t,TRANSFER_FIELDS)
      g=g[COMMON+GRADE_FIELDS+["sigungu_requested","source_document","source_sha256"]].rename(columns={"SCHUL_CODE":"elementary_school_id","SCHUL_NM":"elementary_school_name","COL_S_SUM":"total_students","COL_C_SUM":"total_classes","COL_SUM":"students_per_class","COL_S7":"special_students","COL_S8":"itinerant_students","COL_C7":"special_classes","COL_C8":"itinerant_classes","source_document":"grade_source_document","source_sha256":"grade_source_sha256",**{f"COL_S{i}":f"grade{i}_students" for i in range(1,7)},**{f"COL_C{i}":f"grade{i}_classes" for i in range(1,7)}})
      t=t[["SCHUL_CODE",*TRANSFER_FIELDS,"source_document","source_sha256"]].rename(columns={"SCHUL_CODE":"elementary_school_id","MVIN_SUM":"transfer_in","MVT_SUM":"transfer_out","STDNT_SUM":"transfer_report_students","source_document":"transfer_source_document","source_sha256":"transfer_source_sha256",**{f"COL_2{i}1":f"grade{i}_transfer_in" for i in range(1,7)},**{f"COL_2{i}2":f"grade{i}_transfer_out" for i in range(1,7)}})
      d=g.merge(t,on="elementary_school_id",how="outer",validate="one_to_one"); d["data_year"]=year; d["source_name"]="학교알리미 Open API 09·10"; d["parser_version"]=PARSER_VERSION
      d["grade_student_sum"]=d[[f"grade{i}_students" for i in range(1,7)]].sum(axis=1,min_count=6); d["non_regular_students"]=d[["special_students","itinerant_students"]].sum(axis=1,min_count=1)
      d["student_sum_difference"]=d.total_students-d.grade_student_sum
      d["student_reconciliation_difference"]=d.total_students-d.grade_student_sum-d.non_regular_students
      d["grade_transfer_in_sum"]=d[[f"grade{i}_transfer_in" for i in range(1,7)]].sum(axis=1,min_count=6); d["grade_transfer_out_sum"]=d[[f"grade{i}_transfer_out" for i in range(1,7)]].sum(axis=1,min_count=6)
      d["transfer_in_difference"]=d.transfer_in-d.grade_transfer_in_sum; d["transfer_out_difference"]=d.transfer_out-d.grade_transfer_out_sum
      d["net_transfer_rate"]=(d.transfer_in-d.transfer_out)/d.transfer_report_students.replace(0,np.nan)
      outputs.append(d)
    out=pd.concat(outputs,ignore_index=True)
    if out.duplicated(["elementary_school_id","data_year"]).any(): raise ValueError("Phase 9 학교×연도 중복")
    return out.sort_values(["elementary_school_id","data_year"]).reset_index(drop=True)


def _safe_change(current,previous):
    return current/previous.replace(0,np.nan)-1


def engineer_demand_features(longitudinal: pd.DataFrame, latest_year=2026, shrinkage_k=100):
    d=longitudinal.copy()
    if "net_transfer_rate" not in d:
        d["net_transfer_rate"]=(d.transfer_in-d.transfer_out)/d.transfer_report_students.replace(0,np.nan)
    years=sorted(d.data_year.unique()); latest=d[d.data_year.eq(latest_year)].copy()
    if len(years)<2: raise ValueError("Elementary Demand에는 최소 2개 연도가 필요합니다.")
    city_upper=latest[["grade5_students","grade6_students"]].sum().sum()/latest[["grade1_students","grade2_students"]].sum().sum()
    latest["upper_lower_ratio"]=(latest.grade5_students+latest.grade6_students)/(latest.grade1_students+latest.grade2_students).replace(0,np.nan)
    latest["adjusted_upper_grade_index"]=latest.upper_lower_ratio/city_upper
    records=[]
    for school_id,g in d.groupby("elementary_school_id"):
      g=g.sort_values("data_year"); first=g.iloc[0]; last=g.iloc[-1]
      slope=np.polyfit(g.data_year,g.total_students,1)[0] if g.total_students.notna().sum()>=2 else np.nan
      transitions=[]; adjusted=[]
      by_year=g.set_index("data_year")
      for y in years[1:]:
       if y-1 not in by_year.index or y not in by_year.index: continue
       prev_all=d[d.data_year.eq(y-1)]; curr_all=d[d.data_year.eq(y)]
       for grade in range(2,7):
        prev=by_year.at[y-1,f"grade{grade-1}_students"]; curr=by_year.at[y,f"grade{grade}_students"]
        if pd.isna(prev) or prev<=0 or pd.isna(curr): continue
        change=curr/prev-1; city=curr_all[f"grade{grade}_students"].sum()/prev_all[f"grade{grade-1}_students"].sum()-1
        transitions.append(change); adjusted.append(change-city)
      records.append({"elementary_school_id":school_id,"observed_years":g.data_year.nunique(),"first_year":int(g.data_year.min()),"latest_year":int(g.data_year.max()),
       "student_growth_3y":last.total_students/first.total_students-1 if first.total_students else np.nan,"student_trend_slope":slope,"student_trend_slope_rate":slope/g.total_students.mean() if g.total_students.mean() else np.nan,
       "cohort_growth":np.mean(transitions) if transitions else np.nan,"adjusted_cohort_growth":np.mean(adjusted) if adjusted else np.nan})
    features=latest.merge(pd.DataFrame(records),on="elementary_school_id",how="left",validate="one_to_one")
    city_net=(latest.transfer_in.sum()-latest.transfer_out.sum())/latest.transfer_report_students.sum(); reliability=features.total_students/(features.total_students+shrinkage_k)
    features["demand_reliability"]=reliability
    for col,neutral in [("net_transfer_rate",city_net),("student_growth_3y",d.groupby("data_year").total_students.sum().iloc[-1]/d.groupby("data_year").total_students.sum().iloc[0]-1),("student_trend_slope_rate",0),("adjusted_upper_grade_index",1),("adjusted_cohort_growth",0)]:
      features[f"shrunk_{col}"]=neutral+reliability*(features[col]-neutral)
    features["longitudinal_complete"]=features.observed_years.eq(len(years))
    return features


def _percentile(series, limits=(.01,.99)):
    valid=series.dropna(); out=pd.Series(np.nan,index=series.index,dtype=float)
    if valid.empty: return out
    clipped=series.clip(valid.quantile(limits[0]),valid.quantile(limits[1])); out.loc[clipped.notna()]=clipped.dropna().rank(pct=True,method="average")*100; return out


def score_elementary_demand(features: pd.DataFrame, config: dict):
    out=features.copy(); limits=tuple(config["winsor_limits"])
    components={
      "size":["total_students","students_per_class"],
      "mobility":["shrunk_net_transfer_rate"],
      "growth":["shrunk_student_growth_3y","shrunk_student_trend_slope_rate"],
      "upper_cohort":["shrunk_adjusted_upper_grade_index","shrunk_adjusted_cohort_growth"]}
    for theme,cols in components.items():
      values=[]
      for col in cols: out[f"pct_{col}"]=_percentile(out[col],limits); values.append(out[f"pct_{col}"])
      out[f"{theme}_component_score"]=pd.concat(values,axis=1).mean(axis=1)
    weights=config["score_weights"]; parts=pd.DataFrame({k:out[f"{k}_component_score"] for k in components}); available=parts.notna().mul(pd.Series(weights)); denominator=available.sum(axis=1)
    out["elementary_demand_score"]=parts.mul(pd.Series(weights)).sum(axis=1,min_count=1)/denominator.replace(0,np.nan)
    out["demand_score_quality"]=np.select([out.longitudinal_complete & out.demand_reliability.ge(.75),out.observed_years.ge(2)],["HIGH","MEDIUM"],default="LOW")
    valid=out.elementary_demand_score.notna(); out.loc[valid,"elementary_demand_rank"]=out.loc[valid,"elementary_demand_score"].rank(ascending=False,method="min"); out.loc[valid,"elementary_demand_percentile"]=out.loc[valid,"elementary_demand_score"].rank(pct=True)*100
    return out


def cluster_demand_types(scores: pd.DataFrame, config: dict):
    cols=["total_students","shrunk_net_transfer_rate","shrunk_student_growth_3y","shrunk_student_trend_slope_rate","shrunk_adjusted_upper_grade_index","shrunk_adjusted_cohort_growth"]
    valid=scores[cols].notna().all(axis=1); cluster_input=scores.loc[valid,cols].copy()
    limits=tuple(config.get("winsor_limits",(.01,.99)))
    for col in cols:
      cluster_input[col]=cluster_input[col].clip(cluster_input[col].quantile(limits[0]),cluster_input[col].quantile(limits[1]))
    X=StandardScaler().fit_transform(cluster_input); comparisons=[]; candidates=[]
    for k in config["cluster_k"]:
      if len(X)<=k: continue
      km=KMeans(n_clusters=k,random_state=42,n_init=20).fit(X); ks=silhouette_score(X,km.labels_); comparisons.append({"model":"KMEANS","k":k,"silhouette":ks,"bic":np.nan,"minimum_cluster_size":np.bincount(km.labels_).min()}); candidates.append((ks,"KMEANS",k,km.labels_))
      gm=GaussianMixture(n_components=k,random_state=42,n_init=5).fit(X); gl=gm.predict(X); gs=silhouette_score(X,gl) if len(set(gl))>1 else np.nan; comparisons.append({"model":"GMM","k":k,"silhouette":gs,"bic":gm.bic(X),"minimum_cluster_size":np.bincount(gl).min()}); candidates.append((gs,"GMM",k,gl))
    eligible=[x for x in candidates if np.isfinite(x[0]) and min(np.bincount(x[3]))>=config["minimum_cluster_size"]]
    if not eligible: raise ValueError("최소 군집 크기를 만족하는 Phase 9 군집모델이 없습니다.")
    best=max(eligible,key=lambda x:x[0]); out=scores.copy(); out["demand_cluster_id"]=pd.NA; out.loc[valid,"demand_cluster_id"]=best[3]
    profiles=out.loc[valid].groupby("demand_cluster_id").agg(school_count=("elementary_school_id","size"),**{c:(c,"mean") for c in cols},mean_demand_score=("elementary_demand_score","mean")).reset_index()
    standardized=pd.DataFrame(X,columns=cols,index=out.index[valid]); standardized["demand_cluster_id"]=best[3]
    zprofiles=standardized.groupby("demand_cluster_id")[cols].mean()
    names={cluster_id:"균형형" for cluster_id in zprofiles.index}; remaining=set(zprofiles.index)
    growth=zprofiles.shrunk_net_transfer_rate+zprofiles.shrunk_student_growth_3y+zprofiles.shrunk_student_trend_slope_rate+zprofiles.shrunk_adjusted_cohort_growth
    decline=-(zprofiles.shrunk_student_growth_3y+zprofiles.shrunk_student_trend_slope_rate)
    upper=zprofiles.shrunk_adjusted_upper_grade_index+zprofiles.shrunk_adjusted_cohort_growth
    def assign(name, metric, threshold=None):
      if not remaining: return
      cluster_id=max(remaining,key=lambda i:metric.loc[i])
      if threshold is None or metric.loc[cluster_id] >= threshold:
        names[cluster_id]=name; remaining.remove(cluster_id)
    assign("신축주거지 급성장형",growth)
    assign("학생감소형",decline)
    assign("고학년 학군유입형",upper,.5)
    assign("대규모 안정형",zprofiles.total_students,0)
    assign("소규모 안정형",-zprofiles.total_students,0)
    profiles["demand_cluster_name"]=profiles.demand_cluster_id.map(names)
    name_map=profiles.set_index("demand_cluster_id").demand_cluster_name; out["demand_cluster_name"]=out.demand_cluster_id.map(name_map)
    return out,pd.DataFrame(comparisons),profiles,best[1],best[2]


def freeze_phase8_benchmark(root=ROOT):
    root=Path(root); path=root/"data/snapshots/phase8_baseline_benchmark.json"
    expected={"total_apartments":4521,"phase7_scored":4288,"apartments_500plus":560,"scored_500plus":546,"coverage_pct":97.5,"transactions":223932,"panel_rows":581334,"primary_sample":487,"pearson":0.398,"spearman":0.375,"within_sigungu_spearman":0.190,"within_legal_dong_demeaned_spearman":0.005,"legal_dong_fe_10point_pct":3.10,"legal_dong_fe_p_value":0.1887,"feature_status":"USEFUL_FEATURE"}
    if path.exists():
      existing=json.loads(path.read_text(encoding="utf-8"));
      if any(existing.get(k)!=v for k,v in expected.items()): raise ValueError("Phase 8 baseline benchmark mismatch")
      return existing
    expected["frozen_at"]=now(); expected["source_hashes"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/"reports/phase8_validation.md",root/"reports/phase8_regression_results.csv",root/"data/snapshots/school_scores_2026_phase7_final.parquet"]}; write_json(path,expected); return expected


def build_phase9(root=ROOT):
    root=Path(root); config=yaml.safe_load((root/"config/phase9_elementary_demand.yaml").read_text(encoding="utf-8")); freeze_phase8_benchmark(root)
    source=pd.read_parquet(root/"data/processed/phase9_elementary_student_longitudinal.parquet")
    features=engineer_demand_features(source,max(config["years"]),config["shrinkage_k"]); scores=score_elementary_demand(features,config); scores,comparison,profiles,model,k=cluster_demand_types(scores,config)
    write_parquet(root/"data/processed/phase9_elementary_demand_features.parquet",features); write_parquet(root/"data/processed/phase9_elementary_demand_scores.parquet",scores)
    write_csv(root/"reports/phase9_elementary_demand_ranking.csv",scores.sort_values("elementary_demand_rank")); write_csv(root/"reports/phase9_cluster_comparison.csv",comparison); write_csv(root/"reports/phase9_cluster_profiles.csv",profiles)
    master=pd.read_parquet(root/"data/processed/schools.parquet"); master=master[master.school_level.eq("elementary")].copy()
    linkage=master[["school_id","school_name","sigungu","closed","suspended"]].rename(columns={"school_id":"elementary_school_id","school_name":"master_school_name"}).merge(scores[["elementary_school_id","elementary_school_name"]],on="elementary_school_id",how="outer",indicator=True)
    linkage["school_id_linkage_status"]=np.select([linkage._merge.eq("both"),linkage._merge.eq("left_only") & linkage.closed.eq("Y"),linkage._merge.eq("left_only")],["MATCHED","MASTER_CLOSED_NOT_IN_2026_API","MASTER_OPEN_NOT_IN_2026_API"],default="API_ID_NOT_IN_MASTER")
    linkage=linkage.drop(columns="_merge").sort_values(["school_id_linkage_status","sigungu","elementary_school_id"]); write_csv(root/"reports/phase9_school_id_linkage_audit.csv",linkage)
    quality=pd.DataFrame([{"metric":"longitudinal_rows","value":len(source)},{"metric":"unique_schools","value":source.elementary_school_id.nunique()},{"metric":"scored_schools","value":scores.elementary_demand_score.notna().sum()},{"metric":"three_year_complete","value":scores.longitudinal_complete.sum()},{"metric":"school_id_duplicates","value":scores.elementary_school_id.duplicated().sum()},{"metric":"student_reconciliation_mismatch_rows","value":source.student_reconciliation_difference.fillna(0).ne(0).sum()},{"metric":"official_ids_not_in_master","value":linkage.school_id_linkage_status.eq("API_ID_NOT_IN_MASTER").sum()},{"metric":"open_master_ids_not_in_2026_api","value":linkage.school_id_linkage_status.eq("MASTER_OPEN_NOT_IN_2026_API").sum()},{"metric":"closed_master_ids_not_in_2026_api","value":linkage.school_id_linkage_status.eq("MASTER_CLOSED_NOT_IN_2026_API").sum()}]); write_csv(root/"reports/phase9_data_quality.csv",quality)
    top=scores.nsmallest(10,"elementary_demand_rank")[["elementary_school_name","sigungu_requested","elementary_demand_score","student_growth_3y","net_transfer_rate","adjusted_upper_grade_index","adjusted_cohort_growth","demand_cluster_name"]]
    top_csv = top.to_csv(index=False, lineterminator="\n")
    report=f"""# Phase 9 Elementary Demand 검증 보고서\n\n- 공식 원천: 학교알리미 Open API 09·10\n- 실제 사용 연도: {min(config['years'])}~{max(config['years'])}; 공식 최근 3년 제한 때문에 2022~2023은 사용하지 않음\n- 학교×연도: {len(source):,}행 / 학교 {source.elementary_school_id.nunique():,}개\n- 점수 생성: {scores.elementary_demand_score.notna().sum():,}개\n- 3개년 완전 관측: {scores.longitudinal_complete.sum():,}개\n- 2026 공식 ID 중 기존 학교 master 미연결: {linkage.school_id_linkage_status.eq('API_ID_NOT_IN_MASTER').sum():,}개\n- 기존 운영 학교 ID 중 2026 공식 API 미관측: {linkage.school_id_linkage_status.eq('MASTER_OPEN_NOT_IN_2026_API').sum():,}개\n- 선택 cluster: {model} K={k}; 군집은 수요 유형 설명용이며 순위 산식에 사용하지 않음\n- Phase 7 점수와 아파트 가격은 수집·feature·점수 생성 과정에서 읽지 않음\n\n## 상위 10개\n\n```csv\n{top_csv}```\n\n## 해석 원칙\n학생 증가가 신규 입주인지 전통 학군수요인지 점수 하나로 단정하지 않는다. 성장·저학년 규모와 고학년/cohort 순유입을 분리하고 cluster profile로 설명한다. Phase 7과의 비교는 Phase 9.5에서만 수행한다.\n"""; atomic_bytes(root/"reports/phase9_validation.md",report.encode("utf-8"))
    return {"longitudinal_rows":len(source),"schools":int(source.elementary_school_id.nunique()),"scored":int(scores.elementary_demand_score.notna().sum()),"cluster_model":model,"cluster_k":k}
