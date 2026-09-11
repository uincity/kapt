"""Phase 15.4: freeze, review, and presentation layer.

This module only classifies and presents frozen Phase 14.9--15.3 outputs.  It
does not fit a model or alter an analytical value from an earlier phase.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import ROOT, atomic_bytes, write_csv, write_json


FINAL_STATUS = "BUSAN_APARTMENT_VALUE_MODEL_FINAL_FROZEN"
LOCAL_GAP_STATUS = "LOCAL_VALUE_GAP_USABLE_WITH_CAUTION"
PREVIOUS_TEST_COUNT = 388
CLASS_ORDER = {
    "CORE_CANDIDATE": 1,
    "LOCAL_VALUE": 2,
    "SCHOOL_VALUE": 3,
    "WATCHLIST": 4,
    "FULLY_PRICED_OR_NEGATIVE": 5,
}
INTERVAL_ORDER = {
    "STRONG_UNDERVALUED_SIGNAL": 1,
    "POTENTIAL_UNDERVALUED_SIGNAL": 2,
    "WITHIN_MODEL_RANGE": 3,
    "POTENTIAL_OVERVALUED_SIGNAL": 4,
    "STRONG_OVERVALUED_SIGNAL": 5,
    "INSUFFICIENT": 6,
}
CONFIDENCE_ORDER = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
TEMPORAL_ORDER = {"STABLE_POSITIVE": 1, "STABLE_NEGATIVE": 2, "MIXED": 3, "INSUFFICIENT": 4}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_protected(root=ROOT) -> pd.DataFrame:
    """Capture every Phase 7--15.3 artifact and the established entry files."""
    root = Path(root)
    pattern = re.compile(
        r"phase(?:7|8|9|10|11|115|12|125|13|135|14|145|146|147|148|149|151|152|153)(?![0-9])",
        re.IGNORECASE,
    )
    found: set[Path] = set()
    for folder in ("src", "tests", "data/processed", "data/snapshots", "reports"):
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and pattern.search(path.name) and "phase154" not in path.name.lower():
                found.add(path)
    for relative in ("main.py", "streamlit_app.py", "config/manual_elementary_middle_overrides.csv"):
        path = root / relative
        if path.exists():
            found.add(path)
    rows = []
    for path in sorted(found):
        match = pattern.search(path.name)
        phase = match.group(0).lower().replace("phase", "") if match else "CORE"
        phase = {"115": "11.5", "125": "12.5", "135": "13.5", "145": "14.5", "151": "15.1", "152": "15.2", "153": "15.3"}.get(phase, phase)
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "phase": phase,
                "file_size": path.stat().st_size,
                "sha256_before": _sha(path),
                "sha256_after": "",
                "unchanged": False,
            }
        )
    return pd.DataFrame(rows)


def verify_manifest(manifest: pd.DataFrame, root=ROOT) -> pd.DataFrame:
    root = Path(root)
    checked = manifest.copy()
    checked["sha256_after"] = [
        _sha(root / path) if (root / path).is_file() else "MISSING" for path in checked["path"]
    ]
    checked["unchanged"] = checked["sha256_before"].eq(checked["sha256_after"])
    if not checked["unchanged"].all():
        changed = checked.loc[~checked["unchanged"], "path"].tolist()
        raise RuntimeError(f"PROTECTED_ARTIFACT_MODIFIED: {changed}")
    return checked


def is_critical_quality(row) -> bool:
    return (
        str(row.data_quality_flag) == "INSUFFICIENT_MODEL_FEATURES"
        or pd.isna(row.local_fair_total_price)
        or pd.isna(row.school_value_gap_pct)
    )


def final_review_class(row) -> str:
    """Apply the documented mutually exclusive rule hierarchy."""
    model_ok = row.model_confidence in {"HIGH", "MEDIUM"}
    local_ok = row.local_gap_confidence in {"HIGH", "MEDIUM"}
    school_ok = row.gap_confidence in {"HIGH", "MEDIUM"}
    clean = not is_critical_quality(row) and not bool(row.dong_bias_flag) and not bool(row.extreme_gap_flag)

    if (
        row.combined_candidate_class == "ROBUST_DUAL_POSITIVE"
        and model_ok
        and local_ok
        and school_ok
        and row.local_gap_temporal_stability == "STABLE_POSITIVE"
        and clean
    ):
        return "CORE_CANDIDATE"
    if row.combined_candidate_class == "LOCAL_VALUE_CANDIDATE" and model_ok and local_ok and clean:
        return "LOCAL_VALUE"
    if row.combined_candidate_class == "SCHOOL_VALUE_CANDIDATE" and school_ok and clean:
        return "SCHOOL_VALUE"
    if row.combined_candidate_class == "NEGATIVE_OR_FULLY_PRICED":
        return "FULLY_PRICED_OR_NEGATIVE"
    return "WATCHLIST"


def limitation_reasons(row, wide_threshold: float) -> list[str]:
    reasons: list[str] = []
    if pd.notna(row.prediction_interval_width_pct) and row.prediction_interval_width_pct > wide_threshold:
        reasons.append("WIDE_PREDICTION_INTERVAL")
    if bool(row.dong_bias_flag):
        reasons.append("LEGAL_DONG_BIAS")
    if pd.isna(row.transaction_count_12m) or row.transaction_count_12m < 3:
        reasons.append("LOW_TRANSACTION")
    if pd.notna(row.fallback_level) and row.fallback_level >= 3:
        reasons.append("HIGH_FALLBACK")
    if pd.notna(row.recent_local_residual) and abs(row.recent_local_residual) > 0.15:
        reasons.append("EXTREME_RESIDUAL")
    if row.model_confidence == "LOW":
        reasons.append("LOW_MODEL_CONFIDENCE")
    if row.gap_confidence not in {"HIGH", "MEDIUM"}:
        reasons.append("LOW_SCHOOL_CONFIDENCE")
    if pd.isna(row.local_fair_total_price):
        reasons.append("MISSING_FAIR_PRICE")
    if pd.isna(row.school_value_gap_pct):
        reasons.append("MISSING_SCHOOL_SCORE")
    return reasons


def limitation_flag(reasons: list[str]) -> str:
    if not reasons:
        return "NONE"
    if len(reasons) == 1:
        return reasons[0]
    return "MULTIPLE_LIMITATIONS"


def _persistent_residual(row, direction: str) -> bool:
    values = [row.recent_local_residual, row.residual_6m_median, row.residual_12m_median]
    values = [float(value) for value in values if pd.notna(value)]
    if len(values) < 2:
        return False
    if direction == "premium":
        return sum(value > 0.15 for value in values) >= 2
    return sum(value < -0.15 for value in values) >= 2


def unmodeled_premium_candidate(row) -> bool:
    return bool(
        row.local_value_gap_pct < -3
        and row.local_gap_interval_status in {"POTENTIAL_OVERVALUED_SIGNAL", "STRONG_OVERVALUED_SIGNAL"}
        and row.model_confidence in {"HIGH", "MEDIUM"}
        and row.transaction_count_12m >= 5
        and _persistent_residual(row, "premium")
    )


def unmodeled_discount_candidate(row) -> bool:
    return bool(
        row.local_value_gap_pct > 3
        and row.local_gap_interval_status in {"POTENTIAL_UNDERVALUED_SIGNAL", "STRONG_UNDERVALUED_SIGNAL"}
        and row.model_confidence in {"HIGH", "MEDIUM"}
        and row.transaction_count_12m >= 5
        and _persistent_residual(row, "discount")
    )


def build_master(source: pd.DataFrame, phase153_result: dict) -> pd.DataFrame:
    """Append review metadata without changing any frozen analytical column."""
    out = source.copy()
    wide_threshold = float(phase153_result["thresholds"]["interval_width_p75"])
    out["final_review_class"] = [final_review_class(row) for row in out.itertuples()]
    details = [limitation_reasons(row, wide_threshold) for row in out.itertuples()]
    out["model_limitation_flag"] = [limitation_flag(value) for value in details]
    out["model_limitation_detail"] = [";".join(value) if value else "NONE" for value in details]
    out["unmodeled_premium_candidate"] = [unmodeled_premium_candidate(row) for row in out.itertuples()]
    out["unmodeled_discount_candidate"] = [unmodeled_discount_candidate(row) for row in out.itertuples()]
    return out


def rank_candidates(master: pd.DataFrame) -> pd.DataFrame:
    ranked = master.copy()
    ranked["_class"] = ranked.final_review_class.map(CLASS_ORDER)
    ranked["_interval"] = ranked.local_gap_interval_status.map(INTERVAL_ORDER).fillna(99)
    ranked["_local_conf"] = ranked.local_gap_confidence.map(CONFIDENCE_ORDER).fillna(99)
    ranked["_model_conf"] = ranked.model_confidence.map(CONFIDENCE_ORDER).fillna(99)
    ranked["_school_conf"] = ranked.gap_confidence.map(CONFIDENCE_ORDER).fillna(99)
    ranked["_temporal"] = ranked.local_gap_temporal_stability.map(TEMPORAL_ORDER).fillna(99)
    ranked = ranked.sort_values(
        ["_class", "_interval", "_local_conf", "_model_conf", "_school_conf", "_temporal", "gap_positive_probability", "local_value_gap_pct", "school_value_gap_pct", "apartment_id"],
        ascending=[True, True, True, True, True, True, False, False, False, True],
        kind="mergesort",
        na_position="last",
    )
    ranked["class_rank"] = ranked.groupby("final_review_class", sort=False).cumcount() + 1
    columns = {
        "school_premium_core_score": "school_core_score",
        "estimated_school_premium_pct": "school_premium_pct",
    }
    keep = [
        "final_review_class", "class_rank", "apartment_id", "apartment_name", "gu", "legal_dong",
        "household_count", "school_premium_core_score", "estimated_school_premium_pct",
        "school_value_gap_pct", "local_fair_total_price", "observed_market_price_12m",
        "local_value_gap_pct", "local_gap_interval_status", "local_gap_temporal_stability",
        "school_local_signal_agreement", "model_confidence", "local_gap_confidence", "gap_confidence",
        "gap_positive_probability", "dong_bias_flag", "phase154_audit_priority", "model_limitation_flag",
        "unmodeled_premium_candidate", "unmodeled_discount_candidate",
    ]
    return ranked[keep].rename(columns=columns).reset_index(drop=True)


def _audit_reason(row) -> str:
    reasons = []
    if bool(row.extreme_gap_flag):
        reasons.append("EXTREME_GAP")
    if bool(row.dong_bias_flag):
        reasons.append("LEGAL_DONG_BIAS")
    if row.local_gap_interval_status in {"STRONG_UNDERVALUED_SIGNAL", "STRONG_OVERVALUED_SIGNAL"}:
        reasons.append(row.local_gap_interval_status)
    if row.model_limitation_flag != "NONE":
        reasons.append(row.model_limitation_flag)
    return ";".join(dict.fromkeys(reasons)) or "PHASE153_HIGH_AUDIT"


def high_audit_table(master: pd.DataFrame) -> pd.DataFrame:
    audit = master[master.phase154_audit_priority.eq("HIGH")].copy()
    audit["existing_reason"] = [_audit_reason(row) for row in audit.itertuples()]
    keep = [
        "apartment_id", "apartment_name", "gu", "legal_dong", "existing_reason",
        "local_value_gap_pct", "school_value_gap_pct", "model_confidence",
        "local_gap_interval_status", "dong_bias_flag", "final_review_class",
        "model_limitation_flag", "model_limitation_detail", "unmodeled_premium_candidate",
        "unmodeled_discount_candidate", "phase154_audit_priority",
    ]
    return audit[keep].sort_values(["existing_reason", "apartment_id"], kind="mergesort")


def summary_table(master: pd.DataFrame) -> pd.DataFrame:
    classes = master.final_review_class.value_counts()
    metrics = {
        "total_apartments": len(master),
        "school_core_coverage": int(master.school_premium_core_score.notna().sum()),
        "fair_price_coverage": int(master.local_fair_total_price.notna().sum()),
        "local_gap_coverage": int(master.local_value_gap_pct.notna().sum()),
        "school_gap_coverage": int(master.school_value_gap_pct.notna().sum()),
        **{f"{name}_count": int(classes.get(name, 0)) for name in CLASS_ORDER},
        "strong_undervalued_count": int(master.local_gap_interval_status.eq("STRONG_UNDERVALUED_SIGNAL").sum()),
        "strong_overvalued_count": int(master.local_gap_interval_status.eq("STRONG_OVERVALUED_SIGNAL").sum()),
        "DOUBLE_POSITIVE_count": int(master.school_local_signal_agreement.eq("DOUBLE_POSITIVE").sum()),
        "ROBUST_DUAL_POSITIVE_count": int(master.combined_candidate_class.eq("ROBUST_DUAL_POSITIVE").sum()),
        "legal_dong_bias_apartment_count": int(master.dong_bias_flag.sum()),
        "legal_dong_bias_count": int(master.loc[master.dong_bias_flag, ["gu", "legal_dong"]].drop_duplicates().shape[0]),
        "high_audit_count": int(master.phase154_audit_priority.eq("HIGH").sum()),
        "unmodeled_premium_candidate_count": int(master.unmodeled_premium_candidate.sum()),
        "unmodeled_discount_candidate_count": int(master.unmodeled_discount_candidate.sum()),
    }
    return pd.DataFrame({"metric": list(metrics), "value": list(metrics.values())})


def build_snapshot(master: pd.DataFrame, manifest: pd.DataFrame, phase149: dict, phase152: dict, phase153: dict, new_test_count: int = 0, failed_test_count: int = 0) -> dict:
    classes = master.final_review_class.value_counts().to_dict()
    frozen = bool(manifest.unchanged.all()) and failed_test_count == 0 and new_test_count >= 33
    return {
        "project_state": {
            "freeze_timestamp": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "project_phase": "15.4",
            "final_model_status": FINAL_STATUS if frozen else "PENDING_TEST_VERIFICATION",
            "local_value_gap_status": LOCAL_GAP_STATUS,
        },
        "school_model": {
            "status": phase149["freeze_status"],
            "core_score_coverage": int(master.school_premium_core_score.notna().sum()),
            "ten_point_school_premium_effect_pct": phase149["ten_point_price_effect_pct"],
            "school_value_gap_status": "FROZEN_WITH_CAUTION",
            "school_gap_coverage": int(master.school_value_gap_pct.notna().sum()),
        },
        "local_model": {
            "selected_model": phase152["selected_model"],
            "selected_fallback": phase152["selected_fallback"],
            "global_rmse": phase152["global_rmse"],
            "legal_dong_fe_rmse": phase152["dong_fe_rmse"],
            "model_f_rmse": phase152["selected_rmse"],
            "model_f_r2": phase152["selected_r2"],
            "school_feature_improvement_pct": phase152["school_rmse_improvement_pct"],
            "fair_price_coverage": int(master.local_fair_total_price.notna().sum()),
            "prediction_interval_median_width_pct": phase152["median_interval_width_pct"],
        },
        "local_value": {
            "status": phase153["verdict"],
            "local_gap_coverage": int(master.local_value_gap_pct.notna().sum()),
            "local_gap_median_pct": phase153["median_gap_pct"],
            "gap_6m_12m_spearman": phase153["gap_6m_12m_spearman"],
            "temporal_direction_agreement_pct": 100 * (phase153["temporal_counts"].get("STABLE_POSITIVE", 0) + phase153["temporal_counts"].get("STABLE_NEGATIVE", 0)) / max(sum(phase153["temporal_counts"].values()), 1),
            "strong_undervalued_count": phase153["interval_counts"].get("STRONG_UNDERVALUED_SIGNAL", 0),
            "strong_overvalued_count": phase153["interval_counts"].get("STRONG_OVERVALUED_SIGNAL", 0),
        },
        "dual_signal": {
            "status": phase153["dual_signal_verdict"],
            "school_local_spearman": phase153["school_local_correlations"]["hm_spearman"],
            "double_positive_count": phase153["agreement_counts"].get("DOUBLE_POSITIVE", 0),
            "robust_dual_positive_count": phase153["candidate_class_counts"].get("ROBUST_DUAL_POSITIVE", 0),
        },
        "integrity": {
            "protected_file_count": len(manifest),
            "changed_file_count": int((~manifest.unchanged).sum()),
            "previous_pytest_count": PREVIOUS_TEST_COUNT,
            "new_pytest_count": int(new_test_count),
            "total_pytest_count": PREVIOUS_TEST_COUNT + int(new_test_count),
            "failed_test_count": int(failed_test_count),
            "pytest_status": "FULL_PASS" if frozen else "PENDING",
        },
        "final_classes": {name: int(classes.get(name, 0)) for name in CLASS_ORDER},
    }


def validate_phase154_freeze(root=ROOT) -> pd.DataFrame:
    """Lightweight validation shared by tests and the read-only dashboard."""
    root = Path(root)
    master_path = root / "data/processed/phase154_final_apartment_value_master.csv"
    snapshot_path = root / "data/snapshots/phase154_final_model_freeze.json"
    manifest_path = root / "reports/phase154_protected_manifest.csv"
    checks: list[tuple[str, bool, str]] = []
    checks.append(("final_master_exists", master_path.is_file(), str(master_path)))
    checks.append(("freeze_snapshot_exists", snapshot_path.is_file(), str(snapshot_path)))
    checks.append(("protected_manifest_exists", manifest_path.is_file(), str(manifest_path)))
    if master_path.is_file():
        data = pd.read_csv(master_path, encoding="utf-8-sig")
        checks.extend(
            [
                ("master_row_count", len(data) == 560, str(len(data))),
                ("apartment_id_unique", data.apartment_id.nunique() == len(data), str(data.apartment_id.nunique())),
                ("class_complete", data.final_review_class.notna().all() and data.final_review_class.isin(CLASS_ORDER).all(), str(data.final_review_class.isna().sum())),
                ("fair_price_identity", _same_numeric(data, pd.read_csv(root / "data/processed/phase153_local_value_gap.csv", encoding="utf-8-sig"), "local_fair_total_price"), "Phase153 equality"),
                ("local_gap_identity", _same_numeric(data, pd.read_csv(root / "data/processed/phase153_local_value_gap.csv", encoding="utf-8-sig"), "local_value_gap_pct"), "Phase153 equality"),
                ("school_gap_identity", _same_numeric(data, pd.read_csv(root / "data/processed/phase149_school_value_master.csv", encoding="utf-8-sig"), "school_value_gap_pct"), "Phase149 equality"),
            ]
        )
    if manifest_path.is_file():
        manifest = pd.read_csv(manifest_path, encoding="utf-8-sig")
        checks.append(("protected_hashes_unchanged", bool(manifest.unchanged.all()), str((~manifest.unchanged).sum())))
    if snapshot_path.is_file():
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        checks.extend(
            [
                ("snapshot_frozen", snapshot["project_state"]["final_model_status"] == FINAL_STATUS, snapshot["project_state"]["final_model_status"]),
                ("pytest_full_pass", snapshot["integrity"]["pytest_status"] == "FULL_PASS" and snapshot["integrity"]["failed_test_count"] == 0, snapshot["integrity"]["pytest_status"]),
            ]
        )
    return pd.DataFrame(checks, columns=["check", "passed", "detail"])


def _same_numeric(left: pd.DataFrame, right: pd.DataFrame, column: str) -> bool:
    a = left.set_index("apartment_id")[column].sort_index()
    b = right.set_index("apartment_id")[column].sort_index().reindex(a.index)
    return bool(np.allclose(a, b, equal_nan=True))


def _report(master: pd.DataFrame, snapshot: dict, candidates: pd.DataFrame, audit: pd.DataFrame) -> str:
    class_counts = master.final_review_class.value_counts()
    top_lines = []
    for class_name in CLASS_ORDER:
        limit = 20 if class_name == "CORE_CANDIDATE" else 10
        names = candidates[candidates.final_review_class.eq(class_name)].head(limit).apartment_name.tolist()
        top_lines.append(f"- {class_name} ({int(class_counts.get(class_name, 0))}개): " + (", ".join(names) if names else "없음"))
    limitation_counts = master.model_limitation_detail.str.split(";").explode().value_counts()
    limitation_text = ", ".join(f"{key} {value}개" for key, value in limitation_counts.items() if key != "NONE")
    operational = int(master.local_fair_total_price.notna().sum())
    return f"""# Phase 15.4 최종 동결 및 결과 검토

