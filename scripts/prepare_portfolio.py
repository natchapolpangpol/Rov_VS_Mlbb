"""Copy an explicit source/aggregate allowlist; never include team raw data or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = 'artifacts/real/runs/fd1a7d895cb3477ea72591e4199e5e38'
SCHEDULE = 'artifacts/verification/schedule-9c352aea53f046059815c81cd59ca14f/evidence.json'


def prepare(destination):
    destination = Path(destination).resolve()
    if destination == ROOT or not destination.is_relative_to(ROOT):
        raise ValueError('Choose a separate delivery directory within the workspace')
    files = {ROOT / name for name in ('README.md', 'pyproject.toml', 'requirements-lock.txt', '.gitignore', '.gitattributes')}
    for pattern in ('src/rov_mlbb/*.py', 'tests/*.py', 'scripts/*.py', 'scripts/*.cmd',
                    'config/*.json', 'data/sample/*.json', 'docs/*.md', 'notebooks/analysis.ipynb'):
        files.update(ROOT.glob(pattern))
    for name in ('manifest.json', 'summary/monthly_game_metrics.csv', 'summary/monthly_game_metrics.parquet',
                 'report/report.md', 'report/overview.png', 'report/historical_analysis.json',
                 'report/matched_windows.csv', 'report/timezone_sensitivity.csv'):
        files.add(ROOT / HISTORICAL / name)
    for name in (SCHEDULE, 'artifacts/verification/final-tests.xml',
                 'artifacts/verification/final_environment.json',
                 'artifacts/verification/firestore_notebook_reconciliation.json',
                 'artifacts/verification/historical_rerun.json',
                 'artifacts/real/historical_analysis.executed.ipynb'):
        files.add(ROOT / name)
    missing = [p.relative_to(ROOT).as_posix() for p in files if not p.is_file()]
    if missing:
        raise FileNotFoundError('Missing delivery files: ' + ', '.join(missing))
    patterns = [re.compile(p) for p in (
        r'AIza[0-9A-Za-z_-]{30,}', r'-----BEGIN (?:RSA )?PRIVATE KEY-----',
        r'mongodb(?:\+srv)?://[^\s"<>]+:[^\s"<>]+@',
        r'gh[pousr]_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{30,}',
        r'ya29\.[A-Za-z0-9_-]{30,}')]
    for path in files:
        if path.suffix in ('.png', '.parquet'):
            continue
        content = path.read_text(encoding='utf-8-sig')
        if any(pattern.search(content) for pattern in patterns):
            raise ValueError('Credential-like pattern found in ' + path.relative_to(ROOT).as_posix())
    destination.mkdir(parents=True, exist_ok=True)
    inventory = []
    for path in sorted(files):
        relative = path.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        inventory.append(dict(path=relative.as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    manifest = dict(files=inventory, excluded=['data/imports', '.venv', '.tools', '.prefect',
                                               'original notebooks', 'course materials', 'SQLite databases',
                                               'raw/clean review records', 'OAuth/service account credentials'],
                    notes='Explicit source/aggregate allowlist, with credential-pattern scan. This is not a proof against every possible secret. Research raw data requires separate authorized access; sample demo is self-contained.')
    (destination / 'DELIVERY_MANIFEST.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return {'destination': str(destination), 'file_count': len(files)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', default='artifacts/delivery/portfolio')
    args = parser.parse_args()
    print(json.dumps(prepare(args.destination), indent=2))
