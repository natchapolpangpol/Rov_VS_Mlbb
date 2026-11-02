from __future__ import annotations

import argparse
import json
import sys


def main():
    # Application entry point: use the OS trust store while keeping TLS verification on.
    import truststore
    truststore.inject_into_ssl()
    parser = argparse.ArgumentParser(description="RoV vs MLBB reproducible data pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Process input packets without network access")
    run.add_argument("--config", required=True)
    report = sub.add_parser("report", help="Generate figures and a report for an explicit run")
    report.add_argument("--run-dir", required=True)
    collect_parser = sub.add_parser("collect", help="Collect bounded real inputs; no sample fallback")
    collect_parser.add_argument("--config", required=True)
    collect_parser.add_argument("--sources", nargs="+", choices=["trends", "youtube", "playstore"])
    import_parser = sub.add_parser("import", help="Convert CSV/JSON exports using explicit provenance metadata")
    import_parser.add_argument("--input", required=True)
    import_parser.add_argument("--metadata", required=True)
    import_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            from .pipeline import run_pipeline
            result = run_pipeline(args.config)
            print(json.dumps({k: result[k] for k in ("run_id", "data_kind", "status", "artifact_dir", "summary_rows")}, indent=2))
        elif args.command == "report":
            from .report import create_report
            print(create_report(args.run_dir))
        elif args.command == "import":
            from .importer import convert_export
            print(convert_export(args.input, args.metadata, args.output))
        else:
            from .collectors import collect
            result = collect(args.config, args.sources)
            print(json.dumps(result, indent=2, ensure_ascii=True))
            return 1 if any(s["status"] == "failed" for s in result["sources"].values()) else 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
