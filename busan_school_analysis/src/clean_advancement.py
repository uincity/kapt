"""Parse the actual public 13-다 HTML table, not an assumed Open API schema."""
from html.parser import HTMLParser
import re

import pandas as pd

from .config import provenance

VERSION = 'advancement-html-1.0'
TITLES = {
    'graduates': '졸업자',
    'general_hs_count': '진학자 일반고',
    'specialized_hs_count': '진학자 특성화고',
    'science_hs_count': '진학자 특수목적고 과학고',
    'foreign_international_hs_count': '진학자 특수목적고 외고국제고',
    'arts_sports_hs_count': '진학자 특수목적고 예고체고',
    'meister_hs_count': '진학자 특수목적고 마이스터고',
    'special_purpose_total': '진학자 특수목적고 소계',
    'autonomous_private_hs_count': '진학자 자율고 자율형사립고',
    'autonomous_public_hs_count': '진학자 자율고 자율형공립고',
    'autonomous_total': '진학자 자율고 소계',
    'other_advancement_count': '진학자 기타',
    'advancement_total': '진학자 진학자계',
    'employment_count': '취업자',
    'unaccredited_alternative_count': '대안교육기관진학(학력미인정)',
    'unknown_destination_count': '무직 및 미상',
}


class DisclosureHTML(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.inputs, self.rows, self.options = {}, [], []
        self.row = self.cell = self.option = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name'):
            self.inputs.setdefault(attrs['name'], set()).add(attrs.get('value', ''))
        if tag == 'tr':
            self.row = []
        if tag in {'td', 'th'} and self.row is not None:
            self.cell = dict(tag=tag, title=attrs.get('title'), text='')
        if tag == 'option':
            self.option = dict(value=attrs.get('value'), selected='selected' in attrs, text='')

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'] += data
        if self.option is not None:
            self.option['text'] += data

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.cell is not None:
            self.cell['text'] = self.cell['text'].strip()
            self.row.append(self.cell)
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        if tag == 'option' and self.option is not None:
            self.options.append(self.option)
            self.option = None


def decode_html(content):
    # Official pages currently declare UTF-8 but return CP949 bytes.
    try:
        return content.decode('utf-8')
    except UnicodeDecodeError:
        return content.decode('cp949')


def count(text):
    text = text.strip().replace(',', '')
    if not re.fullmatch(r'\d+', text):
        return None
    return int(text)


def parse_advancement(content, *, school, year, document, collected_at):
    text = decode_html(content)
    page = DisclosureHTML(text)
    record = provenance(year, '학교알리미 공시 13-다', document, collected_at)
    record.update(year=year, requested_year=year, middle_school_id=school['school_id'],
                  middle_school_name=school['school_name'], sigungu=school['sigungu'],
                  parser_version=VERSION, source_url='https://www.schoolinfo.go.kr/ei/pp/Pneipp_b06_s0p.do',
                  school_public_id=school['school_public_id'], availability='unavailable',
                  observed_year=None, eligible_for_scoring=False, review_reason='')
    for name in list(TITLES) + ['foreign_language_hs_count', 'international_hs_count',
                               'arts_hs_count', 'sports_hs_count', 'other_special_hs_count']:
        record[name] = None
    years = page.inputs.get('JG_YEAR', set())
    if len(years) == 1 and next(iter(years)).isdigit():
        record['observed_year'] = int(next(iter(years)))
    selected = {o['value'][:4] for o in page.options if o['selected'] and o.get('value')}
    if '입력된 데이터가 없습니다.' in text and '졸업생의 진로 현황' in text:
        record.update(availability='not_published', manual_review=True, confidence=0.0,
                      review_reason='official_page_reports_no_data')
        return record
    identity_ok = page.inputs.get('SHL_IDF_CD') == {school['school_public_id']}
    if not identity_ok:
        record.update(availability='identity_or_page_error', manual_review=True, confidence=0.0,
                      review_reason='missing_or_mismatched_public_school_id')
        return record
    if years != {str(year)} or selected != {str(year)}:
        record.update(availability='year_mismatch', manual_review=True, confidence=0.0,
                      review_reason='requested_year_not_published_or_response_year_differs')
        return record
    totals = [r for r in page.rows if r and r[0]['text'] == '합계'
              and any(c['title'] == '졸업자' for c in r)]
    if len(totals) != 1:
        record.update(availability='table_unavailable', manual_review=True, confidence=0.0,
                      review_reason='missing_or_ambiguous_total_row')
        return record
    cells = {c['title']: c['text'] for c in totals[0] if c['title']}
    if len(cells) != len([c for c in totals[0] if c['title']]):
        raise ValueError('Duplicate total-row labels; source schema changed.')
    for name, title in TITLES.items():
        record[name] = count(cells.get(title, ''))
    record['source_values'] = str(cells)
    record['category_resolution'] = 'foreign_international_combined;arts_sports_combined;other_special_not_separate'
    if any(record[c] is None for c in TITLES):
        record.update(availability='suppressed_or_incomplete', manual_review=True, confidence=0.0,
                      review_reason='missing_noninteger_or_suppressed_counts')
        return record
    r = record
    sums_ok = (
        r['science_hs_count'] + r['foreign_international_hs_count'] + r['arts_sports_hs_count'] + r['meister_hs_count'] == r['special_purpose_total']
        and r['autonomous_private_hs_count'] + r['autonomous_public_hs_count'] == r['autonomous_total']
        and r['general_hs_count'] + r['specialized_hs_count'] + r['special_purpose_total'] + r['autonomous_total'] + r['other_advancement_count'] == r['advancement_total']
        and r['advancement_total'] + r['employment_count'] + r['unaccredited_alternative_count'] + r['unknown_destination_count'] == r['graduates'])
    sex_rows = [row for row in page.rows if row and row[0]['text'] in {'남', '여'}
                and any(c['title'] == '졸업자' for c in row)]
    if len(sex_rows) == 2:
        for field, title in TITLES.items():
            values = [count(next((c['text'] for c in row if c['title'] == title), '')) for row in sex_rows]
            sums_ok &= all(v is not None for v in values) and sum(v or 0 for v in values) == record[field]
    record.update(availability='available' if sums_ok else 'count_mismatch',
                  eligible_for_scoring=sums_ok and record['graduates'] > 0,
                  manual_review=not sums_ok or record['graduates'] == 0,
                  confidence=1.0 if sums_ok else 0.0,
                  review_reason='' if sums_ok and record['graduates'] else 'count_mismatch_or_zero_graduates')
    return record


def add_rates(frame):
    result = frame.copy()
    required = ['science_hs_count', 'foreign_international_hs_count', 'autonomous_private_hs_count']
    for c in ['graduates', *TITLES]:
        result[c] = pd.to_numeric(result[c], errors='coerce')
    result['academic_selective_count'] = result[required].sum(axis=1, min_count=3)
    denominator = result.graduates.where(result.eligible_for_scoring & result.graduates.gt(0))
    for rate, numerator in {
        'science_rate': 'science_hs_count', 'foreign_international_rate': 'foreign_international_hs_count',
        'autonomous_private_rate': 'autonomous_private_hs_count',
        'academic_selective_rate': 'academic_selective_count',
        'arts_sports_rate': 'arts_sports_hs_count', 'meister_rate': 'meister_hs_count',
    }.items():
        result[rate] = result[numerator] / denominator
    return result
