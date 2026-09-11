"""Phase 13.5-14.5: freeze, price-effect, and school-value-gap validation."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.preprocessing import SplineTransformer

from .config import ROOT, atomic_bytes, write_csv, write_json, write_parquet


APARTMENT_ROOT = ROOT.parent / "busan_apartment_analysis"
SCORE_REFERENCE = 50.0
MIN_COMPARABLES = 5
RANDOM_SEED = 20260911
AREA_BANDS = ("area_group",)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_protected_artifacts(root=ROOT) -> pd.DataFrame:
    """Discover existing Phase 7-13 artifacts without including this phase's outputs."""
    root = Path(root)
    found: set[Path] = set()
    for folder in ("src", "tests", "data/processed", "data/snapshots", "reports"):
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            match = re.search(r"phase(7|8|9|10|11|115|12|125|13)(?![0-9])", name)
            if match and not re.search(r"phase(135|14|145)", name):
                found.add(path)
    for relative in (
        "data/processed/busan_apartment_school_scores_2026.parquet",
        "data/processed/elementary_feeder_scores_2026.parquet",
        "data/processed/elementary_middle_score_detail_2026.parquet",
        "data/processed/busan_elementary_middle_relation_2026.parquet",
        "config/manual_elementary_middle_overrides.csv",
    ):
        path = root / relative
        if path.exists():
            found.add(path)
    rows = []
    for path in sorted(found):
        relative = path.relative_to(root).as_posix()
        match = re.search(r"phase(7|8|9|10|11|115|12|125|13)(?![0-9])", path.name.lower())
        phase = match.group(1) if match else "CORE"
        phase = {"115": "11.5", "125": "12.5"}.get(phase, phase)
        rows.append({
            "path": relative, "phase": phase, "file_size": path.stat().st_size,
            "sha256_before": _sha(path), "sha256_after": "", "unchanged": False,
        })
    return pd.DataFrame(rows)


def verify_manifest(manifest: pd.DataFrame, root=ROOT) -> pd.DataFrame:
    root = Path(root)
    out = manifest.copy()
    after = []
    for relative in out.path:
        path = root / relative
        after.append(_sha(path) if path.exists() else "MISSING")
    out["sha256_after"] = after
    out["unchanged"] = out.sha256_before.eq(out.sha256_after)
    if not out.unchanged.all():
        changed = out.loc[~out.unchanged, "path"].tolist()
        raise RuntimeError(f"PROTECTED_ARTIFACT_MODIFIED: {changed}")
    return out


def finalize_manifest(manifest: pd.DataFrame, root=ROOT) -> pd.DataFrame:
    root = Path(root)
    out = verify_manifest(manifest, root)
    write_csv(root / "reports/phase135_protected_manifest.csv", out)
    return out


def build_transaction_sample(root=ROOT) -> pd.DataFrame:
    root = Path(root)
    index = pd.read_csv(root / "data/processed/phase13_school_premium_index.csv", encoding="utf-8-sig")
    scores = pd.read_parquet(root / "data/processed/busan_apartment_school_scores_2026.parquet")
    kapt = pd.read_parquet(APARTMENT_ROOT / "data/interim/kapt_clean.parquet")
    metadata = scores[["internal_complex_id", "kapt_code"]].merge(
        kapt[["kapt_code", "apartment_age", "parking_per_household"]],
        on="kapt_code", how="left", validate="many_to_one",
    )
    apartment = index.merge(
        metadata, left_on="apartment_id", right_on="internal_complex_id",
        how="left", validate="one_to_one",
    )
    trades = pd.read_parquet(APARTMENT_ROOT / "data/interim/trade_matched.parquet")
    trades = trades[
        trades.internal_complex_id.isin(apartment.apartment_id)
        & ~trades.is_cancelled.fillna(False)
    ].copy()
    keep = [
        "apartment_id", "apartment_name", "household_count", "sigungu", "legal_dong",
        "elementary_name", "school_premium_core_score", "school_premium_addon_score",
        "school_premium_confidence", "data_quality_flag", "has_guaranteed_assignment",
        "apartment_age", "parking_per_household",
    ]
    out = trades.merge(
        apartment[keep], left_on="internal_complex_id", right_on="apartment_id",
        how="inner", validate="many_to_one",
    )
    out["transaction_date"] = pd.to_datetime(out.deal_date)
    start = out.transaction_date.min().to_period("M")
    out["transaction_month_index"] = (
        (out.transaction_date.dt.year - start.year) * 12
        + out.transaction_date.dt.month - start.month
    ).astype(float)
    out["transaction_price"] = pd.to_numeric(out.deal_amount_krw, errors="coerce")
    out["exclusive_area"] = pd.to_numeric(out.area_sqm, errors="coerce")
    out["district"] = out.sigungu_y
    out["log_households"] = np.log(pd.to_numeric(out.household_count, errors="coerce").replace(0, np.nan))
    columns = [
        "apartment_id", "apartment_name", "household_count", "district", "legal_dong",
        "elementary_name", "school_premium_core_score", "school_premium_addon_score",
        "school_premium_confidence", "data_quality_flag", "has_guaranteed_assignment",
        "transaction_date", "transaction_month_index", "transaction_price", "price_per_sqm",
        "exclusive_area", "floor", "area_group", "apartment_age", "parking_per_household",
    ]
    return out[columns].sort_values(["transaction_date", "apartment_id"]).reset_index(drop=True)


def complete_model_sample(frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "school_premium_core_score", "price_per_sqm", "exclusive_area", "floor",
        "area_group", "apartment_age", "parking_per_household", "log_households",
        "legal_dong", "transaction_month_index", "apartment_id",
    ]
    out = frame.copy()
    out["log_households"] = np.log(pd.to_numeric(out.household_count, errors="coerce").replace(0, np.nan))
    valid = out[required].notna().all(axis=1)
    valid &= np.isfinite(pd.to_numeric(out.price_per_sqm, errors="coerce")) & out.price_per_sqm.gt(0)
    return out.loc[valid].copy()


def _control_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    d = frame.reset_index(drop=True)
    x = pd.DataFrame({"const": np.ones(len(d))})
    for column in ("log_households", "floor", "apartment_age", "parking_per_household", "transaction_month_index"):
        x[column] = pd.to_numeric(d[column], errors="coerce").to_numpy(dtype=float)
    x = pd.concat([
        x,
        pd.get_dummies(d.area_group, prefix="area_group", drop_first=True, dtype=float).reset_index(drop=True),
        pd.get_dummies(d.legal_dong, prefix="legal_dong", drop_first=True, dtype=float).reset_index(drop=True),
    ], axis=1)
    return x


