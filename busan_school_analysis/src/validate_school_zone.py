from pathlib import Path

import pandas as pd

from .config import ROOT, atomic_bytes, write_csv


def ensure_same_year(*frames, expected_year):
    observed = set()
    for frame in frames:
        if not frame.empty and 'data_year' in frame:
            observed.update(int(value) for value in frame.data_year.dropna().unique())
    if observed != {int(expected_year)}:
        raise ValueError(f'data_year mismatch: expected {expected_year}, observed {sorted(observed)}')
    return True


def validate_school_zone(office, year, *, root=ROOT):
    if office != 'haeundae' or year != 2025:
        raise ValueError('Phase 4 PoC supports only --office haeundae --year 2025.')
    root = Path(root)
    catchment_path = root / f'data/interim/{office}_elementary_catchment_{year}.parquet'
    group_path = root / f'data/interim/{office}_middle_school_groups_{year}.parquet'
    relation_path = root / f'data/interim/{office}_middle_assignment_{year}.parquet'
    if not catchment_path.exists() or not group_path.exists():
        raise FileNotFoundError('Run both Phase 4 parsers before validation.')
    catchments, groups = pd.read_parquet(catchment_path), pd.read_parquet(group_path)
    relations = pd.read_parquet(relation_path) if relation_path.exists() else pd.DataFrame()
    ensure_same_year(catchments, groups, relations, expected_year=year)

    centum = catchments[catchments.elementary_school_name.eq('센텀초')]
    if centum.empty or not centum.catchment_text.str.contains('19～22통', regex=False).any() or \
            not centum.catchment_text.str.contains('센텀스타', regex=False).any():
        raise ValueError('Centum fixture conditions are absent from the parsed official data.')
    if not ((centum.tong_start == 19) & (centum.tong_end == 22)).any() or \
            not ((centum.tong_start == 26) & (centum.tong_end == 26)).any():
        raise ValueError('Centum tong ranges were not parsed as required.')

    reviews = catchments.loc[catchments.manual_review].copy()
    review_output = root / f'reports/{office}_parse_review_{year}.csv'
    write_csv(review_output, reviews)
    apartment_count = int(catchments.apartment_name_pattern.apply(
        lambda x: len(x) if x is not None and not isinstance(x, (str, float)) else 0).sum())
    raw_rows = int(catchments[['elementary_school_name', 'dong', 'catchment_text']].drop_duplicates().shape[0])
    tong_rate = float(catchments.tong_start.notna().mean())
    metadata = root / f'data/raw/education_office/{office}/{year}/middle_assignment/attachments_metadata.csv'
    documents_ok = metadata.exists() and len(pd.read_csv(metadata)) >= 2
    group_counts = groups.groupby('school_group').middle_school_name.nunique().sort_index()
    status_counts = catchments.parse_status.value_counts()
    exact_exists = (not relations.empty and relations.assignment_certainty.eq('exact').any())
    conditional_exists = not relations.empty
    lines = [
        f'# 해운대교육지원청 Phase 4 검증 보고서 ({year}학년도)', '',
        '## 검증 결과', '',
        f'- 초등학교 전체 수: {catchments.elementary_school_name.nunique()}',
        f'- 통학구역 raw row 수: {raw_rows}',
        f"- PARSED / PARTIAL / REVIEW: {status_counts.get('PARSED', 0)} / {status_counts.get('PARTIAL', 0)} / {status_counts.get('REVIEW', 0)}",
        f'- 통 파싱 성공률: {tong_rate:.1%}',
        f'- 반 파싱 건수: {int(catchments.ban_start.notna().sum())}',
        f'- 아파트명 추출 건수: {apartment_count}',
        f"- 공동통학구역 관련 원문 행 수: {int((catchments.catchment_text.fillna('') + catchments.remarks.fillna('')).str.contains('공동통학구역').sum())}",
        f"- 중입 공식문서 다운로드: {'성공' if documents_ok else '확인 필요'}",
        f'- 중학교 학교군 수: {groups.school_group.nunique()}',
        '- 학교군별 중학교 수: ' + ', '.join(f'{key}={value}' for key, value in group_counts.items()),
        f"- 상세 조건부 초→중 관계 추출: {'가능' if conditional_exists else '불가'}",
        f"- 초등학교별 특정 중학교 확정 관계: {'있음' if exact_exists else '공개 공식자료만으로 확정할 수 없음'}",
        '- data_year mismatch: 없음',
        f'- 수동검토 필요 구간 수: {len(reviews)}', '',
        '## 해석 제한', '',
        '학교군 포함은 특정 학교 배정을 보장하지 않는다. PDF의 일반우선·희망지원 표는 지원 자격과 후보를 명시하지만 정원 및 추첨 조건이 있다.',
        '센텀초가 14학교군에 속한다는 사실만으로 센텀중 배정을 확정하지 않았다. 센텀초는 일반우선배정 표에서 장산중·재송중·재송여중 대상이며, 성별·정원·추첨 조건을 적용받는다.',
        '학교군 안내 웹페이지에는 적용연도가 직접 표시되지 않아 2025 시행계획 PDF를 연도 판정의 기준 문서로 사용했다.', '',
        '## 원문과 provenance', '',
        '- 초등 통학구역 HTML, 게시판 HTML, 게시물 HTML, 첨부 PDF/HWP, 학교군 HTML을 원본 바이트로 보존했다.',
        '- legacy HWP는 자동 해석하지 않고 PDF 텍스트를 사용했다. 수동 보완 CSV는 빈 템플릿으로 제공한다.',
    ]
    report_path = root / f'reports/{office}_phase4_validation.md'
    atomic_bytes(report_path, ('\n'.join(lines) + '\n').encode('utf-8'))
    return {'schools': int(catchments.elementary_school_name.nunique()), 'raw_rows': raw_rows,
            'segments': len(catchments), 'manual_review': len(reviews),
            'school_groups': int(groups.school_group.nunique()),
            'conditional_relations': len(relations), 'exact_relations': int(exact_exists),
            'report': str(report_path)}
