"""Phase 3/7 중학교 점수 동결 자료의 읽기 전용 Streamlit 화면."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from .config import ROOT


MIDDLE_SCORE_PATH = "data/processed/middle_school_scores.parquet"
STATUS_LABELS = {
    "scored": "점수 산출",
    "no_valid_observations": "유효 관측 없음",
    "closed_or_suspended": "폐교 또는 휴교",
}
REVIEW_REASON_LABELS = {
    "small_sample_or_missing_years": "소규모 표본 또는 관측연도 부족",
    "no_valid_observations": "유효 관측 없음",
    "closed_or_suspended": "폐교 또는 휴교",
}


@st.cache_data(ttl="10m", max_entries=4)
def load_middle_school_scores(root_text: str) -> pd.DataFrame:
    return pd.read_parquet(Path(root_text) / MIDDLE_SCORE_PATH)


def filter_middle_school_scores(
    data: pd.DataFrame,
    districts: list[str] | None = None,
    statuses: list[str] | None = None,
    score_range: tuple[float, float] | None = None,
    minimum_observed_years: int = 0,
    warning_filter: str = "전체",
) -> pd.DataFrame:
    out = data.copy()
    if districts:
        out = out[out.sigungu.isin(districts)]
    if statuses:
        out = out[out.score_status.isin(statuses)]
    if score_range is not None:
        out = out[out.middle_school_score.between(*score_range, inclusive="both")]
    out = out[pd.to_numeric(out.available_year_count, errors="coerce").fillna(0).ge(minimum_observed_years)]
    if warning_filter == "표본 경고 있음":
        out = out[out.sample_warning]
    elif warning_filter == "표본 경고 없음":
        out = out[~out.sample_warning]
    return out.reset_index(drop=True)


def middle_ranking_view(data: pd.DataFrame) -> pd.DataFrame:
    view = data[[
        "busan_rank", "sigungu_rank", "sigungu", "middle_school_name", "middle_school_score",
        "score_percentile", "latest_observation_year", "available_year_count", "graduates_total",
        "score_stability", "sample_warning", "score_status",
    ]].copy()
    view = view.rename(columns={
        "busan_rank": "부산 순위", "sigungu_rank": "구·군 순위", "sigungu": "구·군",
        "middle_school_name": "중학교", "middle_school_score": "중학교 점수",
        "score_percentile": "부산 백분위", "latest_observation_year": "최근 관측연도",
        "available_year_count": "관측연도 수", "graduates_total": "누적 졸업자 수",
        "score_stability": "점수 안정성", "sample_warning": "표본 경고", "score_status": "점수 상태",
    })
    view["표본 경고"] = view["표본 경고"].map({True: "확인 필요", False: "이상 없음"})
    view["점수 상태"] = view["점수 상태"].map(STATUS_LABELS).fillna("자료 부족")
    return view.sort_values(["부산 순위", "구·군", "중학교"], na_position="last")


def _detail_table(row: pd.Series) -> pd.DataFrame:
    values = {
        "학교 ID": row.middle_school_id,
        "학교명": row.middle_school_name,
        "구·군": row.sigungu,
        "점수 기준연도": int(row.score_reference_year) if pd.notna(row.score_reference_year) else "자료 부족",
        "관측연도": row.observation_years if pd.notna(row.observation_years) else "자료 부족",
        "관측연도 수": int(row.available_year_count) if pd.notna(row.available_year_count) else 0,
        "누적 졸업자 수": int(row.graduates_total) if pd.notna(row.graduates_total) else "자료 부족",
        "가중 졸업자 수": f"{row.weighted_graduates:.1f}" if pd.notna(row.weighted_graduates) else "자료 부족",
        "점수 안정성": f"{row.score_stability:.3f}" if pd.notna(row.score_stability) else "자료 부족",
        "표본 경고": "확인 필요" if bool(row.sample_warning) else "이상 없음",
        "점수 상태": STATUS_LABELS.get(row.score_status, "자료 부족"),
        "검토 사유": REVIEW_REASON_LABELS.get(row.review_reason, row.review_reason) if pd.notna(row.review_reason) and row.review_reason else "해당 없음",
    }
    return pd.DataFrame({"항목": values.keys(), "값": [str(value) for value in values.values()]})


def render_middle_school_score_dashboard(root=ROOT) -> None:
    root = Path(root)
    st.title("중학교 점수")
    st.caption("학교알리미 2023~2025년 고교 진학현황을 이용한 기존 중학교 점수 동결 결과")
    if not (root / MIDDLE_SCORE_PATH).is_file():
        st.error("중학교 점수 동결 자료를 찾을 수 없습니다.")
        st.stop()
    scores = load_middle_school_scores(str(root.resolve()))

    with st.sidebar:
        st.header("중학교 점수 조회 조건")
        districts = st.multiselect("구·군", sorted(scores.sigungu.dropna().unique()), key="middle_district")
        statuses = st.multiselect("점수 상태", list(STATUS_LABELS), format_func=lambda value: STATUS_LABELS[value])
        score_range = st.slider("중학교 점수", 0.0, 100.0, (0.0, 100.0))
        minimum_years = st.number_input("최소 관측연도 수", min_value=0, max_value=3, value=0, step=1)
        warning_filter = st.segmented_control("표본 경고", ["전체", "표본 경고 있음", "표본 경고 없음"], default="전체")

    filtered = filter_middle_school_scores(scores, districts, statuses, score_range, int(minimum_years), warning_filter or "전체")
    scored = filtered[filtered.middle_school_score.notna()]
    with st.container(horizontal=True):
        st.metric("조회 학교", f"{len(filtered):,}개", border=True)
        st.metric("점수 산출 학교", f"{len(scored):,}개", border=True)
        st.metric("점수 산출률", f"{len(scored) / len(filtered) * 100:.1f}%" if len(filtered) else "자료 부족", border=True)
        st.metric("평균 점수", f"{scored.middle_school_score.mean():.1f}" if len(scored) else "자료 부족", border=True)
        st.metric("표본 경고", f"{filtered.sample_warning.sum():,}개", border=True)

    overview, ranking, detail, guide = st.tabs(["구·군 현황", "중학교 순위", "학교 상세", "점수 안내"])
    with overview:
        district = filtered.groupby("sigungu", as_index=False).agg(
            school_count=("middle_school_id", "nunique"),
            scored_count=("middle_school_score", "count"),
            average_score=("middle_school_score", "mean"),
            median_score=("middle_school_score", "median"),
            warning_count=("sample_warning", "sum"),
        ).rename(columns={"sigungu": "구·군", "school_count": "중학교 수", "scored_count": "점수 산출 학교", "average_score": "평균 점수", "median_score": "점수 중앙값", "warning_count": "표본 경고 학교"})
        st.bar_chart(district.sort_values("평균 점수", ascending=False), x="구·군", y="평균 점수")
        st.dataframe(district, hide_index=True, column_config={"평균 점수": st.column_config.NumberColumn(format="%.1f"), "점수 중앙값": st.column_config.NumberColumn(format="%.1f")})

    with ranking:
        st.dataframe(
            middle_ranking_view(filtered), hide_index=True,
            column_config={
                "부산 순위": st.column_config.NumberColumn(format="%.0f위"),
                "구·군 순위": st.column_config.NumberColumn(format="%.0f위"),
                "중학교 점수": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=100),
                "부산 백분위": st.column_config.NumberColumn(format="%.1f%%"),
                "최근 관측연도": st.column_config.NumberColumn(format="%.0f년"),
                "관측연도 수": st.column_config.NumberColumn(format="%.0f개년"),
                "누적 졸업자 수": st.column_config.NumberColumn(format="%,.0f명"),
                "점수 안정성": st.column_config.NumberColumn(format="%.3f"),
            },
        )

    with detail:
        if filtered.empty:
            st.info("조회 조건에 맞는 중학교가 없습니다.")
        else:
            options = filtered.sort_values(["sigungu", "middle_school_name"])
            labels = options.sigungu.astype(str) + " · " + options.middle_school_name.astype(str)
            selected = st.selectbox("중학교 선택", labels.tolist())
            row = options.iloc[labels.tolist().index(selected)]
            with st.container(horizontal=True):
                st.metric("중학교 점수", f"{row.middle_school_score:.2f}" if pd.notna(row.middle_school_score) else "자료 부족", border=True)
                st.metric("부산 순위", f"{int(row.busan_rank):,}위" if pd.notna(row.busan_rank) else "자료 부족", border=True)
                st.metric("구·군 순위", f"{int(row.sigungu_rank):,}위" if pd.notna(row.sigungu_rank) else "자료 부족", border=True)
                st.metric("부산 백분위", f"{row.score_percentile:.1f}%" if pd.notna(row.score_percentile) else "자료 부족", border=True)
            components = pd.DataFrame({
                "점수 구성": ["과학고 진학률 백분위", "외고·국제고 진학률 백분위", "자율형사립고 진학률 백분위"],
                "백분위": [row.science_rate_percentile, row.foreign_international_rate_percentile, row.autonomous_private_rate_percentile],
            })
            st.bar_chart(components, x="점수 구성", y="백분위")
            rates = pd.DataFrame({
                "진학 구분": ["과학고", "외고·국제고", "자율형사립고", "선별 진학 전체"],
                "3개년 가중 진학률": [row.weighted_science_rate, row.weighted_foreign_international_rate, row.weighted_autonomous_private_rate, row.weighted_academic_selective_rate],
                "표본 보정 진학률": [row.weighted_science_rate_adjusted, row.weighted_foreign_international_rate_adjusted, row.weighted_autonomous_private_rate_adjusted, row.weighted_academic_selective_rate_adjusted],
            })
            st.dataframe(rates, hide_index=True, column_config={"3개년 가중 진학률": st.column_config.NumberColumn(format="percent"), "표본 보정 진학률": st.column_config.NumberColumn(format="percent")})
            st.dataframe(_detail_table(row), hide_index=True)

    with guide:
        st.markdown("""
        - 중학교 점수는 학교알리미 고교 진학현황 중 과학고, 외고·국제고, 자율형사립고 진학률을 최근 3개년 가중치와 표본 크기 보정 후 부산 내 백분위로 계산한 기존 점수입니다.
        - 점수 범위는 0~100이며 부산 순위와 구·군 순위를 함께 제공합니다.
        - 표본 경고는 관측연도가 1개뿐이거나 특정 연도 졸업자 수가 적은 학교를 뜻합니다.
        - 이 점수는 관측된 진학성과 지표이며 학교 자체의 인과적 교육효과나 특정 학생의 진학을 보장하지 않습니다.
        """)

    st.download_button("현재 조회 중학교 자료 내려받기", filtered.to_csv(index=False).encode("utf-8-sig"), "중학교_점수_조회결과.csv", "text/csv")
