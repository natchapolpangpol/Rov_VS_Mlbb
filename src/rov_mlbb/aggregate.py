from __future__ import annotations

import calendar
from datetime import date, timedelta
from statistics import mean, median

import pandas as pd

from .common import GAMES, SOURCES, parse_date
from .config import Config
from .quality import CleanBatch


def months_between(start: date, end: date):
    current = start.replace(day=1)
    while current <= end:
        last = current.replace(day=calendar.monthrange(current.year, current.month)[1])
        yield current, last
        current = last + timedelta(days=1)


def coverage_status(batch: CleanBatch | None, game: str, first: date, last: date) -> str:
    if batch is None:
        return "missing"
    cov = batch.packet["coverage"][game]
    if cov["status"] == "missing":
        return "missing"
    if parse_date(cov["end"]) < first or parse_date(cov["start"]) > last:
        return "missing"
    if cov["status"] != "complete" or parse_date(cov["start"]) > first or parse_date(cov["end"]) < last:
        return "partial"
    if batch.rejected:
        return "filtered"
    return "complete"


def summarize(batches: dict[str, CleanBatch], cfg: Config, run_id: str) -> pd.DataFrame:
    rows = []
    for first, last in months_between(cfg.start, cfg.end):
        lo, hi = max(first, cfg.start), min(last, cfg.end)
        for game in GAMES:
            row = {"run_id": run_id, "data_kind": cfg.mode, "month": first.strftime("%Y-%m"),
                   "game": game, "study_days_in_month": (hi - lo).days + 1}
            for source in SOURCES:
                batch = batches.get(source)
                status = coverage_status(batch, game, first, last)
                row[f"{source}_coverage"] = status
                row[f"{source}_collected_at"] = batch.packet["collected_at"] if batch else None
                provenance = batch.packet.get("provenance", {}) if batch else {}
                row[f"{source}_collection_time_status"] = ("unknown" if batch.packet["collected_at"] is None else "known") if batch else "missing"
                row[f"{source}_collected_no_later_than"] = provenance.get("collected_no_later_than")
                row[f"{source}_exported_at"] = provenance.get("exported_at")
                records = [r for r in batch.records if r["game"] == game] if batch else []
                if source == "trends":
                    days, weighted = 0, 0.0
                    for record in records:
                        start = max(lo, parse_date(record["date"]))
                        end = min(hi, parse_date(record["period_end"]))
                        n = max(0, (end - start).days + 1)
                        weighted += n * record["interest"]
                        days += n
                    row["search_interest"] = weighted / days if days else None
                    row["trends_observed_days"] = days
                    row["trends_query_id"] = batch.packet["context"]["query_id"] if batch else None
                    if status == "complete" and days != (last - first).days + 1:
                        row["trends_coverage"] = "partial"
                elif source == "youtube":
                    selected = [r for r in records if lo <= parse_date(r["event_date"]) <= hi]
                    row["published_video_count"] = len(selected) if selected or status == "complete" else None
                    row["median_views_at_collection"] = median(r["views"] for r in selected) if selected else None
                    row["sampled_channel_count"] = len({r["channel_id"] for r in selected}) if selected or status == "complete" else None
                else:
                    selected = [r for r in records if lo <= parse_date(r["event_date"]) <= hi]
                    row["review_count"] = len(selected) if selected or status == "complete" else None
                    row["mean_review_rating"] = mean(r["rating"] for r in selected) if selected else None
            row["all_sources_complete"] = all(row[f"{s}_coverage"] == "complete" for s in SOURCES)
            rows.append(row)
    result = pd.DataFrame(rows)
    if result.duplicated(["month", "game"]).any():
        raise ValueError("Summary grain violation")
    return result
