"""Read-only Streamlit viewer for the frozen Phase 15.4 value model."""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from .config import ROOT
from .phase154_final_freeze import FINAL_STATUS, validate_phase154_freeze


MASTER_PATH = "data/processed/phase154_final_apartment_value_master.csv"
CANDIDATES_PATH = "reports/phase154_final_candidates.csv"
AUDIT_PATH = "reports/phase154_high_audit_review.csv"
SNAPSHOT_PATH = "data/snapshots/phase154_final_model_freeze.json"

CLASS_LABELS = {
    "CORE_CANDIDATE": "핵심 후보",
    "LOCAL_VALUE": "지역 상대가치 후보",
    "SCHOOL_VALUE": "학군 상대가치 후보",
    "WATCHLIST": "추가 검토",
    "FULLY_PRICED_OR_NEGATIVE": "가격 반영 또는 음의 신호",
}
CONFIDENCE_LABELS = {"HIGH": "높음", "MEDIUM": "보통", "LOW": "낮음"}
INTERVAL_LABELS = {
    "STRONG_UNDERVALUED_SIGNAL": "강한 저평가 신호",
    "POTENTIAL_UNDERVALUED_SIGNAL": "잠재 저평가 신호",
    "WITHIN_MODEL_RANGE": "모델 예측범위 안",
    "POTENTIAL_OVERVALUED_SIGNAL": "잠재 고평가 신호",
    "STRONG_OVERVALUED_SIGNAL": "강한 고평가 신호",
    "INSUFFICIENT": "자료 부족",
}
TEMPORAL_LABELS = {
    "STABLE_POSITIVE": "양의 방향 안정",
    "STABLE_NEGATIVE": "음의 방향 안정",
    "MIXED": "기간별 혼재",
    "INSUFFICIENT": "자료 부족",
}
AGREEMENT_LABELS = {
    "DOUBLE_POSITIVE": "학군·지역 모두 양의 신호",
    "LOCAL_ONLY_POSITIVE": "지역만 양의 신호",
    "SCHOOL_ONLY_POSITIVE": "학군만 양의 신호",
    "DOUBLE_NEGATIVE": "학군·지역 모두 음의 신호",
    "MIXED_OR_NEUTRAL": "혼재 또는 중립",
}
AUDIT_LABELS = {"HIGH": "높음", "MEDIUM": "보통", "LOW": "낮음"}
LIMITATION_LABELS = {
    "NONE": "특이사항 없음",
    "WIDE_PREDICTION_INTERVAL": "넓은 예측구간",
    "LEGAL_DONG_BIAS": "법정동 편향",
    "LOW_TRANSACTION": "거래량 부족",
    "HIGH_FALLBACK": "상위 대체모형 의존",
    "EXTREME_RESIDUAL": "극단 잔차",
    "LOW_MODEL_CONFIDENCE": "낮은 모델 신뢰도",
    "LOW_SCHOOL_CONFIDENCE": "낮은 학군 신뢰도",
    "MISSING_FAIR_PRICE": "적정가격 없음",
    "MISSING_SCHOOL_SCORE": "학군점수 없음",
    "MULTIPLE_LIMITATIONS": "복수 한계",
}


def korean_value(value):
    if pd.isna(value):
        return "자료 부족"
    text = str(value)
    maps = (CLASS_LABELS, CONFIDENCE_LABELS, INTERVAL_LABELS, TEMPORAL_LABELS, AGREEMENT_LABELS, AUDIT_LABELS, LIMITATION_LABELS)
    for mapping in maps:
        if text in mapping:
            return mapping[text]
    if ";" in text:
        return "; ".join(korean_value(part) for part in text.split(";"))
    return text


@st.cache_data(ttl="10m", max_entries=4)
def load_frozen_data(root_text: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    root = Path(root_text)
    master = pd.read_csv(root / MASTER_PATH, encoding="utf-8-sig")
    candidates = pd.read_csv(root / CANDIDATES_PATH, encoding="utf-8-sig")
    audit = pd.read_csv(root / AUDIT_PATH, encoding="utf-8-sig")
    snapshot = json.loads((root / SNAPSHOT_PATH).read_text(encoding="utf-8"))
    return master, candidates, audit, snapshot


def currency_eok(value) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value) / 100_000_000:.2f}억"