def school_basis(scores, model: str) -> tuple[pd.DataFrame, list[str]]:
    score = np.asarray(scores, dtype=float)
    score10 = (score - SCORE_REFERENCE) / 10.0
    if model == "LINEAR":
        out = pd.DataFrame({"school_score_10": score10})
    elif model == "QUADRATIC":
        out = pd.DataFrame({"school_score_10": score10, "school_score_10_sq": score10 ** 2})
    elif model == "BINNED":
        labels = ["score_0_20", "score_20_40", "score_40_60", "score_60_80", "score_80_100"]
        category = pd.cut(score, [-np.inf, 20, 40, 60, 80, np.inf], labels=labels, right=False)
        out = pd.get_dummies(category, dtype=float).drop(columns=["score_40_60"]).reset_index(drop=True)
    elif model == "SPLINE":
        transformer = SplineTransformer(
            degree=3, knots=np.array([0, 20, 40, 60, 80, 100], dtype=float)[:, None],
            include_bias=False, extrapolation="linear",
        )
        values = transformer.fit_transform(score[:, None])
        out = pd.DataFrame(values, columns=[f"school_spline_{i}" for i in range(values.shape[1])])
    elif model == "NONE":
        out = pd.DataFrame(index=range(len(score)))
    else:
        raise ValueError(model)
    return out, out.columns.tolist()


def design_matrix(frame: pd.DataFrame, model: str) -> tuple[pd.DataFrame, list[str]]:
    controls = _control_matrix(frame)
    basis, school_columns = school_basis(frame.school_premium_core_score, model)
    return pd.concat([controls, basis], axis=1).astype(float), school_columns


def fit_ols(y, x: pd.DataFrame, groups=None, clustered=False):
    y = np.asarray(y, dtype=float)
    X = x.to_numpy(dtype=float)
    beta = np.linalg.pinv(X.T @ X) @ X.T @ y
    prediction = X @ beta
    residual = y - prediction
    n, k = X.shape
    sse = float(residual @ residual)
    sigma = max(sse / n, 1e-15)
    loglike = -n / 2 * (math.log(2 * math.pi) + 1 + math.log(sigma))
    covariance = np.linalg.pinv(X.T @ X) * sse / max(n - k, 1)
    if clustered:
        values = np.asarray(groups)
        inverse = np.linalg.pinv(X.T @ X)
        meat = np.zeros_like(inverse)
        unique = np.unique(values)
        for group in unique:
            indices = np.flatnonzero(values == group)
            score = X[indices].T @ residual[indices, None]
            meat += score @ score.T
        correction = (len(unique) / max(len(unique) - 1, 1)) * ((n - 1) / max(n - k, 1))
        covariance = inverse @ meat @ inverse * correction
    r2 = 1 - sse / float(((y - y.mean()) ** 2).sum())
    return {
        "beta": beta, "covariance": covariance, "prediction": prediction, "residual": residual,
        "rmse": float(np.sqrt(np.mean(residual ** 2))), "mae": float(np.mean(np.abs(residual))),
        "r_squared": r2, "adjusted_r_squared": 1 - (1 - r2) * (n - 1) / max(n - k, 1),
        "aic": 2 * k - 2 * loglike, "bic": k * math.log(n) - 2 * loglike,
        "n": n, "k": k,
    }


def school_effect(model_fit, columns, school_columns, model: str, scores) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    basis, _ = school_basis(scores, model)
    reference, _ = school_basis(np.repeat(SCORE_REFERENCE, len(basis)), model)
    delta = basis.to_numpy() - reference.to_numpy()
    indices = [columns.index(c) for c in school_columns]
    beta = model_fit["beta"][indices]
    covariance = model_fit["covariance"][np.ix_(indices, indices)]
    log_effect = delta @ beta
    variance = np.einsum("ij,jk,ik->i", delta, covariance, delta)
    se = np.sqrt(np.maximum(variance, 0))
    return log_effect, log_effect - 1.96 * se, log_effect + 1.96 * se


def compare_price_models(frame: pd.DataFrame):
    d = complete_model_sample(frame).sort_values(["transaction_date", "apartment_id"]).reset_index(drop=True)
    y = np.log(d.price_per_sqm.to_numpy(dtype=float))
    cutoff = d.transaction_date.quantile(.75)
    train = d.transaction_date.le(cutoff).to_numpy()
    rows, fitted = [], {}
    for model in ("NONE", "LINEAR", "QUADRATIC", "BINNED", "SPLINE"):
        x, school_columns = design_matrix(d, model)
        full = fit_ols(y, x, d.apartment_id, clustered=model in {"NONE", "LINEAR", "QUADRATIC", "SPLINE"})
        temporal = fit_ols(y[train], x.loc[train])
        prediction = x.loc[~train].to_numpy() @ temporal["beta"]
        error = y[~train] - prediction
        calibration = np.polyfit(prediction, y[~train], 1) if len(prediction) else [np.nan, np.nan]
        monotonic = True
        if model != "NONE":
            grid = np.arange(0, 101, dtype=float)
            effect, _, _ = school_effect(full, x.columns.tolist(), school_columns, model, grid)
            monotonic = bool(np.all(np.diff(effect) >= -1e-7))
        rows.append({
            "model": f"MODEL_{model}", "n_transactions": len(d), "n_apartments": d.apartment_id.nunique(),
            "train_end": cutoff, "train_transactions": int(train.sum()), "test_transactions": int((~train).sum()),
            "future_leakage": bool(d.loc[train, "transaction_date"].max() >= d.loc[~train, "transaction_date"].min()),
            "adjusted_r_squared": full["adjusted_r_squared"], "aic": full["aic"], "bic": full["bic"],
            "rmse_insample": full["rmse"], "mae_insample": full["mae"],
            "rmse_oos": float(np.sqrt(np.mean(error ** 2))), "mae_oos": float(np.mean(np.abs(error))),
            "r2_oos": 1 - float(error @ error) / float(((y[~train] - y[~train].mean()) ** 2).sum()),
            "calibration_slope": float(calibration[0]), "calibration_intercept": float(calibration[1]),
            "monotonic": monotonic, "parameter_count": full["k"],
        })
        fitted[model] = {"fit": full, "x": x, "school_columns": school_columns}
    comparison = pd.DataFrame(rows)
    linear = comparison.set_index("model").loc["MODEL_LINEAR"]
    candidates = comparison[
        comparison.model.isin(["MODEL_QUADRATIC", "MODEL_BINNED", "MODEL_SPLINE"])
        & comparison.monotonic
        & comparison.rmse_oos.le(linear.rmse_oos * .995)
        & comparison.mae_oos.le(linear.mae_oos * .995)
    ]
    selected = "LINEAR" if candidates.empty else candidates.sort_values(["rmse_oos", "mae_oos", "parameter_count"]).iloc[0].model.removeprefix("MODEL_")
    return d, comparison, fitted, selected


