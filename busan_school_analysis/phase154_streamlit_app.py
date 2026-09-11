"""부산 아파트 가치분석 읽기 전용 Streamlit 진입점."""
import streamlit as st

st.set_page_config(page_title="부산 아파트 최종 가치분석", page_icon=":material/analytics:", layout="wide")
page = st.navigation(
    [
        st.Page("app_pages/final_value_review.py", title="최종 가치분석", icon=":material/analytics:"),
        st.Page("app_pages/elementary_demand.py", title="초등학교 수요 분석", icon=":material/school:"),
        st.Page("app_pages/middle_school_score.py", title="중학교 점수", icon=":material/leaderboard:"),
    ],
    position="sidebar",
)
page.run()
