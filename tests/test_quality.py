import json
from pathlib import Path

import pytest

from rov_mlbb.aggregate import summarize
from rov_mlbb.common import DataError
from rov_mlbb.config import load_config
from rov_mlbb.quality import clean_packet


def packet(scenario, source):
    return json.loads((scenario.parent / f"{source}.json").read_text())


@pytest.mark.parametrize("value", [None, "oops", -1, 6, 2.5, True, float("nan")])
def test_invalid_rating_quarantined_with_accounting(scenario, value):
    p = packet(scenario, "playstore")
    p["records"] = p["records"][:2]
    p["records"][0]["rating"] = value
    batch = clean_packet(p, "playstore", load_config(scenario))
    report = batch.report()
    assert report["accepted_rows"] == 1 and report["rejected_rows"] == 1
    assert sum(report[x] for x in ("accepted_rows", "rejected_rows", "duplicate_rows")) == report["input_rows"]


def test_timezone_month_boundary(scenario):
    p = packet(scenario, "youtube")
    p["records"] = [{**p["records"][0], "published_at": "2025-01-31T18:00:00Z"}]
    batch = clean_packet(p, "youtube", load_config(scenario))
    assert batch.records[0]["event_date"] == "2025-02-01"


def test_trends_interval_weighting_and_partial_coverage(scenario):
    p = packet(scenario, "trends")
    p["records"] = [
        {"game": "rov", "date": "2025-01-01", "period_end": "2025-01-15", "interest": 20, "is_partial": False},
        {"game": "rov", "date": "2025-01-16", "period_end": "2025-02-05", "interest": 40, "is_partial": False},
    ]
    cfg = load_config(scenario)
    batch = clean_packet(p, "trends", cfg)
    data = summarize({"trends": batch}, cfg, "test")
    jan = data[(data.game == "rov") & (data.month == "2025-01")].iloc[0]
    feb = data[(data.game == "rov") & (data.month == "2025-02")].iloc[0]
    assert jan.search_interest == pytest.approx((15 * 20 + 16 * 40) / 31)
    assert jan.trends_observed_days == 31 and jan.trends_coverage == "complete"
    assert feb.trends_observed_days == 5 and feb.trends_coverage == "partial"


def test_overlapping_trends_intervals_rejected(scenario):
    p = packet(scenario, "trends")
    p["records"].append({**p["records"][0], "date": "2025-01-02"})
    batch = clean_packet(p, "trends", load_config(scenario))
    assert batch.report()["reasons"]["overlapping_trend_interval"] == 2
    assert len(batch.records) + len(batch.rejected) + batch.duplicates == len(p["records"])


def test_independently_scaled_trends_not_accepted(scenario):
    p = packet(scenario, "trends")
    p["context"]["scale"] = "per_game"
    with pytest.raises(DataError, match="shared query"):
        clean_packet(p, "trends", load_config(scenario))