def _residual_relation(frame, residual, segment, level) -> dict:
    d = frame.copy()
    d["residual"] = np.asarray(residual)
    x = pd.DataFrame({"const": 1.0, "school_score_10": (d.school_premium_core_score - 50) / 10})
    fit = fit_ols(d.residual, x, d.apartment_id, clustered=True)
    index = x.columns.get_loc("school_score_10")
    coefficient = fit["beta"][index]
    se = math.sqrt(max(fit["covariance"][index, index], 0))
    groups = max(d.apartment_id.nunique() - 1, 1)
    pvalue = 2 * stats.t.sf(abs(coefficient / se), groups) if se else np.nan
    apartment = d.groupby("apartment_id", as_index=False).agg(
        score=("school_premium_core_score", "first"), residual=("residual", "median")
    )
    return {
        "segment": segment, "location_level": level, "transaction_count": len(d),
        "apartment_count": d.apartment_id.nunique(), "coefficient_per_10": coefficient,
        "standard_error": se, "p_value": pvalue, "ci95_low": coefficient - 1.96 * se,
        "ci95_high": coefficient + 1.96 * se, "r_squared": fit["r_squared"],
        "spearman": apartment.score.corr(apartment.residual, method="spearman"),
        "pearson": apartment.score.corr(apartment.residual, method="pearson"),
    }


def _within_location(frame, residual) -> pd.DataFrame:
    d = frame.copy()
    d["residual"] = np.asarray(residual)
    apartment = d.groupby(["apartment_id", "district", "legal_dong"], as_index=False).agg(
        score=("school_premium_core_score", "first"), price=("price_per_sqm", "median"),
        residual=("residual", "median"),
    )
    rows = []
    for level, keys in (("LEGAL_DONG", ["district", "legal_dong"]), ("DISTRICT", ["district"])):
        eligible = apartment.groupby(keys).apartment_id.transform("nunique").ge(3)
        a = apartment[eligible].copy()
        score = a.score - a.groupby(keys).score.transform("mean")
        price = a.price - a.groupby(keys).price.transform("mean")
        rows.append({
            "location_level": level, "sample_count": len(a), "apartment_count": a.apartment_id.nunique(),
            "group_count": a.groupby(keys).ngroups, "spearman": score.corr(price, method="spearman"),
            "pearson": score.corr(price, method="pearson"),
            "partial_residual_spearman": a.score.corr(a.residual, method="spearman"),
            "status": "AVAILABLE",
        })
    rows.append({
        "location_level": "ADMIN_DONG", "sample_count": 0, "apartment_count": 0,
        "group_count": 0, "spearman": np.nan, "pearson": np.nan,
        "partial_residual_spearman": np.nan, "status": "ADMIN_DONG_NOT_AVAILABLE",
    })
    return pd.DataFrame(rows)


def recent_apartment_prices(transactions: pd.DataFrame) -> pd.DataFrame:
    end = transactions.transaction_date.max()
    rows = []
    for apartment_id, group in transactions.groupby("apartment_id", sort=True):
        choice = None
        for months, minimum in ((6, 3), (12, 3), (24, 1)):
            start = end - pd.DateOffset(months=months) + pd.Timedelta(days=1)
            candidate = group[group.transaction_date.between(start, end)]
            if len(candidate) >= minimum:
                choice = (months, candidate)
                break
        if choice is None:
            continue
        months, candidate = choice
        rows.append({
            "apartment_id": apartment_id, "price_window_used": f"{months}M",
            "transaction_count": len(candidate), "representative_area_m2": candidate.exclusive_area.median(),
            "recent_market_price": candidate.transaction_price.median(),
            "recent_market_price_per_m2": candidate.price_per_sqm.median(),
            "recent_transaction_date": candidate.transaction_date.max(),
        })
    return pd.DataFrame(rows)


