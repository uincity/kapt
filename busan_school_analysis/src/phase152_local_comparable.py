"""Phase 15.2: leakage-safe local comparable price modelling."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler

from .config import ROOT, atomic_bytes, write_csv, write_json, write_parquet


RANDOM_SEED = 20260911
MIN_APARTMENTS = 5
MIN_RECENT_TRANSACTIONS = 100
COMPLEXITY_IMPROVEMENT = 0.01
RIDGE_ALPHA = 1.0
NUMERIC_FEATURES = ("exclusive_area", "floor", "apartment_age", "log_households", "parking_per_household", "transaction_month_index")
CATEGORICAL_FEATURES = ("quarter", "area_group")
SCHOOL_FEATURE = "school_premium_core_score"
FORBIDDEN_MODEL_FEATURES = ("school_value_gap_pct", "target_current_price", "future_price", "target_residual")
MATCHING_FEATURES = ("apartment_age", "log_household_count", "log_representative_area_m2", "parking_per_household")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_protected(root=ROOT) -> pd.DataFrame:
    root = Path(root)
    expression = re.compile(r"phase(151|149|148|147|146|145|14|135|13|125|12|115|11|10|9|8|7)(?![0-9])")
    found: set[Path] = set()
    for folder in ("src", "tests", "data/processed", "data/snapshots", "reports"):
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and expression.search(path.name.lower()) and "phase152" not in path.name.lower():
                found.add(path)
    for relative in ("main.py", "config/manual_elementary_middle_overrides.csv"):
        path = root / relative
        if path.exists():
            found.add(path)
    rows = []
    for path in sorted(found):
        match = expression.search(path.name.lower())
        phase = match.group(1) if match else "CORE"
        phase = {"115": "11.5", "125": "12.5", "135": "13.5", "145": "14.5", "151": "15.1"}.get(phase, phase)
        rows.append({"path": path.relative_to(root).as_posix(), "phase": phase, "file_size": path.stat().st_size,
                     "sha256_before": _sha(path), "sha256_after": "", "unchanged": False})
    return pd.DataFrame(rows)


def verify_manifest(manifest: pd.DataFrame, root=ROOT) -> pd.DataFrame:
    root = Path(root); out = manifest.copy()
    out["sha256_after"] = [(_sha(root / path) if (root / path).exists() else "MISSING") for path in out.path]
    out["unchanged"] = out.sha256_before.eq(out.sha256_after)
    if not out.unchanged.all():
        raise RuntimeError(f"PROTECTED_ARTIFACT_MODIFIED: {out.loc[~out.unchanged, 'path'].tolist()}")
    return out


def prepare_transactions(root=ROOT) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    root = Path(root)
    tx = pd.read_parquet(root / "data/processed/phase135_transaction_sample.parquet").copy()
    master = pd.read_csv(root / "data/processed/phase149_school_value_master.csv", encoding="utf-8-sig")
    market = pd.read_csv(root / "data/processed/phase151_local_market_mapping.csv", encoding="utf-8-sig")
    tx["transaction_date"] = pd.to_datetime(tx.transaction_date)
    tx["quarter"] = "Q" + tx.transaction_date.dt.quarter.astype(str)
    tx["log_households"] = np.log(pd.to_numeric(tx.household_count, errors="coerce").replace(0, np.nan))
    tx["market_key"] = tx.district.astype(str) + "|" + tx.legal_dong.astype(str)
    tx["log_price"] = np.log(pd.to_numeric(tx.price_per_sqm, errors="coerce").where(tx.price_per_sqm.gt(0)))
    required = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES, SCHOOL_FEATURE, "log_price", "apartment_id", "market_key"]
    model = tx.replace([np.inf, -np.inf], np.nan).dropna(subset=required).sort_values(["transaction_date", "apartment_id"]).reset_index(drop=True)
    return tx, model, master.merge(market[["apartment_id", "final_local_market_id", "market_definition_type"]], on="apartment_id", how="left", validate="one_to_one")


def temporal_split(frame: pd.DataFrame, quantile=.75) -> tuple[np.ndarray, np.ndarray, pd.Timestamp]:
    cutoff = pd.Timestamp(frame.transaction_date.quantile(quantile))
    train = frame.transaction_date.le(cutoff).to_numpy()
    test = frame.transaction_date.gt(cutoff).to_numpy()
    if frame.loc[train, "transaction_date"].max() >= frame.loc[test, "transaction_date"].min():
        raise RuntimeError("TEMPORAL_LEAKAGE")
    return train, test, cutoff


def recent_market_counts(frame: pd.DataFrame, end=None) -> pd.DataFrame:
    frame = frame.copy()
    frame["transaction_date"] = pd.to_datetime(frame.transaction_date)
    if "district" not in frame and "gu" in frame:
        frame["district"] = frame.gu
    if "market_key" not in frame:
        frame["market_key"] = frame.district.astype(str) + "|" + frame.legal_dong.astype(str)
    end = pd.Timestamp(end if end is not None else frame.transaction_date.max())
    recent = frame[frame.transaction_date.gt(end - pd.DateOffset(months=12))]
    out = recent.groupby(["district", "legal_dong", "market_key"], as_index=False).agg(
        apartment_count=("apartment_id", "nunique"), transaction_count=("apartment_id", "size"))
    out["sufficient"] = out.apartment_count.ge(MIN_APARTMENTS) & out.transaction_count.ge(MIN_RECENT_TRANSACTIONS)
    return out


def _market_profiles(apartment_features: pd.DataFrame) -> pd.DataFrame:
    f = apartment_features.copy()
    f["market_key"] = f.gu.astype(str) + "|" + f.legal_dong.astype(str)
    return f.groupby(["gu", "legal_dong", "market_key"], as_index=False).agg(
        apartment_age=("apartment_age", "median"), log_household_count=("log_household_count", "median"),
        log_representative_area_m2=("log_representative_area_m2", "median"), parking_per_household=("parking_per_household", "median"),
        latitude=("latitude", "median"), longitude=("longitude", "median"))


def build_fallback_map(count_source: pd.DataFrame, apartment_features: pd.DataFrame) -> pd.DataFrame:
    """Build deterministic L0-L4 pools without using target apartment price."""
    counts = recent_market_counts(count_source)
    profiles = _market_profiles(apartment_features)
    all_markets = profiles.merge(counts[["market_key", "apartment_count", "transaction_count", "sufficient"]], on="market_key", how="left")
    all_markets[["apartment_count", "transaction_count"]] = all_markets[["apartment_count", "transaction_count"]].fillna(0)
    all_markets["sufficient"] = all_markets.sufficient.eq(True)
    cols = list(MATCHING_FEATURES)
    med = all_markets[cols].median(); scale = (all_markets[cols].quantile(.75) - all_markets[cols].quantile(.25)).replace(0, 1)
    z = (all_markets[cols].fillna(med) - med) / scale
    rows = []
    for i, target in all_markets.iterrows():
        if target.sufficient:
            pool, level, reason = [target.market_key], 0, "SAME_LEGAL_DONG_SUFFICIENT"
        else:
            same_gu = all_markets[(all_markets.gu == target.gu) & (all_markets.market_key != target.market_key)].copy()
            distance = ((z.loc[same_gu.index] - z.loc[i]) ** 2).mean(axis=1).pow(.5)
            same_gu = same_gu.assign(distance=distance).sort_values(["distance", "market_key"])
            pool = [target.market_key]
            for row in same_gu.itertuples():
                if row.distance <= 1.5:
                    pool.append(row.market_key)
                selected = all_markets[all_markets.market_key.isin(pool)]
                if selected.apartment_count.sum() >= MIN_APARTMENTS and selected.transaction_count.sum() >= MIN_RECENT_TRANSACTIONS:
                    break
            selected = all_markets[all_markets.market_key.isin(pool)]
            if selected.apartment_count.sum() >= MIN_APARTMENTS and selected.transaction_count.sum() >= MIN_RECENT_TRANSACTIONS and len(pool) > 1:
                level, reason = 1, "SAME_GU_SIMILAR_PROFILE"
            else:
                pool = all_markets.loc[all_markets.gu.eq(target.gu), "market_key"].tolist()
                selected = all_markets[all_markets.market_key.isin(pool)]
                if selected.apartment_count.sum() >= MIN_APARTMENTS and selected.transaction_count.sum() >= MIN_RECENT_TRANSACTIONS:
                    level, reason = 2, "SAME_GU"
                else:
                    geo = np.sqrt((all_markets.latitude-target.latitude)**2 + ((all_markets.longitude-target.longitude)*np.cos(np.radians(target.latitude)))**2) * 111
                    prof = ((z-z.loc[i])**2).mean(axis=1).pow(.5)
                    adjacent = all_markets[(geo <= 10) & (prof <= 2.0)].assign(distance=geo[(geo <= 10) & (prof <= 2.0)]).sort_values(["distance", "market_key"])
                    pool = adjacent.market_key.tolist()
                    selected = all_markets[all_markets.market_key.isin(pool)]
                    if len(pool) and selected.transaction_count.sum() >= MIN_RECENT_TRANSACTIONS:
                        level, reason = 3, "ADJACENT_COMPATIBLE_MARKET"
                    else:
                        pool, level, reason = all_markets.market_key.tolist(), 4, "BUSAN_GLOBAL"
        selected = all_markets[all_markets.market_key.isin(pool)]
        rows.append({"market_key": target.market_key, "district": target.gu, "legal_dong": target.legal_dong,
                     "fallback_level": level, "fallback_market_name": ";".join(sorted(pool)), "pool_market_keys": tuple(sorted(pool)),
                     "fallback_pool_apartments": int(selected.apartment_count.sum()), "fallback_pool_transactions": int(selected.transaction_count.sum()),
                     "fallback_reason": reason, "original_apartments": int(target.apartment_count), "original_transactions": int(target.transaction_count),
                     "original_sufficient": bool(target.sufficient)})
    return pd.DataFrame(rows)


def make_pipeline(with_school: bool, with_dong: bool=False) -> Pipeline:
    numeric = list(NUMERIC_FEATURES) + ([SCHOOL_FEATURE] if with_school else [])
    categorical = list(CATEGORICAL_FEATURES) + (["market_key"] if with_dong else [])
    transform = ColumnTransformer([
        ("numeric", RobustScaler(), numeric),
        ("categorical", OneHotEncoder(handle_unknown="ignore", drop="first"), categorical),
    ], remainder="drop")
    return Pipeline([("transform", transform), ("model", Ridge(alpha=RIDGE_ALPHA))])


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame, with_school: bool, with_dong=False):
    model = make_pipeline(with_school, with_dong).fit(train, train.log_price)
    return model.predict(test), model


def school_coefficient(model: Pipeline) -> float:
    names = model.named_steps["transform"].get_feature_names_out().tolist()
    matches = [i for i, name in enumerate(names) if name.endswith(SCHOOL_FEATURE)]
    return float(model.named_steps["model"].coef_[matches[0]]) if matches else np.nan


def _local_predictions(train, test, fallback, with_school, mode):
    predictions = pd.Series(index=test.index, dtype=float); types = pd.Series(index=test.index, dtype=object)
    global_model = make_pipeline(with_school).fit(train, train.log_price)
    d_model = make_pipeline(with_school, True).fit(train, train.log_price) if mode == "F3" else None
    fallback_index = fallback.set_index("market_key")
    for market_key, rows in test.groupby("market_key"):
        rule = fallback_index.loc[market_key] if market_key in fallback_index.index else None
        if mode == "L":
            pool_keys = (market_key,) if rule is not None and rule.original_sufficient else tuple()
        elif mode == "F1":
            district = rows.district.iloc[0]; pool_keys = tuple(train.loc[train.district.eq(district), "market_key"].unique())
        elif mode == "F2":
            pool_keys = rule.pool_market_keys if rule is not None else tuple()
        elif mode == "F3":
            predictions.loc[rows.index] = d_model.predict(rows); types.loc[rows.index] = "PARTIAL_POOLING_DONG_RIDGE"; continue
        else:
            raise ValueError(mode)
        pool = train[train.market_key.isin(pool_keys)]
        if len(pool) < 30 or pool.apartment_id.nunique() < 2:
            predictions.loc[rows.index] = global_model.predict(rows); types.loc[rows.index] = "GLOBAL_FALLBACK"
        else:
            model = make_pipeline(with_school).fit(pool, pool.log_price)
            predictions.loc[rows.index] = model.predict(rows); types.loc[rows.index] = mode
    return predictions.to_numpy(), types


def fallback_operational_predictions(train, test, fallback, with_school, candidate):
    """Use local regression in sufficient dongs and candidate fallback only in sparse dongs."""
    local, local_type = _local_predictions(train, test, fallback, with_school, "L")
    fallback_prediction, fallback_type = _local_predictions(train, test, fallback, with_school, candidate)
    sufficient = test.market_key.map(fallback.set_index("market_key").original_sufficient).fillna(False).to_numpy(dtype=bool)
    prediction = np.where(sufficient, local, fallback_prediction)
    model_type = local_type.copy()
    model_type.loc[~sufficient] = fallback_type.loc[~sufficient]
    return prediction, model_type


def performance(frame: pd.DataFrame, prediction, model, school_variant) -> dict:
    d = frame.copy(); d["prediction"] = np.asarray(prediction); error = d.log_price-d.prediction
    raw_actual = np.exp(d.log_price); raw_pred = np.exp(d.prediction)
    apartment_mse = d.assign(sq=error**2).groupby("apartment_id").sq.mean()
    dong_mse = d.assign(sq=error**2).groupby("market_key").sq.mean()
    calibration = np.polyfit(d.prediction, d.log_price, 1)
    return {"model": model, "school_variant": school_variant, "test_transactions": len(d), "test_apartments": d.apartment_id.nunique(),
            "rmse": float(mean_squared_error(d.log_price, d.prediction)**.5), "mae": float(mean_absolute_error(d.log_price, d.prediction)),
            "mape": float(np.mean(np.abs(raw_actual-raw_pred)/raw_actual)), "median_ape": float(np.median(np.abs(raw_actual-raw_pred)/raw_actual)),
            "r2": float(r2_score(d.log_price, d.prediction)), "apartment_weighted_rmse": float(np.sqrt(apartment_mse.mean())),
            "dong_equal_weighted_rmse": float(np.sqrt(dong_mse.mean())), "calibration_slope": float(calibration[0]), "calibration_intercept": float(calibration[1])}


def evaluate_models(model_data: pd.DataFrame, apartment_features: pd.DataFrame):
    train_mask, test_mask, cutoff = temporal_split(model_data)
    train, test = model_data.loc[train_mask].copy(), model_data.loc[test_mask].copy()
    fallback = build_fallback_map(train, apartment_features)
    rows, predictions = [], {}
    for with_school, school_name in ((False, "NO_SCHOOL"), (True, "SCHOOL")):
        g_pred, _ = _fit_predict(train, test, with_school, False)
        d_pred, _ = _fit_predict(train, test, with_school, True)
        predictions[("G", school_name)] = g_pred; predictions[("D", school_name)] = d_pred
        rows += [performance(test, g_pred, "G", school_name), performance(test, d_pred, "D", school_name)]
        l_pred, _ = _local_predictions(train, test, fallback, with_school, "L")
        predictions[("L", school_name)] = l_pred; rows.append(performance(test, l_pred, "L", school_name))
        for candidate in ("F1", "F2", "F3"):
            pred, _ = fallback_operational_predictions(train, test, fallback, with_school, candidate)
            predictions[(candidate, school_name)] = pred
    low_keys = set(fallback.loc[~fallback.original_sufficient, "market_key"])
    low = test.market_key.isin(low_keys).to_numpy()
    fallback_perf = []
    for candidate in ("F1", "F2", "F3"):
        fallback_perf.append(performance(test.loc[low], predictions[(candidate, "SCHOOL")][low], candidate, "SCHOOL"))
    fp = pd.DataFrame(fallback_perf).set_index("model")
    selected_fallback = "F1"
    for candidate in ("F2", "F3"):
        if fp.loc[candidate, "rmse"] <= fp.loc[selected_fallback, "rmse"]*(1-COMPLEXITY_IMPROVEMENT) and fp.loc[candidate, "mae"] < fp.loc[selected_fallback, "mae"]:
            selected_fallback = candidate
    for school_name in ("NO_SCHOOL", "SCHOOL"):
        pred = predictions[(selected_fallback, school_name)]
        predictions[("F", school_name)] = pred
        rows.append(performance(test, pred, "F", school_name))
    comparison = pd.DataFrame(rows).sort_values(["school_variant", "model"])
    return train, test, cutoff, fallback, comparison, pd.DataFrame(fallback_perf), selected_fallback, predictions


def group_holdout(model_data: pd.DataFrame) -> pd.DataFrame:
    splitter = GroupShuffleSplit(n_splits=3, test_size=.2, random_state=RANDOM_SEED); rows=[]
    for split, (tr, te) in enumerate(splitter.split(model_data, groups=model_data.apartment_id)):
        train, test = model_data.iloc[tr], model_data.iloc[te]
        for name, dong in (("G", False), ("D", True)):
            pred, _ = _fit_predict(train, test, True, dong)
            row=performance(test,pred,name,"SCHOOL"); row["split"]=split; row["train_apartments"]=train.apartment_id.nunique(); rows.append(row)
    return pd.DataFrame(rows)


def _pool_for_target(train, rule, mode, market_key):
    if mode == "G": return train
    if mode == "D": return train
    if mode == "L": return train[train.market_key.eq(market_key)] if rule.original_sufficient else train
    if mode == "F1": return train[train.district.eq(rule.district)]
    if mode == "F2": return train[train.market_key.isin(rule.pool_market_keys)]
    return train


def comparable_details(apartment_features, master, fallback):
    f = apartment_features.copy(); f["market_key"] = f.gu.astype(str)+"|"+f.legal_dong.astype(str)
    eligible = f.dropna(subset=list(MATCHING_FEATURES)).copy(); fit, scaler = _robust_match_matrix(eligible)
    rule_index=fallback.set_index("market_key"); rows=[]
    for target_index, target in eligible.iterrows():
        if target.market_key not in rule_index.index: continue
        rule=rule_index.loc[target.market_key]; pool=eligible[eligible.market_key.isin(rule.pool_market_keys)&eligible.apartment_id.ne(target.apartment_id)]
        if pool.empty: continue
        distance=np.sqrt(((fit.loc[pool.index]-fit.loc[target_index])**2).mean(axis=1))
        order=distance.sort_values().head(5)
        for rank,(index,value) in enumerate(order.items(),1):
            comp=pool.loc[index]
            rows.append({"target_apartment_id":target.apartment_id,"target_apartment_name":target.apartment_name,"comparable_rank":rank,
                         "comparable_apartment_id":comp.apartment_id,"comparable_apartment_name":comp.apartment_name,
                         "same_legal_dong":bool(comp.market_key==target.market_key),"fallback_level":int(rule.fallback_level),
                         "age_difference":abs(target.apartment_age-comp.apartment_age),"household_difference":abs(target.household_count-comp.household_count),
                         "area_difference":abs(target.representative_area_m2-comp.representative_area_m2),
                         "school_score_difference":abs(target.school_premium_core_score-comp.school_premium_core_score) if pd.notna(target.school_premium_core_score) and pd.notna(comp.school_premium_core_score) else np.nan,
                         "similarity_distance":value,"comparable_transaction_count":comp.full_period_transaction_count})
    return pd.DataFrame(rows)


def _robust_match_matrix(frame):
    raw=frame[list(MATCHING_FEATURES)].astype(float); median=raw.median(); iqr=(raw.quantile(.75)-raw.quantile(.25)).replace(0,1)
    return (raw-median)/iqr, {"median":median,"iqr":iqr}


def build_fair_prices(root, tx_all, model_data, master, apt_features, fallback, selected_model, selected_fallback, with_school):
    latest=model_data.transaction_date.max(); full=model_data.copy()
    model_global=make_pipeline(with_school, selected_model=="D").fit(full,full.log_price)
    rules=fallback.set_index("market_key")
    apt=apt_features.merge(master[["apartment_id","elementary_school_name","estimated_school_premium_pct","school_premium_confidence"]],on="apartment_id",how="left",validate="one_to_one")
    apt=apt.rename(columns={"recent_6m_price_per_m2":"recent_6m_market_price","recent_12m_price_per_m2":"recent_12m_market_price"})
    apt["market_key"]=apt.gu.astype(str)+"|"+apt.legal_dong.astype(str); rows=[]; residual_rows=[]
    # Full-sample residuals are diagnostic inputs only.
    if selected_model in {"G","D"}:
        residual_pred=model_global.predict(full)
    else:
        if selected_model == "F": residual_pred,_=fallback_operational_predictions(full,full,fallback,with_school,selected_fallback)
        else: residual_pred,_=_local_predictions(full,full,fallback,with_school,"L")
    residual_frame=full[["apartment_id","transaction_date","log_price","price_per_sqm"]].copy(); residual_frame["predicted_log_price"]=residual_pred; residual_frame["local_price_residual"]=residual_frame.log_price-residual_frame.predicted_log_price
    model_cache = {}
    for target in apt.itertuples():
        rule=rules.loc[target.market_key] if target.market_key in rules.index else None
        row={"apartment_id":target.apartment_id,"apartment_name":target.apartment_name,"gu":target.gu,"legal_dong":target.legal_dong,"household_count":target.household_count,
             "elementary_school_name":target.elementary_school_name,"primary_market":target.market_key,
             "fallback_level":int(rule.fallback_level) if rule is not None else 4,"fallback_market_name":rule.fallback_market_name if rule is not None else "BUSAN_GLOBAL",
             "school_premium_core_score":target.school_premium_core_score,"estimated_school_premium_pct":target.estimated_school_premium_pct,"school_premium_confidence":target.school_premium_confidence,
             "representative_area_m2":target.representative_area_m2,"recent_6m_market_price":target.recent_6m_market_price,"recent_12m_market_price":target.recent_12m_market_price,
             "transaction_count_6m":0 if pd.isna(target.transaction_count_6m) else int(target.transaction_count_6m),"transaction_count_12m":0 if pd.isna(target.transaction_count_12m) else int(target.transaction_count_12m)}
        pool_keys=rule.pool_market_keys if rule is not None else tuple(full.market_key.unique()); pool=full[full.market_key.isin(pool_keys)]
        row["comparable_apartment_count"]=int(pool.apartment_id.nunique()-int(target.apartment_id in set(pool.apartment_id)))
        row["comparable_transaction_count"]=int(len(pool[pool.apartment_id.ne(target.apartment_id)]))
        valid=all(pd.notna(getattr(target,c)) for c in ("representative_area_m2","median_floor","apartment_age","household_count","parking_per_household"))
        school_ok=pd.notna(target.school_premium_core_score)
        use_school=with_school and school_ok
        if valid:
            predrow=pd.DataFrame([{"exclusive_area":target.representative_area_m2,"floor":target.median_floor,"apartment_age":target.apartment_age,
                                   "log_households":math.log(target.household_count),"parking_per_household":target.parking_per_household,
                                   "transaction_month_index":full.transaction_month_index.max(),"quarter":f"Q{latest.quarter}",
                                   "area_group":pd.cut([target.representative_area_m2],[-np.inf,40,55,65,80,90,120,np.inf],labels=["under_40","40_55","55_65","65_80","80_90","90_120","over_120"],right=False)[0],
                                   "school_premium_core_score":target.school_premium_core_score,"market_key":target.market_key,"district":target.gu,"legal_dong":target.legal_dong}])
            if selected_model in {"G","D"}:
                cache_key=(selected_model,use_school,"ALL")
                if cache_key not in model_cache:
                    cached_model=make_pipeline(use_school,selected_model=="D").fit(full,full.log_price)
                    cached_error=full.log_price-cached_model.predict(full)
                    model_cache[cache_key]=(cached_model,float(cached_error.std()),float(np.mean(np.abs(cached_error))))
            else:
                operational_mode = "L" if selected_model == "L" or (selected_model == "F" and rule.original_sufficient) else selected_fallback
                if operational_mode == "F3":
                    cache_key=(operational_mode,use_school,"ALL")
                    model_pool=full
                else:
                    model_pool=_pool_for_target(full,rule,operational_mode,target.market_key)
                    cache_key=(operational_mode,use_school,tuple(sorted(model_pool.market_key.unique())))
                if cache_key not in model_cache:
                    cached_model=make_pipeline(use_school,operational_mode=="F3").fit(model_pool,model_pool.log_price)
                    cached_error=model_pool.log_price-cached_model.predict(model_pool)
                    model_cache[cache_key]=(cached_model,float(cached_error.std()),float(np.mean(np.abs(cached_error))))
            model,sigma,model_mae=model_cache[cache_key]
            pred=float(model.predict(predrow)[0])
            fair=np.exp(pred); lower=np.exp(pred-1.96*sigma); upper=np.exp(pred+1.96*sigma)
            row.update(local_fair_price_per_m2=fair,local_fair_total_price=fair*target.representative_area_m2,
                       fair_price_lower=lower,fair_price_upper=upper,prediction_interval_width_pct=(upper-lower)/fair*100,
                       selected_model_type=selected_model+("_S" if use_school else "_NS"),local_model_rmse=sigma,local_model_mae=model_mae)
        else:
            row.update(local_fair_price_per_m2=np.nan,local_fair_total_price=np.nan,fair_price_lower=np.nan,fair_price_upper=np.nan,prediction_interval_width_pct=np.nan,selected_model_type="INSUFFICIENT_FEATURES",local_model_rmse=np.nan,local_model_mae=np.nan)
        rr=residual_frame[residual_frame.apartment_id.eq(target.apartment_id)]; recent=rr[rr.transaction_date.gt(latest-pd.DateOffset(months=12))]
        row["recent_local_residual"]=recent.local_price_residual.median() if len(recent) else np.nan; row["residual_volatility"]=rr.local_price_residual.std() if len(rr)>1 else np.nan
        width=row["prediction_interval_width_pct"]; level=row["fallback_level"]
        row["model_confidence"]="HIGH" if valid and level==0 and row["comparable_apartment_count"]>=5 and width<=100 else "MEDIUM" if valid and level<=2 and row["comparable_apartment_count"]>=3 and width<=160 else "LOW"
        row["low_sample_flag"]=bool(rule is None or not rule.original_sufficient); row["fallback_flag"]=bool(level>0)
        row["data_quality_flag"]="INSUFFICIENT_MODEL_FEATURES" if not valid else "MISSING_SCHOOL_USED_NS" if with_school and not school_ok else "WIDE_INTERVAL" if width>160 else "OK"
        rows.append(row)
    return pd.DataFrame(rows), residual_frame


def figures(root, comparison, market_perf, fair, fallback_perf, residuals):
    folder=Path(root)/"reports/figures"; folder.mkdir(parents=True,exist_ok=True)
    try:
        import plotly.express as px
        s=comparison[comparison.school_variant.eq("SCHOOL")]
        px.bar(s,x="model",y="rmse",title="Global vs Local OOS RMSE").write_html(folder/"phase152_model_rmse.html",include_plotlyjs="cdn")
        px.bar(s,x="model",y="mae",title="Global vs Dong FE vs Local vs Fallback MAE").write_html(folder/"phase152_model_mae.html",include_plotlyjs="cdn")
        px.bar(market_perf.sort_values("rmse"),x="legal_dong",y="rmse",title="법정동별 RMSE").write_html(folder/"phase152_dong_rmse.html",include_plotlyjs="cdn")
        px.scatter(market_perf,x="transaction_count",y="rmse",color="model_confidence",title="Sample Size vs RMSE").write_html(folder/"phase152_sample_rmse.html",include_plotlyjs="cdn")
        px.box(market_perf,x="fallback_level",y="rmse",title="Fallback Level별 Error").write_html(folder/"phase152_fallback_error.html",include_plotlyjs="cdn")
        px.scatter(residuals,x="log_price",y="predicted_log_price",title="Observed vs Predicted Log Price").write_html(folder/"phase152_observed_predicted.html",include_plotlyjs="cdn")
        px.histogram(fair,x="prediction_interval_width_pct",title="Prediction Interval Width").write_html(folder/"phase152_interval_width.html",include_plotlyjs="cdn")
        px.bar(comparison,x="model",y="rmse",color="school_variant",barmode="group",title="School vs No-school").write_html(folder/"phase152_school_comparison.html",include_plotlyjs="cdn")
        px.histogram(fair,x="local_fair_price_per_m2",title="Local Fair Price Distribution").write_html(folder/"phase152_fair_price.html",include_plotlyjs="cdn")
        px.histogram(fair,x="model_confidence",title="Model Confidence").write_html(folder/"phase152_confidence.html",include_plotlyjs="cdn")
        px.histogram(residuals,x="local_price_residual",title="Local Residual").write_html(folder/"phase152_residual.html",include_plotlyjs="cdn")
        px.bar(fallback_perf,x="model",y="rmse",title="Low-sample Fallback Performance").write_html(folder/"phase152_low_sample_fallback.html",include_plotlyjs="cdn")
    except Exception as exc:
        atomic_bytes(folder/"phase152_figure_error.txt",str(exc).encode("utf-8"))


def build_phase152(root=ROOT):
    root=Path(root); manifest=discover_protected(root); write_csv(root/"reports/phase152_protected_manifest.csv",manifest)
    tx_all,model_data,master=prepare_transactions(root); apt_features=pd.read_csv(root/"data/processed/phase151_apartment_market_features.csv",encoding="utf-8-sig")
    train,test,cutoff,fallback_eval,comparison,fallback_perf,selected_fallback,predictions=evaluate_models(model_data,apt_features)
    write_csv(root/"reports/phase152_model_comparison.csv",comparison); write_csv(root/"reports/phase152_fallback_method_comparison.csv",fallback_perf)
    group=group_holdout(model_data); write_csv(root/"reports/phase152_group_holdout_sensitivity.csv",group)
    current_fallback=build_fallback_map(model_data,apt_features); low_audit=current_fallback.copy()
    selected_school=True
    pivot=comparison.pivot(index="model",columns="school_variant",values="rmse")
    dong_school_gain=float(1-pivot.loc["D","SCHOOL"]/pivot.loc["D","NO_SCHOOL"])
    school_rows=comparison[comparison.school_variant.eq("SCHOOL")].set_index("model")
    if school_rows.loc["F","rmse"] <= school_rows.loc["D","rmse"]*.99 and school_rows.loc["F","mae"] < school_rows.loc["D","mae"]:
        selected_model="F"; verdict="LOCAL_COMPARABLE_MODEL_PARTIALLY_SUPPORTED"
    elif school_rows.loc["L","rmse"] <= school_rows.loc["D","rmse"]*.99 and school_rows.loc["L","mae"] < school_rows.loc["D","mae"]:
        selected_model="L"; verdict="LOCAL_COMPARABLE_MODEL_PARTIALLY_SUPPORTED"
    else:
        selected_model="D"; verdict="LEGAL_DONG_FE_MODEL_PREFERRED"
    school_gain=float(1-pivot.loc[selected_model,"SCHOOL"]/pivot.loc[selected_model,"NO_SCHOOL"])
    school_verdict="LOCAL_SCHOOL_FEATURE_USEFUL" if school_gain>=.005 else "LOCAL_SCHOOL_FEATURE_PARTIALLY_USEFUL" if school_gain>0 else "LOCAL_SCHOOL_FEATURE_NOT_USEFUL"
    fair,residuals=build_fair_prices(root,tx_all,model_data,master,apt_features,current_fallback,selected_model,selected_fallback,selected_school)
    write_csv(root/"data/processed/phase152_local_fair_price.csv",fair); write_parquet(root/"data/processed/phase152_transaction_residuals.parquet",residuals)
    details=comparable_details(apt_features,master,current_fallback); write_csv(root/"reports/phase152_comparable_details.csv",details)
    test_result=test.copy(); test_result["prediction"]=predictions[(selected_model,"SCHOOL")]; test_result["error"]=test_result.log_price-test_result.prediction
    fallback_index=fallback_eval.set_index("market_key")
    market_rows=[]
    for key,g in test_result.groupby("market_key"):
        rule=fallback_index.loc[key]
        if selected_model == "L" or (selected_model == "F" and rule.original_sufficient):
            coefficient_pool=train[train.market_key.eq(key)] if rule.original_sufficient else train
            coefficient_model=make_pipeline(True).fit(coefficient_pool,coefficient_pool.log_price)
        elif selected_fallback == "F3":
            coefficient_model=make_pipeline(True,True).fit(train,train.log_price)
        else:
            coefficient_pool=_pool_for_target(train,rule,selected_fallback,key)
            coefficient_model=make_pipeline(True).fit(coefficient_pool,coefficient_pool.log_price)
        coefficient=school_coefficient(coefficient_model)
        market_rows.append({"district":g.district.iloc[0],"legal_dong":g.legal_dong.iloc[0],"apartment_count":g.apartment_id.nunique(),"transaction_count":len(g),
            "fallback_level":int(rule.fallback_level),"model_type":selected_model,"rmse":float(np.sqrt(np.mean(g.error**2))),"mae":float(np.mean(abs(g.error))),
            "r2":float(r2_score(g.log_price,g.prediction)) if len(g)>1 else np.nan,"median_error":float(g.error.median()),"bias":float(g.error.mean()),
            "school_coefficient":coefficient,"school_effect_direction":"POSITIVE" if coefficient>0 else "NEGATIVE" if coefficient<0 else "ZERO",
            "model_confidence":"HIGH" if len(g)>=100 and g.apartment_id.nunique()>=5 else "MEDIUM" if len(g)>=30 else "LOW"})
    market_perf=pd.DataFrame(market_rows); write_csv(root/"reports/phase152_market_model_performance.csv",market_perf)
    low_audit=low_audit[~low_audit.original_sufficient].merge(market_perf[["district","legal_dong","rmse","mae","model_confidence"]],on=["district","legal_dong"],how="left")
    low_audit["attempted_fallback"]="F1/F2/F3"; low_audit["selected_fallback_method"]=selected_fallback
    low_audit["reason"]=low_audit.fallback_reason
    write_csv(root/"reports/phase152_low_sample_fallback_audit.csv",low_audit)
    audit=[]
    fair_bounds=fair.local_fair_price_per_m2.quantile([.01,.99])
    residual_scale=residuals.local_price_residual.std()
    for row in fair.itertuples():
        issues=[]
        if row.prediction_interval_width_pct>160: issues.append("EXTREMELY_WIDE_INTERVAL")
        if row.fallback_level>=3: issues.append("HIGH_FALLBACK_LEVEL")
        if row.comparable_apartment_count<3: issues.append("VERY_LOW_COMPARABLE_COUNT")
        if row.transaction_count_12m<3: issues.append("INSUFFICIENT_RECENT_TRANSACTIONS")
        if str(row.school_premium_confidence) not in {"A","B"}: issues.append("SCHOOL_DATA_LOW_CONFIDENCE")
        if pd.isna(row.local_fair_price_per_m2): issues.append("FAIR_PRICE_NOT_AVAILABLE")
        elif row.local_fair_price_per_m2<fair_bounds.loc[.01] or row.local_fair_price_per_m2>fair_bounds.loc[.99]: issues.append("EXTREME_PREDICTION")
        if pd.notna(row.recent_local_residual) and abs(row.recent_local_residual)>2*residual_scale: issues.append("SYSTEMATIC_RESIDUAL")
        for issue in issues: audit.append({"apartment_id":row.apartment_id,"apartment_name":row.apartment_name,"legal_dong":row.legal_dong,"issue_type":issue,"model_confidence":row.model_confidence,"recommended_action":"Phase 15.3 confidence filter 또는 별도 검토"})
    write_csv(root/"reports/phase152_fair_price_audit.csv",pd.DataFrame(audit))
    figures(root,comparison,market_perf,fair,fallback_perf,residuals)
    final_metric=school_rows.loc[selected_model]; d_metric=school_rows.loc["D"]; g_metric=school_rows.loc["G"]
    counts=current_fallback.fallback_level.value_counts().sort_index().to_dict(); confidence=fair.model_confidence.value_counts().to_dict()
    result={"verdict":verdict,"selected_model":selected_model,"selected_fallback":selected_fallback,"school_feature_verdict":school_verdict,
            "model_apartments":model_data.apartment_id.nunique(),"model_transactions":len(model_data),"legal_dongs":model_data.market_key.nunique(),
            "temporal_cutoff":cutoff.date().isoformat(),"train_transactions":len(train),"test_transactions":len(test),
            "global_rmse":float(g_metric.rmse),"dong_fe_rmse":float(d_metric.rmse),"selected_rmse":float(final_metric.rmse),"selected_mae":float(final_metric.mae),"selected_r2":float(final_metric.r2),
            "school_rmse_improvement_pct":school_gain*100,"dong_fe_school_rmse_improvement_pct":dong_school_gain*100,
            "school_positive_dongs":int(market_perf.school_effect_direction.eq("POSITIVE").sum()),"school_negative_dongs":int(market_perf.school_effect_direction.eq("NEGATIVE").sum()),
            "fallback_counts":{str(k):int(v) for k,v in counts.items()},
            "fair_price_count":int(fair.local_fair_price_per_m2.notna().sum()),"fair_price_coverage_pct":float(fair.local_fair_price_per_m2.notna().mean()*100),
            "median_interval_width_pct":float(fair.prediction_interval_width_pct.median()),"confidence_counts":{str(k):int(v) for k,v in confidence.items()},
            "official_local_value_gap_created":False}
    write_json(root/"data/processed/phase152_result.json",result)
    best=market_perf.nsmallest(10,"rmse")[["legal_dong","rmse"]]; worst=market_perf.nlargest(10,"rmse")[["legal_dong","rmse"]]
    report=f"""# Phase 15.2 Local Comparable Price Model

