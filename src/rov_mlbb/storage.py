from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .common import DataError, digest, json_text, utc_now

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('running','complete','partial','failed')),
    data_kind TEXT NOT NULL, config_hash TEXT NOT NULL, config_json TEXT NOT NULL,
    artifact_dir TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS run_sources (
    run_id TEXT NOT NULL REFERENCES runs(run_id), source TEXT NOT NULL,
    raw_path TEXT NOT NULL, raw_sha256 TEXT NOT NULL, report_json TEXT NOT NULL,
    PRIMARY KEY (run_id, source)
);
CREATE TABLE IF NOT EXISTS observations (
    source TEXT NOT NULL, record_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL, first_run_id TEXT NOT NULL REFERENCES runs(run_id),
    PRIMARY KEY (source, record_key, payload_hash)
);
CREATE TABLE IF NOT EXISTS run_records (
    run_id TEXT NOT NULL REFERENCES runs(run_id), source TEXT NOT NULL,
    record_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
    PRIMARY KEY(run_id, source, record_key),
    FOREIGN KEY(source,record_key,payload_hash) REFERENCES observations(source,record_key,payload_hash)
);
CREATE TABLE IF NOT EXISTS monthly_metrics (
    run_id TEXT NOT NULL REFERENCES runs(run_id), month TEXT NOT NULL,
    game TEXT NOT NULL CHECK(game IN ('rov','mlbb')), metrics_json TEXT NOT NULL,
    PRIMARY KEY (run_id, month, game)
);
CREATE VIEW IF NOT EXISTS latest_complete_monthly AS
SELECT * FROM monthly_metrics WHERE run_id = (
    SELECT run_id FROM runs WHERE status='complete' ORDER BY finished_at DESC LIMIT 1
);
"""


def connect(path: Path, mode: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    existing = conn.execute("SELECT value FROM metadata WHERE key='data_kind'").fetchone()
    if existing and existing[0] != mode:
        conn.close()
        raise DataError("SQLite namespace cannot mix sample and real data")
    conn.execute("INSERT OR IGNORE INTO metadata VALUES ('data_kind', ?)", (mode,))
    conn.commit()
    return conn


@contextmanager
def exclusive_lock(path: Path):
    """OS releases this lock on process death; a leftover file is not a stale lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    if path.stat().st_size == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise DataError("Another pipeline owns this artifact directory; retry after it finishes") from exc
    try:
        yield
    finally:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def begin_run(conn, run_id, cfg, directory):
    # Called only while holding the OS lock. A previous running row is now orphaned.
    conn.execute("UPDATE runs SET status='failed', finished_at=?, error=? WHERE status='running'",
                 (utc_now(), "Process interrupted before finalization"))
    conn.execute("INSERT INTO runs VALUES (?,?,NULL,'running',?,?,?,?,NULL)",
                 (run_id, utc_now(), cfg.mode, digest(cfg.raw), json_text(cfg.raw), str(directory)))
    conn.commit()


def persist_results(conn, run_id, batches, source_reports, summary, status):
    """Commit all accepted records, lineage, summary and terminal state together."""
    with conn:
        for source, batch in batches.items():
            meta = source_reports[source]
            conn.execute("INSERT INTO run_sources VALUES (?,?,?,?,?)",
                         (run_id, source, meta["raw_path"], meta["raw_sha256"], json_text(meta)))
            for record in batch.records:
                key, payload_hash = record["record_key"], digest(record)
                conn.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?)",
                             (source, key, payload_hash, json_text(record), run_id))
                conn.execute("INSERT INTO run_records VALUES (?,?,?,?)", (run_id, source, key, payload_hash))
        for row in json.loads(summary.to_json(orient="records")):
            conn.execute("INSERT INTO monthly_metrics VALUES (?,?,?,?)",
                         (run_id, row["month"], row["game"], json_text(row)))
        conn.execute("UPDATE runs SET status=?, finished_at=? WHERE run_id=?", (status, utc_now(), run_id))
