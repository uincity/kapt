"""Auditable user overrides for elementary-to-middle assignment relations."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import write_csv

OVERRIDE_COLUMNS = [
    "elementary_school_id", "elementary_school_name", "middle_school_id",
    "middle_school_name", "relation_type", "relation_status",
    "assignment_share", "override_reason", "override_source", "updated_at",
]
ALLOWED_TYPES = {"EXACT", "ELIGIBLE", "CONDITIONAL", "GROUP_MEMBERSHIP", "UNRESOLVED"}
ALLOWED_STATUSES = {"ACTIVE", "EXCLUDED_NOT_APPLICABLE", "EXCLUDED_AMBIGUOUS_SCHOOL", "UNRESOLVED_EXTERNAL_OFFICE"}


def load_overrides(path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)
    out = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    for col in OVERRIDE_COLUMNS:
        if col not in out: out[col] = ""
    return out[OVERRIDE_COLUMNS]


def validate_overrides(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if out.empty: return out.reindex(columns=OVERRIDE_COLUMNS)
    bad_type = sorted(set(out.relation_type) - ALLOWED_TYPES)
    bad_status = sorted(set(out.relation_status) - ALLOWED_STATUSES)
    if bad_type: raise ValueError(f"허용되지 않은 배정관계 유형입니다: {bad_type}")
    if bad_status: raise ValueError(f"허용되지 않은 반영상태입니다: {bad_status}")
    if out[["elementary_school_id", "middle_school_id"]].eq("").any().any():
        raise ValueError("초등학교·중학교 ID가 없는 관계는 이 화면에서 수정할 수 없습니다.")
    if out.duplicated(["elementary_school_id", "middle_school_id"]).any():
        raise ValueError("같은 초등학교·중학교 override가 중복되었습니다.")
    share = pd.to_numeric(out.assignment_share.replace("", pd.NA), errors="coerce")
    if share.dropna().lt(0).any() or share.dropna().gt(1).any():
        raise ValueError("실제 배정비율은 0~1 사이여야 합니다.")
    return out[OVERRIDE_COLUMNS]


def save_school_overrides(path, school_rows: pd.DataFrame, elementary_school_id: str) -> pd.DataFrame:
    path = Path(path); current = load_overrides(path)
    current = current[current.elementary_school_id.ne(str(elementary_school_id))]
    rows = school_rows.copy()
    if "override_enabled" in rows:
        rows = rows[rows.override_enabled.astype(bool)].drop(columns="override_enabled")
    rows = rows.reindex(columns=OVERRIDE_COLUMNS)
    if len(rows): rows["updated_at"] = datetime.now().astimezone().isoformat()
    combined = pd.concat([current, rows], ignore_index=True)
    combined = validate_overrides(combined.where(combined.notna(), ""))
    write_csv(path, combined)
    return combined


def apply_relation_overrides(relations: pd.DataFrame, path) -> pd.DataFrame:
    out = relations.copy()
    out["original_relation_type"] = out.relation_type
    out["original_relation_status"] = out.relation_status
    out["override_applied"] = False
    out["assignment_share"] = pd.NA
    out["override_reason"] = pd.NA
    out["override_source"] = pd.NA
    overrides = validate_overrides(load_overrides(path))
    if overrides.empty: return out
    lookup = overrides.set_index(["elementary_school_id", "middle_school_id"])
    for idx, row in out.iterrows():
        key = (str(row.elementary_school_id), str(row.middle_school_id))
        if key not in lookup.index: continue
        item = lookup.loc[key]
        out.at[idx, "relation_type"] = item.relation_type
        out.at[idx, "relation_status"] = item.relation_status
        out.at[idx, "assignment_share"] = pd.to_numeric(item.assignment_share, errors="coerce")
        out.at[idx, "override_reason"] = item.override_reason
        out.at[idx, "override_source"] = item.override_source
        out.at[idx, "override_applied"] = True
    return out
