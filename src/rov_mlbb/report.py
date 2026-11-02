from __future__ import annotations

import json
import calendar
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .common import DataError, SOURCES, read_json


def load_run(run_dir: str | Path):
    run_dir = Path(run_dir).resolve()
    manifest = read_json(run_dir / "manifest.json")
    if manifest["status"] not in ("complete", "partial"):
        raise DataError("Cannot report a failed or unfinished run")
    data = pd.read_parquet(run_dir / "summary/monthly_game_metrics.parquet")
    if set(data["run_id"]) != {manifest["run_id"]} or set(data["data_kind"]) != {manifest["data_kind"]}:
        raise DataError("Summary and manifest provenance mismatch")
    return manifest, data


def select_metrics(frame: pd.DataFrame, game="all", start=None, end=None):
    """Filter a single validated run without imputing missing observations."""
    if game not in ("all", "rov", "mlbb"):
        raise DataError("Choose all, rov, or mlbb")
    start = start or frame["month"].min()
    end = end or frame["month"].max()
    if start > end:
        raise DataError("Start month must not follow end month")
    selected = frame.loc[frame["month"].between(start, end)]
    if game != "all":
        selected = selected.loc[selected["game"] == game]
    if selected.empty:
        raise DataError("No rows match the selected game and months")
    return selected.sort_values(["month", "game"]).copy()


