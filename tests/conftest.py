from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scenario(tmp_path):
    cfg = json.loads((ROOT / "config/sample.json").read_text())
    cfg["project_root"] = str(tmp_path)
    for source in cfg["inputs"]:
        path = tmp_path / f"{source}.json"
        path.write_text((ROOT / "data/sample" / f"{source}.json").read_text(encoding="utf-8"), encoding="utf-8")
        cfg["inputs"][source] = path.name
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def mutate_packet(config_path, source, change):
    cfg = json.loads(config_path.read_text())
    path = config_path.parent / cfg["inputs"][source]
    packet = json.loads(path.read_text(encoding="utf-8"))
    change(packet)
    path.write_text(json.dumps(packet), encoding="utf-8")
