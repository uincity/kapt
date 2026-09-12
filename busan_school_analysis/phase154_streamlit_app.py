"""부산아파트 학군분석 읽기 전용 Streamlit 진입점."""
import streamlit as st

st.set_page_config(page_title="부산아파트 학군분석", page_icon=":material/analytics:", layout="wide")
st.sidebar.title("부산아파트 학군분석")
page = st.navigation(
    [
        st.Page("app_pages/elementary_demand.py", title="초등학교수요분석", icon=":material/school:"),
        st.Page("app_pages/middle_school_score.py", title="중학교 점수", icon=":material/leaderboard:"),
        st.Page("app_pages/final_value_review.py", title="학군프리미엄분석", icon=":material/analytics:"),
    ],
    position="sidebar",
)
page.run()
st.set_page_config(page_title="부산아파트 학군분석")
