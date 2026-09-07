"""Local Phase 5 validation view. Generate inputs with main.py validate-centum."""
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='Centum validation', layout='wide')
st.title('Centum validation')
st.caption('2025 통학구역 · K-apt 후보와 배정 근거 확인')


@st.cache_data(ttl=60, max_entries=4)
def load_frames():
    return {
        'catchments': pd.read_parquet(ROOT / 'data/interim/haeundae_elementary_catchment_2025.parquet'),
        'candidates': pd.read_parquet(ROOT / 'data/interim/haeundae_apartment_elementary_candidates_2025.parquet'),
        'matches': pd.read_parquet(ROOT / 'data/processed/haeundae_apartment_elementary_match_2025.parquet'),
        'middle': pd.read_parquet(ROOT / 'data/interim/haeundae_elementary_middle_validation_2025.parquet'),
        'reviews': pd.read_csv(ROOT / 'reports/haeundae_phase4_review_resolution_2025.csv'),
    }


try:
    frames = load_frames()
except FileNotFoundError:
    st.info('검증 자료를 먼저 생성하세요: python main.py validate-centum --office haeundae --year 2025')
    st.stop()

names = sorted(frames['matches'].elementary_school_name.unique())
school = st.selectbox('초등학교 선택', names, index=names.index('센텀초') if '센텀초' in names else 0)
matches = frames['matches'].query('elementary_school_name == @school')
catchments = frames['catchments'].query('elementary_school_name == @school')
middle = frames['middle'].query('elementary_school_name == @school')
st.warning('학교군 포함·조건부 지원은 배정 확정이 아닙니다. K-apt 주소와 좌표는 현재 스냅샷이며 2025 당시 정보를 보증하지 않습니다.')
with st.container(horizontal=True):
    st.metric('단지명 검증', len(matches), border=True)
    st.metric('확인 완료', int(matches.match_status.eq('CONFIRMED').sum()), border=True)
    st.metric('검수 필요', int(matches.manual_review.sum()), border=True)

st.subheader('공식 통학구역 원문')
for text in catchments.catchment_text.unique():
    st.write(text)
st.dataframe(catchments[['dong', 'raw_segment', 'tong_start', 'tong_end', 'ban_start', 'ban_end',
                        'apartment_name_pattern', 'parse_status']], hide_index=True)

st.subheader('K-apt 매칭 검증')
only_large = st.checkbox('표에서만 500세대 이상 표시', value=False)
visible = matches[matches.households.ge(500)] if only_large else matches
st.dataframe(visible[['raw_apartment_name', 'complex_name', 'internal_complex_id', 'apartment_address',
                     'households', 'distance_m', 'name_score', 'address_score', 'match_method',
                     'match_status', 'confidence', 'manual_review']], hide_index=True,
             column_config={'distance_m': st.column_config.NumberColumn('직선거리(m)', format='%.0f')})
st.caption('직선거리는 이상치 점검용입니다. 주소점수 0.8은 법정동 보조근거이며 통·반 확인이 아닙니다.')
with st.expander('모든 후보와 근거 확인'):
    st.dataframe(frames['candidates'].query('elementary_school_name == @school'), hide_index=True)
    st.dataframe(matches[['raw_apartment_name', 'evidence_source', 'evidence_text']], hide_index=True)

st.subheader('중학교 관계와 성과정보')
labels = {'exact': '확정', 'eligible': '지원 가능', 'group_only': '학교군 참고 · 개별 배정 미확정',
          'conditional_not_guaranteed': '조건부 지원 · 배정 보장 없음', 'unresolved': '근거 미확보'}
middle = middle.copy()
middle['관계 설명'] = middle.assignment_certainty.map(labels)
st.dataframe(middle[['middle_school_name', '관계 설명', 'assignment_type', 'assignment_certainty',
                    'gender_condition', 'guaranteed_assignment', 'middle_school_score',
                    'score_reference_year', 'score_join_status']], hide_index=True)
st.caption('중학교 점수는 해당 학교의 Phase 3 참고 지표이며 아파트·초등학교 점수로 집계하지 않습니다.')
with st.expander('배정자료 출처'):
    st.dataframe(middle[['middle_school_name', 'evidence_source', 'evidence_text']], hide_index=True)
st.subheader('기존 통학구역 검수 7건')
st.dataframe(frames['reviews'], hide_index=True)
