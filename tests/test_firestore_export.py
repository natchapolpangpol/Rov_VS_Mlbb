import json

import pytest

from rov_mlbb.collectors import CollectionError
from rov_mlbb.firestore_export import FirestoreReader, decode_value


class Session:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        data = next(self.pages)
        class Response:
            status_code = 200
            def json(self):
                return data
        return Response()


def doc(name):
    return {'name': 'projects/example-project/databases/(default)/documents/reviews/' + name,
            'fields': {'score': {'integerValue': '4'}, 'at': {'timestampValue': '2025-01-01T01:00:00Z'}}}


def test_capped_export_preserves_native_types_and_does_not_claim_coverage(tmp_path):
    session = Session([{'documents': [doc('a')], 'nextPageToken': 'second'}])
    reader = FirestoreReader('example-project', session=session)
    folder, manifest = reader.export('reviews', tmp_path, max_documents=1)
    assert manifest['status'] == 'capped' and not manifest['collection_exhausted']
    assert manifest['original_collected_at'] is None
    row = json.loads((folder / 'records.jsonl').read_text())
    assert row['data']['score'] == 4
    assert json.loads((folder / 'page-00001.json').read_text())['documents'][0]['fields']['score'] == {'integerValue': '4'}
    assert session.calls[0][0] == 'GET'


def test_export_pages_and_nested_values(tmp_path):
    session = Session([{'documents': [doc('a')], 'nextPageToken': 'second'}, {'documents': [doc('b')]}])
    reader = FirestoreReader('example-project', session=session)
    _, result = reader.export('reviews', tmp_path, max_documents=10, page_size=1)
    assert result['document_count'] == 2 and result['collection_exhausted']
    assert session.calls[1][2]['params']['pageToken'] == 'second'
    assert decode_value({'mapValue': {'fields': {'x': {'arrayValue': {'values': [{'nullValue': None}]}}}}}) == {'x': [None]}


def test_duplicate_document_marks_export_failed(tmp_path):
    session = Session([{'documents': [doc('a')], 'nextPageToken': 'second'}, {'documents': [doc('a')]}])
    with pytest.raises(CollectionError, match='Repeated document'):
        FirestoreReader('example-project', session=session).export('reviews', tmp_path)
    manifest = next(tmp_path.glob('*/manifest.json'))
    assert json.loads(manifest.read_text())['status'] == 'failed'


def test_collection_listing_only_calls_metadata_endpoint():
    session = Session([{'collectionIds': ['reviews'], 'nextPageToken': 'next'}, {'collectionIds': ['videos']}])
    assert FirestoreReader('example-project', session=session).list_collections() == ['reviews', 'videos']
    assert all(method == 'POST' and url.endswith(':listCollectionIds') for method, url, _ in session.calls)