def build_phase135(root, transactions, model_data, baseline_fit, baseline_residual):
    root = Path(root)
    recent_cutoff = transactions.transaction_date.max() - pd.DateOffset(months=12) + pd.Timedelta(days=1)
    recent = model_data[model_data.transaction_date.ge(recent_cutoff)].copy()
    recent_indices = recent.index
    residual = pd.Series(baseline_residual, index=model_data.index).loc[recent_indices].to_numpy()
    within = _within_location(recent, residual)
    write_csv(root / "reports/phase135_within_location_robustness.csv", within)
    relation = pd.DataFrame([_residual_relation(recent, residual, "ALL", "BASELINE_RESIDUAL")])
    write_csv(root / "reports/phase135_residual_price_validation.csv", relation)

    count = model_data.groupby("apartment_id").size()
    volume = model_data.apartment_id.map(count)
    volume_band = pd.cut(volume, [-np.inf, 29, 99, np.inf], labels=["LOW_LT30", "MID_30_99", "HIGH_GE100"])
    volume_rows = []
    for band in volume_band.cat.categories:
        mask = volume_band.eq(band).to_numpy()
        if mask.sum() and model_data.loc[mask, "apartment_id"].nunique() >= 3:
            volume_rows.append(_residual_relation(model_data.loc[mask], np.asarray(baseline_residual)[mask], str(band), "TRANSACTION_VOLUME"))
    volume_table = pd.DataFrame(volume_rows)
    write_csv(root / "reports/phase135_transaction_volume_robustness.csv", volume_table)

    confidence_rows = []
    for confidence, group in model_data.groupby("school_premium_confidence"):
        mask = model_data.index.isin(group.index)
        confidence_rows.append(_residual_relation(group, np.asarray(baseline_residual)[mask], str(confidence), "CONFIDENCE"))
    confidence_table = pd.DataFrame(confidence_rows)
    write_csv(root / "reports/phase135_confidence_robustness.csv", confidence_table)

    prices = recent_apartment_prices(transactions)
    apartment_residual = model_data.assign(non_school_price_residual=baseline_residual).groupby("apartment_id").non_school_price_residual.median()
    phase13 = pd.read_csv(root / "data/processed/phase13_school_premium_index.csv", encoding="utf-8-sig")
    audit = phase13.merge(prices, on="apartment_id", how="left").merge(
        apartment_residual.rename("residual_premium"), left_on="apartment_id", right_index=True, how="left"
    )
    audit["transaction_count"] = audit.transaction_count.fillna(0).astype(int)
    residual_z = (audit.residual_premium - audit.residual_premium.mean()) / audit.residual_premium.std()
    reasons = np.select(
        [audit.transaction_count.lt(3), audit.school_premium_confidence.eq("C"), residual_z.abs().gt(3), audit.data_quality_flag.ne("OK")],
        ["EXTREMELY_LOW_TRANSACTION_COUNT", "MAPPING_UNCERTAINTY", "PRICE_OUTLIER", audit.data_quality_flag], default="",
    )
    audit["sanity_flag"] = pd.Series(reasons).ne("")
    audit["sanity_reason"] = reasons
    selections = []
    specifications = [
        ("CORE_TOP_30", "school_premium_core_score", False), ("CORE_BOTTOM_30", "school_premium_core_score", True),
        ("RESIDUAL_TOP_30", "residual_premium", False), ("RESIDUAL_BOTTOM_30", "residual_premium", True),
    ]
    for label, column, ascending in specifications:
        subset = audit.dropna(subset=[column]).sort_values([column, "apartment_id"], ascending=[ascending, True], kind="mergesort").head(30).copy()
        subset["audit_segment"] = label
        selections.append(subset)
    sanity = pd.concat(selections, ignore_index=True).drop_duplicates(["apartment_id", "audit_segment"])
    sanity_columns = [
        "audit_segment", "apartment_id", "apartment_name", "legal_dong", "sigungu", "household_count",
        "elementary_name", "school_premium_core_score", "school_premium_confidence",
        "recent_market_price", "residual_premium", "transaction_count", "has_guaranteed_assignment",
        "sanity_flag", "sanity_reason",
    ]
    write_csv(root / "reports/phase135_top_bottom_sanity_audit.csv", sanity[sanity_columns])

    missing = phase13[phase13.school_premium_core_score.isna()].copy()
    missing_out = pd.DataFrame({
        "apartment_id": missing.apartment_id, "apartment_name": missing.apartment_name,
        "household_count": missing.household_count, "missing_reason": missing.data_quality_flag,
        "source_status": "ELEMENTARY_DEMAND_MISSING_API",
        "recommended_action": "학교알리미 공식 데이터 관측 시 재검증; 현재 점수 미추정 유지",
    })
    write_csv(root / "reports/phase135_missing_school_score_apartments.csv", missing_out)

    legal_positive = float(within.loc[within.location_level.eq("LEGAL_DONG"), "spearman"].iloc[0]) > 0
    residual_positive = relation.coefficient_per_10.iloc[0] > 0
    volume_positive = int((volume_table.coefficient_per_10 > 0).sum()) >= 2
    ab = confidence_table[confidence_table.segment.isin(["A", "B"])]
    confidence_consistent = len(ab) == 2 and (ab.coefficient_per_10 > 0).all()
    fatal = len(phase13) != 560 or not phase13.apartment_id.is_unique or len(missing) != 3
    criteria = {
        "within_dong_positive": bool(legal_positive), "residual_relation_positive": bool(residual_positive),
        "multiple_volume_bands_positive": bool(volume_positive), "confidence_a_b_consistent": bool(confidence_consistent),
        "no_critical_mapping_error": bool(not fatal),
    }
    score = sum(criteria.values())
    verdict = "SCHOOL_PREMIUM_INDEX_NOT_READY" if fatal else "SCHOOL_PREMIUM_INDEX_FROZEN" if score >= 4 else "SCHOOL_PREMIUM_INDEX_FREEZE_WITH_CAUTION"
    result = {
        "verdict": verdict, "criteria": criteria, "phase13_apartments": len(phase13),
        "model_transactions": len(model_data), "model_apartments": model_data.apartment_id.nunique(),
        "recent_transactions": len(recent), "recent_apartments": recent.apartment_id.nunique(),
        "within_legal_dong_spearman": float(within.loc[within.location_level.eq("LEGAL_DONG"), "spearman"].iloc[0]),
        "residual_coefficient_per_10": float(relation.coefficient_per_10.iloc[0]),
        "residual_p_value": float(relation.p_value.iloc[0]), "sanity_flag_count": int(audit.sanity_flag.sum()),
        "missing_score_apartments": len(missing),
    }
    write_json(root / "data/processed/phase135_result.json", result)
    report = f"""# Phase 13.5 School Premium Freeze Validation

- 분석 거래/단지: {len(model_data):,}건 / {model_data.apartment_id.nunique():,}개
- 최근 12개월 거래/단지: {len(recent):,}건 / {recent.apartment_id.nunique():,}개
- 법정동 내부 Spearman: {result['within_legal_dong_spearman']:.4f}
- 비학군 가격 residual에 대한 Core score 10점 계수: {result['residual_coefficient_per_10']:.5f} (p={result['residual_p_value']:.4g})
- 거래량 구간별 양의 계수: {int((volume_table.coefficient_per_10 > 0).sum())}/{len(volume_table)}
- Confidence A/B 계수 방향 일치: {confidence_consistent}
- 사람이 확인할 sanity flag: {result['sanity_flag_count']}개
- 점수 미생성 단지: {len(missing)}개(추정·대체하지 않음)
- 행정동은 현재 공식 연결키가 없어 `ADMIN_DONG_NOT_AVAILABLE`로 기록했다.
- 판정: **{verdict}**

본 분석은 관측자료의 조건부 연관성 검증이며 인과효과를 뜻하지 않는다.
"""
    atomic_bytes(root / "reports/phase135_school_premium_freeze_validation.md", report.encode("utf-8"))
    return result, audit


