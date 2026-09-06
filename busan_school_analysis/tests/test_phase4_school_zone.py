from pathlib import Path

import pandas as pd
import pytest

from src.parse_catchment import parse_ban, parse_catchment_html, parse_segment
from src.parse_middle_assignment import parse_school_groups_html
from src.validate_school_zone import ensure_same_year

FIXTURES = Path(__file__).parent / 'fixtures'


def test_parse_single_tong():
    row = parse_segment('26통')
    assert (row['tong_start'], row['tong_end'], row['parse_status']) == (26, 26, 'PARSED')


def test_parse_tong_range():
    row = parse_segment('1～5통')
    assert (row['tong_start'], row['tong_end']) == (1, 5)


def test_parse_ban_range():
    assert parse_ban('5통 1~4반') == (1, 4)
    assert parse_ban('5통(1,2,3반)') == (1, 3)


def test_parse_apartment_parentheses():
    row = parse_segment('26통(센텀스타)')
    assert row['apartment_name_pattern'] == ['센텀스타']


def test_parse_multiple_apartments():
    row = parse_segment('19~22통(센텀파크1, 2차)')
    assert row['apartment_name_pattern'] == ['센텀파크1차', '센텀파크2차']


def test_keep_raw_text():
    raw = '5통 1~4반(복잡한 원문)'
    assert parse_segment(raw)['raw_segment'] == raw


def test_partial_parse_flag():
    row = parse_segment('1~5통 일부')
    assert row['parse_status'] == 'PARTIAL' and row['manual_review']


def test_manual_review_flag():
    row = parse_segment('신입생에 한하여 신청 가능')
    assert row['parse_status'] == 'REVIEW' and row['manual_review']


def test_school_group_many_to_many():
    html = (FIXTURES / 'haeundae_middle_groups.html').read_text(encoding='utf-8')
    frame = parse_school_groups_html(html)
    group14 = frame[frame.school_group.eq('14학교군')]
    assert {'센텀중', '재송중', '재송여중'}.issubset(set(group14.middle_school_name))
    assert group14.groupby('middle_school_name').residence_dong.nunique().min() >= 2
    assert group14.assignment_certainty.eq('group_only').all()


def test_data_year_mismatch():
    with pytest.raises(ValueError, match='mismatch'):
        ensure_same_year(pd.DataFrame({'data_year': [2025]}),
                         pd.DataFrame({'data_year': [2026]}), expected_year=2025)


def test_centum_elementary_fixture():
    html = (FIXTURES / 'haeundae_catchment_2025.html').read_text(encoding='utf-8')
    frame = parse_catchment_html(html)
    centum = frame[(frame.elementary_school_name == '센텀초') & (frame.dong == '재송1동')]
    assert len(centum) == 2
    assert ((centum.tong_start == 19) & (centum.tong_end == 22)).any()
    assert ((centum.tong_start == 26) & (centum.tong_end == 26)).any()
    names = {name for values in centum.apartment_name_pattern.dropna() for name in values}
    assert {'센텀파크1차', '센텀파크2차', '센텀스타'}.issubset(names)
    assert centum.catchment_text.str.contains('19～22통(센텀파크1, 2차)', regex=False).all()
