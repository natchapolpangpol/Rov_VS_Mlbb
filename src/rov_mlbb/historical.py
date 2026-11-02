"""Adapt the archived team Firestore data with explicit provenance uncertainty."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import uuid

from .common import APPS, GAMES, DataError, digest, parse_timestamp, read_json, write_json


def read_export(item):
    folder = Path(item['folder']).resolve()
    manifest = read_json(folder / 'manifest.json')
    if manifest['status'] != 'exported' or not manifest['collection_exhausted']:
        raise DataError('Historical adapter requires an exhausted collection export, not a preview')
    contents = (folder / 'records.jsonl').read_bytes()
    if hashlib.sha256(contents).hexdigest() != manifest['records_sha256']:
        raise DataError('Firestore export content hash mismatch')
    for page in manifest['pages']:
        if hashlib.sha256((folder / page['file']).read_bytes()).hexdigest() != page['sha256']:
            raise DataError('Firestore native page hash mismatch')
    rows = [json.loads(line) for line in contents.decode('utf-8').splitlines()]
    if len(rows) != manifest['document_count']:
        raise DataError('Firestore export row count mismatch')
    return rows, manifest, folder


def historical_timestamp(value, assumed_timezone):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(assumed_timezone))
    return parse_timestamp(parsed.isoformat()).isoformat()


def make_packet(source, exports, root, assumed_timezone):
    records, evidence, upper_bounds, exported_times = [], [], [], []
    coverage = {}
    for game in GAMES:
        name = f'{game}_youtube' if source == 'youtube' else f'{game}_google_play'
        rows, manifest, folder = read_export(exports[name])
        evidence.append({'collection': name, 'manifest': str(folder / 'manifest.json'),
                         'records_sha256': manifest['records_sha256'], 'document_count': len(rows)})
        exported_times.append(manifest['export_finished_at'])
        event_dates = []
        for wrapper in rows:
            row, metadata = wrapper['data'], wrapper['firestore']
            upper_bounds.append(parse_timestamp(metadata['updateTime']))
            if source == 'youtube':
                if row['game'].lower() != game:
                    raise DataError('Firestore collection/game mismatch')
                record = {k: row.get(k) for k in ('video_id', 'channel_id', 'title', 'published_at', 'views', 'likes')}
                record['published_at'] = parse_timestamp(record['published_at']).isoformat()
                event = parse_timestamp(record['published_at'])
            else:
                record = {'review_id': row['reviewId'], 'app_id': APPS[game], 'rating': row['score'],
                          'language': row['lang_source'],
                          'reviewed_at': historical_timestamp(row['at'], assumed_timezone)}
                event = parse_timestamp(record['reviewed_at'])
            record.update(game=game, source_record_ref=metadata['name'])
            records.append(record)
            event_dates.append(event.astimezone(ZoneInfo('Asia/Bangkok')).date().isoformat())
        coverage[game] = {'start': min(event_dates), 'end': max(event_dates), 'status': 'partial',
                          'note': 'All documents from the team archive exported; completeness of original API collection is unverified. Review filtering and source selection follow the original notebook.'}
    records.sort(key=lambda r: (r['game'], r.get('video_id', r.get('review_id')), r['source_record_ref']))
    provenance = {'collection_time_status': 'unknown', 'collected_no_later_than': max(upper_bounds).isoformat(),
                  'exported_at': max(exported_times), 'snapshot_id': digest({'source': source, 'records': records}),
                  'source_exports': evidence,
                  'timing_basis': 'Original notebook and archived records omit collection time. Firestore document updateTime supplies only a no-later-than bound; export time is recorded separately.',
                  'notebook_sha256': hashlib.sha256((root / 'RovVsMlbb_Pipeline.ipynb').read_bytes()).hexdigest()}
    context = {'selection': ('Original notebook selected channels and case-sensitive title keywords; comments removed and video_id deduplicated before upload.' if source == 'youtube' else
                              'Original notebook: country th, request lang_source th, non-null appVersion, rolling one-year filter; RoV NEWEST, MLBB MOST_RELEVANT.'),
               'historical_archive': True}
    if source == 'playstore':
        context.update(source_timezone_assumed=assumed_timezone,
                       timezone_basis='Explicit assumption for timezone-naive Colab output; not verified in the source. Compare UTC and Asia/Bangkok sensitivity runs.',
                       language_caveat='Request language does not verify author nationality or actual text language')
    return {'schema_version': 2, 'source': source, 'data_kind': 'real', 'collected_at': None,
            'provenance': provenance, 'context': context, 'coverage': coverage, 'records': records}


def adapt(export_index, trends_packet, assumed_timezone='UTC', artifact_root='artifacts'):
    root = Path(__file__).resolve().parents[2]
    index = read_json(Path(export_index))
    exports = {item['collection']: item for item in index['exports']}
    folder = root / 'data/imports' / f'historical-{uuid.uuid4().hex}'
    folder.mkdir(parents=True)
    inputs = {'trends': str(Path(trends_packet).resolve())}
    for source in ('youtube', 'playstore'):
        packet = make_packet(source, exports, root, assumed_timezone)
        path = folder / f'{source}.json'
        write_json(path, packet)
        inputs[source] = str(path)
    config = {'project_root': str(root), 'artifact_root': artifact_root, 'data_kind': 'real',
              'study_start': '2025-01-01', 'study_end': '2026-03-10', 'timezone': 'Asia/Bangkok',
              'max_rejected_fraction': 0.05, 'inputs': inputs,
              'scope_basis': 'RovVsMlbb_Pipeline.ipynb cell 16; review subset and query edge gaps retained explicitly.'}
    path = folder / 'pipeline_config.json'
    write_json(path, config)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-index', required=True)
    parser.add_argument('--trends-packet', required=True)
    parser.add_argument('--assumed-review-timezone', default='UTC', choices=['UTC', 'Asia/Bangkok'])
    parser.add_argument('--artifact-root', default='artifacts')
    args = parser.parse_args()
    print(adapt(args.export_index, args.trends_packet, args.assumed_review_timezone, args.artifact_root))


if __name__ == '__main__':
    main()
