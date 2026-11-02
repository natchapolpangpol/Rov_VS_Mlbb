# Import existing project data

Ask a teammate for **CSV or JSON arrays**, not their database password or service-account key.
The importer retains the original bytes and a hash alongside its canonical packet.

Required provenance:

- Actual collection time (especially cumulative YouTube statistics)
- Timezone of naive timestamps, if any
- Channel selection, language/storefront, date filters and pagination limits
- Whether each game's coverage is complete, partial or unknown/missing
- For Trends: proof the two columns were retrieved together in one request/window with the same normalization

Do not invent missing metadata. A new download date is not the original collection time.

## Trends metadata example

Save this beside a Google multiTimeline export and adjust it to match the actual file:

```json
{
  "source": "trends",
  "data_kind": "real",
  "collected_at": "2025-04-02T10:00:00+07:00",
  "context": {
    "selection": "Both terms queried together, TH, 2025-01-01 to 2025-03-31",
    "scale": "joint_request",
    "query_id": "describe-the-exact-export-window-and-settings",
    "terms": {"rov": "rov", "mlbb": "mlbb"}
  },
  "coverage": {
    "rov": {"start": "2025-01-01", "end": "2025-03-31", "status": "complete", "note": "Replace with verified provenance"},
    "mlbb": {"start": "2025-01-01", "end": "2025-03-31", "status": "complete", "note": "Replace with verified provenance"}
  },
  "interval_days": 1,
  "column_map": {"rov": "rov: (Thailand)", "mlbb": "mlbb: (Thailand)"}
}
```

Use `interval_days=7` only for weekly exports. For monthly/custom intervals supply a `period_end` column explicitly. Headers may differ by UI language; use `column_map` to map canonical names to the exact original column names. Censored values such as `<1` are quarantined, not silently converted to zero.

## Original notebook exports

YouTube aliases match `video_id`, `channel_id`, `title`, `published_at`, `views`, `likes`, `game`.
Repeated rows from comment expansion deduplicate only when their video fields agree.

Play Store aliases include `reviewId` → `review_id`, `at` → `reviewed_at`, `score` → `rating`, `lang_source` → `language`.
For a per-game export, set metadata `game`, `app_id`, and `language` where absent from rows.
Set `source_timezone` only when the export's timezone is known. Usernames, profile images and review text are not required by the clean schema.

Each packet is one source per run. If a source is split across several original files, combine them with preserved provenance before conversion; do not overwrite one game's packet with the other. The current importer handles one input file at a time.

After conversion, set the packet path in a real pipeline config and run the normal validation pipeline. The importer does not mark data valid merely because conversion succeeded.

## Historical Firestore archive

The user account has already authenticated locally using Google Application Default Credentials. No private key JSON is needed. Offline reruns do not need authentication. A new Windows machine can install Google Cloud CLI, then use `gcloud auth application-default login --project=rovvsm-4c944` with an authorized account. The optional local `scripts/connect_firestore.cmd` assumes the portable SDK is installed under .tools; the SDK and credentials are not bundled with portfolio source.

Read-only commands (new reads may be metered by the project's existing plan):

```powershell
.\.venv\Scripts\python.exe -m rov_mlbb.firestore_export --project rovvsm-4c944 --list-collections
.\.venv\Scripts\python.exe -m rov_mlbb.firestore_export --project rovvsm-4c944 --collection rov_youtube --max-documents 5000
```

Each collection export writes native typed pages, decoded `records.jsonl`, hashes and a manifest. It exports direct documents only, not nested subcollections. `capped` is not a full export. Pagination is sequential, not a transactional database-wide snapshot. The exporter never creates, edits or deletes Firestore documents.

The local full-export index has the shape `{"exports": [{"collection": "rov_youtube", "folder": "data/imports/firestore-..."}, ...]}`. Use full exhausted exports for rov_youtube, mlbb_youtube, rov_google_play and mlbb_google_play. Preserve native manifests and page hashes. For relocation, update the index folder paths rather than copying old absolute paths blindly.

To recreate the historical input packets from the existing archive and jointly collected Trends:

```powershell
.\.venv\Scripts\python.exe -m rov_mlbb.historical --export-index data/imports/firestore_full_export.json --trends-packet data/imports/cda0b86d18cd4d3c86b255ad486b54e2/trends.json --assumed-review-timezone UTC
```

This prints a new pipeline_config.json path. Run it with the normal CLI `run --config <printed-path>`, then create a report for the returned artifact_dir. To reproduce the sensitivity analysis, repeat adaptation with `--assumed-review-timezone Asia/Bangkok --artifact-root artifacts/timezone-sensitivity` and run that config.

The adapter needs the original notebook for its provenance hash, but never executes it. Archived input has unknown `collected_at`, a separately recorded export time and a document-update upper bound. Do not fill missing collection dates with today. See [schema v2](data_dictionary.md) and [notebook reconciliation](firestore_notebook_mapping.md).

New historical Trends can be collected with `collect --config config/historical.collect.json --sources trends`. A fresh query may return revised or differently sampled values, so preserve the frozen packet to reproduce the exact reported numbers. Do not combine independently normalized query IDs into one curve.
