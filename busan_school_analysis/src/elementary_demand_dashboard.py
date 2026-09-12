"""Phase 9 초등학교 수요 자료의 읽기 전용 Streamlit 화면."""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from .config import ROOT
from .detail_navigation import detail_selection, school_ranking_table


DEMAND_PATH = "data/processed/phase9_elementary_demand_scores.parquet"
LONGITUDINAL_PATH = "data/processed/phase9_elementary_student_longitudinal.parquet"

QUALITY_LABELS = {"HIGH": "높음", "MEDIUM": "보통", "LOW": "낮음"}


@st.cache_data(ttl="10m", max_entries=4)
def load_elementary_demand_data(root_text: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = Path(root_text)
    scores = pd.read_parquet(root / DEMAND_PATH)
    history = pd.read_parquet(root / LONGITUDINAL_PATH)
    return scores, history


def filter_elementary_demand(
    data: pd.DataFrame,
    districts: list[str] | None = None,
    clusters: list[str] | None = None,
    qualities: list[str] | None = None,
    score_range: tuple[float, float] | None = None,
    minimum_students: int = 0,
) -> pd.DataFrame:
    out = data.copy()
    if districts:
        out = out[out.sigungu_requested.isin(districts)]
    if clusters:
        out = out[out.demand_cluster_name.isin(clusters)]
    if qualities:
        out = out[out.demand_score_quality.isin(qualities)]
    if score_range is not None:
        out = out[out.elementary_demand_score.between(*score_range, inclusive="both")]
    out = out[out.total_students.ge(minimum_students)]
    return out.reset_index(drop=True)


def _ranking_view(data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    out["district_rank"] = out.groupby("sigungu_requested")["elementary_demand_score"].rank(method="min", ascending=False)
    columns = {
        "elementary_demand_rank": "부산 순위",
        "district_rank": "구·군 순위",
        "sigungu_requested": "구·군",
        "elementary_school_name": "초등학교",
        "elementary_demand_score": "초등학교 수요점수",
        "elementary_demand_percentile": "부산 백분위",
        "demand_cluster_name": "학생수요 유형",
        "demand_score_quality": "자료 신뢰도",
        "total_students": "전체 학생수",
        "total_classes": "전체 학급수",
        "students_per_class": "학급당 학생수",
        "transfer_in": "전입 학생수",
        "transfer_out": "전출 학생수",
        "net_transfer_rate": "순전입률",
        "student_growth_3y": "최근 3개년 학생수 증감률",
        "adjusted_upper_grade_index": "보정 고학년 지수",
        "adjusted_cohort_growth": "보정 동일학년군 성장률",
    }
    selected = list(columns)
    view = out[selected].rename(columns=columns).sort_values(["부산 순위", "초등학교"])
    view["자료 신뢰도"] = view["자료 신뢰도"].map(QUALITY_LABELS).fillna("자료 부족")
    return view


def _school_detail(row: pd.Series) -> pd.DataFrame:
    values = {
        "학교 ID": row.elementary_school_id,
        "학교명": row.elementary_school_name,
        "구·군": row.sigungu_requested,
        "관할 교육지원청": row.JU_ORG_NM,
        "기준연도": int(row.data_year),
        "전체 학생수": int(row.total_students),
        "전체 학급수": int(row.total_classes),
        "학급당 학생수": f"{row.students_per_class:.1f}명",
        "전입 학생수": int(row.transfer_in),
        "전출 학생수": int(row.transfer_out),
        "순전입률": f"{row.net_transfer_rate * 100:.2f}%",
        "최근 3개년 학생수 증감률": f"{row.student_growth_3y * 100:.2f}%",
        "학생수 추세 기울기": f"{row.student_trend_slope:.1f}명/년",
        "보정 고학년 지수": f"{row.adjusted_upper_grade_index:.3f}",
        "보정 동일학년군 성장률": f"{row.adjusted_cohort_growth * 100:.2f}%",
        "학생수요 유형": row.demand_cluster_name if pd.notna(row.demand_cluster_name) else "자료 부족",
        "자료 신뢰도": QUALITY_LABELS.get(row.demand_score_quality, "자료 부족"),
    }
    return pd.DataFrame({"항목": values.keys(), "값": [str(value) for value in values.values()]})


def render_elementary_demand_dashboard(root=ROOT) -> None:
    root = Path(root)
    st.title("초등학교수요분석")
    st.caption("학교알리미 2024~2026년 학생·학급·전입전출 자료로 산출한 9단계 동결 결과")
    if not (root / DEMAND_PATH).is_file() or not (root / LONGITUDINAL_PATH).is_file():
        st.error("초등학교 수요 동결 자료를 찾을 수 없습니다.")
        st.stop()
    scores, history = load_elementary_demand_data(str(root.resolve()))

    with st.sidebar:
        st.header("초등학교 수요 조회 조건")
        districts = st.multiselect("구·군", sorted(scores.sigungu_requested.dropna().unique()), placeholder="선택")
        clusters = st.multiselect("학생수요 유형", sorted(scores.demand_cluster_name.dropna().unique()), placeholder="선택")
        qualities = st.multiselect("자료 신뢰도", ["HIGH", "MEDIUM", "LOW"], format_func=lambda value: QUALITY_LABELS[value], placeholder="선택")
        score_range = st.slider("초등학교 수요점수", 0.0, 100.0, (0.0, 100.0))
        minimum_students = st.number_input("최소 학생수", min_value=0, value=0, step=100)

    filtered = filter_elementary_demand(scores, districts, clusters, qualities, score_range, int(minimum_students))
    with st.container(horizontal=True):
        st.metric("조회 학교", f"{len(filtered):,}개", border=True)
        st.metric("평균 수요점수", f"{filtered.elementary_demand_score.mean():.1f}" if len(filtered) else "N/A", border=True)
        st.metric("전체 학생수", f"{filtered.total_students.sum():,.0f}명", border=True)
        st.metric("순전입 학생", f"{(filtered.transfer_in.sum() - filtered.transfer_out.sum()):+,.0f}명", border=True)
        st.metric("자료 신뢰도 높음", f"{filtered.demand_score_quality.eq('HIGH').sum():,}개", border=True)

    overview, ranking, detail, trend, guide = st.tabs(["구·군 현황", "학교 순위", "학교 상세", "연도별 추이", "지표 안내"], key="elementary_tabs", on_change="rerun")
    with overview:
        district = filtered.groupby("sigungu_requested", as_index=False).agg(
            school_count=("elementary_school_id", "nunique"),
            average_score=("elementary_demand_score", "mean"),
            median_score=("elementary_demand_score", "median"),
            total_students=("total_students", "sum"),
            net_transfer=("transfer_in", "sum"),
            transfer_out=("transfer_out", "sum"),
        )
        district["net_transfer"] -= district["transfer_out"]
        district = district.rename(columns={"sigungu_requested": "구·군", "school_count": "학교 수", "average_score": "평균 수요점수", "median_score": "수요점수 중앙값", "total_students": "전체 학생수", "net_transfer": "순전입 학생수"}).drop(columns="transfer_out")
        st.bar_chart(district.sort_values("평균 수요점수", ascending=False), x="구·군", y="평균 수요점수")
        st.dataframe(district, hide_index=True, column_config={"평균 수요점수": st.column_config.NumberColumn(format="%.1f"), "수요점수 중앙값": st.column_config.NumberColumn(format="%.1f"), "전체 학생수": st.column_config.NumberColumn(format="%,d명"), "순전입 학생수": st.column_config.NumberColumn(format="%+d명")})

    with ranking:
        view = _ranking_view(filtered)
        school_ranking_table(
            view, filtered.loc[view.index, "elementary_school_id"],
            key="elementary_ranking", tab_key="elementary_tabs", selection_key="elementary_detail",
        )

    with detail:
        if filtered.empty:
            st.info("조회 조건에 맞는 학교가 없습니다.")
        else:
            options = filtered.sort_values(["sigungu_requested", "elementary_school_name"])
            labels = options.sigungu_requested.astype(str) + " · " + options.elementary_school_name.astype(str)
            row = detail_selection("초등학교 선택", options, "elementary_school_id", labels.tolist(), key="elementary_detail")
            with st.container(horizontal=True):
                st.metric("초등학교 수요점수", f"{row.elementary_demand_score:.1f}", border=True)
                st.metric("부산 순위", f"{int(row.elementary_demand_rank):,}위", border=True)
                district_scores = scores[scores.sigungu_requested.eq(row.sigungu_requested)]
                district_ranks = district_scores.elementary_demand_score.rank(method="min", ascending=False)
                district_rank = int(district_ranks.loc[district_scores.elementary_school_id.eq(row.elementary_school_id)].iloc[0])
                st.metric("구·군 순위", f"{district_rank:,}위", border=True)
                st.metric("전체 학생수", f"{int(row.total_students):,}명", border=True)
            grade = pd.DataFrame({"학년": ["1학년", "2학년", "3학년", "4학년", "5학년", "6학년"], "학생수": [row[f"grade{i}_students"] for i in range(1, 7)], "학급수": [row[f"grade{i}_classes"] for i in range(1, 7)]})
            st.bar_chart(grade, x="학년", y="학생수")
            st.dataframe(_school_detail(row), hide_index=True)
            components = pd.DataFrame({"점수 구성": ["학생·학급 규모", "전입·전출 이동", "최근 3개년 증감", "고학년·동일학년군"], "점수": [row.size_component_score, row.mobility_component_score, row.growth_component_score, row.upper_cohort_component_score]})
            st.bar_chart(components, x="점수 구성", y="점수")

    with trend:
        school_ids = set(filtered.elementary_school_id)
        history_view = history[history.elementary_school_id.isin(school_ids)].copy()
        if history_view.empty:
            st.info("연도별 자료가 없습니다.")
        else:
            school_options = filtered.sort_values(["sigungu_requested", "elementary_school_name"])
            school_labels = school_options.sigungu_requested.astype(str) + " · " + school_options.elementary_school_name.astype(str)
            selected_label = st.selectbox("추이 확인 학교", school_labels.tolist(), placeholder="선택")
            school_id = school_options.iloc[school_labels.tolist().index(selected_label)].elementary_school_id
            selected_history = history_view[history_view.elementary_school_id.eq(school_id)].sort_values("data_year")
            chart_data = selected_history.rename(columns={"data_year": "연도", "total_students": "전체 학생수", "transfer_in": "전입", "transfer_out": "전출"})
            st.line_chart(chart_data, x="연도", y="전체 학생수")
            st.dataframe(chart_data[["연도", "전체 학생수", "전입", "전출"]], hide_index=True)

    with guide:
        st.markdown("""
        - **초등학교 수요점수**는 학생 규모, 학급 규모, 전입·전출, 최근 3개 공시연도 증감, 부산 학령구조를 보정한 고학년 지수와 동일학년군 변화를 0~100으로 표현합니다.
        - 이 점수는 학교 교육의 질이나 서열을 뜻하지 않습니다. 학생 자료에서 관측되는 해당 통학구역의 주거·학군 수요 정도입니다.
        - **학생수요 유형**은 학교 우열 등급이 아니라 학생수요 패턴을 설명하기 위한 군집입니다.
        - 제공 기간은 2024~2026년이며, 장기 추세나 인과관계로 해석하지 않습니다.
        """)

    st.download_button("현재 조회 학교 자료 내려받기", filtered.to_csv(index=False).encode("utf-8-sig"), "초등학교_수요_조회결과.csv", "text/csv")
