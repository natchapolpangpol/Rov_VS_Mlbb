# Scope and evidence status

## Intended consumer

A creator or content analyst comparing signals about RoV and MLBB. This is a project design assumption; no user interviews have been conducted.

## Questions

1. How does relative search interest change within a jointly normalized query window?
2. How does published content in the selected channels vary over time?
3. How do the number and scores of accessible reviews change, and do the separate signals tell a consistent descriptive story?

These sources cannot directly prove player migration, total player counts or causal effects of an event.

## Study window

Working window: **2025-01-01 through 2026-03-10**, derived from cell 16 of `RovVsMlbb_Pipeline.ipynb`. Monthly aggregation uses Asia/Bangkok. This preserves the notebook's scope; no additional teacher rubric has been supplied. Reviews cover only part of this window.

The descriptive comparison uses April–July and August–November 2025, two 122-day windows within the review archive's observed dates. This choice follows coverage inspection, not a pre-registered causal design. Full monthly output remains available.

`config/sample.json` uses Q1 2025 for deterministic software tests only.
`config/pilot.json` uses October 2026 for bounded live connectivity checks only; this is not a silent replacement of the original historical study.

## Initial real-data pilot, 2 November 2026

- Joint Google Trends query: 62 canonical rows (31 dates × two terms) for October 2026.
- Play Store: 280 in-window review rows from a one-page-per-game capped collection. Coverage is partial.
- YouTube: no API key configured in the environment at the time of this check.
- Pipeline produced two game-month rows with status `partial`; no complete real-data pointer was published.

Source batch: `data/imports/c00a8e6d4c0f4c7fb6c1c0386cd6c95c/`.
Pilot run: `48a8bebaccf24b14b44256a1d6b7dc9e`.

Earlier connectivity attempts failed TLS verification until the application used the OS certificate store. An initial Play Store empty response was found to be a swallowed library error and is not valid evidence of zero reviews. That early batch is excluded from analysis; the collector now surfaces the error explicitly.

## Historical data and completed checks

All seven Firestore collections were exported read-only (27,130 documents). Archived YouTube and reviews were adapted into SQLite with explicit unknown collection times. Legacy Trends were excluded because of separately scaled request windows. A new joint historical query supplies Trends for the same study window.

The main real run accepts 5,826 videos, 16,288 reviews and 124 Trends intervals. Its status remains **partial** because of sampling uncertainty, missing review months and boundary intervals. All three sources being present does not imply complete population coverage.

The notebook establishes 28 selected channels and title keywords, different review sorting orders and later language/app-version filtering. Rule consistency, channel composition and UTC-versus-Bangkok review sensitivity have been checked. See [findings](historical_findings.md), [inventory](data_inventory.md) and [notebook mapping](firestore_notebook_mapping.md).

SQLite is the local portfolio database. Firestore supplies a historical import and is unnecessary for offline reruns. A YouTube API key is only needed for new collection. Scheduled execution was verified using two real local Prefect timer runs on sample data; this is not a claim of unattended production collection.

Delivery consists of source, Markdown report, notebook, charts and a demonstration script. No university report/slide template, deadline or rubric has been supplied. Formatting requirements can be applied later without inventing missing metadata. Repository publication to natchapolpangpol/Rov_VS_Mlbb is authorized by the user. No application deployment is included.
