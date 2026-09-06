from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urljoin

import pandas as pd
import requests

from .config import ROOT, PARSER_VERSION, atomic_bytes, now, write_csv, write_json
from .collect_catchment import _archive

BASE = 'https://home.pen.go.kr'
BOARD_URL = BASE + '/haeundae/na/ntt/selectNttList.do?bbsId=3550&mi=11419'
POST_URL = BASE + '/haeundae/na/ntt/selectNttInfo.do?mi=11419&bbsId=3550&nttSn={}'
FILE_API = BASE + '/haeundae/na/ntt/fileDownChk.do'
GROUP_URL = BASE + '/haeundae/cm/cntnts/cntntsView.do?cntntsId=253&mi=11431'
TARGETS = ('2025학년도 중학교 입학 배정 시행계획', '2025학년도 중학교 입학 배정 시행요강')


class _BoardParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_row = False
        self.row_text = []
        self.ids = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr':
            self.in_row, self.row_text, self.ids = True, [], []
        if self.in_row and attrs.get('data-id'):
            self.ids.append(attrs['data-id'])

    def handle_data(self, data):
        if self.in_row:
            self.row_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'tr' and self.in_row:
            self.rows.append((' '.join(''.join(self.row_text).split()), list(dict.fromkeys(self.ids))))
            self.in_row = False


def _board_records(html):
    parser = _BoardParser()
    parser.feed(html)
    found = []
    for text, ids in parser.rows:
        for title in TARGETS:
            if title in text and ids:
                date = re.search(r'20\d{2}[.\-/]\d{2}[.\-/]\d{2}', text)
                found.append(dict(post_title=title, post_date=date.group(0) if date else None,
                                  ntt_sn=ids[0]))
    return found


def _safe_name(name, fallback):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name or '')).strip(' .')
    return value or fallback


def _validate_attachment(content, extension):
    ext = extension.lower().lstrip('.')
    if ext == 'pdf' and not content.startswith(b'%PDF'):
        raise ValueError('Attachment advertised as PDF has invalid magic bytes.')
    if ext == 'hwp' and not content.startswith(bytes.fromhex('D0CF11E0A1B11AE1')):
        raise ValueError('Attachment advertised as legacy HWP has invalid magic bytes.')
    if ext in ('hwpx', 'xlsx', 'docx') and not content.startswith(b'PK'):
        raise ValueError('ZIP-based attachment has invalid magic bytes.')


def collect_middle_assignment(office, year, *, force=False, root=ROOT, session=requests):
    if office != 'haeundae' or year != 2025:
        raise ValueError('Phase 4 PoC supports only --office haeundae --year 2025.')
    base = Path(root) / f'data/raw/education_office/{office}/{year}/middle_assignment'
    metadata_path = base / 'attachments_metadata.csv'
    group_path = base / 'middle_school_groups.html'
    group_meta_path = base / 'middle_school_groups_metadata.json'
    if metadata_path.exists() and group_path.exists() and group_meta_path.exists() and not force:
        frame = pd.read_csv(metadata_path)
        for row in frame.itertuples():
            local = base / row.local_file
            if not local.exists() or hashlib.sha256(local.read_bytes()).hexdigest() != row.sha256:
                raise ValueError('Cached middle-assignment attachment hash mismatch.')
        return {'status': 'cached', 'posts': int(frame.post_url.nunique()), 'attachments': len(frame)}

    board_pages, records = [], []
    for page in range(1, 4):
        response = session.get(BOARD_URL, params={'currPage': page}, timeout=30)
        response.raise_for_status()
        content = response.content
        html = content.decode(response.encoding or 'utf-8', errors='replace')
        board_pages.append((page, content))
        for item in _board_records(html):
            if item['ntt_sn'] not in {x['ntt_sn'] for x in records}:
                records.append(item)
    missing = [title for title in TARGETS if not any(title in item['post_title'] for item in records)]
    if missing:
        raise ValueError('Required official 2025 posts were not found on scanned board pages.')

    group_response = session.get(GROUP_URL, timeout=30)
    group_response.raise_for_status()
    group_content = group_response.content
    if '14학교군' not in group_content.decode(group_response.encoding or 'utf-8', errors='replace'):
        raise ValueError('Official middle-school group table was not found.')

    downloads, metadata, collected = [], [], now()
    for item in records:
        post_url = POST_URL.format(item['ntt_sn'])
        post_response = session.get(post_url, timeout=30)
        post_response.raise_for_status()
        api_response = session.get(FILE_API, params={'bbsId': '3550', 'mi': '11419',
                                                     'nttSn': item['ntt_sn']}, timeout=30)
        api_response.raise_for_status()
        payload = api_response.json()
        attachments = payload.get('nttFileList') or []
        if not attachments:
            raise ValueError(f"Official post {item['ntt_sn']} has no downloadable attachments.")
        downloads.append((f'post_{item["ntt_sn"]}.html', post_response.content))
        for index, attachment in enumerate(attachments, 1):
            remote_path = attachment.get('flpth') or attachment.get('filePath')
            if not remote_path:
                raise ValueError('Attachment API schema changed: path is missing.')
            attachment_url = urljoin(BASE, remote_path)
            file_response = session.get(attachment_url, timeout=60)
            file_response.raise_for_status()
            body = file_response.content
            extension = (attachment.get('extsn') or Path(remote_path).suffix).lstrip('.').lower()
            _validate_attachment(body, extension)
            original_name = attachment.get('fileNm') or Path(remote_path).name
            filename = _safe_name(original_name, f'{item["ntt_sn"]}_{index}.{extension}')
            if not Path(filename).suffix and extension:
                filename += '.' + extension
            downloads.append((filename, body))
            metadata.append(dict(post_title=item['post_title'], post_date=item['post_date'],
                                 data_year=year, education_office=office, post_url=post_url,
                                 attachment_name=original_name, attachment_url=attachment_url,
                                 attachment_type=extension, downloaded_at=collected,
                                 sha256=hashlib.sha256(body).hexdigest(), local_file=filename,
                                 parser_version=PARSER_VERSION))
    if force:
        _archive([metadata_path, group_path, group_meta_path] +
                 [base / name for name, _ in downloads], base / 'history')
    for page, content in board_pages:
        atomic_bytes(base / f'board_page_{page}.html', content)
    for name, body in downloads:
        atomic_bytes(base / name, body)
    atomic_bytes(group_path, group_content)
    write_json(group_meta_path, dict(data_year=year, education_office=office, source_url=GROUP_URL,
                                     collected_at=collected, http_status=group_response.status_code,
                                     content_hash=hashlib.sha256(group_content).hexdigest(),
                                     parser_version=PARSER_VERSION,
                                     year_basis='2025 PoC reference; page itself has no explicit effective year'))
    write_csv(metadata_path, pd.DataFrame(metadata))
    return {'status': 'downloaded', 'posts': len(records), 'attachments': len(metadata)}
