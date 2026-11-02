from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .common import DataError, SOURCES, parse_date, read_json


@dataclass(frozen=True)
class Config:
    path: Path
    project: Path
    raw: dict[str, Any]

    @property
    def mode(self) -> str:
        return self.raw["data_kind"]

    @property
    def output(self) -> Path:
        return (self.project / self.raw.get("artifact_root", "artifacts") / self.mode).resolve()

    @property
    def start(self):
        return parse_date(self.raw["study_start"])

    @property
    def end(self):
        return parse_date(self.raw["study_end"])

    @property
    def timezone(self):
        return ZoneInfo(self.raw.get("timezone", "Asia/Bangkok"))

    @property
    def reject_limit(self):
        return float(self.raw.get("max_rejected_fraction", 0.05))

    def input_path(self, source: str) -> Path | None:
        value = self.raw.get("inputs", {}).get(source)
        return (self.project / value).resolve() if value else None


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    raw = read_json(path)
    cfg = Config(path, (path.parent / raw.get("project_root", "..")).resolve(), raw)
    if cfg.mode not in ("sample", "real"):
        raise DataError("data_kind must be sample or real")
    if cfg.start > cfg.end:
        raise DataError("study_start must not exceed study_end")
    if not 0 <= cfg.reject_limit <= 1:
        raise DataError("max_rejected_fraction must be in [0,1]")
    if set(raw.get("inputs", {})) - set(SOURCES):
        raise DataError("Unknown input source")
    _ = cfg.timezone
    return cfg
