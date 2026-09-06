"""Synthetic fixtures validate logic; they are not real Schoolinfo observations."""
from datetime import datetime
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest
import requests

from src.clean_school import clean_schools
from src.collect_schoolinfo import collect_schools, download
from src.config import ROOT
from src.geocode_school import geocode_schools


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / 'config').mkdir()
    for name in ['settings.yaml', 'schoolinfo_codes.csv']:
        shutil.copyfile(ROOT / 'config' / name, tmp_path / 'config' / name)
    monkeypatch.setenv('SCHOOLINFO_API_KEY', 'test-secret-only')
    monkeypatch.setenv('KAKAO_API_KEY', 'test-kakao-secret')
    monkeypatch.setattr('src.collect_schoolinfo.time.sleep', lambda _: None)
    return tmp_path


class Response:
    status_code = 200

    def __init__(self, payload):
        self.content = json.dumps(payload).encode()

    def json(self):
        return json.loads(self.content)


class Schools:
    def __init__(self, fail=None):
        self.calls = 0
        self.fail = fail

    def get(self, endpoint, **kwargs):
        self.calls += 1
        if self.fail == self.calls:
            return Response({'resultCode': 'fail', 'resultMsg': 'test-secret-only'})
        p = kwargs['params']
        return Response({'resultCode': 'success', 'list': [{
            'SCHUL_CODE': p['sggCode'] + p['schulKndCode'], 'SCHUL_NM': '검증학교',
            'SCHUL_KND_SC_CODE': p['schulKndCode'], 'ADRCD_CD': p['sggCode'] + '10000',
            'SCHUL_RDNMA': '부산광역시 예시로 10', 'ADRES_BRKDN': '부산광역시 예시동',
            'LTTUD': '35.18', 'LGTUD': '129.12', 'COEDU_SC_CODE': 'fixture',
            'FOND_SC_CODE': 'fixture', 'HS_KND_SC_NM': 'fixture'}]})


def test_complete_collection_and_cache_reuse_without_key(project, monkeypatch):
    year = datetime.now().year
    session = Schools()
    result = collect_schools(year, root=project, session=session)
    assert result['school_count'] == 32 and session.calls == 32
    frame = pd.read_parquet(project / 'data/processed/schools.parquet')
    assert frame.school_id.nunique() == 32
    assert {'data_year', 'source_name', 'source_document', 'collected_at', 'parser_version',
            'manual_review', 'confidence'}.issubset(frame.columns)
    monkeypatch.delenv('SCHOOLINFO_API_KEY')
    collect_schools(year, root=project, session=session)
    assert session.calls == 32
    for path in (project / 'data/raw').rglob('*.json'):
        assert b'test-secret-only' not in path.read_bytes()


def test_partial_failure_preserves_published_output(project):
    year = datetime.now().year
    collect_schools(year, root=project, session=Schools())
    output = project / 'data/processed/schools.parquet'
    before = output.read_bytes()
    with pytest.raises(ValueError, match='incomplete'):
        collect_schools(year, root=project, session=Schools(fail=2), force=True)
    assert output.read_bytes() == before
    assert list((project / f'data/raw/schoolinfo/{year}/history').glob('*.json'))
    for path in project.rglob('*.json'):
        assert b'test-secret-only' not in path.read_bytes()


def test_historical_collection_never_downloads_current_data(project):
    session = Schools()
    with pytest.raises(ValueError):
        collect_schools(datetime.now().year - 1, root=project, session=session)
    assert session.calls == 0
    assert not (project / 'data/processed/schools.parquet').exists()


def test_tampered_cache_rejected(project):
    year = datetime.now().year
    collect_schools(year, root=project, session=Schools())
    raw = next((project / f'data/raw/schoolinfo/{year}').glob('*_02.json'))
    raw.write_bytes(raw.read_bytes() + b' ')
    with pytest.raises(ValueError, match='incomplete'):
        collect_schools(year, root=project, session=Schools())


@pytest.mark.parametrize('change', [dict(SCHUL_CODE=None), dict(SCHUL_KND_SC_CODE='03'),
                                    dict(ADRCD_CD='1111000000')])
def test_live_schema_and_scope_must_match(change):
    row = dict(SCHUL_CODE='fixture', SCHUL_NM='검증초', SCHUL_KND_SC_CODE='02')
    row.update(change)
    with pytest.raises(ValueError):
        clean_schools({'resultCode': 'success', 'list': [row]}, year=2026,
                      region=dict(sido='부산광역시', sigungu='해운대구', sgg_code='26350'),
                      level='02', document='synthetic_fixture', collected_at='2026-09-05')


def test_missing_fields_are_not_invented():
    row = dict(SCHUL_CODE='fixture', SCHUL_NM='검증초', SCHUL_KND_SC_CODE='02',
               LTTUD='129', LGTUD='35')
    frame = clean_schools({'resultCode': 'success', 'list': [row]}, year=2026,
                         region=dict(sido='부산광역시', sigungu='해운대구', sgg_code='26350'),
                         level='02', document='synthetic_fixture', collected_at='2026-09-05')
    assert frame.latitude.isna().all() and frame.gender_type.isna().all()
    assert frame.manual_review.all()


def test_http_exception_does_not_leak_key():
    class Failure:
        def get(self, *args, **kwargs):
            raise requests.RequestException('https://example?apiKey=test-secret-only')
    with pytest.raises(ValueError) as error:
        download(Failure(), {}, dict(endpoint='https://example', retries=0, timeout=1))
    assert 'test-secret-only' not in str(error.value)


def test_geocode_caches_shared_address_and_preserves_provenance(project):
    collect_schools(datetime.now().year, root=project, session=Schools())
    path = project / 'data/processed/schools.parquet'
    frame = pd.read_parquet(path)
    frame['latitude'] = float('nan')
    frame['longitude'] = float('nan')
    frame.to_parquet(path, index=False)
    class Kakao:
        calls = 0
        def get(self, *args, **kwargs):
            self.calls += 1
            return Response({'documents': [{'y': '35.18', 'x': '129.12'}]})
    kakao = Kakao()
    result = geocode_schools(root=project, session=kakao)
    assert kakao.calls == 1 and result['failure_count'] == 0
    result = geocode_schools(root=project, session=kakao)
    assert result['requests_made'] == 0
    result_frame = pd.read_parquet(path)
    assert result_frame.source_name.eq('학교알리미 Open API').all()
    assert result_frame.coordinate_source.eq('kakao').all()


def test_geocode_failure_is_cached_and_reported(project):
    collect_schools(datetime.now().year, root=project, session=Schools())
    path = project / 'data/processed/schools.parquet'
    frame = pd.read_parquet(path)
    frame['latitude'] = float('nan')
    frame['longitude'] = float('nan')
    frame.to_parquet(path, index=False)
    class Missing:
        calls = 0
        def get(self, *args, **kwargs):
            self.calls += 1
            return Response({'documents': []})
    missing = Missing()
    geocode_schools(root=project, session=missing)
    before = missing.calls
    geocode_schools(root=project, session=missing)
    assert before == missing.calls
    failures = pd.read_csv(project / 'data/interim/school_geocode_failures.csv')
    assert len(failures) == 32