def percent_text(value, digits: int = 2) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):.{digits}f}%"


def score_text(value) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{float(value):.1f}"


def filter_master(
    data: pd.DataFrame,
    gu: list[str] | None = None,
    legal_dong: list[str] | None = None,
    review_class: list[str] | None = None,
    model_confidence: list[str] | None = None,
    local_confidence: list[str] | None = None,
    school_confidence: list[str] | None = None,
    interval_status: list[str] | None = None,
    school_score_range: tuple[float, float] | None = None,
    local_gap_range: tuple[float, float] | None = None,
    school_gap_range: tuple[float, float] | None = None,
    households_min: int = 0,
    dong_bias: str = "전체",
    audit_priority: list[str] | None = None,
) -> pd.DataFrame:
    out = data.copy()
    for column, selected in (
        ("gu", gu), ("legal_dong", legal_dong), ("final_review_class", review_class),
        ("model_confidence", model_confidence), ("local_gap_confidence", local_confidence),
        ("gap_confidence", school_confidence), ("local_gap_interval_status", interval_status),
        ("phase154_audit_priority", audit_priority),
    ):
        if selected:
            out = out[out[column].isin(selected)]
    for column, limits in (
        ("school_premium_core_score", school_score_range),
        ("local_value_gap_pct", local_gap_range),
        ("school_value_gap_pct", school_gap_range),
    ):
        if limits is not None:
            out = out[out[column].between(limits[0], limits[1], inclusive="both")]
    out = out[out.household_count.ge(households_min)]
    if dong_bias == "편향 있음":
        out = out[out.dong_bias_flag]
    elif dong_bias == "편향 없음":
        out = out[~out.dong_bias_flag]
    return out.reset_index(drop=True)


def health_check(root=ROOT) -> tuple[bool, pd.DataFrame]:
    checks = validate_phase154_freeze(root)
    return bool(checks.passed.all()), checks


def download_frame(data: pd.DataFrame) -> bytes:
    return data.to_csv(index=False).encode("utf-8-sig")


def _range(data: pd.Series, fallback=(0.0, 100.0)) -> tuple[float, float]:
    values = pd.to_numeric(data, errors="coerce").dropna()
    if values.empty:
        return fallback
    low, high = float(np.floor(values.min())), float(np.ceil(values.max()))
    if low == high:
        high = low + 1.0
    return low, high


def _display_table(data: pd.DataFrame, columns: list[str]) -> None:
    labels = {
        "apartment_name": "단지명", "gu": "구", "legal_dong": "법정동", "household_count": "세대수",
        "school_premium_core_score": "학군 핵심 점수", "school_value_gap_pct": "학군 상대가치 격차",
        "local_value_gap_pct": "지역 상대가치 격차", "local_fair_total_price": "적정가격",
        "observed_market_price_12m": "최근 12개월 관측가격", "local_gap_interval_status": "예측구간 판정",
        "model_confidence": "모델 신뢰도", "local_gap_confidence": "지역 Gap 신뢰도",
        "gap_confidence": "학군 Gap 신뢰도", "final_review_class": "최종 검토 분류",
        "phase154_audit_priority": "감사 우선순위", "model_limitation_detail": "모델 한계",
    }
    view = data[columns].copy()
    for column in ("local_fair_total_price", "observed_market_price_12m"):
        if column in view:
            view[column] = pd.to_numeric(view[column], errors="coerce") / 100_000_000
    for column in ("final_review_class", "model_confidence", "local_gap_confidence", "gap_confidence", "local_gap_interval_status", "phase154_audit_priority", "model_limitation_detail"):
        if column in view:
            view[column] = view[column].map(korean_value)
    view = view.rename(columns=labels)
    st.dataframe(
        view,
        hide_index=True,
        column_config={
            "세대수": st.column_config.NumberColumn(format="%d"),
            "학군 핵심 점수": st.column_config.NumberColumn(format="%.1f"),
            "학군 상대가치 격차": st.column_config.NumberColumn(format="%.2f%%"),
            "지역 상대가치 격차": st.column_config.NumberColumn(format="%.2f%%"),
            "적정가격": st.column_config.NumberColumn(format="%.2f억"),
            "최근 12개월 관측가격": st.column_config.NumberColumn(format="%.2f억"),
        },
    )


