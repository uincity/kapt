from pathlib import Path
import re

import pandas as pd

from .config import ROOT, PARSER_VERSION, atomic_bytes, write_csv, write_parquet
from .collect_middle_assignment import GROUP_URL
from .parsers.html_parser import tables_from_html
from .parsers.pdf_parser import parse_pdf


def _names(text, suffix):
    return list(dict.fromkeys(re.findall(rf'[가-힣]+{suffix}', str(text))))


def parse_school_groups_html(html, *, year=2025, source_url=GROUP_URL):
    table = next((t for t in tables_from_html(html)
                  if t and any('학교군' in cell for cell in t[0]) and
                  any(any(re.fullmatch(r'1[3-7]학교군', cell) for cell in row) for row in t)), None)
    if table is None:
        raise ValueError('Official middle-school group table was not found or changed.')
    records = []
    for values in table:
        values = (values + [''] * 6)[:6]
        if not re.fullmatch(r'1[3-7]학교군', values[0]):
            continue
        group, subregion, coed, male, female, residence = values
        residence_dongs = [x.strip() for x in re.split(r'[,，]', residence) if x.strip()]
        raw_text = ' | '.join(values)
        for gender, cell in [('coed', coed), ('male', male), ('female', female)]:
            for school in _names(cell, '중'):
                for dong in residence_dongs or [None]:
                    records.append(dict(data_year=year, education_office='haeundae', school_group=group,
                                        subregion=subregion, middle_school_name=school,
                                        school_gender=gender, residence_dong=dong,
                                        source_url=source_url, raw_text=raw_text,
                                        assignment_certainty='group_only', parser_version=PARSER_VERSION))
    frame = pd.DataFrame(records)
    if frame.empty or set(frame.school_group) != {f'{n}학교군' for n in range(13, 18)}:
        raise ValueError('Expected official school groups 13–17 were not fully parsed.')
    return frame


def _relation_rows(text, source_document):
    """Read only explicit conditional tables on PDF pages 26–27.

    These rows mean eligibility for a preference/priority procedure; none means a
    guaranteed assignment. The patterns deliberately fail closed if the table changes.
    """
    compact = text.replace('\r', '')
    priority_start = compact.rfind('14학교군 중 일반우선배정 대상 학교')
    priority_end = compact.find('【기타 2】', priority_start)
    preference_start = compact.rfind('14ㆍ17학교군 중 희망지원 대상 학교')
    preference_end = compact.find('【서식 2】', preference_start)
    priority = compact[priority_start:priority_end] if priority_start >= 0 and priority_end > priority_start else ''
    preference = (compact[preference_start:preference_end]
                  if preference_start >= 0 and preference_end > preference_start else '')
    specifications = []
    if priority:
        specifications.extend([
            ('general_priority', '26', _names(priority[priority.find('센텀초'):priority.find('학교군 내 과밀')], '초'),
             ['장산중', '재송중', '재송여중'], '정원 범위 내 일반우선배정; 배정되지 않을 수 있음'),
            ('general_priority', '26', _names(priority[priority.find('반여초'):priority.find('※ 국ㆍ사립')], '초'),
             ['반여중'], '정원 범위 내 일반우선배정; 배정되지 않을 수 있음')])
    if preference:
        specifications.extend([
            ('preference', '27', _names(preference[preference.find('반석초'):preference.find('센텀중')], '초'),
             ['장산중', '인지중'], '1·2희망 후 초과 시 추첨'),
            ('preference', '27', ['송수초'] if '송수초' in preference else [],
             ['센텀중', '장산중'], '1·2희망 후 초과 시 추첨'),
            ('preference', '27', ['반여초'] if '반여초' in preference else [],
             ['반여중', '인지중'], '1·2희망 후 초과 시 추첨'),
            ('preference', '27', ['삼어초'] if '삼어초' in preference else [],
             ['반안중', '장산중'], '1·2희망 후 초과 시 추첨')])
    rows = []
    for assignment_type, page, elementaries, middles, condition in specifications:
        for elementary in elementaries:
            for middle in middles:
                rows.append(dict(data_year=2025, education_office='haeundae',
                                 elementary_school_name=elementary, dong=None, tong_start=None,
                                 tong_end=None, ban_start=None, ban_end=None, school_group='14학교군',
                                 subregion='재송·반여', middle_school_name=middle,
                                 gender_condition='female' if middle.endswith('여중') else
                                                  'male' if middle == '재송중' else 'all',
                                 assignment_type=assignment_type,
                                 assignment_certainty='conditional_not_guaranteed',
                                 source_document=source_document, source_page_or_section=f'PDF p.{page}',
                                 source_text=condition, parse_status='PARSED', manual_review=False))
    return pd.DataFrame(rows)


def parse_middle_assignment(office, year, *, root=ROOT):
    if office != 'haeundae' or year != 2025:
        raise ValueError('Phase 4 PoC supports only --office haeundae --year 2025.')
    base = Path(root) / f'data/raw/education_office/{office}/{year}/middle_assignment'
    group_path = base / 'middle_school_groups.html'
    if not group_path.exists():
        raise FileNotFoundError('Collect middle-assignment sources before parsing.')
    groups = parse_school_groups_html(group_path.read_text(encoding='utf-8'), year=year)
    group_output = Path(root) / f'data/interim/{office}_middle_school_groups_{year}.parquet'
    write_parquet(group_output, groups)

    metadata_path = base / 'attachments_metadata.csv'
    metadata = pd.read_csv(metadata_path) if metadata_path.exists() else pd.DataFrame()
    plan_rows = (metadata[(metadata.attachment_type.str.lower() == 'pdf') &
                          metadata.post_title.str.contains('시행계획', na=False)]
                 if not metadata.empty else pd.DataFrame())
    if not plan_rows.empty:
        plan = base / plan_rows.iloc[0].local_file
    else:
        pdfs = list(base.glob('*.pdf'))
        plan = next((p for p in pdfs if '계획' in p.name or 'plan' in p.name.lower()), None)
    if plan is None or not plan.exists():
        raise FileNotFoundError('The official 2025 assignment-plan PDF is missing.')
    parsed = parse_pdf(plan)
    if '2025학년도 중학교 입학' not in parsed.text:
        raise ValueError('The preserved PDF text is unavailable or has the wrong data year.')
    companion = plan.with_suffix('.txt')
    if not companion.exists():
        atomic_bytes(companion, parsed.text.encode('utf-8'))
    relations = _relation_rows(parsed.text, str(plan.relative_to(root)))
    relation_output = Path(root) / f'data/interim/{office}_middle_assignment_{year}.parquet'
    if not relations.empty:
        write_parquet(relation_output, relations)

    manual = Path(root) / f'data/manual/{office}_middle_assignment_{year}_manual.csv'
    columns = list(relations.columns) if not relations.empty else [
        'data_year', 'education_office', 'elementary_school_name', 'dong', 'tong_start', 'tong_end',
        'ban_start', 'ban_end', 'school_group', 'subregion', 'middle_school_name', 'gender_condition',
        'assignment_type', 'assignment_certainty', 'source_document', 'source_page_or_section',
        'source_text', 'parse_status', 'manual_review']
    if not manual.exists():
        write_csv(manual, pd.DataFrame(columns=columns))
    return {'school_groups': int(groups.school_group.nunique()), 'group_rows': len(groups),
            'conditional_relation_rows': len(relations),
            'relation_output': str(relation_output) if not relations.empty else None,
            'extraction_method': parsed.extraction_method}
