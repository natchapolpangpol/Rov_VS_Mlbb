import pytest

from rov_mlbb.collectors import CollectionError, TransientError, classify_title, http_json, retry_call


def test_transient_failure_retries_with_backoff():
    calls, waits, events = [], [], []
    def operation():
        calls.append(1)
        if len(calls) < 3:
            raise TransientError("temporary")
        return 42
    assert retry_call(operation, sleep=waits.append, events=events) == 42
    assert waits == [2, 4]
    assert [e["status"] for e in events] == ["transient_failure", "transient_failure", "ok"]


def test_permanent_failure_is_not_retried():
    calls = []
    def operation():
        calls.append(1)
        raise CollectionError("invalid key")
    with pytest.raises(CollectionError):
        retry_call(operation, sleep=lambda _: None)
    assert len(calls) == 1


def test_missing_api_key_fails_without_network(monkeypatch):
    from rov_mlbb.collectors import collect_youtube
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(CollectionError, match="not set"):
        collect_youtube({}, [])


def test_http_error_does_not_expose_key():
    class Response:
        status_code = 403
        url = "https://example.com?key=VERY_SECRET_VALUE"
    class Session:
        def get(self, *args, **kwargs):
            return Response()
    with pytest.raises(CollectionError) as exc:
        http_json(Session(), "https://example.com", {"key": "VERY_SECRET_VALUE"}, [])
    assert "VERY_SECRET" not in str(exc.value)


@pytest.mark.parametrize("title,expected", [("RoV test", "rov"), ("rov: test", "rov"), ("MLBB", "mlbb"),
    ("mobile legends guide", "mlbb"), ("RoV vs MLBB", None), ("improvement guide", None), ("อาร์โอวี", "rov")])
def test_title_classification_boundaries(title, expected):
    assert classify_title(title) == expected


def test_playstore_swallowed_upstream_error_does_not_become_zero(monkeypatch):
    import ssl
    import importlib
    from rov_mlbb.collectors import collect_playstore
    original_ssl = ssl._create_default_https_context
    try:
        mod = importlib.import_module("google_play_scraper.features.reviews")
    finally:
        ssl._create_default_https_context = original_ssl
    def fail(*args, **kwargs):
        raise ValueError("malformed upstream response")
    monkeypatch.setattr(mod, "_fetch_review_items", fail)
    with pytest.raises(CollectionError, match="not an empty population"):
        collect_playstore({"study_start": "2025-01-01", "study_end": "2025-01-31",
                           "playstore": {"max_pages_per_game": 1}}, [])
    assert ssl._create_default_https_context is original_ssl
    assert mod._fetch_review_items is fail


def test_playstore_unverified_empty_first_page_is_not_complete(monkeypatch):
    import ssl
    import importlib
    from rov_mlbb.collectors import collect_playstore
    original_ssl = ssl._create_default_https_context
    try:
        mod = importlib.import_module("google_play_scraper.features.reviews")
    finally:
        ssl._create_default_https_context = original_ssl
    monkeypatch.setattr(mod, "_fetch_review_items", lambda *a, **k: ([], None))
    with pytest.raises(CollectionError, match="Unverified empty"):
        collect_playstore({"study_start": "2025-01-01", "study_end": "2025-01-31"}, [])
