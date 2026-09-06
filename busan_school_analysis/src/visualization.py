"""Standalone Plotly ranking report; no web server or paid map API needed."""
import pandas as pd
import plotly.express as px

from .config import ROOT, atomic_bytes


def ranking_report(root=ROOT):
    scores = pd.read_parquet(root / 'data/processed/middle_school_scores.parquet')
    reference = int(scores.data_year.iloc[0])
    ranked = scores.loc[scores.middle_school_score.notna()].sort_values('busan_rank')
    top = ranked.head(30).sort_values('middle_school_score')
    chart = px.bar(top, x='middle_school_score', y='middle_school_name', orientation='h',
                   color='sigungu', hover_data=['busan_rank', 'graduates', 'available_year_count',
                                               'weighted_academic_selective_rate', 'sample_warning'],
                   labels={'middle_school_score': '중학교 점수', 'middle_school_name': '중학교', 'sigungu': '구·군'},
                   title=f'{reference - 2}–{reference} 공개 진학성과 · 부산 중학교 상위 30개', height=960)
    chart.update_layout(template='plotly_white', xaxis_range=[0, 100])
    cols = ['busan_rank', 'middle_school_name', 'sigungu', 'graduates', 'science_hs_count',
            'foreign_international_hs_count', 'autonomous_private_hs_count', 'academic_selective_rate',
            'weighted_academic_selective_rate', 'middle_school_score', 'available_year_count',
            'sample_warning', 'score_status']
    table = scores[cols].to_html(index=False, na_rep='미산출', float_format=lambda x: f'{x:.4f}')
    body = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>부산 중학교 진학성과 검증</title>
<style>body{{font:16px sans-serif;margin:32px;color:#172b3a}}table{{border-collapse:collapse;font-size:13px}}td,th{{padding:8px;border:1px solid #ddd}}th{{position:sticky;top:0;background:#eff4f8}}.table{{overflow:auto}}p{{max-width:1000px;line-height:1.7}}</style>
<h1>부산 중학교 진학성과 검증</h1><p>기준연도 {reference} · 점수 산출 {len(ranked)}개 / 기본정보 {len(scores)}개.
원자료: 학교알리미 졸업생의 진로 현황(13-다). 과학고·외고국제고·자율형사립고를 사용한다.
예고체고·마이스터고는 별도 지표다. 외고와 국제고의 개별 인원은 원자료에 없어 분리하지 않는다.</p>
<p>점수는 최근 3년 가중치 0.5/0.3/0.2, 졸업생 수 보정 k=100을 적용한 지표의 부산 백분위 가중합이다.
학교 교육의 인과적 효과나 입학 배정을 보장하지 않는다. 졸업자/인원/원진학률 열은 학교별 최신 검증연도의 값이며,
weighted 열은 3개년 가중평균이다. 진학률 단위는 0–1이다. 폐교·휴교와 자료 미확인 학교는 순위를 부여하지 않는다.</p>
{chart.to_html(full_html=False, include_plotlyjs=True)}<h2>전체 학교와 검수 상태</h2><div class="table">{table}</div></html>'''
    path = root / 'reports/middle_school_ranking.html'
    atomic_bytes(path, body.encode('utf-8'))
    return dict(report=str(path), ranked_schools=len(ranked))
