"""Phase 7 local validation dashboard."""
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="부산 학군점수 검증", layout="wide")
st.title("부산 학군점수 검증")
st.caption("2025 공식 통학구역·중입 근거와 Phase 3 중학교 성과를 연결한 설명 가능한 점수")


@st.cache_data(ttl=60, max_entries=4)
def load_frames():
    return {
        "apartments": pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_2025.parquet"),
        "large": pd.read_parquet(ROOT / "data/processed/busan_apartment_school_scores_500plus_2025.parquet"),
        "feeders": pd.read_parquet(ROOT / "data/processed/elementary_feeder_scores_2025.parquet"),
        "middle": pd.read_parquet(ROOT / "data/processed/middle_school_scores.parquet"),
        "relations": pd.read_parquet(ROOT / "data/processed/busan_elementary_middle_relation_2025.parquet"),
        "detail": pd.read_parquet(ROOT / "data/processed/elementary_middle_score_detail_2025.parquet"),
        "sensitivity": pd.read_parquet(ROOT / "data/processed/busan_school_score_sensitivity_2025.parquet"),
        "quality": pd.read_csv(ROOT / "reports/phase7_school_score_quality.csv"),
    }


try:
    frames = load_frames()
except FileNotFoundError:
    # Preserve the Phase 5 fixture view used by the regression suite.
    try:
        legacy_matches = pd.read_parquet(ROOT / "data/processed/haeundae_apartment_elementary_match_2025.parquet")
        legacy_middle = pd.read_parquet(ROOT / "data/interim/haeundae_elementary_middle_validation_2025.parquet")
        names = sorted(legacy_matches.elementary_school_name.unique())
        school = st.selectbox("초등학교 선택", names, index=names.index("센텀초") if "센텀초" in names else 0)
        visible = legacy_matches[legacy_matches.elementary_school_name.eq(school)]
        only_large = st.checkbox("표에서만 500세대 이상 표시", value=False)
        if only_large:
            visible = visible[visible.households.ge(500)]
        st.dataframe(visible, hide_index=True)
        st.dataframe(legacy_middle[legacy_middle.elementary_school_name.eq(school)], hide_index=True)
    except FileNotFoundError:
        st.info("Phase 7 자료를 먼저 생성하세요: python main.py phase7-build")
    st.stop()

pages = ["Overview", "Middle ranking", "Feeder ranking", "Apartment ranking",
         "Centum validation", "Score sensitivity", "Data quality"]
page = st.sidebar.selectbox("메뉴", pages)
st.warning("학교군 포함과 조건부 지원은 배정 확정이 아닙니다. 거리는 직선거리이며 실제 보행 통학거리와 다릅니다.")

if page == "Overview":
    apartments = frames["apartments"]
    with st.container(horizontal=True):
        st.metric("전체 단지", f"{len(apartments):,}", border=True)
        st.metric("점수 생성", f"{apartments.school_zone_score.notna().sum():,}", border=True)
        st.metric("500세대 이상 점수", f"{frames['large'].school_zone_score.notna().sum():,}/{len(frames['large']):,}", border=True)
        st.metric("Feeder 점수", f"{frames['feeders'].elementary_feeder_score.notna().sum():,}", border=True)
    chart = apartments.dropna(subset=["school_zone_score"])["school_zone_score"].round().value_counts().sort_index()
    st.bar_chart(chart, x_label="학군점수", y_label="단지 수")

elif page == "Middle ranking":
    cols = ["busan_rank", "middle_school_name", "sigungu", "middle_school_score", "score_stability", "sample_warning"]
    st.dataframe(frames["middle"].dropna(subset=["middle_school_score"]).sort_values("busan_rank")[cols], hide_index=True,
                 column_config={"middle_school_score": st.column_config.NumberColumn("점수", format="%.2f")})

elif page == "Feeder ranking":
    feeder = frames["feeders"].dropna(subset=["elementary_feeder_score"]).sort_values("elementary_feeder_score", ascending=False)
    cols = ["elementary_school_name", "elementary_feeder_score", "eligible_middle_count", "weighted_middle_score",
            "worst_middle_score", "feeder_exclusivity", "feeder_uncertainty", "assignment_data_quality"]
    st.dataframe(feeder[cols], hide_index=True)