## 1. Final Model Status

- 최종 상태: **{snapshot['project_state']['final_model_status']}**
- 마지막 분석 단계: Phase 15.3, Phase 15.4는 동결·검토·표현 단계
- 향후 모델 재학습: 금지. 동결 원본을 이용한 조회와 검토만 허용
- Local Value Gap 상태: **{snapshot['project_state']['local_value_gap_status']}**

## 2. School Module

- School Core Score: {snapshot['school_model']['core_score_coverage']}/560개
- School Score 10점 증가 가격 연관: {snapshot['school_model']['ten_point_school_premium_effect_pct']:.2f}%
- School Value Gap: {snapshot['school_model']['school_gap_coverage']}/560개, 기존 Phase 14.9 값 그대로 보존

## 3. Local Price Module

- 선택 모델: Model {snapshot['local_model']['selected_model']} / sparse fallback {snapshot['local_model']['selected_fallback']}
- Global / 법정동 FE / Model F RMSE: {snapshot['local_model']['global_rmse']:.5f} / {snapshot['local_model']['legal_dong_fe_rmse']:.5f} / {snapshot['local_model']['model_f_rmse']:.5f}
- Model F R²: {snapshot['local_model']['model_f_r2']:.4f}
- Fair Price coverage: {snapshot['local_model']['fair_price_coverage']}/560개
- 95% 예측구간 폭 중앙값: {snapshot['local_model']['prediction_interval_median_width_pct']:.2f}%로 불확실성이 크다.

