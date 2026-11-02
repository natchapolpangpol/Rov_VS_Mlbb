import json
from pathlib import Path

import pytest

from rov_mlbb.common import DataError
from rov_mlbb.importer import convert_export


def test_google_csv_preamble_and_provenance(tmp_path):
    source = tmp_path / "multiTimeline.csv"
    source.write_text('Category: All categories\n\nDay,rov: (Thailand),mlbb: (Thailand)\n2025-01-01,60,30\n', encoding="utf-8")
    meta = {"source": "trends", "data_kind": "real", "collected_at": "2025-02-01T00:00:00Z",
            "context": {"selection": "Imported joint request", "scale": "joint_request", "query_id": "a",
                        "terms": {"rov": "rov", "mlbb": "mlbb"}},
            "coverage": {g: {"status": "partial", "start": "2025-01-01", "end": "2025-01-01", "note": "One observed day"} for g in ("rov", "mlbb")},
            "interval_days": 1, "column_map": {"rov": "rov: (Thailand)", "mlbb": "mlbb: (Thailand)"}}
    metadata = tmp_path / "meta.json"
    metadata.write_text(json.dumps(meta))
    target = tmp_path / "packet.json"
    convert_export(source, metadata, target)
    packet = json.loads(target.read_text())
    assert [r["interest"] for r in packet["records"]] == ["60", "30"]
    assert (tmp_path / "packet.original.csv").read_bytes() == source.read_bytes()
    with pytest.raises(DataError, match="exists"):
        convert_export(source, metadata, target)
