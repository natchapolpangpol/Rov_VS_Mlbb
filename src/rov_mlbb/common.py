from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SOURCES = ("trends", "youtube", "playstore")
GAMES = ("rov", "mlbb")
APPS = {"rov": "com.garena.game.kgth", "mlbb": "com.mobile.legends"}


class DataError(ValueError):
    """An invalid input or violated data contract (not retryable)."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(value) + "\n", encoding="utf-8")


def parse_date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise DataError("invalid_iso_date") from exc


def parse_timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("Timezone required")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise DataError("invalid_or_timezone_missing_timestamp") from exc


def numeric(value: Any, *, low: float, high: float | None = None, integer=False) -> float | int:
    if isinstance(value, bool) or value is None:
        raise DataError("invalid_number")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise DataError("invalid_number") from exc
    if not math.isfinite(result) or result < low or (high is not None and result > high):
        raise DataError("number_out_of_range")
    if integer and not result.is_integer():
        raise DataError("integer_required")
    return int(result) if integer else result


def required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataError(f"missing_{field}")
    return value.strip()
