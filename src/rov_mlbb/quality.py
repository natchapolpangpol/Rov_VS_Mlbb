from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
import re

from .common import APPS, GAMES, SOURCES, DataError, digest, numeric, parse_date, parse_timestamp, required_text
from .config import Config


@dataclass
class CleanBatch:
    source: str
    packet: dict
    records: list[dict]
    rejected: list[dict]
    duplicates: int

    def report(self):
        count = len(self.packet["records"])
        return {
            "source": self.source,
            "input_rows": count,
            "accepted_rows": len(self.records),
            "duplicate_rows": self.duplicates,
            "rejected_rows": len(self.rejected),
            "rejected_fraction": len(self.rejected) / count if count else 0,
            "reasons": dict(Counter(r["reason"] for r in self.rejected)),
            "coverage": self.packet["coverage"],
            "collected_at": self.packet["collected_at"],
            "collection_time_status": "unknown" if self.packet["collected_at"] is None else "known",
            "provenance": self.packet.get("provenance", {}),
        }


def collection_timing(packet):
    """An upper bound is validation evidence, never a fabricated collection time."""
    if packet.get("schema_version") == 1:
        value = parse_timestamp(packet.get("collected_at"))
        return value, value
    if packet.get("schema_version") != 2 or packet.get("collected_at") is not None:
        raise DataError("Unsupported packet timing contract")
    provenance = packet.get("provenance", {})
    if provenance.get("collection_time_status") != "unknown":
        raise DataError("Historical schema 2 requires explicit unknown collection time")
    if not re.fullmatch(r"[0-9a-f]{64}", provenance.get("snapshot_id", "")):
        raise DataError("Historical input requires a stable SHA-256 snapshot_id")
    upper = parse_timestamp(provenance.get("collected_no_later_than"))
    exported = parse_timestamp(provenance.get("exported_at"))
    if upper > exported:
        raise DataError("Collection upper bound cannot follow export time")
    required_text(provenance.get("timing_basis"), "timing_basis")
    if not provenance.get("source_exports"):
        raise DataError("Historical input requires source export evidence")
    return None, upper


def validate_packet(packet: dict, source: str, cfg: Config) -> None:
    if source not in SOURCES or packet.get("source") != source:
        raise DataError("Packet source mismatch")
    if packet.get("data_kind") != cfg.mode:
        raise DataError("Cannot mix sample and real data")
    if packet.get("schema_version") not in (1, 2) or not isinstance(packet.get("records"), list):
        raise DataError("Expected schema_version 1 or 2 and records array")
    collected, upper = collection_timing(packet)
    context = packet.get("context")
    if not isinstance(context, dict) or not context.get("selection"):
        raise DataError("Document the source selection in context.selection")
    coverage = packet.get("coverage", {})
    if set(coverage) != set(GAMES):
        raise DataError("Coverage must be explicit for both games")
    for game, cov in coverage.items():
        if cov.get("status") not in ("complete", "partial", "missing"):
            raise DataError(f"Invalid coverage status for {game}")
        if cov["status"] != "missing":
            start, end = parse_date(cov.get("start")), parse_date(cov.get("end"))
            if start > end or end > upper.astimezone(cfg.timezone).date():
                raise DataError("Invalid/future coverage range")
        required_text(cov.get("note"), "coverage_note")
    if source == "trends":
        if context.get("scale") != "joint_request" or not context.get("query_id"):
            raise DataError("Trends require one shared query scale; independently scaled series are not comparable")
        if set(context.get("terms", {})) != set(GAMES):
            raise DataError("Trends context must identify both query terms")