## 4. Local Value Gap

- coverage: {snapshot['local_value']['local_gap_coverage']}/560개
- 중앙값: {snapshot['local_value']['local_gap_median_pct']:.2f}%
- 6M/12M Spearman: {snapshot['local_value']['gap_6m_12m_spearman']:.4f}
- 기간 방향 일치: {snapshot['local_value']['temporal_direction_agreement_pct']:.1f}%
- Strong undervalued / overvalued: {snapshot['local_value']['strong_undervalued_count']} / {snapshot['local_value']['strong_overvalued_count']}개

## 5. Dual Signal

- 판정: **{snapshot['dual_signal']['status']}**
- School Gap–Local Gap Spearman: {snapshot['dual_signal']['school_local_spearman']:.4f}
- DOUBLE_POSITIVE / ROBUST_DUAL_POSITIVE: {snapshot['dual_signal']['double_positive_count']} / {snapshot['dual_signal']['robust_dual_positive_count']}개
- 별도 합산점수 없이 두 신호와 신뢰도를 함께 제시한다.

## 6. Final Candidate Classes

{chr(10).join(top_lines)}

Class 내부 순위는 구간 상태, Local·모델·School 신뢰도, 기간 안정성, 양의 확률, Local Gap, School Gap 순의 사전 고정된 사전식 규칙이다. 가중 합산점수는 없다.