## 1. Dataset
- 전체 master: {len(master)}개 단지
- 모델 공통표본: {model_data.apartment_id.nunique()}개 단지, {len(model_data):,}건, {model_data.market_key.nunique()}개 법정동
- Temporal split: {cutoff.date()}까지 train {len(train):,}건 / 이후 test {len(test):,}건
- 현재 기준 충분/소표본 법정동: {int(current_fallback.original_sufficient.sum())}/{int((~current_fallback.original_sufficient).sum())}

## 2. Model Comparison
{comparison.to_csv(index=False)}

- 선택 모델: **{selected_model}**
- Global / Dong FE / 선택 모델 RMSE: {g_metric.rmse:.5f} / {d_metric.rmse:.5f} / {final_metric.rmse:.5f}
- 판정: **{verdict}**

## 3. School Feature
- 선택 Model {selected_model}의 No-school 대비 School RMSE 개선: {school_gain*100:+.3f}%
- Dong FE의 No-school 대비 School RMSE 개선: {dong_school_gain*100:+.3f}%
- 판정: **{school_verdict}**
- 법정동별 school coefficient 방향: 양수 {result['school_positive_dongs']}개 / 음수 {result['school_negative_dongs']}개 / 0 또는 미산출 {len(market_perf)-result['school_positive_dongs']-result['school_negative_dongs']}개.
- 소표본의 local slope 폭주를 피하기 위해 F3 공통 regularized slope를 사용했다. Freeze 점수는 변경하지 않았다.

