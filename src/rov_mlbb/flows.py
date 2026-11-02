"""Local Prefect orchestration. Run as a module; no Prefect Cloud account needed."""
from __future__ import annotations

import argparse
from pathlib import Path

from prefect import flow, task

from .collectors import collect
from .pipeline import run_pipeline
from .report import create_report


@task(name="collect-bounded-real-inputs", persist_result=False)
def collect_task(config_path: str):
    # Source-specific HTTP retry lives in collectors; never retry missing credentials.
    result = collect(config_path)
    failures = [s for s, result in result["sources"].items() if result["status"] == "failed"]
    if failures:
        raise RuntimeError(f"Collection incomplete for {failures}; inspect {result['directory']}/collection_status.json")
    return result["pipeline_config"]


@task(name="validate-integrate-persist", persist_result=False)
def prepare_task(config_path: str):
    return run_pipeline(config_path)


@task(name="render-run-report", persist_result=False)
def report_task(result: dict):
    return str(create_report(result["artifact_dir"]))


@flow(name="rov-mlbb-local-batch", log_prints=True, persist_result=False)
def batch_flow(config_path: str):
    result = prepare_task(config_path)
    report_task(result)
    print(f"{result['data_kind']} | {result['status']} | {result['run_id']}")
    return result


@flow(name="rov-mlbb-real-refresh", log_prints=True, persist_result=False)
def refresh_flow(config_path: str):
    packet_config = collect_task(config_path)
    result = prepare_task(packet_config)
    report_task(result)
    return result


def main():
    import truststore
    truststore.inject_into_ssl()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--refresh", action="store_true", help="Collect real data before processing")
    parser.add_argument("--serve", action="store_true", help="Stay running for a local scheduled deployment")
    parser.add_argument("--interval", type=int, default=86400)
    args = parser.parse_args()
    target = refresh_flow if args.refresh else batch_flow
    config = str(Path(args.config).resolve())
    if args.serve:
        if args.interval < 60:
            parser.error("Interval must be at least 60 seconds")
        target.serve(name="rov-mlbb-refresh" if args.refresh else "rov-mlbb-batch",
                     interval=args.interval, parameters={"config_path": config},
                     limit=1, pause_on_shutdown=True)
    else:
        target(config)


if __name__ == "__main__":
    main()
