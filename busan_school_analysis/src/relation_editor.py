"""Streamlit editor for auditable elementary-middle relation overrides."""
from pathlib import Path

import pandas as pd
import streamlit as st

from .relation_overrides import load_overrides, save_school_overrides


def render_relation_editor(root, relations, detail, feeders, schools):
    root=Path(root); path=root/"config/manual_elementary_middle_overrides.csv"
    school_district=(relations[["elementary_school_id","elementary_school_name"]].dropna(subset=["elementary_school_id"])
                     .drop_duplicates("elementary_school_id")
                     .merge(schools[["school_id","sigungu"]].drop_duplicates("school_id"),left_on="elementary_school_id",right_on="school_id",how="left"))
    districts=sorted(school_district.sigungu.dropna().unique())
    district_default=districts.index("해운대구") if "해운대구" in districts else 0
    district=st.sidebar.selectbox("구·군 선택",districts,index=district_default)
    names=sorted(school_district.loc[school_district.sigungu.eq(district),"elementary_school_name"].unique())
    default=names.index("센텀초") if "센텀초" in names else 0
    school=st.sidebar.selectbox("초등학교 선택",names,index=default)
    current=relations[relations.elementary_school_name.eq(school)].copy()
    scores=detail[["elementary_school_id","middle_school_id","middle_school_score","busan_rank"]].drop_duplicates(["elementary_school_id","middle_school_id"])
    current=current.merge(scores,on=["elementary_school_id","middle_school_id"],how="left",suffixes=("","_상세"))
    overrides=load_overrides(path); keys=set(zip(overrides.elementary_school_id,overrides.middle_school_id))
    current["override_enabled"]=[(str(e),str(m)) in keys for e,m in zip(current.elementary_school_id,current.middle_school_id)]
    current["assignment_share"]=pd.to_numeric(current.get("assignment_share"),errors="coerce")
    current["override_reason"]=current.get("override_reason",pd.Series(index=current.index,dtype="object")).fillna("")
    current["override_source"]=current.get("override_source",pd.Series(index=current.index,dtype="object")).fillna("")
    type_to_ko={"EXACT":"확정 배정","ELIGIBLE":"배정 가능","CONDITIONAL":"조건부 배정","GROUP_MEMBERSHIP":"학교군 포함","UNRESOLVED":"미확정"}
    status_to_ko={"ACTIVE":"점수 반영","EXCLUDED_NOT_APPLICABLE":"해당 없음으로 제외","EXCLUDED_AMBIGUOUS_SCHOOL":"학교 미확정으로 제외","UNRESOLVED_EXTERNAL_OFFICE":"타 교육지원청 미확정"}
    ko_to_type={v:k for k,v in type_to_ko.items()}; ko_to_status={v:k for k,v in status_to_ko.items()}
    current["relation_type"]=current.relation_type.map(type_to_ko).fillna(current.relation_type)
    current["relation_status"]=current.relation_status.map(status_to_ko).fillna(current.relation_status)
    st.info("수정할 행의 ‘수정 적용’을 선택하세요. 공식 확정 배정이면 관계유형을 ‘확정 배정’으로, 계산에서 제외할 후보는 반영상태를 ‘해당 없음으로 제외’로 설정합니다.")
    reason=st.text_input("공통 수정 근거",placeholder="예: 2026학년도 실제 배정 결과에서 센텀중 100% 확인")
    source=st.text_input("근거 자료",placeholder="문서명, 페이지 또는 확인 가능한 내부 자료명")
    cols=["override_enabled","elementary_school_id","elementary_school_name","middle_school_id","middle_school_name","middle_school_score","busan_rank","relation_type","relation_status","assignment_share","override_reason","override_source","source_text"]
    edited=st.data_editor(current[cols],hide_index=True,width="stretch",num_rows="fixed",
      disabled=["elementary_school_id","elementary_school_name","middle_school_id","middle_school_name","middle_school_score","busan_rank","source_text"],
      column_config={
       "override_enabled":st.column_config.CheckboxColumn("수정 적용"),"elementary_school_id":"초등학교 ID","elementary_school_name":"초등학교",
       "middle_school_id":"중학교 ID","middle_school_name":"중학교","middle_school_score":st.column_config.NumberColumn("중학교 점수",format="%.2f"),
       "busan_rank":st.column_config.NumberColumn("부산 순위",format="%d"),
       "relation_type":st.column_config.SelectboxColumn("관계유형",options=list(ko_to_type),required=True),
       "relation_status":st.column_config.SelectboxColumn("반영상태",options=list(ko_to_status),required=True),
       "assignment_share":st.column_config.NumberColumn("실제 배정비율",min_value=0.,max_value=1.,step=.01,format="%.2f"),
       "override_reason":"행별 수정 근거","override_source":"행별 근거 자료","source_text":"기존 원문"})
    feeder=feeders[feeders.elementary_school_name.eq(school)]
    if len(feeder):
      row=feeder.iloc[0]
      with st.container(horizontal=True):
       st.metric("현재 진학권 점수",f"{row.elementary_feeder_score:.2f}",border=True)
       st.metric("배정 후보 수",f"{row.eligible_middle_count:.0f}",border=True)
       st.metric("중학교 평균",f"{row.mean_middle_score:.2f}",border=True)
       st.metric("최저 중학교",f"{row.worst_middle_score:.2f}",border=True)
    if st.button("수정사항 저장 및 학군점수 재계산",type="primary"):
      selected=edited[edited.override_enabled]
      if len(selected) and not reason and selected.override_reason.astype(str).str.strip().eq("").any():
       st.error("수정 근거를 입력하세요."); return
      if len(selected):
       selected["relation_type"]=selected.relation_type.map(ko_to_type)
       selected["relation_status"]=selected.relation_status.map(ko_to_status)
       selected.loc[selected.override_reason.astype(str).str.strip().eq(""),"override_reason"]=reason
       selected.loc[selected.override_source.astype(str).str.strip().eq(""),"override_source"]=source
      school_id=str(current.elementary_school_id.dropna().iloc[0])
      save_school_overrides(path,selected,school_id)
      with st.spinner("2026학년도 배정관계와 학군점수를 다시 계산하고 있습니다."):
       from .phase7_assignment_2026 import build_assignment_2026
       result=build_assignment_2026(root)
      st.cache_data.clear()
      st.success(f"저장했습니다. 전체 점수 단지 {result['apartments_scored']:,}개, 500세대 이상 {result['apartments_500plus_scored']:,}개입니다. Phase 8 가격분석은 별도로 다시 실행하세요.")
      st.rerun()

