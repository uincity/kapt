"""부산아파트 학군분석 읽기 전용 Streamlit 진입점."""
import streamlit as st

st.set_page_config(
    page_title="부산아파트 학군분석",
    page_icon=":material/analytics:",
    layout="wide",
    initial_sidebar_state="expanded",
)
page1 = st.Page("app_pages/elementary_demand.py", title="초등학교수요분석", icon=":material/school:")
page2 = st.Page("app_pages/middle_school_score.py", title="중학교 점수", icon=":material/leaderboard:")
page3 = st.Page("app_pages/final_value_review.py", title="학군프리미엄분석", icon=":material/analytics:")

page = st.navigation([page1, page2, page3], position="hidden")

with st.sidebar:
    st.link_button(
        "제작자: 열심남",
        "https://uincity.github.io/",
        icon=":material/open_in_new:",
        use_container_width=True,
    )
    st.title("부산아파트 학군분석")
    st.page_link(page1, label="초등학교수요분석", icon=":material/school:")
    st.page_link(page2, label="중학교 점수", icon=":material/leaderboard:")
    st.page_link(page3, label="학군프리미엄분석", icon=":material/analytics:")

page.run()
