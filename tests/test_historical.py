import json
from pathlib import Path
import sqlite3

import pytest

from rov_mlbb.common import DataError
from rov_mlbb.historical import historical_timestamp, read_export
from rov_mlbb.pipeline import run_pipeline
from conftest import mutate_packet


def unknown_time(packet):
    packet.update(schema_version=2, collected_at=None, provenance={
        'collection_time_status': 'unknown', 'collected_no_later_than': '2025-04-03T00:00:00Z',
        'exported_at': '2026-11-02T00:00:00Z', 'snapshot_id': 'a' * 64,
        'timing_basis': 'Historical document existed by the bound; original collection time not recorded',
        'source_exports': [{'manifest': 'test-export.json'}]})
    for coverage in packet['coverage'].values():
        coverage['status'] = 'partial'


def test_unknown_collection_time_is_not_replaced_with_export_date(scenario):
    mutate_packet(scenario, 'youtube', unknown_time)
    result = run_pipeline(scenario)
    rows = json.loads((Path(result['artifact_dir']) / 'clean/youtube.json').read_text())
    assert all(r['collected_at'] is None for r in rows)
    assert all(':unknown_snapshot:' in r['record_key'] for r in rows)
    mutate_packet(scenario, 'youtube', lambda p: p['provenance'].update(exported_at='2026-11-03T00:00:00Z'))
    run_pipeline(scenario)
    with sqlite3.connect(result['database']) as conn:
        assert conn.execute("SELECT COUNT(*) FROM observations WHERE source='youtube'").fetchone()[0] == 10


def test_unknown_time_needs_valid_bound_and_evidence(scenario):
    mutate_packet(scenario, 'youtube', unknown_time)
    mutate_packet(scenario, 'youtube', lambda p: p['provenance'].update(collected_no_later_than='2027-01-01T00:00:00Z'))
    with pytest.raises(DataError, match='bound cannot follow'):
        run_pipeline(scenario)


def test_review_timezone_assumption_changes_only_interpretation():
    value = '2025-01-31T20:00:00'
    assert historical_timestamp(value, 'UTC') == '2025-01-31T20:00:00+00:00'
    assert historical_timestamp(value, 'Asia/Bangkok') == '2025-01-31T13:00:00+00:00'


def test_historical_adapter_rejects_tampered_archive_and_preview(tmp_path):
    import hashlib
    records = b'{"data": {"score": 4}}\n'
    page = b'{"documents": []}'
    (tmp_path / 'records.jsonl').write_bytes(records)
    (tmp_path / 'page-00001.json').write_bytes(page)
    manifest = dict(status='exported', collection_exhausted=True, document_count=1,
                    records_sha256=hashlib.sha256(records).hexdigest(),
                    pages=[dict(file='page-00001.json', sha256=hashlib.sha256(page).hexdigest())])
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    assert len(read_export({'folder': str(tmp_path)})[0]) == 1
    (tmp_path / 'records.jsonl').write_bytes(records.replace(b'4', b'5'))
    with pytest.raises(DataError, match='content hash mismatch'):
        read_export({'folder': str(tmp_path)})
    (tmp_path / 'records.jsonl').write_bytes(records)
    (tmp_path / 'page-00001.json').write_bytes(b'{}')
    with pytest.raises(DataError, match='native page hash mismatch'):
        read_export({'folder': str(tmp_path)})
    manifest.update(collection_exhausted=False, status='capped')
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(DataError, match='exhausted'):
        read_export({'folder': str(tmp_path)})