def build_phase14(root, transactions, model_data, comparison, fitted, selected):
    root = Path(root)
    write_csv(root / "reports/phase14_model_comparison.csv", comparison)
    selected_data = fitted[selected]
    fit = selected_data["fit"]
    x = selected_data["x"]
    columns = x.columns.tolist()
    school_columns = selected_data["school_columns"]
    grid = np.arange(0, 101, dtype=float)
    effect, lower, upper = school_effect(fit, columns, school_columns, selected, grid)
    curve = pd.DataFrame({
        "school_score": grid, "predicted_log_price": effect,
        "relative_price_effect_pct": np.expm1(effect) * 100,
        "lower_ci_pct": np.expm1(lower) * 100, "upper_ci_pct": np.expm1(upper) * 100,
        "reference_score": SCORE_REFERENCE, "selected_model": selected,
    })
    write_csv(root / "reports/phase14_school_score_price_effect_curve.csv", curve)

    # Model coefficients use apartment-clustered covariance.
    coefficient_rows = []
    for column in school_columns:
        index = columns.index(column)
        coefficient = fit["beta"][index]
        se = math.sqrt(max(fit["covariance"][index, index], 0))
        pvalue = 2 * stats.t.sf(abs(coefficient / se), max(model_data.apartment_id.nunique() - 1, 1)) if se else np.nan
        coefficient_rows.append({
            "model": selected, "variable": column, "coefficient": coefficient,
            "standard_error": se, "p_value": pvalue, "ci95_low": coefficient - 1.96 * se,
            "ci95_high": coefficient + 1.96 * se,
        })
    write_csv(root / "reports/phase14_school_model_coefficients.csv", pd.DataFrame(coefficient_rows))

    # Predict actual score and the fixed reference score with identical controls.
    basis_reference, _ = school_basis(np.repeat(SCORE_REFERENCE, len(model_data)), selected)
    x_reference = x.copy()
    x_reference[school_columns] = basis_reference.to_numpy()
    prediction_actual = x.to_numpy() @ fit["beta"]
    prediction_reference = x_reference.to_numpy() @ fit["beta"]
    prediction_table = model_data[["apartment_id", "transaction_date", "transaction_price", "exclusive_area"]].copy()
    prediction_table["baseline_expected_price_row"] = np.exp(prediction_reference) * prediction_table.exclusive_area
    prediction_table["school_adjusted_expected_price_row"] = np.exp(prediction_actual) * prediction_table.exclusive_area
    prediction_table["school_effect_log"] = prediction_actual - prediction_reference
    write_parquet(root / "data/processed/phase14_transaction_predictions.parquet", prediction_table)

    recent = recent_apartment_prices(transactions)
    end = transactions.transaction_date.max()
    rows = []
    phase13 = pd.read_csv(root / "data/processed/phase13_school_premium_index.csv", encoding="utf-8-sig")
    for apartment_id, apartment in phase13.set_index("apartment_id").iterrows():
        price = recent[recent.apartment_id.eq(apartment_id)]
        if price.empty:
            rows.append({"apartment_id": apartment_id})
            continue
        price = price.iloc[0]
        months = int(str(price.price_window_used).removesuffix("M"))
        start = end - pd.DateOffset(months=months) + pd.Timedelta(days=1)
        subset = prediction_table[
            prediction_table.apartment_id.eq(apartment_id)
            & prediction_table.transaction_date.between(start, end)
        ]
        if subset.empty or pd.isna(apartment.school_premium_core_score):
            rows.append({"apartment_id": apartment_id, **price.to_dict()})
            continue
        score = float(apartment.school_premium_core_score)
        curve_row = curve.iloc[int(np.clip(round(score), 0, 100))]
        baseline = subset.baseline_expected_price_row.median()
        adjusted = subset.school_adjusted_expected_price_row.median()
        rows.append({
            "apartment_id": apartment_id, **price.to_dict(), "baseline_expected_price": baseline,
            "school_adjusted_expected_price": adjusted,
            "estimated_school_premium_pct": (adjusted / baseline - 1) * 100,
            "estimated_school_premium_amount": adjusted - baseline,
            "model_uncertainty_pct": (curve_row.upper_ci_pct - curve_row.lower_ci_pct) / 2,
        })
    estimates = pd.DataFrame(rows)
    duplicate = [c for c in estimates.columns if c != "apartment_id" and c in phase13.columns]
    estimates = estimates.drop(columns=duplicate, errors="ignore")
    output = phase13.merge(estimates, on="apartment_id", how="left", validate="one_to_one")
    output["as_of_date"] = end.date().isoformat()
    output = output.rename(columns={"sigungu": "gu", "elementary_name": "elementary_school_name"})
    required = [
        "apartment_id", "apartment_name", "legal_dong", "gu", "household_count",
        "elementary_school_name", "school_premium_core_score", "school_premium_confidence",
        "representative_area_m2", "recent_market_price", "baseline_expected_price",
        "school_adjusted_expected_price", "estimated_school_premium_pct",
        "estimated_school_premium_amount", "model_uncertainty_pct", "transaction_count",
        "price_window_used", "as_of_date", "data_quality_flag",
    ]
    write_csv(root / "data/processed/phase14_apartment_school_premium_value.csv", output[required])

    linear = fitted["LINEAR"]
    linear_effect, _, _ = school_effect(
        linear["fit"], linear["x"].columns.tolist(), linear["school_columns"], "LINEAR",
        output.school_premium_core_score.fillna(SCORE_REFERENCE),
    )
    output["linear_school_premium_pct"] = np.expm1(linear_effect) * 100
    result = {
        "selected_model": selected, "reference_score": SCORE_REFERENCE,
        "model_transactions": len(model_data), "model_apartments": model_data.apartment_id.nunique(),
        "priced_apartments": int(output.estimated_school_premium_pct.notna().sum()),
        "oos_rmse": float(comparison.set_index("model").loc[f"MODEL_{selected}", "rmse_oos"]),
        "oos_mae": float(comparison.set_index("model").loc[f"MODEL_{selected}", "mae_oos"]),
        "premium_median": float(output.estimated_school_premium_pct.median()),
        "premium_p25": float(output.estimated_school_premium_pct.quantile(.25)),
        "premium_p75": float(output.estimated_school_premium_pct.quantile(.75)),
    }
    linear_40 = float(curve.loc[curve.school_score.eq(40), "relative_price_effect_pct"].iloc[0])
    linear_50 = float(curve.loc[curve.school_score.eq(50), "relative_price_effect_pct"].iloc[0])
    linear_60 = float(curve.loc[curve.school_score.eq(60), "relative_price_effect_pct"].iloc[0])
    result["ten_point_effect_at_50_pct"] = (1 + linear_60 / 100) / (1 + linear_50 / 100) * 100 - 100
    write_json(root / "data/processed/phase14_result.json", result)
    points = curve[curve.school_score.isin([20, 40, 60, 80, 100])][["school_score", "relative_price_effect_pct"]]
    report = f"""# Phase 14 School Premium Price Effect

- 동일 표본 Model_NS/Model_S: {len(model_data):,}건, {model_data.apartment_id.nunique():,}개 단지
- 선택 모델: **{selected}**
- 기준 점수: {SCORE_REFERENCE:.0f}점
- 50점에서 60점으로 증가할 때 모델상 가격차이: {result['ten_point_effect_at_50_pct']:.2f}%
- Temporal OOS RMSE/MAE: {result['oos_rmse']:.5f} / {result['oos_mae']:.5f}
- 프리미엄 계산 가능 단지: {result['priced_apartments']}개
- 아파트별 예상 프리미엄 중앙값/P25/P75: {result['premium_median']:.2f}% / {result['premium_p25']:.2f}% / {result['premium_p75']:.2f}%

## 점수별 기준점 대비 모델 가격차이

```csv
{points.to_csv(index=False)}```

가격효과는 동일 통제조건에서 관측된 연관성이다. 인과효과나 개별 단지의 감정가격으로 해석하지 않는다.
"""
    atomic_bytes(root / "reports/phase14_school_premium_price_effect.md", report.encode("utf-8"))
    return result, output, curve


