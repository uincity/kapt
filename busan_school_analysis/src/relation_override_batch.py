"""Export and import a Korean, pair-level elementary-middle override workbook."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

import pandas as pd

from .config import ROOT, write_csv
from .relation_overrides import OVERRIDE_COLUMNS, load_overrides, validate_overrides

TYPE_KO = {
    "EXACT": "확정 배정", "ELIGIBLE": "배정 가능", "CONDITIONAL": "조건부 배정",
    "GROUP_MEMBERSHIP": "학교군 포함", "UNRESOLVED": "미확정",
}
STATUS_KO = {
    "ACTIVE": "점수 반영", "EXCLUDED_NOT_APPLICABLE": "해당 없음으로 제외",
    "EXCLUDED_AMBIGUOUS_SCHOOL": "학교 미확정으로 제외",
    "UNRESOLVED_EXTERNAL_OFFICE": "타 교육지원청 미확정",
}
TYPE_EN = {v: k for k, v in TYPE_KO.items()}
STATUS_EN = {v: k for k, v in STATUS_KO.items()}
DEFAULT_REVIEW_PATH = "em_school/초중배정관계_일괄검토_2026.csv"


def _joined(series):
    return " | ".join(dict.fromkeys(str(v).strip() for v in series.dropna() if str(v).strip()))


def export_relation_review(root=ROOT, output=DEFAULT_REVIEW_PATH):
    root=Path(root); relations=pd.read_parquet(root/"data/processed/busan_elementary_middle_relation_2026.parquet")
    schools=pd.read_parquet(root/"data/processed/schools.parquet")
    district=schools[["school_id","sigungu"]].drop_duplicates("school_id").rename(columns={"school_id":"elementary_school_id","sigungu":"district_name"})
    valid=relations[relations.middle_school_id.notna()].copy()
    active_exact=valid[valid.relation_type.eq("EXACT")&valid.relation_status.eq("ACTIVE")]
    multiple_exact_ids=set(active_exact.groupby("elementary_school_id").middle_school_id.nunique().loc[lambda x:x.gt(1)].index)
    rows=[]
    for (elementary_id,middle_id),g in valid.groupby(["elementary_school_id","middle_school_id"],sort=False,dropna=False):
        types=list(dict.fromkeys(g.relation_type.astype(str))); statuses=list(dict.fromkeys(g.relation_status.astype(str)))
        notes=[]
        if elementary_id in multiple_exact_ids: notes.append("활성 확정배정이 복수이므로 정정 필요")
        if (g.relation_type.eq("EXACT")&g.relation_status.eq("ACTIVE")&~pd.to_numeric(g.assignment_share,errors="coerce").eq(1.0)).any():
            notes.append("확정배정인데 실제배정비율이 1.0이 아님")
        row={
            "수정적용":"N", "수정가능":"Y", "초등학교ID":elementary_id,
            "초등학교":g.elementary_school_name.iloc[0], "중학교ID":middle_id,
            "중학교":g.middle_school_name_current.fillna(g.middle_school_name).iloc[0],
            "현재관계유형":TYPE_KO.get(types[0],types[0]) if len(types)==1 else "복수 원본유형",
            "현재반영상태":STATUS_KO.get(statuses[0],statuses[0]) if len(statuses)==1 else "복수 원본상태",
            "수정관계유형":"", "수정반영상태":"", "실제배정비율":"",
            "수정근거":"", "근거자료":"", "원본행수":len(g),
            "성별조건":_joined(g.gender_condition), "학교군":_joined(g.school_group),
            "교육지원청":_joined(g.education_office), "기존원문":_joined(g.source_text),
            "출처문서":_joined(g.source_document), "출처위치":_joined(g.source_page_or_section),
            "기존override적용":"Y" if g.override_applied.fillna(False).any() else "N",
            "기존배정비율":_joined(g.assignment_share), "검토메모":"; ".join(notes),
        }
        rows.append(row)
    # Unresolved school IDs remain visible but cannot be imported until the ID is resolved.
    for row in relations[relations.middle_school_id.isna()].itertuples(index=False):
        rows.append({"수정적용":"N","수정가능":"N","초등학교ID":row.elementary_school_id,
            "초등학교":row.elementary_school_name,"중학교ID":"","중학교":row.middle_school_name_current or row.middle_school_name,
            "현재관계유형":TYPE_KO.get(row.relation_type,row.relation_type),"현재반영상태":STATUS_KO.get(row.relation_status,row.relation_status),
            "수정관계유형":"","수정반영상태":"","실제배정비율":"","수정근거":"","근거자료":"","원본행수":1,
            "성별조건":row.gender_condition,"학교군":row.school_group,"교육지원청":row.education_office,
            "기존원문":row.source_text,"출처문서":row.source_document,"출처위치":row.source_page_or_section,
            "기존override적용":"N","기존배정비율":"","검토메모":"중학교 ID 미해결: 먼저 학교 식별 필요"})
    out=pd.DataFrame(rows).merge(district,left_on="초등학교ID",right_on="elementary_school_id",how="left",validate="many_to_one")
    out=out.drop(columns="elementary_school_id").rename(columns={"district_name":"구군"})
    order=["수정적용","수정가능","구군","교육지원청","초등학교ID","초등학교","중학교ID","중학교",
           "현재관계유형","현재반영상태","수정관계유형","수정반영상태","실제배정비율","수정근거","근거자료",
           "원본행수","성별조건","학교군","기존override적용","기존배정비율","기존원문","출처문서","출처위치","검토메모"]
    out=out[order].sort_values(["구군","초등학교","중학교"],na_position="last").reset_index(drop=True)
    path=root/output; write_csv(path,out)
    return {"output":str(path),"review_rows":len(out),"editable_rows":int(out.수정가능.eq("Y").sum()),
            "unresolved_rows":int(out.수정가능.eq("N").sum()),"source_rows":len(relations),"data_changed":False}


def _selected_review(path: Path):
    review=pd.read_csv(path,dtype=str,encoding="utf-8-sig").fillna("")
    required={"수정적용","수정가능","초등학교ID","초등학교","중학교ID","중학교","수정관계유형","수정반영상태","실제배정비율","수정근거","근거자료"}
    missing=required-set(review.columns)
    if missing: raise ValueError(f"일괄검토 CSV 필수 열이 없습니다: {sorted(missing)}")
    selected=review[review.수정적용.str.strip().str.upper().isin(["Y","YES","1","TRUE"])].copy()
    if selected.empty: raise ValueError("수정적용이 Y인 행이 없습니다.")
    if selected.수정가능.ne("Y").any(): raise ValueError("수정가능=N인 ID 미해결 관계가 선택되었습니다.")
    for col,label in [("수정관계유형","관계유형"),("수정반영상태","반영상태"),("수정근거","수정근거"),("근거자료","근거자료")]:
        if selected[col].str.strip().eq("").any(): raise ValueError(f"선택 행에는 {label}를 모두 입력해야 합니다.")
    selected["relation_type"]=selected.수정관계유형.map(TYPE_EN).fillna(selected.수정관계유형)
    selected["relation_status"]=selected.수정반영상태.map(STATUS_EN).fillna(selected.수정반영상태)
    selected["assignment_share"]=selected.실제배정비율
    exact=selected.relation_type.eq("EXACT")&selected.relation_status.eq("ACTIVE")
    shares=pd.to_numeric(selected.assignment_share.replace("",pd.NA),errors="coerce")
    if (~shares[exact].eq(1.0)).any(): raise ValueError("확정 배정(EXACT/ACTIVE)은 실제배정비율 1.0이 필요합니다.")
    excluded=selected.relation_status.ne("ACTIVE")
    if shares[excluded].dropna().ne(0).any(): raise ValueError("제외 관계의 실제배정비율은 공란 또는 0이어야 합니다.")
    if selected.duplicated(["초등학교ID","중학교ID"]).any(): raise ValueError("선택된 초등학교-중학교 관계가 중복되었습니다.")
    now=datetime.now().astimezone().isoformat()
    out=pd.DataFrame({"elementary_school_id":selected.초등학교ID,"elementary_school_name":selected.초등학교,
        "middle_school_id":selected.중학교ID,"middle_school_name":selected.중학교,
        "relation_type":selected.relation_type,"relation_status":selected.relation_status,
        "assignment_share":selected.assignment_share,"override_reason":selected.수정근거,
        "override_source":selected.근거자료,"updated_at":now})
    return validate_overrides(out),review


def import_relation_review(csv_path, root=ROOT, rebuild=False):
    root=Path(root); source=Path(csv_path); source=source if source.is_absolute() else root/source
    selected,_=_selected_review(source)
    override_path=root/"config/manual_elementary_middle_overrides.csv"; current=load_overrides(override_path)
    keys=set(zip(selected.elementary_school_id,selected.middle_school_id))
    current=current[[ (e,m) not in keys for e,m in zip(current.elementary_school_id,current.middle_school_id) ]]
    combined=validate_overrides(pd.concat([current,selected],ignore_index=True))
    # Validate the effective relation set before committing the override file.
    relations=pd.read_parquet(root/"data/processed/busan_elementary_middle_relation_2026.parquet")
    effective=relations[["elementary_school_id","middle_school_id","relation_type","relation_status"]].drop_duplicates(["elementary_school_id","middle_school_id"],keep="last")
    update=combined.set_index(["elementary_school_id","middle_school_id"])
    for idx,row in effective.iterrows():
        key=(str(row.elementary_school_id),str(row.middle_school_id))
        if key in update.index:
            effective.at[idx,"relation_type"]=update.loc[key].relation_type
            effective.at[idx,"relation_status"]=update.loc[key].relation_status
    active_exact=effective[effective.relation_type.eq("EXACT")&effective.relation_status.eq("ACTIVE")]
    if active_exact.elementary_school_id.duplicated().any():
        names=sorted(active_exact.loc[active_exact.elementary_school_id.duplicated(False),"elementary_school_id"].unique())
        raise ValueError(f"한 초등학교에 활성 확정배정 중학교가 복수입니다: {names[:10]}")
    for elementary_id in active_exact.elementary_school_id:
        other=effective[effective.elementary_school_id.eq(elementary_id)&effective.relation_status.eq("ACTIVE")&~effective.relation_type.eq("EXACT")]
        if len(other): raise ValueError(f"{elementary_id}: 확정배정과 다른 활성 후보가 함께 있습니다. 다른 후보를 제외 처리하세요.")
    backup=override_path.with_name(f"manual_elementary_middle_overrides.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    if override_path.exists(): shutil.copy2(override_path,backup)
    write_csv(override_path,combined)
    result={"selected_rows":len(selected),"total_overrides":len(combined),"backup":str(backup),"override_file":str(override_path),"rebuilt":False}
    if rebuild:
        from .phase7_assignment_2026 import build_assignment_2026
        result["phase7_result"]=build_assignment_2026(root); result["rebuilt"]=True
    return result
