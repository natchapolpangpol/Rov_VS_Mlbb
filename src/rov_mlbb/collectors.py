"""Bounded collectors. No key rotation, no bypass of rate limits, no invented coverage."""
from __future__ import annotations

import importlib
import os
import re
import ssl
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import requests

from .common import APPS, GAMES, SOURCES, DataError, digest, parse_date, parse_timestamp, read_json, utc_now, write_json


class CollectionError(RuntimeError):
    pass


class TransientError(CollectionError):
    pass


def retry_call(fn: Callable, *, attempts=3, delay=2.0, sleep=time.sleep, events=None):
    for attempt in range(1, attempts + 1):
        try:
            value = fn()
            if events is not None:
                events.append({"attempt": attempt, "status": "ok", "at": utc_now()})
            return value
        except TransientError:
            if events is not None:
                events.append({"attempt": attempt, "status": "transient_failure", "at": utc_now()})
            if attempt == attempts:
                raise
            sleep(delay * 2 ** (attempt - 1))


def http_json(session, url, params, events):
    def request():
        try:
            response = session.get(url, params=params, timeout=(10, 30))
        except requests.exceptions.SSLError:
            raise CollectionError("TLS certificate verification failed; check system trust store") from None
        except (requests.Timeout, requests.ConnectionError):
            raise TransientError("Network timeout/connection failure") from None
        if response.status_code in (429, 500, 502, 503, 504):
            raise TransientError(f"Temporary HTTP {response.status_code}")
        if response.status_code != 200:
            # Never include response.url or a requests exception: URL contains API key.
            raise CollectionError(f"Request rejected: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise CollectionError("Source returned non-JSON response") from None
    return retry_call(request, events=events)


def classify_title(title: str) -> str | None:
    rov = bool(re.search(r"(?<![a-z0-9])rov(?![a-z0-9])|อาร์โอวี", title, re.I))
    mlbb = bool(re.search(r"(?<![a-z0-9])mlbb(?![a-z0-9])|mobile\s+legends", title, re.I))
    return "rov" if rov and not mlbb else "mlbb" if mlbb and not rov else None


def cov(start, end, status, note):
    return {"start": str(start), "end": str(end), "status": status, "note": note}


def envelope(source, config, context, records, coverage, upstream):
    return {"schema_version": 1, "source": source, "data_kind": "real",
            "collected_at": utc_now(), "context": context, "records": records,
            "coverage": coverage, "upstream": upstream}


def collect_youtube(config, events):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise CollectionError("YOUTUBE_API_KEY is not set; configure it locally, not in source code")
    channels = config.get("youtube", {}).get("channels", [])
    if not channels:
        raise DataError("At least one explicitly selected YouTube channel is required")
    start, end = parse_date(config["study_start"]), parse_date(config["study_end"])
    zone = ZoneInfo(config.get("timezone", "Asia/Bangkok"))
    limit = int(config.get("youtube", {}).get("max_pages_per_channel", 10))
    session = requests.Session()
    base = "https://www.googleapis.com/youtube/v3/"
    pages, ids, channel_coverage = [], set(), {}
    try:
        for channel in channels:
            response = http_json(session, base + "channels", {"part": "contentDetails", "id": channel, "key": key}, events)
            pages.append({"endpoint": "channels", "response": response})
            if not response.get("items"):
                raise CollectionError(f"Selected channel unavailable: {channel}")
            playlist = response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            token, complete = None, False
            for _ in range(limit):
                params = {"part": "contentDetails", "playlistId": playlist, "maxResults": 50, "key": key}
                if token:
                    params["pageToken"] = token
                response = http_json(session, base + "playlistItems", params, events)
                pages.append({"endpoint": "playlistItems", "channel_id": channel, "response": response})
                dates = []
                for item in response.get("items", []):
                    detail = item.get("contentDetails", {})
                    if not detail.get("videoPublishedAt"):
                        continue
                    published = parse_timestamp(detail["videoPublishedAt"]).astimezone(zone).date()
                    dates.append(published)
                    if start <= published <= end:
                        ids.add(detail["videoId"])
                token = response.get("nextPageToken")
                # An exhausted playlist is certain. Early-stop relies on upload ordering and is recorded.
                if not token or (dates and all(d < start for d in dates)):
                    complete = True
                    break
                time.sleep(0.25)
            channel_coverage[channel] = complete
        rows, excluded, unavailable = [], 0, []
        ordered = sorted(ids)
        for offset in range(0, len(ordered), 50):
            chunk = ordered[offset:offset + 50]
            response = http_json(session, base + "videos", {"part": "snippet,statistics", "id": ",".join(chunk), "key": key}, events)
            pages.append({"endpoint": "videos", "response": response})
            found = set()
            for item in response.get("items", []):
                found.add(item["id"])
                snippet, stats = item["snippet"], item.get("statistics", {})
                game = classify_title(snippet.get("title", ""))
                if game is None:
                    excluded += 1
                    continue
                rows.append({"game": game, "video_id": item["id"], "channel_id": snippet["channelId"],
                             "title": snippet["title"], "published_at": snippet["publishedAt"],
                             "views": stats.get("viewCount"), "likes": stats.get("likeCount")})
            unavailable.extend(set(chunk) - found)
        status = "complete" if all(channel_coverage.values()) and not unavailable else "partial"
        context = {"selection": "Selected channel uploads, case-insensitive title rules; excludes ambiguous/unmatched titles",
                   "channels": channels, "channel_pagination_complete": channel_coverage,
                   "excluded_by_title": excluded, "unavailable_video_ids": sorted(unavailable),
                   "max_pages_per_channel": limit, "timestamp_semantics": "Cumulative views at collection, grouped by publication date",
                   "country_scope": "Thai-focused selected channels; viewer nationality is not known"}
        note = "Coverage refers to selected channels and classification rules only, not all YouTube or all Thai players"
        return envelope("youtube", config, context, rows, {g: cov(start, end, status, note) for g in GAMES}, pages)
    finally:
        session.close()


def collect_trends(config, events):
    from pytrends.request import TrendReq
    start, end = parse_date(config["study_start"]), parse_date(config["study_end"])
    terms = config.get("trends", {}).get("terms", {"rov": "rov", "mlbb": "mlbb"})
    if set(terms) != set(GAMES) or len(set(terms.values())) != 2:
        raise DataError("Trends requires two distinct query terms mapped to rov and mlbb")
    query = {"terms": terms, "geo": "TH", "timeframe": f"{start} {end}", "category": 0, "gprop": ""}
    def fetch():
        try:
            client = TrendReq(hl="en-US", tz=-420, timeout=(10, 30), retries=0)
            client.build_payload([terms[g] for g in GAMES], timeframe=query["timeframe"], geo="TH")
            return client.interest_over_time()
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(exc, requests.exceptions.SSLError):
                raise CollectionError("Trends TLS verification failed; use the CLI with system trust store") from None
            if isinstance(exc, (requests.Timeout, requests.ConnectionError)) or status in (429, 500, 502, 503, 504):
                raise TransientError(f"Trends temporary failure ({status or 'network'})") from None
            raise CollectionError(f"Trends collection failed ({type(exc).__name__}); manual export is supported") from None
    frame = retry_call(fetch, delay=5, attempts=2, events=events)
    if frame.empty:
        raise CollectionError("Trends returned an empty result; not interpreted as zero interest")
    dates = sorted(ts.date() for ts in frame.index)
    if len(dates) < 2:
        raise CollectionError("Cannot infer Trends interval from a single point; use a longer range")
    differences = {(b - a).days for a, b in zip(dates, dates[1:])}
    if differences <= {1}:
        interval = "daily"
    elif differences <= {7}:
        interval = "weekly"
    elif all(28 <= n <= 31 for n in differences):
        interval = "monthly"
    else:
        raise CollectionError("Unexpected Trends sampling interval")
    rows = []
    for timestamp, record in frame.iterrows():
        day = timestamp.date()
        if interval == "monthly":
            import calendar
            finish = day.replace(day=calendar.monthrange(day.year, day.month)[1])
        else:
            finish = day + timedelta(days=6 if interval == "weekly" else 0)
        partial = bool(record.get("isPartial", False)) or finish > end
        for game in GAMES:
            rows.append({"game": game, "date": str(day), "period_end": str(finish),
                         "interest": float(record[terms[game]]), "is_partial": partial})
    context = {**query, "query_id": digest(query), "scale": "joint_request", "interval": interval,
               "selection": "One Google Trends request comparing both terms in TH; no stitching across requests"}
    coverage = {g: cov(min(r["date"] for r in rows), max(r["period_end"] for r in rows), "partial" if any(r["is_partial"] for r in rows) else "complete",
                       "Google sampled search interest, normalized jointly within this query window") for g in GAMES}
    upstream = frame.reset_index().to_json(orient="records", date_format="iso")
    import json
    return envelope("trends", config, context, rows, coverage, json.loads(upstream))


def collect_playstore(config, events):
    # The upstream package changes the global urllib SSL default on import.
    # Restore it immediately and use a verified, time-bounded transport here.
    original_context = ssl._create_default_https_context
    try:
        from google_play_scraper import Sort, reviews
        transport = importlib.import_module("google_play_scraper.utils.request")
        review_module = importlib.import_module("google_play_scraper.features.reviews")
    finally:
        ssl._create_default_https_context = original_context
    original_urlopen = transport._urlopen
    original_fetch = review_module._fetch_review_items
    upstream_errors = []
    def checked_fetch(*args, **kwargs):
        try:
            return original_fetch(*args, **kwargs)
        except Exception as exc:
            upstream_errors.append(exc)
            raise
    # reviews() catches all exceptions and returns an empty list. Preserve evidence
    # of these failures so a network/parser error can never become a known zero.
    review_module._fetch_review_items = checked_fetch
    session = requests.Session()
    def safe_urlopen(obj):
        url = obj if isinstance(obj, str) else obj.full_url
        try:
            response = session.request("GET" if isinstance(obj, str) else obj.get_method(), url,
                                       data=None if isinstance(obj, str) else obj.data,
                                       headers={} if isinstance(obj, str) else dict(obj.header_items()),
                                       timeout=(10, 30))
        except requests.exceptions.SSLError:
            raise CollectionError("Play Store TLS verification failed; use the CLI with system trust store") from None
        except (requests.Timeout, requests.ConnectionError):
            raise TransientError("Play Store network failure") from None
        if response.status_code in (429, 500, 502, 503, 504):
            raise TransientError(f"Play Store HTTP {response.status_code}")
        if response.status_code != 200:
            raise CollectionError(f"Play Store HTTP {response.status_code}")
        return response.text
    transport._urlopen = safe_urlopen
    start, end = parse_date(config["study_start"]), parse_date(config["study_end"])
    zone = ZoneInfo(config.get("timezone", "Asia/Bangkok"))
    settings = config.get("playstore", {})
    language, limit = settings.get("language", "th"), int(settings.get("max_pages_per_game", 5))
    rows, upstream, coverage = [], [], {}
    try:
        for game in GAMES:
            token, complete = None, False
            for page in range(limit):
                def fetch():
                    upstream_errors.clear()
                    page_result = reviews(APPS[game], lang=language, country="th", sort=Sort.NEWEST,
                                          count=200, continuation_token=token)
                    if upstream_errors:
                        error = upstream_errors[-1]
                        if isinstance(error, CollectionError):
                            raise error
                        raise CollectionError(f"Play Store source/parser failed ({type(error).__name__}); not an empty population") from None
                    if page == 0 and not page_result[0]:
                        raise CollectionError("Unverified empty first review page; cannot declare zero reviews")
                    return page_result
                result, next_token = retry_call(fetch, attempts=2, delay=5, events=events)
                serialized = []
                dates = []
                for item in result:
                    timestamp = item.get("at")
                    if timestamp is None:
                        raise CollectionError("Review without timestamp; cannot establish coverage")
                    # Upstream returns naive timestamps via fromtimestamp() in host timezone.
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.astimezone(timezone.utc)
                    else:
                        timestamp = timestamp.astimezone(timezone.utc)
                    day = timestamp.astimezone(zone).date()
                    dates.append(day)
                    # Minimal source fields: omit usernames, avatars and review body (unused here).
                    serialized.append({"reviewId": item.get("reviewId"), "at": timestamp.isoformat(),
                                       "score": item.get("score"), "appVersion": item.get("appVersion")})
                    if start <= day <= end:
                        rows.append({"game": game, "app_id": APPS[game], "review_id": item.get("reviewId"),
                                     "reviewed_at": timestamp.isoformat(), "rating": item.get("score"), "language": language})
                upstream.append({"game": game, "page": page + 1, "records": serialized})
                token_value = getattr(next_token, "token", None)
                if not token_value or (dates and min(dates) < start):
                    complete = True
                    break
                token = next_token
                time.sleep(1)
            coverage[game] = cov(start, end, "complete" if complete else "partial",
                                 "Accessible newest reviews for TH storefront and selected request language; not all players. Capped pagination is partial.")
        context = {"selection": "Accessible newest Google Play reviews in TH storefront", "language": language,
                   "sort": "NEWEST", "max_pages_per_game": limit,
                   "language_caveat": "Request language is not verified review language or author nationality",
                   "raw_projection": "Only reviewId, at, score, appVersion retained; unused personal/profile fields omitted"}
        return envelope("playstore", config, context, rows, coverage, upstream)
    finally:
        transport._urlopen = original_urlopen
        review_module._fetch_review_items = original_fetch
        session.close()


COLLECTORS = {"trends": collect_trends, "youtube": collect_youtube, "playstore": collect_playstore}


def collect(config_path: str | Path, sources: list[str] | None = None) -> dict:
    config_path = Path(config_path).resolve()
    config = read_json(config_path)
    start, end = parse_date(config["study_start"]), parse_date(config["study_end"])
    today = datetime.now(ZoneInfo(config.get("timezone", "Asia/Bangkok"))).date()
    if start > end or end >= today:
        raise DataError("Collection window must end before today and start <= end")
    root = (config_path.parent / config.get("project_root", "..")).resolve()
    output = root / "data/imports" / uuid.uuid4().hex
    output.mkdir(parents=True, exist_ok=False)
    inputs, statuses = {}, {}
    for source in sources or list(SOURCES):
        if source not in COLLECTORS:
            raise DataError(f"Unknown collector {source}")
        events = []
        try:
            packet = COLLECTORS[source](config, events)
            target = output / f"{source}.json"
            write_json(target, packet)
            inputs[source] = str(target)
            statuses[source] = {"status": "collected", "rows": len(packet["records"]), "coverage": packet["coverage"], "events": events}
        except Exception as exc:
            # Safe exception messages only; unknown upstream errors might contain response URLs.
            detail = str(exc) if isinstance(exc, (DataError, CollectionError)) else type(exc).__name__
            statuses[source] = {"status": "failed", "error": detail, "events": events}
        write_json(output / "collection_status.json", statuses)
    pipeline_config = {"project_root": str(root), "data_kind": "real", "artifact_root": "artifacts",
                       "study_start": str(start), "study_end": str(end),
                       "timezone": config.get("timezone", "Asia/Bangkok"),
                       "max_rejected_fraction": 0.05, "inputs": inputs}
    write_json(output / "pipeline_config.json", pipeline_config)
    return {"directory": str(output), "pipeline_config": str(output / "pipeline_config.json"), "sources": statuses}