RELAXATION_RULES = (
    ("STRICT_SAME_DONG", .10, 5, math.log(1.5), False),
    ("RELAXED_SAME_DONG_1", .15, 10, math.log(2.0), False),
    ("RELAXED_SAME_DONG_2", .20, 15, math.log(3.0), False),
    ("ALL_SAME_DONG", np.inf, np.inf, np.inf, False),
    ("DISTRICT_RELAXED", .20, 15, math.log(3.0), True),
)


def comparable_match(row: pd.Series, candidates: pd.DataFrame, minimum=MIN_COMPARABLES) -> dict:
    pool = candidates[candidates.apartment_id.ne(row.apartment_id)]
    for rule, area_tolerance, age_tolerance, household_tolerance, district_level in RELAXATION_RULES:
        location = pool.district.eq(row.district) if district_level else pool.legal_dong.eq(row.legal_dong) & pool.district.eq(row.district)
        match = pool[location].copy()
        if np.isfinite(area_tolerance):
            match = match[(match.representative_area_m2 / row.representative_area_m2 - 1).abs().le(area_tolerance)]
        if np.isfinite(age_tolerance):
            match = match[(match.apartment_age - row.apartment_age).abs().le(age_tolerance)]
        if np.isfinite(household_tolerance):
            match = match[(np.log(match.household_count) - math.log(row.household_count)).abs().le(household_tolerance)]
        if len(match) >= minimum:
            median = match.recent_market_price_per_m2.median()
            return {"comparable_count": len(match), "comparable_rule": rule, "comparable_median_price_per_m2": median,
                    "observed_comparable_premium_pct": (row.recent_market_price_per_m2 / median - 1) * 100}
    return {"comparable_count": 0, "comparable_rule": "INSUFFICIENT_COMPARABLES",
            "comparable_median_price_per_m2": np.nan, "observed_comparable_premium_pct": np.nan}