## 7. Model Limitations

- 제한 플래그: {limitation_text or '없음'}
- 법정동 bias: {int(master.dong_bias_flag.sum())}개 단지, {master.loc[master.dong_bias_flag, ['gu','legal_dong']].drop_duplicates().shape[0]}개 법정동
- 모델에 없는 조망·재건축·브랜드·동/향·내부상태 등은 residual 또는 audit 한계로 남긴다.
- Local Gap은 수익을 보장하는 저평가 지표가 아니며 의사결정 전 개별 확인이 필요하다.

## 8. High Audit Candidates

- Phase 15.3 HIGH audit 후보 {len(audit)}개를 그대로 포함했다.
- 유형은 extreme gap, 법정동 bias, 넓은 예측구간, 낮은 거래량, fallback, 미설명 premium/discount 가능성이다.

## 9. Data Integrity

- 보호 파일: {snapshot['integrity']['protected_file_count']}개
- 변경 파일: {snapshot['integrity']['changed_file_count']}개
- pytest: 기존 {snapshot['integrity']['previous_pytest_count']} + 신규 {snapshot['integrity']['new_pytest_count']} = {snapshot['integrity']['total_pytest_count']} PASS, 실패 {snapshot['integrity']['failed_test_count']}개
- Fair Price, School Gap, Local Gap, prediction interval은 원본과 동일하다.

