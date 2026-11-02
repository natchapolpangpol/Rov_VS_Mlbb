from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import pandas as pd

from .aggregate import summarize
from .common import SOURCES, DataError, digest, read_json, utc_now, write_json
from .config import Config, load_config
from .quality import clean_packet
from .storage import begin_run, connect, exclusive_lock, persist_results


def atomic_pointer(path: Path, value: dict):
    temporary = path.with_suffix(".tmp")
    write_json(temporary, value)
    os.replace(temporary, path)


def run_pipeline(config_path: str | Path) -> dict:
    cfg = load_config(config_path)
    with exclusive_lock(cfg.output / ".pipeline.lock"):
        return _run(cfg)


def _run(cfg: Config) -> dict:
    run_id = uuid.uuid4().hex
    directory = cfg.output / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    database = cfg.output / "pipeline.sqlite"
    conn = connect(database, cfg.mode)
    reports, batches = {}, {}
    started = utc_now()
    committed = False
    begin_run(conn, run_id, cfg, directory)
    write_json(directory / "config.json", cfg.raw)
    try:
        # Persist the byte-identical input before parsing/validation, even for bad inputs.
        for source in SOURCES:
            path = cfg.input_path(source)
            if path is None:
                reports[source] = {"source": source, "status": "missing", "reason": "No input configured"}
                continue
            if not path.is_file():
                raise DataError(f"Configured {source} input does not exist: {path}")
            contents = path.read_bytes()
            raw = directory / "raw" / f"{source}.json"
            raw.parent.mkdir(exist_ok=True)
            raw.write_bytes(contents)
            reports[source] = {"raw_path": str(raw), "raw_sha256": hashlib.sha256(contents).hexdigest()}
            packet = read_json(raw)
            batch = clean_packet(packet, source, cfg)
            batches[source] = batch
            reports[source].update(batch.report())
            write_json(directory / "clean" / f"{source}.json", batch.records)
            write_json(directory / "rejected" / f"{source}.json", batch.rejected)
            if batch.records:
                pd.DataFrame(batch.records).to_parquet(directory / "clean" / f"{source}.parquet", index=False)
            if batch.report()["rejected_fraction"] > cfg.reject_limit:
                raise DataError(f"{source}: rejected fraction exceeds configured gate {cfg.reject_limit}")
        summary = summarize(batches, cfg, run_id)
        if not batches or not any(batch.records for batch in batches.values()):
            raise DataError("No accepted observations; refusing to publish an empty run")
        status = "complete" if bool(summary["all_sources_complete"].all()) else "partial"
        summary_dir = directory / "summary"
        summary_dir.mkdir()
        summary.to_csv(summary_dir / "monthly_game_metrics.csv", index=False, encoding="utf-8-sig")
        summary.to_parquet(summary_dir / "monthly_game_metrics.parquet", index=False)
        result = {"run_id": run_id, "data_kind": cfg.mode, "status": status,
                  "started_at": started, "finished_at": utc_now(), "config_hash": digest(cfg.raw),
                  "artifact_dir": str(directory), "database": str(database),
                  "summary_rows": len(summary), "sources": reports}
        write_json(directory / "manifest.json", result)
        persist_results(conn, run_id, batches, reports, summary, status)
        committed = True
        # Export consumers only see completed files, with explicit completeness status.
        atomic_pointer(cfg.output / "latest_attempt.json", result)
        if status == "complete":
            atomic_pointer(cfg.output / "latest_complete.json", result)
        return result
    except Exception as exc:
        if committed:
            # A pointer is outside the SQLite transaction. Never relabel committed
            # data as a rolled-back failure or erase its successful run membership.
            error = f"Data committed; pointer publication failed: {type(exc).__name__}: {exc}"
            conn.execute("UPDATE runs SET error=? WHERE run_id=?", (error, run_id))
            conn.commit()
            result["publication_error"] = error
            try:
                write_json(directory / "manifest.json", result)
            except OSError:
                pass  # The DB still records the diagnostic if the filesystem is unavailable.
            raise DataError(f"{error}. Inspect run {run_id}; rerun the same input to refresh pointers safely.") from exc
        conn.rollback()
        error = f"{type(exc).__name__}: {exc}"
        conn.execute("UPDATE runs SET status='failed', finished_at=?, error=? WHERE run_id=?",
                     (utc_now(), error, run_id))
        conn.commit()
        result = {"run_id": run_id, "data_kind": cfg.mode, "status": "failed", "error": error,
                  "sources": reports, "artifact_dir": str(directory), "started_at": started,
                  "finished_at": utc_now()}
        write_json(directory / "manifest.json", result)
        atomic_pointer(cfg.output / "latest_attempt.json", result)
        raise
    finally:
        conn.close()