def build_phase145(root, phase14_output, linear_premium):
    root = Path(root)
    kapt = pd.read_parquet(APARTMENT_ROOT / "data/interim/kapt_clean.parquet")
    scores = pd.read_parquet(root / "data/processed/busan_apartment_school_scores_2026.parquet")[["internal_complex_id", "kapt_code"]]
    attributes = scores.merge(
        kapt[["kapt_code", "apartment_age"]], on="kapt_code", how="left", validate="many_to_one"
    )[["internal_complex_id", "apartment_age"]]
    work = phase14_output.merge(attributes, left_on="apartment_id", right_on="internal_complex_id", how="left", validate="one_to_one")
    comparable_base = work.dropna(subset=[
        "recent_market_price_per_m2", "representative_area_m2", "apartment_age", "household_count", "legal_dong", "gu"
    ]).rename(columns={"gu": "district"})
    matches = []
    for _, row in comparable_base.sort_values("apartment_id").iterrows():
        matches.append({"apartment_id": row.apartment_id, **comparable_match(row, comparable_base)})
    match_table = pd.DataFrame(matches)
    work = work.merge(match_table, on="apartment_id", how="left", validate="one_to_one")
    work["baseline_non_school_price"] = work.baseline_expected_price
    work["expected_school_premium_pct"] = work.estimated_school_premium_pct
    work["expected_school_premium_amount"] = work.estimated_school_premium_amount
    work["expected_fair_price"] = work.school_adjusted_expected_price
    work["observed_residual_premium_pct"] = (work.recent_market_price / work.baseline_non_school_price - 1) * 100
    work["residual_method_gap_pct"] = work.expected_school_premium_pct - work.observed_residual_premium_pct
    work["comparable_method_gap_pct"] = work.expected_school_premium_pct - work.observed_comparable_premium_pct
    work["observed_market_premium_pct"] = work[["observed_residual_premium_pct", "observed_comparable_premium_pct"]].mean(axis=1)
    work["school_value_gap_pct"] = work.expected_school_premium_pct - work.observed_market_premium_pct
    work["total_value_gap_pct"] = (work.expected_fair_price / work.recent_market_price - 1) * 100
    work["linear_school_premium_pct"] = linear_premium
    work["linear_gap_pct"] = work.linear_school_premium_pct - work.observed_market_premium_pct
    same_direction = np.sign(work.residual_method_gap_pct).eq(np.sign(work.comparable_method_gap_pct))
    work["gap_confidence"] = np.select(
        [
            work.school_premium_confidence.isin(["A", "B"]) & work.transaction_count.ge(3) & work.comparable_count.ge(10) & same_direction,
            work.school_premium_confidence.isin(["A", "B"]) & work.transaction_count.ge(1) & work.comparable_count.ge(5) & same_direction,
        ], ["HIGH", "MEDIUM"], default="LOW",
    )
    work["school_data_quality_flag"] = work["data_quality_flag"]
    work["data_quality_flag"] = np.select(
        [work.school_premium_core_score.isna(), work.recent_market_price.isna(), work.baseline_non_school_price.isna(), work.comparable_count.fillna(0).lt(MIN_COMPARABLES), ~same_direction],
        ["SCHOOL_SCORE_MISSING", "RECENT_PRICE_MISSING", "MODEL_PRICE_MISSING", "INSUFFICIENT_COMPARABLES", "METHOD_DIRECTION_DISAGREEMENT"], default="OK",
    )
    work["as_of_date"] = work.as_of_date.fillna("")
    columns = [
        "apartment_id", "apartment_name", "legal_dong", "gu", "household_count",
        "school_premium_core_score", "school_premium_confidence", "recent_market_price",
        "baseline_non_school_price", "expected_school_premium_pct", "expected_school_premium_amount",
        "expected_fair_price", "observed_market_premium_pct", "school_value_gap_pct",
        "total_value_gap_pct", "comparable_count", "comparable_rule", "comparable_method_gap_pct",
        "residual_method_gap_pct", "gap_confidence", "transaction_count",
        "price_window_used", "school_data_quality_flag", "data_quality_flag", "as_of_date",
    ]
    output = work[columns].sort_values("apartment_id").reset_index(drop=True)
    write_csv(root / "data/processed/phase145_school_value_gap.csv", output)

    eligible = work[work.school_value_gap_pct.notna()].copy()
    eligible["score_percentile"] = eligible.school_premium_core_score.rank(pct=True) * 100
    ranking_specs = {
        "SCHOOL_VALUE_GAP_TOP_30": (eligible[(eligible.score_percentile >= 70) & (eligible.school_value_gap_pct > 0) & eligible.gap_confidence.isin(["HIGH", "MEDIUM"])], False),
        "HIGH_SCORE_FULLY_PRICED": (eligible[(eligible.score_percentile >= 75) & (eligible.school_value_gap_pct <= 0)], True),
        "LOW_MEDIUM_SCORE_OVERPRICED": (eligible[(eligible.score_percentile < 70) & (eligible.school_value_gap_pct < 0)], True),
        "POTENTIAL_SCHOOL_VALUE_CANDIDATES": (eligible[(eligible.score_percentile >= 70) & (eligible.school_value_gap_pct >= 3) & eligible.gap_confidence.isin(["HIGH", "MEDIUM"]) & eligible.transaction_count.ge(3)], False),
    }
    ranking_rows = []
    for label, (subset, ascending_gap) in ranking_specs.items():
        subset = subset.sort_values(["school_value_gap_pct", "apartment_id"], ascending=[ascending_gap, True], kind="mergesort").head(30).copy()
        subset["ranking_type"] = label
        subset["rank"] = range(1, len(subset) + 1)
        ranking_rows.append(subset)
    rankings = pd.concat(ranking_rows, ignore_index=True) if ranking_rows else pd.DataFrame()
    write_csv(root / "reports/phase145_school_value_gap_rankings.csv", rankings)

    sensitivity = []
    for score_percentile in (60, 70, 80):
        for gap_threshold in (0, 3, 5):
            selected = eligible[
                eligible.score_percentile.ge(score_percentile) & eligible.school_value_gap_pct.ge(gap_threshold)
                & eligible.gap_confidence.isin(["HIGH", "MEDIUM"])
            ]
            sensitivity.append({"score_percentile_threshold": score_percentile, "gap_threshold_pct": gap_threshold,
                                "candidate_count": len(selected)})
    write_csv(root / "reports/phase145_threshold_sensitivity.csv", pd.DataFrame(sensitivity))

    def stability_row(left, right, label):
        valid = eligible[[left, right, "apartment_id"]].dropna()
        top20_left = set(valid.nlargest(20, left).apartment_id)
        top20_right = set(valid.nlargest(20, right).apartment_id)
        top50_left = set(valid.nlargest(50, left).apartment_id)
        top50_right = set(valid.nlargest(50, right).apartment_id)
        return {"comparison": label, "n": len(valid), "spearman": valid[left].corr(valid[right], method="spearman"),
                "top20_overlap": len(top20_left & top20_right), "top20_overlap_pct": len(top20_left & top20_right) / max(len(top20_left), 1) * 100,
                "top50_overlap": len(top50_left & top50_right), "top50_overlap_pct": len(top50_left & top50_right) / max(len(top50_left), 1) * 100}
    stability = pd.DataFrame([
        stability_row("school_value_gap_pct", "linear_gap_pct", "SELECTED_VS_LINEAR"),
        stability_row("residual_method_gap_pct", "comparable_method_gap_pct", "RESIDUAL_VS_COMPARABLE"),
    ])
    write_csv(root / "reports/phase145_gap_stability.csv", stability)

    audit = work.copy()
    audit["unusual_flag"] = audit.data_quality_flag.ne("OK") | audit.school_value_gap_pct.abs().gt(50)
    audit["unusual_reason"] = np.where(audit.school_value_gap_pct.abs().gt(50), "EXTREME_GAP", audit.data_quality_flag)
    audit_columns = [
        "apartment_id", "apartment_name", "school_premium_core_score", "school_premium_confidence", "recent_market_price",
        "baseline_non_school_price", "expected_fair_price", "expected_school_premium_pct",
        "observed_market_premium_pct", "school_value_gap_pct", "comparable_count",
        "residual_method_gap_pct", "comparable_method_gap_pct", "unusual_flag", "unusual_reason",
    ]
    write_csv(root / "reports/phase145_school_value_gap_audit.csv", audit[audit_columns])

    method_row = stability[stability.comparison.eq("RESIDUAL_VS_COMPARABLE")].iloc[0]
    usable_count = int(work.gap_confidence.isin(["HIGH", "MEDIUM"]).sum())
    if method_row.spearman >= .5 and method_row.top20_overlap_pct >= 40 and usable_count >= 100:
        verdict = "SCHOOL_VALUE_GAP_USABLE"
    elif method_row.spearman >= .2 and usable_count >= 50:
        verdict = "SCHOOL_VALUE_GAP_USABLE_WITH_CAUTION"
    else:
        verdict = "SCHOOL_VALUE_GAP_NOT_STABLE"
    result = {
        "verdict": verdict, "apartments": len(output), "gap_available_apartments": int(output.school_value_gap_pct.notna().sum()),
        "confidence_counts": {str(k): int(v) for k, v in output.gap_confidence.value_counts().items()},
        "gap_median": float(output.school_value_gap_pct.median()), "gap_p25": float(output.school_value_gap_pct.quantile(.25)),
        "gap_p75": float(output.school_value_gap_pct.quantile(.75)), "residual_comparable_spearman": float(method_row.spearman),
        "top20_overlap_pct": float(method_row.top20_overlap_pct),
        "potential_candidate_count": int((rankings.ranking_type.eq("POTENTIAL_SCHOOL_VALUE_CANDIDATES")).sum()) if len(rankings) else 0,
    }
    write_json(root / "data/processed/phase145_result.json", result)
    top = rankings[rankings.ranking_type.eq("POTENTIAL_SCHOOL_VALUE_CANDIDATES")].head(20) if len(rankings) else pd.DataFrame()
    priced = rankings[rankings.ranking_type.eq("HIGH_SCORE_FULLY_PRICED")].head(20) if len(rankings) else pd.DataFrame()
    report = f"""# Phase 14.5 School Value Gap Validation

- 정의: 모델상 학군 프리미엄 - residual/comparable 방식의 평균 시장 내재 프리미엄
- Gap 계산 가능 단지: {result['gap_available_apartments']}/{len(output)}개
- Gap 중앙값/P25/P75: {result['gap_median']:.2f}% / {result['gap_p25']:.2f}% / {result['gap_p75']:.2f}%
- residual vs comparable gap Spearman: {result['residual_comparable_spearman']:.4f}
- 두 방식 Top 20 overlap: {result['top20_overlap_pct']:.1f}%
- Gap Confidence HIGH/MEDIUM/LOW: {result['confidence_counts'].get('HIGH',0)}/{result['confidence_counts'].get('MEDIUM',0)}/{result['confidence_counts'].get('LOW',0)}
- 잠재 학군 상대가치 후보: {result['potential_candidate_count']}개
- 판정: **{verdict}**

## 잠재 후보 Top 20

```csv
{top[['apartment_name','gu','legal_dong','school_premium_core_score','school_value_gap_pct','gap_confidence','transaction_count']].to_csv(index=False) if len(top) else '해당 없음'}
```

## 높은 학군점수이나 가격에 충분히 반영된 단지 Top 20

```csv
{priced[['apartment_name','gu','legal_dong','school_premium_core_score','school_value_gap_pct','gap_confidence','transaction_count']].to_csv(index=False) if len(priced) else '해당 없음'}
```

School Value Gap은 누락 입지변수의 영향을 받을 수 있는 상대가치 신호이며 투자수익이나 저평가를 단정하지 않는다.
"""
    atomic_bytes(root / "reports/phase145_school_value_gap_validation.md", report.encode("utf-8"))
    return result, work, rankings