def render_final_value_dashboard(root=ROOT) -> None:
    root = Path(root)
    st.title("최종 가치분석")
    st.caption("15.4단계 동결 결과 조회·검증 화면")
    ok, checks = health_check(root)
    if not ok:
        st.error("동결 파일 무결성 검사에 실패했습니다. 모델은 재계산하지 않았습니다.")
        st.dataframe(checks, hide_index=True)
        st.stop()

    master, candidates, audit, snapshot = load_frozen_data(str(root.resolve()))

    with st.sidebar:
        st.header("조회 조건")
        gu = st.multiselect("구", sorted(master.gu.dropna().unique()), key="p154_gu")
        dong_options = sorted(master.loc[master.gu.isin(gu) if gu else master.index.notna(), "legal_dong"].dropna().unique())
        dong = st.multiselect("법정동", dong_options, key="p154_dong")
        review_class = st.multiselect("최종 검토 분류", list(CLASS_LABELS), format_func=lambda x: CLASS_LABELS[x])
        model_conf = st.multiselect("모델 신뢰도", ["HIGH", "MEDIUM", "LOW"], format_func=lambda x: CONFIDENCE_LABELS[x])
        local_conf = st.multiselect("지역 격차 신뢰도", ["HIGH", "MEDIUM", "LOW"], format_func=lambda x: CONFIDENCE_LABELS[x])
        school_conf = st.multiselect("학군 격차 신뢰도", ["HIGH", "MEDIUM", "LOW"], format_func=lambda x: CONFIDENCE_LABELS[x])
        interval = st.multiselect("예측구간 판정", sorted(master.local_gap_interval_status.dropna().unique()), format_func=lambda x: INTERVAL_LABELS.get(x, x))
        score_limits = _range(master.school_premium_core_score)
        school_score = st.slider("학군 핵심 점수", score_limits[0], score_limits[1], score_limits)
        local_limits = _range(master.local_value_gap_pct, (-100.0, 100.0))
        local_gap = st.slider("지역 상대가치 격차(%)", local_limits[0], local_limits[1], local_limits)
        school_limits = _range(master.school_value_gap_pct, (-100.0, 100.0))
        school_gap = st.slider("학군 상대가치 격차(%)", school_limits[0], school_limits[1], school_limits)
        households = st.number_input("최소 세대수", min_value=0, value=0, step=100)
        dong_bias = st.segmented_control("법정동 편향", ["전체", "편향 있음", "편향 없음"], default="전체")
        audit_priority = st.multiselect("감사 우선순위", ["HIGH", "MEDIUM", "LOW"], format_func=lambda x: AUDIT_LABELS[x])

    filtered = filter_master(
        master, gu, dong, review_class, model_conf, local_conf, school_conf, interval,
        school_score, local_gap, school_gap, int(households), dong_bias or "전체", audit_priority,
    )

    with st.container(horizontal=True):
        st.metric("전체 단지", f"{len(master):,}", border=True)
        st.metric("적정가격 산출", f"{master.local_fair_total_price.notna().sum():,}", border=True)
        st.metric("지역 격차 산출", f"{master.local_value_gap_pct.notna().sum():,}", border=True)
        st.metric("핵심 후보", f"{master.final_review_class.eq('CORE_CANDIDATE').sum():,}", border=True)
        st.metric("이중 양의 신호", f"{master.school_local_signal_agreement.eq('DOUBLE_POSITIVE').sum():,}", border=True)
        st.metric("강건한 이중 후보", f"{master.combined_candidate_class.eq('ROBUST_DUAL_POSITIVE').sum():,}", border=True)
        st.metric("강한 저평가 신호", f"{master.local_gap_interval_status.eq('STRONG_UNDERVALUED_SIGNAL').sum():,}", border=True)
        st.metric("추가 검토", f"{master.final_review_class.eq('WATCHLIST').sum():,}", border=True)
    st.caption(f"현재 필터 결과: {len(filtered):,}개")

    overview, core_tab, detail_tab, dong_tab, audit_tab, validation_tab = st.tabs(
        ["전체 현황", "핵심 후보", "단지 상세", "법정동 검증", "감사·추가 검토", "모델 검증"]
    )

    with overview:
        left, right = st.columns(2)
        with left.container(border=True):
            st.subheader("최종 분류")
            counts = filtered.final_review_class.map(korean_value).value_counts().rename_axis("분류").reset_index(name="단지 수")
            st.bar_chart(counts, x="분류", y="단지 수")
        with right.container(border=True):
            st.subheader("모델 신뢰도")
            conf = filtered.model_confidence.map(korean_value).value_counts().rename_axis("신뢰도").reset_index(name="단지 수")
            st.bar_chart(conf, x="신뢰도", y="단지 수")
        hist_source = filtered[["local_value_gap_pct", "school_value_gap_pct"]].rename(columns={"local_value_gap_pct": "지역 상대가치 격차", "school_value_gap_pct": "학군 상대가치 격차"}).melt(var_name="구분", value_name="격차").dropna()
        st.altair_chart(alt.Chart(hist_source).mark_bar(opacity=.65).encode(x=alt.X("격차:Q", bin=alt.Bin(maxbins=35)), y=alt.Y("count()", title="단지 수"), color="구분:N"))
        quadrant = filtered.dropna(subset=["school_value_gap_pct", "local_value_gap_pct"]).copy()
        quadrant["신호 조합"] = quadrant.school_local_signal_agreement.map(korean_value)
        quadrant["최종 검토 분류"] = quadrant.final_review_class.map(korean_value)
        quadrant["모델 신뢰도"] = quadrant.model_confidence.map(korean_value)
        quadrant = quadrant.rename(columns={"school_value_gap_pct": "학군 상대가치 격차", "local_value_gap_pct": "지역 상대가치 격차", "apartment_name": "단지명", "legal_dong": "법정동"})
        chart = alt.Chart(quadrant).mark_circle(size=60, opacity=.7).encode(
            x=alt.X("학군 상대가치 격차:Q", title="학군 상대가치 격차(%)"),
            y=alt.Y("지역 상대가치 격차:Q", title="지역 상대가치 격차(%)"),
            color=alt.Color("신호 조합:N", title="신호 조합"),
            tooltip=["단지명", "법정동", "최종 검토 분류", "모델 신뢰도"],
        )
        rules = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(strokeDash=[5, 5], color="#777").encode(x="zero:Q") + alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(strokeDash=[5, 5], color="#777").encode(y="zero:Q")
        st.altair_chart(chart + rules)

    with core_tab:
        core = filtered[filtered.final_review_class.eq("CORE_CANDIDATE")].copy()
        _display_table(core, ["apartment_name", "legal_dong", "household_count", "school_premium_core_score", "school_value_gap_pct", "local_value_gap_pct", "local_fair_total_price", "observed_market_price_12m", "local_gap_interval_status", "model_confidence", "local_gap_confidence", "gap_confidence"])

    with detail_tab:
        options = filtered.sort_values(["apartment_name", "apartment_id"])
        if options.empty:
            st.info("조회 조건에 맞는 단지가 없습니다.")
        else:
            labels = options.apartment_name.astype(str) + " · " + options.legal_dong.astype(str) + " · " + options.apartment_id.astype(str)
            selected_label = st.selectbox("단지 선택", labels.tolist())
            row = options.iloc[labels.tolist().index(selected_label)]
            with st.container(horizontal=True):
                st.metric("학군 핵심 점수", score_text(row.school_premium_core_score), border=True)
                st.metric("학군 상대가치 격차", percent_text(row.school_value_gap_pct), border=True)
                st.metric("지역 상대가치 격차", percent_text(row.local_value_gap_pct), border=True)
                st.metric("적정가격", currency_eok(row.local_fair_total_price), border=True)
                st.metric("최근 12개월 가격", currency_eok(row.observed_market_price_12m), border=True)
            st.write(f"**{row.apartment_name}** · {row.gu} {row.legal_dong} · {int(row.household_count):,}세대 · {row.elementary_school_name or '자료 부족'}")
            price = pd.DataFrame({"구분": ["예측 하한", "적정가격", "예측 상한", "관측 12개월"], "가격": [row.fair_price_lower, row.local_fair_total_price, row.fair_price_upper, row.observed_market_price_12m]})
            st.altair_chart(alt.Chart(price.dropna()).mark_point(size=180).encode(x=alt.X("가격:Q", axis=alt.Axis(format="~s")), y=alt.Y("구분:N", sort=None), color="구분:N", tooltip=["구분", alt.Tooltip("가격:Q", format=",")]))
            detail_values = [row.final_review_class, row.school_local_signal_agreement, row.local_gap_interval_status, row.local_gap_temporal_stability, row.model_confidence, row.local_gap_confidence, row.gap_confidence, row.comparable_apartment_count, row.comparable_transaction_count, row.fallback_level, row.phase154_audit_priority, row.model_limitation_detail]
            details = pd.DataFrame({"항목": ["최종 분류", "신호 조합", "구간 판정", "기간 안정성", "모델 신뢰도", "지역 격차 신뢰도", "학군 격차 신뢰도", "비교 단지", "비교 거래", "대체모형 단계", "감사 우선순위", "모델 한계"], "값": [korean_value(value) for value in detail_values]})
            st.dataframe(details, hide_index=True)

    with dong_tab:
        official = filtered[filtered.model_confidence.isin(["HIGH", "MEDIUM"]) & filtered.local_value_gap_pct.notna()]
        dong_summary = official.groupby(["gu", "legal_dong"], as_index=False).agg(
            apartment_count=("apartment_id", "size"), median_local_gap=("local_value_gap_pct", "median"),
            positive_share=("local_value_gap_pct", lambda x: float((x > 3).mean())),
            negative_share=("local_value_gap_pct", lambda x: float((x < -3).mean())),
            bias_flag=("dong_bias_flag", "max"), model_rmse_proxy=("local_model_rmse", "median"),
            median_interval_width=("prediction_interval_width_pct", "median"),
        ).sort_values(["bias_flag", "median_local_gap"], ascending=[False, False])
        dong_summary = dong_summary.rename(columns={"gu": "구", "legal_dong": "법정동", "apartment_count": "단지 수", "median_local_gap": "지역 격차 중앙값", "positive_share": "양의 신호 비율", "negative_share": "음의 신호 비율", "bias_flag": "편향 여부", "model_rmse_proxy": "모델 오차", "median_interval_width": "예측구간 폭 중앙값"})
        dong_summary["편향 여부"] = dong_summary["편향 여부"].map({True: "편향 있음", False: "편향 없음"})
        st.dataframe(dong_summary, hide_index=True, column_config={"지역 격차 중앙값": st.column_config.NumberColumn(format="%.2f%%"), "양의 신호 비율": st.column_config.NumberColumn(format="percent"), "음의 신호 비율": st.column_config.NumberColumn(format="percent"), "예측구간 폭 중앙값": st.column_config.NumberColumn(format="%.2f%%")})

    with audit_tab:
        audit_type = st.pills("감사 유형", ["전체", "미설명 고가요인", "미설명 저가요인", "법정동 편향", "넓은 구간", "낮은 거래량", "대체모형"], default="전체")
        watch = filtered[filtered.final_review_class.eq("WATCHLIST") | filtered.phase154_audit_priority.eq("HIGH")].copy()
        if audit_type == "미설명 고가요인": watch = watch[watch.unmodeled_premium_candidate]
        elif audit_type == "미설명 저가요인": watch = watch[watch.unmodeled_discount_candidate]
        elif audit_type == "법정동 편향": watch = watch[watch.dong_bias_flag]
        elif audit_type == "넓은 구간": watch = watch[watch.model_limitation_detail.str.contains("WIDE_PREDICTION_INTERVAL", na=False)]
        elif audit_type == "낮은 거래량": watch = watch[watch.model_limitation_detail.str.contains("LOW_TRANSACTION", na=False)]
        elif audit_type == "대체모형": watch = watch[watch.fallback_level.gt(0)]
        _display_table(watch, ["apartment_name", "gu", "legal_dong", "local_value_gap_pct", "school_value_gap_pct", "local_gap_interval_status", "model_confidence", "phase154_audit_priority", "model_limitation_detail"])

    with validation_tab:
        st.subheader("동결 모델 상태")
        state = snapshot["project_state"]
        st.success("부산 아파트 가치모형 최종 동결 완료")
        with st.container(horizontal=True):
            st.metric("모형 F 평균제곱근오차", f"{snapshot['local_model']['model_f_rmse']:.5f}", border=True)
            st.metric("모형 F 결정계수", f"{snapshot['local_model']['model_f_r2']:.4f}", border=True)
            st.metric("6개월·12개월 순위상관", f"{snapshot['local_value']['gap_6m_12m_spearman']:.4f}", border=True)
            st.metric("학군·지역 순위상관", f"{snapshot['dual_signal']['school_local_spearman']:.4f}", border=True)
            st.metric("보호 파일", f"{snapshot['integrity']['protected_file_count']:,}", border=True)
            st.metric("자동 검증", f"{snapshot['integrity']['total_pytest_count']:,}개 통과", border=True)
        check_labels = {"final_master_exists": "최종 자료 존재", "freeze_snapshot_exists": "동결 스냅샷 존재", "protected_manifest_exists": "보호목록 존재", "master_row_count": "단지 수", "apartment_id_unique": "단지 ID 고유성", "class_complete": "최종 분류 완전성", "fair_price_identity": "적정가격 원본 동일성", "local_gap_identity": "지역 격차 원본 동일성", "school_gap_identity": "학군 격차 원본 동일성", "protected_hashes_unchanged": "보호 파일 무변경", "snapshot_frozen": "최종 동결 상태", "pytest_full_pass": "전체 자동검증 통과"}
        checks_view = checks.rename(columns={"check": "검증 항목", "passed": "통과", "detail": "상세"})
        checks_view["검증 항목"] = checks_view["검증 항목"].map(check_labels).fillna(checks_view["검증 항목"])
        checks_view["통과"] = checks_view["통과"].map({True: "통과", False: "실패"})
        st.dataframe(checks_view, hide_index=True)

    st.subheader("자료 내려받기")
    with st.container(horizontal=True):
        st.download_button("현재 필터 결과", download_frame(filtered), "phase154_filtered.csv", "text/csv")
        st.download_button("핵심 후보", download_frame(master[master.final_review_class.eq("CORE_CANDIDATE")]), "phase154_core_candidates.csv", "text/csv")
        st.download_button("추가 검토", download_frame(master[master.final_review_class.eq("WATCHLIST")]), "phase154_watchlist.csv", "text/csv")
        st.download_button("높은 우선순위 감사 후보", download_frame(audit), "phase154_high_audit.csv", "text/csv")

    st.warning("본 분석은 통계적 상대가치 모형이며 실제 매매가격의 조망, 재건축 기대, 내부 상태, 동·향 등 모든 개별 요인을 반영하지 않습니다. 지역 상대가치 격차는 수익을 보장하는 저평가 지표가 아니라 유사 단지 대비 상대가치 검토 신호입니다.")


def streamlit_uses_only_frozen_sources() -> bool:
    return all("phase154" in path for path in (MASTER_PATH, CANDIDATES_PATH, AUDIT_PATH, SNAPSHOT_PATH))