def plot_metrics(manifest: dict, frame: pd.DataFrame):
    """Shared plot for exported reports and notebook filters; caller closes figure."""
    label = "SYNTHETIC DEMO - NOT RESEARCH FINDINGS" if manifest["data_kind"] == "sample" else "REAL COLLECTED DATA"
    unknown_youtube_time = manifest.get("sources", {}).get("youtube", {}).get("collection_time_status") == "unknown"
    if unknown_youtube_time:
        label += "\nYouTube snapshot time not recorded in the source archive"
    columns = [("search_interest", "Search interest (joint query; day-weighted)"),
               ("published_video_count", "Published videos in selected channels"),
               ("mean_review_rating", "Mean rating among collected reviews"),
               ("review_count", "Collected reviews"),
               ("median_views_at_collection", "Median archived views (snapshot time unknown)" if unknown_youtube_time else "Median cumulative views at collection")]
    fig, axes = plt.subplots(3, 2, figsize=(13, 11))
    colors = {"rov": "#087e8b", "mlbb": "#bf4a22"}
    months = sorted(frame['month'].unique())
    month_positions = {month: i for i, month in enumerate(months)}
    for ax, (column, title) in zip(axes.flat, columns):
        source = ('trends' if column == 'search_interest' else
                  'playstore' if column in ('review_count', 'mean_review_rating') else 'youtube')
        for game, subset in frame.groupby("game", sort=True):
            values = pd.to_numeric(subset[column], errors="coerce")
            coverage = manifest.get('sources', {}).get(source, {}).get('coverage', {}).get(game, {})
            edges = []
            for row in subset.itertuples():
                year, month = map(int, row.month.split('-'))
                first = row.month + '-01'
                last = row.month + f'-{calendar.monthrange(year, month)[1]:02d}'
                edges.append(row.study_days_in_month < calendar.monthrange(year, month)[1]
                             or coverage.get('start', first) > first or coverage.get('end', last) < last)
            edge_mask = pd.Series(edges, index=subset.index)
            # Isolated crosses keep truncated boundary months from looking like a trend collapse.
            positions = subset['month'].map(month_positions)
            ax.plot(positions, values.mask(edge_mask), marker="o", linewidth=2,
                    label=game.upper(), color=colors[game])
            ax.scatter(positions.loc[edge_mask], values.loc[edge_mask], marker='x',
                       color=colors[game], s=50, zorder=3)
        ax.set_title(title, fontsize=11)
        ax.set_xticks(range(len(months)), months)
        ax.tick_params(axis="x", labelrotation=45, labelsize=8)
        ax.grid(axis="y", alpha=0.25)
        ax.legend(frameon=False)
        if column == "mean_review_rating":
            ax.set_ylim(1, 5)
        elif column == "search_interest":
            ax.set_ylim(0, 100)
        else:
            ax.set_ylim(bottom=0)
        if frame[column].isna().all():
            ax.set_yticks([])
            ax.get_legend().remove()
            ax.text(0.5, 0.5, "No observed data", transform=ax.transAxes,
                    ha="center", color="#666666")
    coverage_ax = axes.flat[-1]
    coverage_ax.axis("off")
    coverage_ax.set_title("Coverage within the declared sampling frame", fontsize=11)
    coverage_lines = []
    for source in SOURCES:
        counts = frame[f"{source}_coverage"].value_counts().sort_index()
        coverage_lines.append(source.upper() + ": " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    coverage_ax.text(0.03, 0.85, "\n\n".join(coverage_lines)
                     + "\n\nCounts refer to game-month rows.\nPartial observations are shown; gaps stay missing."
                     + "\nCrosses: truncated boundary months (not joined)."
                     + "\nViews are grouped by video publication month."
                     + "\nThey are NOT views earned during that month.",
                     va="top", fontsize=10, transform=coverage_ax.transAxes)
    fig.suptitle(f"RoV vs MLBB | {label}", fontsize=14, weight="bold")
    fig.text(0.5, 0.015, f"Run {manifest['run_id'][:12]} | status: {manifest['status']} | gaps are not zeros; see coverage table", ha="center", fontsize=10)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    return fig


def create_report(run_dir: str | Path) -> Path:
    run_dir = Path(run_dir).resolve()
    manifest, frame = load_run(run_dir)
    destination = run_dir / "report"
    destination.mkdir(exist_ok=True)
    label = "SYNTHETIC DEMO - NOT RESEARCH FINDINGS" if manifest["data_kind"] == "sample" else "REAL COLLECTED DATA"
    fig = plot_metrics(manifest, frame)
    fig.savefig(destination / "overview.png", dpi=160)
    plt.close(fig)
    quality_rows = []
    for source in SOURCES:
        row = manifest["sources"].get(source, {})
        quality_rows.append(f"| {source} | {row.get('input_rows', '-')} | {row.get('accepted_rows', '-')} | {row.get('duplicate_rows', '-')} | {row.get('rejected_rows', '-')} |")
    coverage_rows = [f"| {r.month} | {r.game} | {r.trends_coverage} | {r.youtube_coverage} | {r.playstore_coverage} |" for r in frame.itertuples()]
    timing_rows = []
    for source in SOURCES:
        info = manifest["sources"].get(source, {})
        provenance = info.get("provenance", {})
        timing_rows.append(f"| {source} | {info.get('collected_at') or 'unknown / unavailable'} | {provenance.get('collected_no_later_than', '-')} | {provenance.get('exported_at', '-')} |")
    # Describe only observations actually present, never invent business conclusions.
    findings = []
    if manifest["data_kind"] == "sample":
        findings.append("This is a software demonstration only. All values are synthetic and must not be presented as game popularity findings.")
    else:
        for game, subset in frame.groupby("game"):
            total = subset["review_count"].sum(min_count=1)
            if pd.notna(total):
                findings.append(f"{game.upper()}: {int(total):,} reviews observed in the selected time window. This is a collected sample, not a count of players.")
        findings.append("Cross-source conclusions require checking coverage and query scope before comparison. This report does not infer migration or causality.")
    text = f"""# RoV vs MLBB - run report

**{label}**

- Run: `{manifest['run_id']}`
- Status: **{manifest['status']}**
- Processing finished: `{manifest['finished_at']}` (collection times are stored per source in the dataset)
- Full metrics: [CSV](../summary/monthly_game_metrics.csv), [Parquet](../summary/monthly_game_metrics.parquet)
- Provenance and quality: [manifest](../manifest.json)

![Overview](overview.png)

## Observations

""" + "\n\n".join(findings) + """

## Source timing

An upper bound is not an exact collection time. Export time is the time the archive was copied, not the time views or ratings were originally fetched.
Archived YouTube values with unknown collection time are descriptive snapshot values; do not treat them as current views or age-adjusted performance.

| Source | Original collection time | Collected no later than (bound only) | Archive exported at |
|---|---|---|---|
""" + "\n".join(timing_rows) + """

## Quality accounting

| Source | Input rows | Accepted | Exact duplicates | Rejected |
|---|---:|---:|---:|---:|
""" + "\n".join(quality_rows) + """

## Monthly coverage

`complete` means complete within the declared sampling frame, not the entire population.
`filtered` indicates rejected records; `partial` indicates incomplete time/pagination/interval coverage.
Missing/unknown counts remain null; zero requires documented complete coverage with no matching records.

| Month | Game | Trends | YouTube | Play Store |
|---|---|---|---|---|
""" + "\n".join(coverage_rows) + """

## Interpretation limits

- Search interest is a normalized index within one joint query, not search volume or player count.
- Weekly Trends values are weighted by overlapping days when summarized by month; this is an approximation, not recovered daily observations.
- Video views are cumulative at collection, grouped by publication month. Older videos have had more time to accumulate views.
- Reviews represent the accessible storefront/language request and filtering rules. Request language does not establish nationality.
- A before/after comparison alone does not identify the cause of a change.
"""
    report = destination / "report.md"
    report.write_text(text, encoding="utf-8")
    return report