def build_figures(root, model_data, baseline_residual, comparison, fitted, curve, gap, rankings):
    root = Path(root)
    folder = root / "reports/figures"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        import plotly.express as px
        apartment = model_data.assign(residual=baseline_residual).groupby("apartment_id", as_index=False).agg(
            school_premium_core_score=("school_premium_core_score", "first"), residual=("residual", "median")
        )
        px.scatter(apartment, x="school_premium_core_score", y="residual", title="Core score와 비학군 가격 residual").write_html(folder / "phase135_core_vs_residual.html", include_plotlyjs="cdn")
        apartment["score_decile"] = pd.qcut(apartment.school_premium_core_score.rank(method="first"), 10, labels=[f"D{i}" for i in range(1, 11)])
        decile = apartment.groupby("score_decile", observed=True).residual.median().reset_index()
        px.bar(decile, x="score_decile", y="residual", title="학군점수 분위별 residual premium").write_html(folder / "phase135_score_decile_residual.html", include_plotlyjs="cdn")
        px.line(curve, x="school_score", y="relative_price_effect_pct", title="학군점수별 모델 가격 프리미엄").write_html(folder / "phase14_school_premium_curve.html", include_plotlyjs="cdn")
        curves = []
        score_grid = np.arange(0, 101, dtype=float)
        for model in ("LINEAR", "QUADRATIC", "SPLINE"):
            fitted_model = fitted[model]
            effect, _, _ = school_effect(
                fitted_model["fit"], fitted_model["x"].columns.tolist(),
                fitted_model["school_columns"], model, score_grid,
            )
            curves.append(pd.DataFrame({"school_score": score_grid, "relative_price_effect_pct": np.expm1(effect) * 100, "model": model}))
        px.line(pd.concat(curves, ignore_index=True), x="school_score", y="relative_price_effect_pct", color="model", title="Linear·Quadratic·Spline 프리미엄 곡선").write_html(folder / "phase14_linear_vs_spline.html", include_plotlyjs="cdn")
        valid = gap.dropna(subset=["recent_market_price", "expected_fair_price"])
        px.scatter(valid, x="recent_market_price", y="expected_fair_price", color="gap_confidence", title="관측가격과 예상 공정가격").write_html(folder / "phase145_observed_vs_expected.html", include_plotlyjs="cdn")
        px.histogram(gap, x="school_value_gap_pct", color="gap_confidence", title="School Value Gap 분포").write_html(folder / "phase145_gap_histogram.html", include_plotlyjs="cdn")
        px.scatter(gap, x="school_premium_core_score", y="school_value_gap_pct", color="gap_confidence", title="학군점수와 School Value Gap").write_html(folder / "phase145_gap_vs_score.html", include_plotlyjs="cdn")
        top = rankings[rankings.ranking_type.eq("SCHOOL_VALUE_GAP_TOP_30")].head(30)
        px.bar(top, x="school_value_gap_pct", y="apartment_name", orientation="h", color="gap_confidence", title="School Value Gap Top 30").write_html(folder / "phase145_top30_gap.html", include_plotlyjs="cdn")
        px.box(gap, x="gap_confidence", y="school_value_gap_pct", title="Gap confidence별 분포").write_html(folder / "phase145_confidence_gap.html", include_plotlyjs="cdn")
        counts = model_data.groupby("apartment_id").size()
        plot = apartment.copy(); plot["transaction_count"] = plot.apartment_id.map(counts)
        plot["volume_band"] = pd.cut(plot.transaction_count, [-np.inf, 29, 99, np.inf], labels=["Low", "Mid", "High"])
        px.scatter(plot, x="school_premium_core_score", y="residual", color="volume_band", title="거래량별 학군점수-가격 residual").write_html(folder / "phase135_volume_score_price.html", include_plotlyjs="cdn")
    except Exception as exc:
        atomic_bytes(folder / "phase145_figure_error.txt", str(exc).encode("utf-8"))


def build_phase135_145(root=ROOT):
    root = Path(root)
    np.random.seed(RANDOM_SEED)
    manifest = discover_protected_artifacts(root)
    write_csv(root / "reports/phase135_protected_manifest.csv", manifest)
    transactions = build_transaction_sample(root)
    write_parquet(root / "data/processed/phase135_transaction_sample.parquet", transactions)
    model_data = complete_model_sample(transactions).sort_values(["transaction_date", "apartment_id"]).reset_index(drop=True)
    comparison_data, comparison, fitted, selected = compare_price_models(model_data)
    baseline_fit = fitted["NONE"]["fit"]
    baseline_residual = baseline_fit["residual"]
    phase135, _ = build_phase135(root, transactions, comparison_data, baseline_fit, baseline_residual)
    if phase135["verdict"] == "SCHOOL_PREMIUM_INDEX_NOT_READY":
        finalize_manifest(manifest, root)
        return {"phase135": phase135, "phase14": "NOT_RUN", "phase145": "NOT_RUN"}
    phase14, phase14_output, curve = build_phase14(root, transactions, comparison_data, comparison, fitted, selected)
    linear = fitted["LINEAR"]
    linear_effect, _, _ = school_effect(
        linear["fit"], linear["x"].columns.tolist(), linear["school_columns"], "LINEAR",
        phase14_output.school_premium_core_score.fillna(SCORE_REFERENCE),
    )
    phase145, gap, rankings = build_phase145(root, phase14_output, np.expm1(linear_effect) * 100)
    build_figures(root, comparison_data, baseline_residual, comparison, fitted, curve, gap, rankings)
    frozen = {
        "status": phase135["verdict"], "source_path": "data/processed/phase13_school_premium_index.csv",
        "source_sha256": _sha(root / "data/processed/phase13_school_premium_index.csv"),
        "row_count": 560, "apartment_id_unique": True,
    }
    write_json(root / "data/snapshots/phase135_school_premium_freeze.json", frozen)
    final_manifest = finalize_manifest(manifest, root)
    return {
        "phase135": phase135, "phase14": phase14, "phase145": phase145,
        "protected_artifacts": len(final_manifest), "protected_unchanged": bool(final_manifest.unchanged.all()),
    }