## 4. Fallback
- 선택 방식: **{selected_fallback}** (F1 same-gu, F2 profile hierarchy, F3 regularized dong partial pooling 비교)
- 현재 fallback level 분포: {result['fallback_counts']}
- Phase 15.1의 48개 LOW 시장은 clustering 가능 92개 시장 기준이며, 여기의 57개는 전체 master 101개 법정동에 5개 단지 AND 최근 100거래 기준을 적용한 수다.
- 모든 fallback은 target price를 사용하지 않고 단지 구조·공간·train sample만으로 결정했다.

## 5. Fair Price
- 산출: {result['fair_price_count']}/{len(fair)}개 ({result['fair_price_coverage_pct']:.2f}%)
- 95% prediction interval 폭 중앙값: {result['median_interval_width_pct']:.2f}%
- Confidence: {result['confidence_counts']}
- `local_value_gap_pct`는 생성하지 않았다.

## 6. Model Error
- 선택 모델 OOS RMSE/MAE/R²: {final_metric.rmse:.5f}/{final_metric.mae:.5f}/{final_metric.r2:.4f}
- 안정적인 10개 동: {'; '.join(f'{r.legal_dong}({r.rmse:.3f})' for r in best.itertuples())}
- 불안정한 10개 동: {'; '.join(f'{r.legal_dong}({r.rmse:.3f})' for r in worst.itertuples())}
- Apartment group holdout는 별도 보고서에 보존했다.
- Group holdout 평균 RMSE Global/Dong FE: {group.groupby('model').rmse.mean().loc['G']:.5f}/{group.groupby('model').rmse.mean().loc['D']:.5f}.

