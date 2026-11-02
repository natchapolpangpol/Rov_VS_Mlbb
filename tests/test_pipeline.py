from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from rov_mlbb.common import DataError
from rov_mlbb.pipeline import run_pipeline
from rov_mlbb.storage import exclusive_lock
from conftest import mutate_packet


def table_counts(db):
    with sqlite3.connect(db) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("runs", "observations", "run_records", "monthly_metrics")}


def test_end_to_end_values_lineage_and_idempotency(scenario):
    first = run_pipeline(scenario)
    folder = Path(first["artifact_dir"])
    summary = pd.read_parquet(folder / "summary/monthly_game_metrics.parquet")
    jan = summary[(summary.game == "rov") & (summary.month == "2025-01")].iloc[0]
    assert (jan.search_interest, jan.published_video_count, jan.median_views_at_collection) == (60, 2, 200)
    assert (jan.review_count, jan.mean_review_rating) == (2, 3)
    assert first["sources"]["playstore"]["duplicate_rows"] == 1
    assert first["status"] == "complete"
    before = table_counts(first["database"])
    second = run_pipeline(scenario)
    after = table_counts(second["database"])
    assert before["observations"] == after["observations"] == 28
    assert after["runs"] == 2 and after["run_records"] == 56 and after["monthly_metrics"] == 12
    for source in ("trends", "youtube", "playstore"):
        assert (folder / "raw" / f"{source}.json").read_bytes() == (scenario.parent / f"{source}.json").read_bytes()
    assert (summary.loc[(summary.game == "mlbb") & (summary.month == "2025-03"), "published_video_count"] == 0).all()


def test_failed_run_preserves_published_result(scenario):
    first = run_pipeline(scenario)
    mutate_packet(scenario, "playstore", lambda p: p["records"][0].update(rating=99))
    with pytest.raises(DataError, match="gate"):
        run_pipeline(scenario)
    output = Path(first["database"]).parent
    assert json.loads((output / "latest_complete.json").read_text())["run_id"] == first["run_id"]
    failed = json.loads((output / "latest_attempt.json").read_text())
    assert failed["status"] == "failed"
    with sqlite3.connect(first["database"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE status='failed'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM run_records WHERE run_id=?", (failed["run_id"],)).fetchone()[0] == 0


def test_missing_source_stays_null_and_not_complete(scenario):
    cfg = json.loads(scenario.read_text())
    del cfg["inputs"]["youtube"]
    scenario.write_text(json.dumps(cfg))
    result = run_pipeline(scenario)
    data = pd.read_parquet(Path(result["artifact_dir"]) / "summary/monthly_game_metrics.parquet")
    assert result["status"] == "partial"
    assert data.published_video_count.isna().all()
    assert (data.youtube_coverage == "missing").all()
    assert not (Path(result["database"]).parent / "latest_complete.json").exists()


def test_namespace_mismatch_fails(scenario):
    mutate_packet(scenario, "trends", lambda p: p.update(data_kind="real"))
    with pytest.raises(DataError, match="mix"):
        run_pipeline(scenario)


def test_declared_missing_file_fails_instead_of_zero(scenario):
    (scenario.parent / "youtube.json").unlink()
    with pytest.raises(DataError, match="does not exist"):
        run_pipeline(scenario)


def test_conflicting_duplicates_are_not_arbitrarily_selected(scenario):
    mutate_packet(scenario, "youtube", lambda p: p["records"].append({**p["records"][0], "views": 9999}))
    with pytest.raises(DataError):
        run_pipeline(scenario)
    result = json.loads((scenario.parent / "artifacts/sample/latest_attempt.json").read_text())
    assert result["sources"]["youtube"]["reasons"]["conflicting_duplicate_key"] == 2


def test_changed_review_retains_reproducible_old_version(scenario):
    first = run_pipeline(scenario)
    def update(p):
        p["records"] = [r for r in p["records"] if r["review_id"] != "sample-rov-1-0"]
        p["records"].append({"game": "rov", "app_id": "com.garena.game.kgth", "review_id": "sample-rov-1-0",
                             "reviewed_at": "2025-01-02T08:00:00Z", "rating": 5, "language": "th"})
    mutate_packet(scenario, "playstore", update)
    second = run_pipeline(scenario)
    assert table_counts(second["database"])["observations"] == 29
    with sqlite3.connect(first["database"]) as conn:
        vals = conn.execute("SELECT o.payload_json FROM observations o JOIN run_records r USING(source,record_key,payload_hash) WHERE r.run_id=? AND r.source='playstore' AND r.record_key=?", (first["run_id"], "com.garena.game.kgth:sample-rov-1-0")).fetchall()
    assert json.loads(vals[0][0])["rating"] == 4


def test_exclusive_lock_rejects_second_writer(tmp_path):
    lock = tmp_path / "pipeline.lock"
    with exclusive_lock(lock):
        with pytest.raises(DataError, match="Another"):
            with exclusive_lock(lock):
                pass
    with exclusive_lock(lock):
        pass


def test_pointer_failure_does_not_relabel_committed_data(scenario, monkeypatch):
    from rov_mlbb import pipeline
    first = run_pipeline(scenario)
    before = table_counts(first["database"])
    original = pipeline.atomic_pointer
    def unavailable(*args):
        raise OSError("simulated pointer storage failure")
    monkeypatch.setattr(pipeline, "atomic_pointer", unavailable)
    with pytest.raises(DataError, match="Data committed; pointer publication failed"):
        run_pipeline(scenario)
    with sqlite3.connect(first["database"]) as conn:
        row = conn.execute("SELECT run_id,status,error,artifact_dir FROM runs WHERE run_id != ?", (first["run_id"],)).fetchone()
    assert row[1] == "complete" and "pointer publication failed" in row[2]
    assert json.loads((Path(row[3]) / "manifest.json").read_text())["publication_error"] == row[2]
    pointer = Path(first["database"]).parent / "latest_complete.json"
    assert json.loads(pointer.read_text())["run_id"] == first["run_id"]
    assert table_counts(first["database"])["observations"] == before["observations"]
    monkeypatch.setattr(pipeline, "atomic_pointer", original)
    recovered = run_pipeline(scenario)
    assert json.loads(pointer.read_text())["run_id"] == recovered["run_id"]
    assert table_counts(first["database"])["observations"] == before["observations"]


def test_persistence_failure_rolls_back_all_new_results(scenario, monkeypatch):
    from rov_mlbb import pipeline
    first = run_pipeline(scenario)
    counts = table_counts(first["database"])
    def fail_with_uncommitted_write(conn, run_id, *args):
        conn.execute("INSERT INTO monthly_metrics VALUES (?, '2025-01', 'rov', '{}')", (run_id,))
        raise OSError("simulated database write failure")
    monkeypatch.setattr(pipeline, "persist_results", fail_with_uncommitted_write)
    with pytest.raises(OSError, match="database write failure"):
        run_pipeline(scenario)
    after = table_counts(first["database"])
    assert after["monthly_metrics"] == counts["monthly_metrics"]
    assert after["observations"] == counts["observations"]
    assert after["run_records"] == counts["run_records"]
    with sqlite3.connect(first["database"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE status='failed'").fetchone()[0] == 1
