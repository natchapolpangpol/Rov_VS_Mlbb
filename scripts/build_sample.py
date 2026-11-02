"""Build deterministic synthetic input. Never downloads or impersonates real data."""
from __future__ import annotations

import calendar
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    sample = ROOT / "data" / "sample"
    sample.mkdir(parents=True, exist_ok=True)
    coverage = {g: {"status": "complete", "start": "2025-01-01", "end": "2025-03-31",
                    "note": "Complete only within this deterministic synthetic fixture"} for g in ("rov", "mlbb")}
    contexts = {
        "trends": {"selection": "SYNTHETIC fixture, not Google data", "scale": "joint_request",
                   "query_id": "sample-joint-2025-q1", "terms": {"rov": "rov", "mlbb": "mlbb"},
                   "geo": "TH"},
        "youtube": {"selection": "SYNTHETIC fixture channels; not actual YouTube videos"},
        "playstore": {"selection": "SYNTHETIC fixture reviews; not actual Play Store reviews"},
    }
    packets = {s: {"schema_version": 1, "source": s, "data_kind": "sample",
                   "collected_at": "2025-04-02T00:00:00Z", "context": context,
                   "coverage": coverage, "records": []} for s, context in contexts.items()}
    apps = {"rov": "com.garena.game.kgth", "mlbb": "com.mobile.legends"}
    for game in ("rov", "mlbb"):
        for month in range(1, 4):
            last = calendar.monthrange(2025, month)[1]
            packets["trends"]["records"].append({"game": game, "date": f"2025-{month:02d}-01",
                "period_end": f"2025-{month:02d}-{last}", "interest": (70 - month * 10) if game == "rov" else (10 + month * 10), "is_partial": False})
            for i, rating in enumerate([4, 2] if game == "rov" else [5, 3]):
                packets["playstore"]["records"].append({"game": game, "app_id": apps[game],
                    "review_id": f"sample-{game}-{month}-{i}", "reviewed_at": f"2025-{month:02d}-0{i+2}T08:00:00Z",
                    "rating": rating, "language": "th"})
            if game == "mlbb" and month == 3:
                continue  # a known zero, not missing coverage
            for i, views in enumerate([100 * month, 300 * month]):
                packets["youtube"]["records"].append({"game": game,
                    "video_id": f"sample-{game}-{month}-{i}", "channel_id": f"sample-{game}-channel",
                    "title": f"SYNTHETIC {game.upper()} video {month}/{i}",
                    "published_at": f"2025-{month:02d}-0{i+2}T08:00:00Z", "views": views, "likes": views // 10})
    packets["playstore"]["records"].append(dict(packets["playstore"]["records"][0]))
    for source, packet in packets.items():
        (sample / f"{source}.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Wrote 3 SYNTHETIC packets to data/sample (no network)")


if __name__ == "__main__":
    main()
