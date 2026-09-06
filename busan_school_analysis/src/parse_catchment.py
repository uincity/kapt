import json
from pathlib import Path
import re

import pandas as pd

from .config import ROOT, PARSER_VERSION, write_parquet
from .parsers.html_parser import tables_from_html

CATCHMENT_URL = ('https://home.pen.go.kr/haeundae/cm/cntnts/cntntsView.do'
                 '?cntntsId=311&mi=11750')
COMPLEX_MARKERS = ('일부', '제외', '공동통학구역', '신입생에 한하여', '신입생에 한해', '신청 가능')
RANGE = r'(\d+)\s*[~～∼\-]\s*(\d+)'


def split_segments(text):
    text = re.sub(r'\s+', ' ', str(text or '')).strip(' ,')
    parts, current, depth = [], [], 0
    for char in text:
        if char in '([':
            depth += 1
        elif char in ')]':
            depth = max(0, depth - 1)
        if char in ',;' and depth == 0:
            value = ''.join(current).strip()
            if value:
                parts.append(value)
            current = []
        else:
            current.append(char)
    value = ''.join(current).strip()
    if value:
        parts.append(value)
    # Some official cells concatenate clauses after a closing parenthesis without a comma.
    return [piece.strip() for part in parts for piece in
            re.split(r'(?<=\))\s+(?=\d+\s*(?:[~～∼\-]\s*\d+\s*)?통)', part) if piece.strip()]


def parse_tong(text):
    match = re.search(RANGE + r'\s*통', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r'(\d+)\s*통', text)
    return (int(match.group(1)), int(match.group(1))) if match else (None, None)


def parse_ban(text):
    plain = re.search(RANGE + r'\s*반', text)
    if plain:
        return int(plain.group(1)), int(plain.group(2))
    parenthetical = re.search(r'\(([^()]*)\)', text)
    if parenthetical and re.fullmatch(r'[\d\s,·~～∼\-]+반?', parenthetical.group(1)):
        nums = [int(n) for n in re.findall(r'\d+', parenthetical.group(1))]
        return (min(nums), max(nums)) if nums else (None, None)
    one = re.search(r'(\d+)\s*반', text)
    if one:
        return int(one.group(1)), int(one.group(1))
    return None, None


def _apartment_names(text):
    match = re.search(r'\(([^()]*)\)', text)
    if not match:
        return []
    content = match.group(1).strip()
    if re.fullmatch(r'[\d\s,·~～∼\-]+반?', content) or re.search(r'번지|도로|제외|일부', content):
        return []
    names = [x.strip() for x in re.split(r'[,·]', content) if x.strip()]
    if len(names) >= 2 and re.match(r'^\d+차$', names[1]):
        first = names[0]
        prefix_match = re.match(r'^(.*?)(\d+)(?:차)?$', first)
        if prefix_match:
            prefix, number = prefix_match.groups()
            names[0] = f'{prefix}{number}차'
            names = [names[0]] + [f'{prefix}{x}' if re.match(r'^\d+차$', x) else x
                                  for x in names[1:]]
    return names


def parse_segment(text):
    raw = str(text).strip()
    tong_start, tong_end = parse_tong(raw)
    ban_start, ban_end = parse_ban(raw)
    address = raw if re.search(r'\d+\s*번지|(?:로|길)\s*\d+|[가-힣0-9]+(?:읍|면|리)(?:\b|\()', raw) else None
    apartments = [] if address else _apartment_names(raw)
    complex_condition = any(marker in raw for marker in COMPLEX_MARKERS)
    recognized = tong_start is not None or ban_start is not None or bool(apartments) or address is not None
    if not recognized:
        status = 'REVIEW'
    elif complex_condition or (raw.count('(') != raw.count(')')):
        status = 'PARTIAL'
    else:
        status = 'PARSED'
    if '공동통학구역' in raw:
        kind = 'shared'
    elif '제외' in raw:
        kind = 'exclusion'
    elif address:
        kind = 'address'
    elif apartments:
        kind = 'tong_apartment'
    elif ban_start is not None:
        kind = 'tong_ban'
    elif tong_start is not None:
        kind = 'tong'
    else:
        kind = 'unparsed'
    return dict(tong_start=tong_start, tong_end=tong_end, ban_start=ban_start, ban_end=ban_end,
                address_pattern=address, apartment_name_pattern=apartments or None,
                catchment_type=kind, raw_segment=raw, parse_status=status,
                confidence={'PARSED': 1.0, 'PARTIAL': 0.6, 'REVIEW': 0.2}[status],
                manual_review=status != 'PARSED')


def raw_catchment_rows(html):
    matches = []
    for table in tables_from_html(html):
        for idx, row in enumerate(table):
            if len(row) >= 5 and row[:5] == ['순', '학교별', '동별', '통학구역', '비 고']:
                for raw_index, values in enumerate(table[idx + 1:], 1):
                    values = (values + [''] * 5)[:5]
                    if values[1] and values[2] and values[3]:
                        matches.append(dict(raw_row_index=raw_index,
                                            elementary_school_name=values[1], dong=values[2],
                                            catchment_text=values[3], remarks=values[4] or None))
    if not matches:
        raise ValueError('Official catchment table was not found or its schema changed.')
    return matches


def parse_catchment_html(html, *, year=2025, source_url=CATCHMENT_URL):
    records = []
    for raw in raw_catchment_rows(html):
        for segment_index, segment in enumerate(split_segments(raw['catchment_text']), 1):
            record = dict(data_year=year, education_office='haeundae', **raw,
                          segment_index=segment_index, source_url=source_url,
                          parser_version=PARSER_VERSION)
            record.update(parse_segment(segment))
            records.append(record)
    return pd.DataFrame(records)


def parse_catchments(office, year, *, root=ROOT):
    if office != 'haeundae' or year != 2025:
        raise ValueError('Phase 4 PoC supports only --office haeundae --year 2025.')
    path = Path(root) / f'data/raw/education_office/{office}/{year}/elementary_catchment.html'
    if not path.exists():
        raise FileNotFoundError(f'Collect the official catchment first: {path}')
    frame = parse_catchment_html(path.read_text(encoding='utf-8'), year=year)
    output = Path(root) / f'data/interim/{office}_elementary_catchment_{year}.parquet'
    write_parquet(output, frame)
    return {'rows': len(frame), 'schools': int(frame.elementary_school_name.nunique()),
            'output': str(output)}
