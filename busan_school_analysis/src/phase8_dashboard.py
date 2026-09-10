"""Streamlit view for the Phase 8 school premium validation artifacts."""
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


@st.cache_data(ttl=60, max_entries=2)
def _load(root: str):
    root = Path(root)
    return {
        "panel": pd.read_parquet(root / "data/processed/phase8_apartment_school_price_panel.parquet"),
        "corr": pd.read_csv(root / "reports/phase8_school_price_correlation.csv"),
        "quintile": pd.read_csv(root / "reports/phase8_school_quintile_analysis.csv"),
        "reg": pd.read_csv(root / "reports/phase8_regression_results.csv"),
        "pairs": pd.read_csv(root / "reports/phase8_comparable_pairs.csv"),
        "top": pd.read_csv(root / "reports/phase8_top30_school_price.csv"),
    }


def render_phase8(root):
    try: d = _load(str(root))
    except FileNotFoundError:
        st.info("Phase 8 자료를 먼저 생성하세요: python main.py phase8-build"); return
    p=d["panel"].copy(); p["year_month"]=p.year_month.astype(str)
    latest=sorted(p.year_month.dropna().unique())[-1]
    with st.sidebar:
        period=st.selectbox("분석 기간",["최근 월", "최근 12개월 패널", "전체 패널"])
        area_labels={"under_40":"40㎡ 미만","40_55":"40~55㎡","55_65":"55~65㎡(59㎡형)","65_80":"65~80㎡","80_90":"80~90㎡(84㎡형)","90_120":"90~120㎡","over_120":"120㎡ 이상"}
        area=st.multiselect("면적그룹",sorted(p.area_group.dropna().unique()),default=["80_90"] if "80_90" in set(p.area_group) else [],format_func=lambda x:area_labels.get(x,x))
        minimum=st.number_input("최소 세대수",min_value=0,value=500,step=100)
        sigungu=st.multiselect("구군",sorted(p.sigungu.dropna().unique()))
        dong=st.multiselect("법정동",sorted(p.legal_dong.dropna().unique()))
        quality=st.multiselect("학군 품질",["HIGH","MEDIUM","LOW"],default=["HIGH"],format_func=lambda x:{"HIGH":"높음","MEDIUM":"보통","LOW":"낮음"}[x])
    if period=="최근 월": view=p[p.year_month.eq(latest)]
    elif period=="최근 12개월 패널": view=p[p.year_month.ge(str(pd.Period(latest,freq="M")-11))]
    else: view=p
    if area: view=view[view.area_group.isin(area)]
    view=view[view.households.ge(minimum)&view.school_zone_score.notna()]
    if sigungu: view=view[view.sigungu.isin(sigungu)]
    if dong: view=view[view.legal_dong.isin(dong)]
    if quality: view=view[view.school_score_quality.isin(quality)]
    tabs=st.tabs(["A. 부산 전체","B. 구군별","C. 법정동 비교","D. 유사단지 쌍","E. 회귀분석","F. 가격 방어력"])
    with tabs[0]:
        st.plotly_chart(px.scatter(view,x="school_zone_score",y="median_price_per_sqm",hover_name="complex_name",color="sigungu",labels={"school_zone_score":"학군점수","median_price_per_sqm":"㎡당 중앙가격","sigungu":"구·군"}),width="stretch")
        st.dataframe(d["quintile"],hide_index=True)
    with tabs[1]:
        st.plotly_chart(px.scatter(view,x="school_zone_score",y="median_price_per_sqm",facet_col="sigungu",facet_col_wrap=4,labels={"school_zone_score":"학군점수","median_price_per_sqm":"㎡당 중앙가격","sigungu":"구·군"}),width="stretch")
        st.dataframe(d["corr"][d["corr"].scope.eq("SIGUNGU")],hide_index=True)
    with tabs[2]:
        latest_view=view.sort_values("year_month").groupby("internal_complex_id").tail(1)
        st.plotly_chart(px.scatter(latest_view,x="school_zone_score",y="median_price_per_sqm",color="legal_dong",hover_name="complex_name"),width="stretch")
        st.caption("법정동 고정 비교는 동일 동에 분석 가능 단지가 3개 이상일 때 산출합니다.")
    with tabs[3]: st.dataframe(d["pairs"],hide_index=True,width="stretch")
    with tabs[4]:
        st.plotly_chart(px.bar(d["reg"],x="model",y="score_10point_association_pct",color="price_variant",error_y="score_10point_se_pct",barmode="group"),width="stretch")
        st.dataframe(d["reg"],hide_index=True)
        st.caption("10점 차이 수치는 관측 특성을 통제한 통계적 연관이며 인과효과가 아닙니다.")
    with tabs[5]:
        monthly=view.groupby("year_month",as_index=False).median_price_per_sqm.median(); monthly["change"]=monthly.median_price_per_sqm.pct_change(); monthly["market_phase"]=monthly.change.map(lambda x:"상승" if x>=0 else "하락")
        st.plotly_chart(px.line(monthly,x="year_month",y="median_price_per_sqm",color="market_phase",markers=True),width="stretch")
        st.dataframe(d["top"],hide_index=True,width="stretch")