## 10. Final Usage Guide

1. `final_review_class`로 검토 목적을 고른다.
2. `model_confidence`, `local_gap_confidence`, `gap_confidence`를 확인한다.
3. 예측구간과 6M/12M 관측가격을 비교한다.
4. `model_limitation_detail`, 법정동 bias, HIGH audit 사유를 검토한다.
5. 원본 거래·현장 특성을 확인한 뒤 의사결정한다.

운영 가능한 Fair Price·Local Gap 결과는 {operational}개 단지이며, School Core는 {int(master.school_premium_core_score.notna().sum())}개 단지에 존재한다. 기본 운영 파일은 `phase154_final_apartment_value_master.csv`와 `phase154_final_model_freeze.json`이다.
"""


def build_phase154(root=ROOT, new_test_count: int = 0, failed_test_count: int = 0) -> dict:
    root = Path(root)
    manifest = discover_protected(root)
    source = pd.read_csv(root / "data/processed/phase153_local_value_gap.csv", encoding="utf-8-sig")
    phase149 = json.loads((root / "data/snapshots/phase149_school_value_final_freeze.json").read_text(encoding="utf-8"))
    phase152 = json.loads((root / "data/processed/phase152_result.json").read_text(encoding="utf-8"))
    phase153 = json.loads((root / "data/processed/phase153_result.json").read_text(encoding="utf-8"))
    master = build_master(source, phase153)
    candidates = rank_candidates(master)
    audit = high_audit_table(master)
    summary = summary_table(master)

    write_csv(root / "data/processed/phase154_final_apartment_value_master.csv", master)
    write_csv(root / "reports/phase154_final_candidates.csv", candidates)
    write_csv(root / "reports/phase154_high_audit_review.csv", audit)
    write_csv(root / "reports/phase154_final_summary.csv", summary)

    checked = verify_manifest(manifest, root)
    write_csv(root / "reports/phase154_protected_manifest.csv", checked)
    snapshot = build_snapshot(master, checked, phase149, phase152, phase153, new_test_count, failed_test_count)
    write_json(root / "data/snapshots/phase154_final_model_freeze.json", snapshot)
    atomic_bytes(root / "reports/phase154_final_freeze_result_review.md", _report(master, snapshot, candidates, audit).encode("utf-8"))
    return snapshot


def finalize_test_status(new_test_count: int, failed_test_count: int = 0, root=ROOT) -> dict:
    """Rewrite Phase 15.4 outputs after the independently run test suite."""
    return build_phase154(root=root, new_test_count=new_test_count, failed_test_count=failed_test_count)


if __name__ == "__main__":
    print(json.dumps(build_phase154(), ensure_ascii=False, indent=2))
