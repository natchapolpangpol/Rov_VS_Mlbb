import json
from pathlib import Path

import pytest

from rov_mlbb.common import DataError
from rov_mlbb.pipeline import run_pipeline
from rov_mlbb.report import create_report, load_run, select_metrics


def test_report_filters_and_run_provenance(scenario):
    result = run_pipeline(scenario)
    folder = Path(result["artifact_dir"])
    manifest, frame = load_run(folder)
    selected = select_metrics(frame, "rov", "2025-01", "2025-01")
    assert len(selected) == 1
    assert selected.iloc[0].median_views_at_collection == 200
    assert len(frame) == 6
    assert "SYNTHETIC DEMO" in create_report(folder).read_text()
    with pytest.raises(DataError, match="Start"):
        select_metrics(frame, start="2025-03", end="2025-01")
    manifest["data_kind"] = "real"
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DataError, match="provenance"):
        load_run(folder)


def test_missing_metric_survives_report_filter(scenario):
    config = json.loads(scenario.read_text())
    del config["inputs"]["youtube"]
    scenario.write_text(json.dumps(config))
    result = run_pipeline(scenario)
    _, frame = load_run(result["artifact_dir"])
    selected = select_metrics(frame, "mlbb")
    assert selected.median_views_at_collection.isna().all()
    assert selected.published_video_count.isna().all()
    assert (selected.youtube_coverage == "missing").all()
    assert "partial" in create_report(result["artifact_dir"]).read_text()