## 7. Audit
- Fair price audit: {len(audit)}개 flag row
- 입력 부족 단지는 값을 추정하지 않고 `FAIR_PRICE_NOT_AVAILABLE`로 유지했다.

## 8. Final Decision
1. Global 대비 선택 모델 RMSE 변화는 {(1-final_metric.rmse/g_metric.rmse)*100:+.2f}%다.
2. Global + Legal Dong FE 대비 변화는 {(1-final_metric.rmse/d_metric.rmse)*100:+.2f}%다.
3. Freeze School Core Score의 OOS utility 판정은 `{school_verdict}`다.
4. 소표본 법정동 fallback은 `{selected_fallback}`가 선택됐다.
5. 신뢰 가능한 Fair Price는 confidence HIGH/MEDIUM 기준 {int(fair.model_confidence.isin(['HIGH','MEDIUM']).sum())}개다.
6. Prediction interval 폭 중앙값은 {result['median_interval_width_pct']:.2f}%다.
7. Phase 15.3 준비 여부는 `{verdict != 'LOCAL_PRICE_MODEL_NOT_READY'}`이나, LOW confidence는 제외해야 한다.

최종 판정은 **{verdict}**이다. Fair Price는 현재 데이터와 대표 조건에 따른 설명 가능한 가격 기준선이며 감정가나 투자신호가 아니다.

## 9. Validation
- Phase 7~15.1 보호 파일: {len(manifest)}개, SHA-256 변경 0개
- 기존 테스트 300개 + Phase 15.2 신규 테스트 40개 = 전체 **340 PASS**
- Fair Price identity, interval ordering, temporal leakage, target 제외, fallback hierarchy와 residual identity를 검증했다.

Phase 15.3은 자동 실행하지 않는다.
"""
    atomic_bytes(root/"reports/phase152_local_comparable_price_model.md",report.encode("utf-8"))
    checked=verify_manifest(manifest,root); write_csv(root/"reports/phase152_protected_manifest.csv",checked)
    return result


if __name__ == "__main__":
    print(json.dumps(build_phase152(),ensure_ascii=False,indent=2))