def clean_row(row: Any, packet: dict, cfg: Config) -> dict:
    if not isinstance(row, dict):
        raise DataError("record_must_be_object")
    source = packet["source"]
    game = required_text(row.get("game"), "game").lower()
    if game not in GAMES:
        raise DataError("unknown_game")
    result = {"game": game}
    collected, upper = collection_timing(packet)
    if source == "trends":
        start, end = parse_date(row.get("date")), parse_date(row.get("period_end"))
        if start > end or (end - start).days > 31:
            raise DataError("invalid_trend_interval")
        if type(row.get("is_partial")) is not bool:
            raise DataError("is_partial_boolean_required")
        if row["is_partial"]:
            raise DataError("partial_trend_interval")
        result.update(date=start.isoformat(), period_end=end.isoformat(),
                      interest=numeric(row.get("interest"), low=0, high=100),
                      query_id=packet["context"]["query_id"])
        key = f"{result['query_id']}:{game}:{start}:{end}"
        event = start
        if end < cfg.start or start > cfg.end:
            raise DataError("outside_study")
    else:
        field = "published_at" if source == "youtube" else "reviewed_at"
        timestamp = parse_timestamp(row.get(field))
        if timestamp > upper:
            raise DataError("event_after_collection" if collected else "event_after_collection_upper_bound")
        event = timestamp.astimezone(cfg.timezone).date()
        if event < cfg.start or event > cfg.end:
            raise DataError("outside_study")
        result.update({field: timestamp.isoformat(), "event_date": event.isoformat()})
        if source == "youtube":
            video_id = required_text(row.get("video_id"), "video_id")
            result.update(video_id=video_id,
                          channel_id=required_text(row.get("channel_id"), "channel_id"),
                          title=required_text(row.get("title"), "title"),
                          views=numeric(row.get("views"), low=0, integer=True),
                          likes=None if row.get("likes") is None else numeric(row["likes"], low=0, integer=True),
                          collected_at=collected.isoformat() if collected else None)
            if collected:
                key = f"{video_id}:{collected.isoformat()}"
            else:
                snapshot = packet["provenance"]["snapshot_id"]
                result.update(snapshot_id=snapshot, collection_time_status="unknown",
                              collected_no_later_than=upper.isoformat())
                key = f"{video_id}:unknown_snapshot:{snapshot}"
        else:
            review_id = required_text(row.get("review_id"), "review_id")
            app_id = required_text(row.get("app_id"), "app_id")
            if app_id != APPS[game]:
                raise DataError("app_game_mismatch")
            result.update(review_id=review_id, app_id=app_id,
                          rating=numeric(row.get("rating"), low=1, high=5, integer=True),
                          language=required_text(row.get("language"), "language"))
            key = f"{app_id}:{review_id}"
    cov = packet["coverage"][game]
    if cov["status"] == "missing":
        raise DataError("record_for_missing_source")
    if source == "trends":
        if start < parse_date(cov["start"]) or end > parse_date(cov["end"]):
            raise DataError("outside_declared_coverage")
    elif not parse_date(cov["start"]) <= event <= parse_date(cov["end"]):
        raise DataError("outside_declared_coverage")
    result["record_key"] = key
    return result


def clean_packet(packet: dict, source: str, cfg: Config) -> CleanBatch:
    validate_packet(packet, source, cfg)
    groups: dict[str, list[tuple[int, dict]]] = {}
    rejected: list[dict] = []
    for index, row in enumerate(packet["records"]):
        try:
            cleaned = clean_row(row, packet, cfg)
            groups.setdefault(cleaned["record_key"], []).append((index, cleaned))
        except DataError as exc:
            rejected.append({"row_index": index, "reason": str(exc)})
    accepted, duplicates = [], 0
    for items in groups.values():
        if len({digest(item[1]) for item in items}) != 1:
            rejected.extend({"row_index": i, "reason": "conflicting_duplicate_key"} for i, _ in items)
        else:
            accepted.append(items[0][1])
            duplicates += len(items) - 1
    # Reject overlapping intervals rather than silently double weighting days.
    if source == "trends":
        bad = set()
        for game in GAMES:
            intervals = sorted((r for r in accepted if r["game"] == game), key=lambda r: r["date"])
            for i, left in enumerate(intervals):
                for right in intervals[i + 1:]:
                    if right["date"] > left["period_end"]:
                        break
                    bad.update([left["record_key"], right["record_key"]])
        for key in bad:
            # The complete duplicate group is counted as rejected, not duplicated.
            items = groups[key]
            duplicates -= len(items) - 1
            rejected.extend({"row_index": i, "reason": "overlapping_trend_interval"} for i, _ in items)
        accepted = [r for r in accepted if r["record_key"] not in bad]
    return CleanBatch(source, packet, accepted, rejected, duplicates)
