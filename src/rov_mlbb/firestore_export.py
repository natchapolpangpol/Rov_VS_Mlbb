"""Bounded, read-only Firestore REST exports authenticated with the user's ADC.

Firestore export time is NOT the original Trends/YouTube/review collection time.
This module preserves native typed fields and does not claim analytical coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote
import uuid

from .collectors import CollectionError, TransientError, retry_call
from .common import utc_now, write_json


def decode_value(value):
    if 'nullValue' in value:
        return None
    for kind in ('stringValue', 'booleanValue', 'timestampValue', 'referenceValue', 'bytesValue', 'geoPointValue'):
        if kind in value:
            return value[kind]
    if 'integerValue' in value:
        return int(value['integerValue'])
    if 'doubleValue' in value:
        number = value['doubleValue']
        # Preserve special Firestore numbers as text; downstream validation decides their use.
        return number if isinstance(number, (int, float)) else str(number)
    if 'arrayValue' in value:
        return [decode_value(v) for v in value['arrayValue'].get('values', [])]
    if 'mapValue' in value:
        return {k: decode_value(v) for k, v in value['mapValue'].get('fields', {}).items()}
    raise CollectionError('Unknown Firestore value type; raw response is preserved')


class FirestoreReader:
    def __init__(self, project, database='(default)', session=None):
        if not re.fullmatch(r'[a-z][a-z0-9-]{4,61}[a-z0-9]', project):
            raise CollectionError('Invalid Project ID')
        if not re.fullmatch(r'[A-Za-z0-9_()-]+', database):
            raise CollectionError('Invalid database ID')
        self.project, self.database = project, database
        self.base = f'https://firestore.googleapis.com/v1/projects/{project}/databases/{quote(database, safe="")}/documents'
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            from google.auth.exceptions import DefaultCredentialsError
            try:
                credentials, _ = google.auth.default(
                    scopes=['https://www.googleapis.com/auth/datastore'], quota_project_id=project)
            except DefaultCredentialsError:
                raise CollectionError('Google login is required. Run scripts/connect_firestore.cmd first.') from None
            session = AuthorizedSession(credentials)
        self.session = session
        self.events = []

    def _read(self, method, url, **kwargs):
        import requests
        def operation():
            try:
                response = self.session.request(method, url, timeout=(10, 60), **kwargs)
            except requests.RequestException as error:
                raise TransientError(f'Firestore transport failed: {type(error).__name__}') from None
            if response.status_code == 429 or response.status_code >= 500:
                raise TransientError(f'Firestore HTTP {response.status_code}')
            if response.status_code != 200:
                raise CollectionError(f'Firestore HTTP {response.status_code}; verify account, project and IAM access')
            try:
                return response.json()
            except ValueError:
                raise CollectionError('Firestore response was not valid JSON') from None
        return retry_call(operation, events=self.events)

    def list_collections(self):
        names, token = [], None
        for _ in range(20):
            body = {'pageSize': 100}
            if token:
                body['pageToken'] = token
            result = self._read('POST', self.base + ':listCollectionIds', json=body)
            names.extend(result.get('collectionIds', []))
            token = result.get('nextPageToken')
            if not token:
                return sorted(set(names))
        raise CollectionError('Collection listing reached its metadata page limit')

    def export(self, collection, output_root, max_documents=100, page_size=100):
        segments = collection.split('/')
        if len(segments) % 2 != 1 or any(not s or s in ('.', '..') for s in segments):
            raise CollectionError('Specify a collection path, optionally including parent document segments')
        if not 1 <= max_documents <= 50000 or not 1 <= page_size <= 1000:
            raise CollectionError('max_documents must be 1..50000 and page_size 1..1000')
        folder = Path(output_root) / f'firestore-{uuid.uuid4().hex}'
        folder.mkdir(parents=True)
        manifest = {'status': 'running', 'project_id': self.project, 'database_id': self.database,
                    'collection_path': collection, 'export_started_at': utc_now(),
                    'original_collected_at': None, 'max_documents': max_documents,
                    'document_count': 0, 'pages': [], 'collection_exhausted': False,
                    'scope': 'Direct documents of this collection only; subcollections are not recursively exported',
                    'consistency': 'Sequential paginated reads; not an atomic database backup',
                    'provenance_note': 'Document create/update time and export time are not original source collection times'}
        token, seen = None, set()
        try:
            with (folder / 'records.jsonl').open('w', encoding='utf-8') as stream:
                while manifest['document_count'] < max_documents:
                    params = {'pageSize': min(page_size, max_documents - manifest['document_count']), 'orderBy': '__name__'}
                    if token:
                        params['pageToken'] = token
                    response = self._read('GET', self.base + '/' + quote(collection, safe='/'), params=params)
                    page = folder / f"page-{len(manifest['pages']) + 1:05d}.json"
                    write_json(page, response)
                    manifest['pages'].append({'file': page.name, 'sha256': hashlib.sha256(page.read_bytes()).hexdigest()})
                    for document in response.get('documents', []):
                        if document['name'] in seen:
                            raise CollectionError('Repeated document across pages; refusing an ambiguous export')
                        seen.add(document['name'])
                        record = {'data': {k: decode_value(v) for k, v in document.get('fields', {}).items()},
                                  'firestore': {k: document.get(k) for k in ('name', 'createTime', 'updateTime')}}
                        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
                        manifest['document_count'] += 1
                    next_token = response.get('nextPageToken')
                    if not next_token:
                        manifest['collection_exhausted'] = True
                        break
                    if next_token == token:
                        raise CollectionError('Firestore pagination token did not advance')
                    token = next_token
            manifest['status'] = 'exported' if manifest['collection_exhausted'] else 'capped'
            manifest['records_sha256'] = hashlib.sha256((folder / 'records.jsonl').read_bytes()).hexdigest()
        except Exception as error:
            manifest['status'] = 'failed'
            manifest['error_type'] = type(error).__name__
            raise
        finally:
            manifest['export_finished_at'] = utc_now()
            manifest['events'] = self.events
            write_json(folder / 'manifest.json', manifest)
        return folder, manifest


def main():
    import truststore
    truststore.inject_into_ssl()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--database', default='(default)')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--list-collections', action='store_true')
    mode.add_argument('--collection')
    parser.add_argument('--max-documents', type=int, default=100)
    parser.add_argument('--output-root', default='data/imports')
    args = parser.parse_args()
    try:
        reader = FirestoreReader(args.project, args.database)
        if args.list_collections:
            print(json.dumps({'project': args.project, 'collections': reader.list_collections()}, ensure_ascii=False, indent=2))
        else:
            folder, result = reader.export(args.collection, args.output_root, args.max_documents)
            print(json.dumps({'directory': str(folder.resolve()), 'status': result['status'],
                              'document_count': result['document_count'],
                              'collection_exhausted': result['collection_exhausted']}, indent=2))
    except CollectionError as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
