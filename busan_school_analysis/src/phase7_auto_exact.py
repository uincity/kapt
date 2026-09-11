"""Conservative promotion of deterministic 2026 official assignment rows."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil

import pandas as pd

from .config import ROOT, write_csv
from .relation_overrides import load_overrides, validate_overrides

PATTERN=re.compile(r"남학생 중입=([^;]+);\s*여학생 중입=(.+)$")
YONGSO_ID="S020002045"
YONGSO_POSSIBLE_MIDDLES={"S020000607","S020000604"}


def official_exact_candidate_audit(relations: pd.DataFrame) -> pd.DataFrame:
    active=relations[relations.relation_status.eq("ACTIVE")&relations.middle_school_id.notna()].copy()
    counts=active.groupby("elementary_school_id").middle_school_id.nunique()
    single=active[active.elementary_school_id.map(counts).eq(1)].copy()
    rows=[]
    for row in single.itertuples(index=False):
        match=PATTERN.search(str(row.source_text)); male=match.group(1).strip() if match else ""; female=match.group(2).strip() if match else ""
        current=str(row.middle_school_name_current).replace("학교","").strip()
        official_pdf=Path(str(row.source_document)).suffix.lower()==".pdf" and "북부교육지청" in str(row.source_document)
        same_single=bool(match and male==female and "," not in male and male.replace("학교","").strip()==current)
        passed=bool(official_pdf and same_single and pd.notna(row.elementary_school_id) and pd.notna(row.middle_school_id))
        rows.append({"elementary_school_id":row.elementary_school_id,"elementary_school_name":row.elementary_school_name,
            "middle_school_id":row.middle_school_id,"middle_school_name":row.middle_school_name_current,
            "education_office":row.education_office,"school_group":row.school_group,"male_assignment":male,
            "female_assignment":female,"single_active_candidate":True,"official_bukbu_pdf":official_pdf,
            "male_female_same_single_school":same_single,"auto_exact_pass":passed,
            "decision":"PROMOTE_EXACT" if passed else "KEEP_ELIGIBLE_REVIEW",
            "source_document":row.source_document,"source_page":row.source_page_or_section,"source_text":row.source_text,
            "source_sha256":row.source_sha256,"previous_relation_type":row.relation_type,"previous_relation_status":row.relation_status})
    return pd.DataFrame(rows).sort_values(["auto_exact_pass","education_office","elementary_school_name"],ascending=[False,True,True]).reset_index(drop=True)


def apply_official_exact_candidates(root=ROOT):
    root=Path(root); relation_path=root/"data/processed/busan_elementary_middle_relation_2026.parquet"
    override_path=root/"config/manual_elementary_middle_overrides.csv"
    relations=pd.read_parquet(relation_path); audit=official_exact_candidate_audit(relations)
    candidates=audit[audit.auto_exact_pass].copy(); current=load_overrides(override_path)
    # User-directed correction: the two 0.5 Yongso paths are possible, not exact.
    yongso=current.elementary_school_id.eq(YONGSO_ID)&current.middle_school_id.isin(YONGSO_POSSIBLE_MIDDLES)
    current.loc[yongso,"relation_type"]="ELIGIBLE"
    current.loc[yongso,"override_reason"]="용소초 복수 배정가능 관계로 정정; 기존 확인 비율 보존"
    now=datetime.now().astimezone().isoformat()
    additions=pd.DataFrame({
        "elementary_school_id":candidates.elementary_school_id,"elementary_school_name":candidates.elementary_school_name,
        "middle_school_id":candidates.middle_school_id,"middle_school_name":candidates.middle_school_name,
        "relation_type":"EXACT","relation_status":"ACTIVE","assignment_share":"1.0",
        "override_reason":"2026 북부교육지원청 공식 배정표의 남녀 동일 단일 배정학교 자동검증",
        "override_source":candidates.source_document.astype(str)+"; "+candidates.source_page.astype(str),"updated_at":now})
    keys=set(zip(additions.elementary_school_id,additions.middle_school_id))
    retained=current[[(e,m) not in keys for e,m in zip(current.elementary_school_id,current.middle_school_id)]]
    combined=validate_overrides(pd.concat([retained,additions],ignore_index=True).fillna(""))
    shares=pd.to_numeric(combined.assignment_share.replace("",pd.NA),errors="coerce")
    exact=combined.relation_type.eq("EXACT")&combined.relation_status.eq("ACTIVE")
    if (~shares[exact].eq(1.0)).any(): raise ValueError("EXACT/ACTIVE override must have assignment_share=1.0")
    if combined.loc[exact,"elementary_school_id"].duplicated().any(): raise ValueError("Multiple active EXACT overrides for one elementary school")
    backup=override_path.with_name(f"manual_elementary_middle_overrides.backup_auto_exact_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    shutil.copy2(override_path,backup)
    write_csv(override_path,combined)
    audit["applied_at"]=now; write_csv(root/"reports/phase7_official_exact_candidate_audit.csv",audit)
    return {"candidate_schools":len(audit),"promoted_exact":len(candidates),"kept_for_review":int((~audit.auto_exact_pass).sum()),
            "yongso_rows_changed_to_eligible":int(yongso.sum()),"backup":str(backup),"override_rows":len(combined)}