elif page == "Apartment ranking":
    source = frames["apartments"]
    with st.sidebar:
        sigungu = st.multiselect("구군", sorted(source.sigungu.dropna().unique()))
        only_large = st.checkbox("500세대 이상", value=False)
        quality = st.multiselect("품질", ["HIGH", "MEDIUM", "LOW"])
    view = source.copy()
    if sigungu:
        view = view[view.sigungu.isin(sigungu)]
    if only_large:
        view = view[view.households.ge(500)]
    if quality:
        view = view[view.school_score_quality.isin(quality)]
    view = view.sort_values("busan_school_rank", na_position="last")
    cols = ["busan_school_rank", "complex_name", "sigungu", "legal_dong", "households", "elementary_school_names",
            "school_zone_score", "school_zone_percentile", "school_zone_grade", "mean_middle_score",
            "worst_middle_score", "feeder_exclusivity", "nearest_elementary_distance_m", "school_score_quality"]
    event = st.dataframe(view[cols], hide_index=True, on_select="rerun", selection_mode="single-row",
                         column_config={"school_zone_score": st.column_config.ProgressColumn("학군점수", min_value=0, max_value=100)})
    if event.selection.rows:
        selected = view.iloc[event.selection.rows[0]]
        st.subheader(f"{selected.complex_name} 점수 구성")
        st.json({"초등학교": selected.elementary_school_names, "최종점수": selected.school_zone_score,
                 "feeder 평균": selected.mean_elementary_feeder_score, "feeder 최저": selected.worst_elementary_feeder_score,
                 "접근성": selected.elementary_accessibility_score, "배정자료 품질": selected.assignment_data_quality})
        ids = selected.elementary_school_ids if isinstance(selected.elementary_school_ids, (list, tuple)) else []
        detail = frames["detail"][frames["detail"].elementary_school_id.isin(ids)]
        st.dataframe(detail[["elementary_school_name", "middle_school_name", "relation_type",
                             "assignment_reliability_weight", "middle_school_score", "busan_rank"]], hide_index=True)

elif page == "Centum validation":
    feeders = frames["feeders"][frames["feeders"].elementary_school_name.astype(str).str.contains("센텀")]
    relations = frames["detail"][frames["detail"].elementary_school_name.astype(str).str.contains("센텀")]
    apartments = frames["apartments"][frames["apartments"].elementary_school_names.astype(str).str.contains("센텀")]
    st.subheader("센텀초 feeder")
    st.dataframe(feeders, hide_index=True)
    st.subheader("센텀초 → 중학교 공식 관계 수준")
    st.dataframe(relations[["middle_school_name", "relation_type", "assignment_reliability_weight",
                            "guaranteed_assignment", "middle_school_score", "busan_rank"]], hide_index=True)
    st.caption("센텀초→센텀중은 GROUP_MEMBERSHIP이며 EXACT로 승격하지 않습니다.")
    st.subheader("센텀 관련 단지")
    st.dataframe(apartments.sort_values("busan_school_rank"), hide_index=True)

elif page == "Score sensitivity":
    sensitivity = frames["sensitivity"].dropna(subset=["rank_base"]).sort_values("rank_base")
    with st.container(horizontal=True):
        st.metric("민감 단지", int(sensitivity.ranking_sensitive.sum()), border=True)
        st.metric("최대 순위 범위", f"{sensitivity.rank_range.max():.0f}", border=True)
    st.dataframe(sensitivity[["complex_name", "rank_base", "rank_quality", "rank_stability",
                              "rank_range", "ranking_sensitive"]], hide_index=True)

else:
    st.dataframe(frames["quality"], hide_index=True)
    st.subheader("아파트 품질 상태")
    st.bar_chart(frames["apartments"].school_score_quality.value_counts())
    st.subheader("중입 관계 유형")
    st.bar_chart(frames["relations"].relation_type.value_counts())
    st.dataframe(frames["apartments"][frames["apartments"].school_score_status.ne("SCORED")][
        ["internal_complex_id", "complex_name", "school_score_status", "school_score_quality"]], hide_index=True)
