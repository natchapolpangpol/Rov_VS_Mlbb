"""Verify two actual timer-triggered local Prefect runs, then stop owned processes.

Offline sample only. Each invocation has its own SQLite databases and log directory.
No Prefect Cloud account or external data API is used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import uuid

import psutil
import requests

from rov_mlbb.common import read_json, utc_now, write_json


def stop_owned_tree(process):
    if process is None:
        return []
    try:
        parent = psutil.Process(process.pid)
        owned = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return []
    for child in owned:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(owned, timeout=8)
    for child in alive:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(alive, timeout=5)
    return [child.pid for child in alive]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8420)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    # Refuse to attach to an unrelated server on the selected port.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', args.port))
    directory = root / 'artifacts/verification' / f'schedule-{uuid.uuid4().hex}'
    directory.mkdir(parents=True)
    config = read_json(root / 'config/sample.json')
    config['project_root'] = str(root)
    config['artifact_root'] = str(directory / 'pipeline')
    config_path = directory / 'sample.json'
    write_json(config_path, config)
    api = f'http://127.0.0.1:{args.port}/api'
    env = {**os.environ, 'PREFECT_HOME': str(directory / 'prefect-home'),
           'PREFECT_API_URL': api, 'PREFECT_SERVER_ANALYTICS_ENABLED': 'false',
           'PREFECT_LOGGING_COLORS': 'false', 'PYTHONUNBUFFERED': '1'}
    evidence = {'started_at': utc_now(), 'data_kind': 'sample', 'status': 'running',
                'interval_seconds': 60, 'directory': str(directory),
                'api': api, 'python': sys.version, 'completed_flow_runs': []}
    server = runner = None
    deployment_id = None
    logs = []
    session = requests.Session()
    session.trust_env = False  # localhost only; bypass ambient external proxy configuration.
    def launch(arguments, name):
        stream = (directory / f'{name}.log').open('w', encoding='utf-8')
        logs.append(stream)
        return subprocess.Popen([sys.executable, *arguments], cwd=root, env=env,
                                stdout=stream, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    def api_request(path, body=None):
        if body is None:
            response = session.get(api + path, timeout=5)
        else:
            response = session.post(api + path, json=body, timeout=5)
        response.raise_for_status()
        return response.json() if response.content else None
    print(f'Evidence directory: {directory}', flush=True)
    try:
        server = launch(['-m', 'prefect', 'server', 'start', '--host', '127.0.0.1', '--port', str(args.port)], 'server')
        evidence['server_pid'] = server.pid
        ready_deadline = time.monotonic() + 90
        while True:
            if server.poll() is not None:
                raise RuntimeError('Owned Prefect server exited; inspect server.log')
            try:
                api_request('/health')
                break
            except requests.RequestException:
                if time.monotonic() > ready_deadline:
                    raise TimeoutError('Owned server still live but health endpoint did not become ready')
                time.sleep(2)
        runner = launch(['-m', 'rov_mlbb.flows', '--config', str(config_path), '--serve', '--interval', '60'], 'runner')
        evidence['runner_pid'] = runner.pid
        print('Local server healthy; timer deployment starting.', flush=True)
        deadline = time.monotonic() + args.timeout
        observed = set()
        while time.monotonic() < deadline:
            if server.poll() is not None or runner.poll() is not None:
                raise RuntimeError('Owned server or runner exited before verification completed')
            runs = api_request('/flow_runs/filter', {'limit': 100, 'sort': 'EXPECTED_START_TIME_ASC'})
            for run in runs:
                key = (run['id'], run.get('state_name'))
                if key not in observed and run.get('state_name') != 'Scheduled':
                    print(f"Timer run {run['id']}: {run.get('state_name')} | auto_scheduled={run.get('auto_scheduled')}", flush=True)
                    observed.add(key)
            completed = [run for run in runs if run.get('state_name') == 'Completed' and run.get('auto_scheduled')]
            if len(completed) >= 2:
                evidence['completed_flow_runs'] = completed
                deployment_id = completed[0]['deployment_id']
                break
            failed = [run for run in runs if run.get('state_name') in ('Failed', 'Crashed')]
            if failed:
                evidence['failed_flow_runs'] = failed
                raise RuntimeError('A timer-triggered flow failed; inspect runner log')
            time.sleep(3)
        else:
            raise TimeoutError('Live scheduler did not produce two completed timer runs before observation deadline')
        api_request(f'/deployments/{deployment_id}/pause_deployment', {})
        evidence['deployment'] = api_request(f'/deployments/{deployment_id}')
        assert evidence['deployment']['paused'] is True
        ids = [run['id'] for run in completed]
        write_json(directory / 'flow_logs.json', api_request('/logs/filter', {
            'logs': {'flow_run_id': {'any_': ids}}, 'limit': 200, 'sort': 'TIMESTAMP_ASC'}))
        database = directory / 'pipeline/sample/pipeline.sqlite'
        with sqlite3.connect(database) as conn:
            evidence['table_counts'] = {table: conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                                        for table in ('runs', 'observations', 'run_records', 'monthly_metrics')}
            evidence['pipeline_runs'] = [dict(zip(('run_id', 'status', 'started_at', 'finished_at'), row))
                for row in conn.execute('SELECT run_id,status,started_at,finished_at FROM runs ORDER BY started_at')]
        assert evidence['table_counts']['observations'] == 28
        assert all(run['status'] == 'complete' for run in evidence['pipeline_runs'])
        assert len(evidence['pipeline_runs']) >= 2
        evidence['status'] = 'passed'
    except Exception as error:
        evidence['status'] = 'failed'
        evidence['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        # Pause any deployment created by this isolated server before stopping it.
        if server is not None and server.poll() is None:
            try:
                deployments = api_request('/deployments/filter', {'limit': 100})
                for deployment in deployments:
                    api_request(f"/deployments/{deployment['id']}/pause_deployment", {})
            except requests.RequestException as error:
                evidence['cleanup_api_error'] = type(error).__name__
        evidence['remaining_owned_pids'] = stop_owned_tree(runner) + stop_owned_tree(server)
        if evidence['remaining_owned_pids']:
            evidence['status'] = 'failed'
        for stream in logs:
            stream.close()
        evidence['finished_at'] = utc_now()
        write_json(directory / 'evidence.json', evidence)
        print(f"Verification: {evidence['status']} | {directory / 'evidence.json'}", flush=True)
    return 0 if evidence['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
