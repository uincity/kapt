"""Phase 5 evidence-preserving validation. No school-score aggregation."""
import hashlib
import json
from pathlib import Path

import pandas as pd

from .config import ROOT, atomic_bytes, now, settings, write_csv, write_json, write_parquet
from .match_apartment_school import build_apartment_matches, filter_500plus, load_overrides

INPUTS = {
    'schools': 'data/processed/schools.parquet',
    'advancement': 'data/processed/middle_school_advancement.parquet',
    'scores': 'data/processed/middle_school_scores.parquet',
    'apartments': 'data/interim/apartment_master.parquet',
    'catchments': 'data/interim/haeundae_elementary_catchment_2025.parquet',
    'groups': 'data/interim/haeundae_middle_school_groups_2025.parquet',
    'assignment': 'data/interim/haeundae_middle_assignment_2025.parquet',
}


def schema_audit(root=ROOT):
    root = Path(root)
    result = {}
    for name, relative in INPUTS.items():
        path = root / relative
        frame = pd.read_parquet(path)
        result[name] = dict(path=relative, rows=len(frame), columns=list(frame.columns),
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    required = {'internal_complex_id', 'kapt_code', 'complex_name', 'address', 'road_address',
                'legal_dong', 'households', 'latitude', 'longitude'}
    if not required.issubset(result['apartments']['columns']):
        raise ValueError('Apartment master required columns missing.')
    upstream = (root / settings(root)['apartment_project']).resolve()
    result['upstream'] = []
    for relative in ['data/interim/kapt_clean.parquet', 'data/processed/busan_complex_summary.csv',
                     'data/processed/apartment_match_log.csv', 'data/interim/kapt_coordinates.parquet']:
        path = upstream / relative
        frame = pd.read_parquet(path) if path.suffix == '.parquet' else pd.read_csv(path)
        result['upstream'].append(dict(path=str(path), rows=len(frame), columns=list(frame.columns),
                                       sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    result['audited_at'] = now()
    write_json(root / 'reports/haeundae_phase5_schema_audit.json', result)
    return result


def assignment_is_guaranteed(certainty):
    return str(certainty).lower() == 'exact'


def school_key(name):
    return str(name).replace('등학교', '').replace('학교', '').replace('여자', '여').replace(' ', '')


def build_middle_validation(groups, assignments, scores, school_names=None):
    if school_names is None:
        school_names = ['센텀초']
    if not groups.data_year.eq(2025).all() or not assignments.data_year.eq(2025).all():
        raise ValueError('Assignment data_year mismatch.')
    records = []
    for school in school_names:
        explicit = assignments[assignments.elementary_school_name.eq(school)]
        if explicit.empty:
            records.append(dict(data_year=2025, elementary_school_name=school,
                                middle_school_name=None, assignment_type='unresolved',
                                assignment_certainty='unresolved', gender_condition=None,
                                evidence_source=None, evidence_text='초등학교별 학교군 근거 미확보'))
            continue
        # Membership comes only from explicit official elementary records, not distance/dong.
        for group in explicit.school_group.dropna().unique():
            members = groups[groups.school_group.eq(group)][
                ['middle_school_name', 'school_gender', 'source_url', 'raw_text']].drop_duplicates()
            evidence = explicit[explicit.school_group.eq(group)].iloc[0]
            for row in members.itertuples():
                records.append(dict(data_year=2025, elementary_school_name=school,
                                    middle_school_name=row.middle_school_name, school_group=group,
                                    assignment_type='group_membership', assignment_certainty='group_only',
                                    gender_condition=row.school_gender, evidence_source=row.source_url,
                                    group_membership_source=evidence.source_document,
                                    group_membership_section=evidence.source_page_or_section,
                                    evidence_text=row.raw_text, temporal_review=True,
                                    temporal_note='학교군 HTML 적용연도 미표시; 2025 PDF와 별도 대조 필요'))
        for row in explicit.itertuples():
            records.append(dict(data_year=row.data_year, elementary_school_name=school,
                                middle_school_name=row.middle_school_name, school_group=row.school_group,
                                assignment_type=row.assignment_type, assignment_certainty=row.assignment_certainty,
                                gender_condition=row.gender_condition, evidence_source=row.source_document,
                                source_page_or_section=row.source_page_or_section,
                                evidence_text=row.source_text, temporal_review=False))
    frame = pd.DataFrame(records)
    frame['guaranteed_assignment'] = frame.assignment_certainty.map(assignment_is_guaranteed)
    lookup = scores.copy()
    lookup['_join_name'] = lookup.middle_school_name.map(school_key)
    lookup = lookup[lookup['_join_name'].isin(frame.middle_school_name.map(school_key))]
    if lookup['_join_name'].duplicated().any():
        raise ValueError('Duplicate middle school names: reviewed ID mapping required.')
    frame['_join_name'] = frame.middle_school_name.map(school_key)
    frame = frame.merge(lookup[['_join_name', 'middle_school_id', 'middle_school_score',
                                'score_reference_year', 'observation_years', 'score_status']],
                        on='_join_name', how='left', validate='many_to_one')
    frame['score_source_document'] = INPUTS['scores']
    frame['score_join_status'] = frame.middle_school_id.notna().map({True: 'matched', False: 'unavailable'})
    return frame.drop(columns='_join_name')


def resolve_phase4_reviews(reviews, matches):
    records = []
    for review in reviews.itertuples():
        name = review.raw_segment if review.catchment_type == 'unparsed' else None
        relevant = matches[(matches.elementary_school_name == review.elementary_school_name) &
                           (matches.raw_apartment_name == name)] if name else matches.iloc[:0]
        result = relevant.iloc[0] if len(relevant) else None
        contextual = result is not None and pd.notna(result.internal_complex_id)
        records.append(dict(
            review_id=f'P5-{review.raw_row_index:03d}-{review.segment_index:02d}',
            elementary_school_name=review.elementary_school_name, raw_catchment_text=review.catchment_text,
            raw_segment=review.raw_segment, parsed_dong=review.dong,
            parsed_tong=f'{review.tong_start:g}-{review.tong_end:g}' if pd.notna(review.tong_start) else None,
            parsed_ban=f'{review.ban_start:g}-{review.ban_end:g}' if pd.notna(review.ban_start) else None,
            parsed_apartment_name=name,
            review_reason='괄호 없는 단지명' if name else '일부/제외 경계 추가 확인 필요',
            resolved=False, resolution_method='contextual_candidate' if contextual else 'unresolved',
            resolved_value=None, candidate_internal_complex_id=result.internal_complex_id if contextual else None,
            candidate_complex_name=result.complex_name if contextual else None,
            candidate_address=result.apartment_address if contextual else None,
            candidate_count=int(result.viable_candidate_count) if contextual else 0,
            evidence_type='official_context+kapt_address' if contextual else 'official_document',
            evidence_source=review.source_url, evidence_text=review.raw_segment,
            confidence='medium' if contextual else 'low', manual_review=True,
            reviewer_note=('단지명 후보 및 법정동 확인. 통·반과 2025 적용 주소 근거 미확보'
                           if contextual else '원문 보존. 일부/제외 경계와 주소의 확정 대응 미확보')))
    return pd.DataFrame(records)


def markdown_table(frame):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    rows = ['| ' + ' | '.join(map(str, frame.columns)) + ' |',
            '| ' + ' | '.join('---' for _ in frame.columns) + ' |']
    rows += ['| ' + ' | '.join(cell(x) for x in row) + ' |' for row in frame.itertuples(index=False, name=None)]
    return '\n'.join(rows)


def quality_metrics(matches, middle):
    large = filter_500plus(matches)
    return dict(
        raw_apartment_names=int(matches.raw_apartment_name.nunique()), validation_rows=len(matches),
        candidate_search_success_rate=float(matches.viable_candidate_count.gt(0).mean()),
        match_status={key: int(matches.match_status.eq(key).sum()) for key in ['CONFIRMED', 'REVIEW', 'UNRESOLVED']},
        match_methods={key: int(matches.match_method.eq(key).sum()) for key in
                       ['official_exact', 'normalized_exact', 'fuzzy_supported', 'contextual_candidate',
                        'contextual_supported', 'manual_override', 'unresolved']},
        manual_override_count=int(matches.override_applied.sum()),
        address_support_rate=float(matches.address_score.ge(.8).mean()),
        official_confirmed_rate=float(matches.match_status.eq('CONFIRMED').mean()),
        households_500plus_rows=len(large),
        households_500plus_confirmed_rate=float(large.match_status.eq('CONFIRMED').mean()) if len(large) else None,
        unknown_households=int(matches.households.isna().sum()),
        spatial_outlier_count=int(matches.spatial_outlier.sum()),
        relation_counts={key: int(middle.assignment_certainty.eq(key).sum()) for key in
                         ['exact', 'eligible', 'group_only', 'conditional_not_guaranteed', 'unresolved']})


def write_report(root, matches, view, middle, resolutions, metrics):
    centum = matches[matches.elementary_school_name.eq('센텀초')]
    def table(frame, columns):
        return markdown_table(frame[columns])
    lines = ['# 해운대교육지원청 Phase 5 검증 보고서', '', '## A. Phase 5 개요', '',
             '2025 통학구역의 센텀초 전체, 재송1·2동 단지명, 괄호 없는 두 검수 단지를 비교했다. '
             '현재 K-apt 및 학교 좌표는 2025 당시 주소를 보증하지 않는다. 법정동은 행정동/통·반 확정 근거가 아니다. '
             'CONFIRMED는 공식 주소 확인 또는 근거 있는 confirmed override에만 부여한다. 점수 집계는 하지 않는다.', '',
             '## B. 기존 Phase 4 REVIEW 7건 처리 결과', '',
             table(resolutions, ['review_id', 'elementary_school_name', 'raw_segment', 'resolved',
                                 'resolution_method', 'candidate_complex_name', 'reviewer_note']), '',
             '## C. 통학구역 아파트명 → K-apt 매칭 결과', '',
             '차수 충돌은 제외한다. 후보가 여럿이면 첫 후보를 확정하지 않는다.', '',
             table(matches, ['elementary_school_name', 'raw_apartment_name', 'complex_name', 'internal_complex_id',
                             'name_score', 'address_score', 'viable_candidate_count', 'match_method', 'match_status']), '',
             '## D. 센텀초 상세 validation', '',
             table(centum, ['raw_catchment_text', 'raw_apartment_name', 'complex_name', 'internal_complex_id',
                            'households', 'apartment_address', 'distance_m', 'match_method', 'confidence', 'match_status']), '',
             '## E. 500세대 이상 관련 아파트', '',
             '후보 관계도 포함하는 검증 view이며 확정 학군 목록이 아니다. 작은 단지는 전체 파일에 유지한다.', '',
             table(view, ['elementary_school_name', 'internal_complex_id', 'complex_name', 'households', 'match_status']), '',
             '## F. 초등학교 → 중학교 관계', '',
             table(middle, ['elementary_school_name', 'middle_school_name', 'assignment_type', 'assignment_certainty',
                            'gender_condition', 'guaranteed_assignment', 'middle_school_score', 'score_reference_year']), '',
             '## G. 센텀초 → 센텀중 판정 결과', '',
             f'현재 상태: **{metrics["centum_middle_status"]}**. 2025 시행계획 일반우선배정 표의 센텀초 14학교군과 '
             '학교군 HTML의 센텀중 포함을 연결한 참고 관계다. 개별 지원자격/배정 확정이 아니다. '
             '센텀초 일반우선배정 명시 후보는 장산중·재송중·재송여중이다.', '',
             '근거: [시행계획 게시물](https://home.pen.go.kr/haeundae/na/ntt/selectNttInfo.do?mi=11419&bbsId=3550&nttSn=879684) '
             '첨부 PDF 인쇄 26쪽 기타1 및 '
             '[학교군 안내](https://home.pen.go.kr/haeundae/cm/cntnts/cntntsView.do?cntntsId=253&mi=11431). '
             '학교군 HTML 적용연도 미표시로 temporal_review를 저장한다.', '',
             '## H. unresolved/manual_review 목록', '',
             table(matches[matches.manual_review], ['elementary_school_name', 'raw_apartment_name', 'match_method', 'match_status']), '',
             '기존 검수 7건은 review_resolution CSV에 보존한다. 괄호 없는 두 이름은 법정동 수준 주소만 확인되어 contextual_candidate다.', '',
             '## I. 데이터 품질 지표', '', '```json', json.dumps(metrics, ensure_ascii=False, indent=2), '```', '',
             '비율 분모는 validation_rows(단지명×초등학교)다. 500세대 비율은 세대수 확인 view 행이 분모다. '
             '유사도 0.72 이상 후보를 보존한다. name_score는 확률이 아니며 주소점수 0.8은 법정동 보조근거다.', '',
             '## J. Phase 6 확대 적용 가능 여부', '',
             '검수용 후보 생성은 확대 가능하다. 자동 확정은 공식 주소/통·반·연도 근거 보강 후 진행한다.', '',
             '## K. Phase 6 전에 수정해야 할 규칙', '',
             '- 행정동↔법정동 후보 변환 휴리스틱을 공식 코드·경계 자료로 교체한다.',
             '- Phase 4 중입 PDF의 고정 학교명 표 추출을 변경 fixture로 검증하고 원문/페이지 해시를 연결한다.',
             '- 복합 통, 번지, 동호수 조건을 명시 문법으로 파싱한다.',
             '- 별칭·브랜드·차수 차이는 주소 근거와 분리하고 여러 후보를 자동 축약하지 않는다.',
             '- 2025 적용 자료와 현재 K-apt/학교군 스냅샷의 시간 차이를 보완한다.',
             '- 검증된 학교 ID 매핑을 유지하고 group_only를 eligible/exact로 승격하지 않는다.', '']
    atomic_bytes(root / 'reports/haeundae_phase5_validation.md', '\n'.join(lines).encode('utf-8'))


def build_phase5(office, year, *, root=ROOT):
    if office != 'haeundae' or year != 2025:
        raise ValueError('Phase 5 supports only haeundae, 2025.')
    root = Path(root)
    audit = schema_audit(root)
    print('Phase 5 schema audit: ' + ', '.join(f'{k}={audit[k]["rows"]} rows' for k in INPUTS))
    frames = {key: pd.read_parquet(root / path) for key, path in INPUTS.items()}
    for key in ['catchments', 'assignment', 'groups']:
        if not frames[key].data_year.eq(year).all():
            raise ValueError('Phase 4 data_year mismatch: ' + key)
    overrides = load_overrides(root / 'config/manual_apartment_school_overrides.csv')
    candidates, matches = build_apartment_matches(frames['catchments'], frames['apartments'], frames['schools'], overrides)
    middle = build_middle_validation(frames['groups'], frames['assignment'], frames['scores'],
                                     sorted(matches.elementary_school_name.unique()))
    reviews = pd.read_csv(root / 'reports/haeundae_parse_review_2025.csv')
    resolutions = resolve_phase4_reviews(reviews, matches)
    view = filter_500plus(matches)
    for column in ['eligible_middle_schools', 'middle_assignment_types', 'middle_assignment_certainties']:
        view[column] = pd.Series([[] for _ in range(len(view))], index=view.index, dtype=object)
    for index, row in view.iterrows():
        related = middle[middle.elementary_school_name.eq(row.elementary_school_name)]
        eligible = related[related.assignment_certainty.isin(['exact', 'eligible', 'conditional_not_guaranteed'])]
        view.at[index, 'eligible_middle_schools'] = eligible.middle_school_name.dropna().unique().tolist()
        view.at[index, 'middle_assignment_types'] = related.assignment_type.unique().tolist()
        view.at[index, 'middle_assignment_certainties'] = related.assignment_certainty.unique().tolist()
    metrics = quality_metrics(matches, middle)
    target = middle[middle.elementary_school_name.eq('센텀초') & middle.middle_school_name.eq('센텀중')]
    metrics['centum_middle_status'] = ','.join(target.assignment_certainty.unique()) if len(target) else 'unresolved'
    metrics.update(review_total=len(resolutions), review_resolved=int(resolutions.resolved.sum()))
    for path, frame in {
        'data/interim/haeundae_apartment_elementary_candidates_2025.parquet': candidates,
        'data/processed/haeundae_apartment_elementary_match_2025.parquet': matches,
        'data/interim/haeundae_elementary_middle_validation_2025.parquet': middle,
        'data/processed/haeundae_school_apartments_500plus_2025.parquet': view,
    }.items():
        write_parquet(root / path, frame)
    write_csv(root / 'reports/haeundae_phase4_review_resolution_2025.csv', resolutions)
    write_csv(root / 'reports/haeundae_centum_apartment_validation_2025.csv', matches[matches.elementary_school_name.eq('센텀초')])
    write_json(root / 'reports/haeundae_phase5_quality_2025.json', metrics)
    write_report(root, matches, view, middle, resolutions, metrics)
    return metrics
