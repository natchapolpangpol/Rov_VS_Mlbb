"""Offline, isolated demonstration of idempotency, rejection, and safe recovery."""
from pathlib import Path
import shutil
import sqlite3
import uuid

from rov_mlbb.collectors import TransientError, retry_call
from rov_mlbb.common import DataError, read_json, utc_now, write_json
from rov_mlbb.pipeline import run_pipeline
from rov_mlbb.report import create_report


def counts(database):
    with sqlite3.connect(database) as conn:
        return {name: conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
                for name in ('runs', 'observations', 'run_records', 'monthly_metrics')}


root = Path(__file__).resolve().parents[1]
folder = root / 'artifacts/demos' / uuid.uuid4().hex
(folder / 'inputs').mkdir(parents=True)
config = read_json(root / 'config/sample.json')
config.update(project_root='.', artifact_root='pipeline')
for source in config['inputs']:
    shutil.copyfile(root / f'data/sample/{source}.json', folder / f'inputs/{source}.json')
    config['inputs'][source] = f'inputs/{source}.json'
config_path = folder / 'config.json'
write_json(config_path, config)
evidence = {'data_kind': 'sample', 'label': 'SYNTHETIC SOFTWARE DEMO, NOT RESEARCH FINDINGS',
            'started_at': utc_now(), 'directory': str(folder)}
print(evidence['label'])
first = run_pipeline(config_path)
before = counts(first['database'])
second = run_pipeline(config_path)
after = counts(second['database'])
assert before['observations'] == after['observations'] == 28
evidence['rerun'] = {'first_run': first['run_id'], 'second_run': second['run_id'],
                     'before': before, 'after': after, 'duplicate_observations_added': 0}
print('Rerun: 28 observations remain 28; separate run history is retained.')
review_path = folder / 'inputs/playstore.json'
original = review_path.read_bytes()
packet = read_json(review_path)
packet['records'][0]['rating'] = 99
write_json(review_path, packet)
try:
    run_pipeline(config_path)
except DataError as error:
    evidence['expected_failure'] = {'error': str(error),
        'manifest': read_json(folder / 'pipeline/sample/latest_attempt.json')}
else:
    raise AssertionError('Deliberately invalid input unexpectedly passed')
finally:
    review_path.write_bytes(original)
assert evidence['expected_failure']['manifest']['status'] == 'failed'
assert read_json(folder / 'pipeline/sample/latest_complete.json')['run_id'] == second['run_id']
assert counts(first['database'])['run_records'] == after['run_records']
evidence['last_complete_preserved_after_failure'] = True
print('Rating 99 rejected; failed run preserved the last complete pointer and inserted no results.')
recovered = run_pipeline(config_path)
evidence['recovery'] = {'run_id': recovered['run_id'], 'counts': counts(first['database']),
                         'report': str(create_report(recovered['artifact_dir']))}
assert evidence['recovery']['counts']['observations'] == 28
events, waits = [], []
attempts = 0
def temporary_failure():
    global attempts
    attempts += 1
    if attempts < 3:
        raise TransientError('Deliberately simulated transient error')
    return 'ok'
retry_call(temporary_failure, sleep=waits.append, events=events)
assert waits == [2, 4] and attempts == 3
evidence['retry_simulation'] = {'network_used': False, 'delays_recorded_not_slept': waits, 'events': events}
evidence.update(status='passed', finished_at=utc_now())
write_json(folder / 'evidence.json', evidence)
print('Recovery passed. Simulated retry used 3 attempts with planned backoff 2s, 4s; no network requests.')
print(f"Evidence: {folder / 'evidence.json'}")
print(f"Report: {evidence['recovery']['report']}")
