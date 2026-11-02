"""Convert friend exports into canonical packets without guessing provenance."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .common import DataError, GAMES, SOURCES, parse_date, parse_timestamp, read_json, write_json


def read_records(path: Path):
    if path.suffix.lower() == ".json":
        value = read_json(path)
        if not isinstance(value, list):
            raise DataError("JSON export must be an array of objects; transform Firestore typed exports first")
        return value
    if path.suffix.lower() != ".csv":
        raise DataError("Only CSV or JSON-array exports are supported")
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    # Google's multiTimeline CSV has a category preamble and blank line.
    for index, line in enumerate(lines):
        if line.startswith(("Day,", "Week,", "Month,", "date,")):
            lines = lines[index:]
            break
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def timestamp(value, source_timezone):
    if value in (None, ""):
        return value  # quality layer records the rejection
    try:
        return parse_timestamp(value).isoformat()
    except DataError:
        if not source_timezone:
            raise DataError("Naive export timestamp: set source_timezone in metadata explicitly")
        try:
            parsed = datetime.fromisoformat(str(value))
            return parsed.replace(tzinfo=ZoneInfo(source_timezone)).isoformat()
        except ValueError as exc:
            raise DataError("Invalid export timestamp") from exc


def convert_export(input_path: str | Path, metadata_path: str | Path, output_path: str | Path):
    source_path, target = Path(input_path), Path(output_path)
    if target.exists():
        raise DataError("Output exists; choose a new packet filename to preserve previous imports")
    metadata = read_json(Path(metadata_path))
    source = metadata.get("source")
    if source not in SOURCES or metadata.get("data_kind") != "real":
        raise DataError("Import metadata must identify a known source and data_kind=real")
    parse_timestamp(metadata.get("collected_at"))
    for field in ("context", "coverage"):
        if field not in metadata:
            raise DataError(f"Metadata requires {field}; do not infer complete coverage from existing rows")
    raw = read_records(source_path)
    mapping = metadata.get("column_map", {})
    source_timezone = metadata.get("source_timezone")
    converted = []
    def value(row, field, aliases=()):
        for key in [mapping.get(field, field), *aliases]:
            if key in row:
                return row[key]
        return None
    for row in raw:
        if not isinstance(row, dict):
            raise DataError("Export rows must be objects")
        game = value(row, "game", ("Game",)) or metadata.get("game")
        if source == "trends":
            day = value(row, "date", ("Day", "Week", "Month"))
            finish = value(row, "period_end")
            if not finish:
                if metadata.get("interval_days") not in (1, 7):
                    raise DataError("Trends export requires period_end or explicit interval_days=1/7")
                finish = (parse_date(day) + timedelta(days=metadata["interval_days"] - 1)).isoformat()
            partial = str(value(row, "is_partial", ("isPartial",)) or "false").lower()
            if partial not in ("true", "false"):
                raise DataError("Unrecognized isPartial value")
            for trend_game in GAMES:
                interest = value(row, trend_game)
                if interest is None:
                    raise DataError("Provide both jointly queried Trends columns and map their exact headers")
                # Google '<1' is censored, not exact zero. Keep it non-numeric for quarantine.
                converted.append({"game": trend_game, "date": day, "period_end": finish,
                                  "interest": interest, "is_partial": partial == "true"})
        elif source == "youtube":
            converted.append({"game": game, "video_id": value(row, "video_id"), "channel_id": value(row, "channel_id"),
                "title": value(row, "title"), "published_at": timestamp(value(row, "published_at"), source_timezone),
                "views": value(row, "views"), "likes": value(row, "likes") if value(row, "likes") != "" else None})
        else:
            converted.append({"game": game, "app_id": value(row, "app_id") or metadata.get("app_id"),
                "review_id": value(row, "review_id", ("reviewId",)), "rating": value(row, "rating", ("score",)),
                "reviewed_at": timestamp(value(row, "reviewed_at", ("at",)), source_timezone),
                "language": value(row, "language", ("lang_source",)) or metadata.get("language")})
    packet = {"schema_version": 1, "source": source, "data_kind": "real",
              "collected_at": metadata["collected_at"], "context": metadata["context"],
              "coverage": metadata["coverage"], "records": converted,
              "import_provenance": {"filename": source_path.name, "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                                    "metadata": metadata}, "upstream": raw}
    write_json(target, packet)
    # Byte-identical copy of original export beside the canonical packet.
    archive = target.parent / f"{target.stem}.original{source_path.suffix.lower()}"
    if archive.exists():
        target.unlink()
        raise DataError("Original archive path exists; choose a new output name")
    archive.write_bytes(source_path.read_bytes())
    return target
