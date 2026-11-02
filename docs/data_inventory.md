# Data inventory

Working study window: 2025-01-01 through 2026-03-10, derived from the original notebook. Monthly aggregation: Asia/Bangkok. Inventory checked on 2026-11-02.

| Local dataset | Records | Purpose / limitations |
|---|---:|---|
| Firestore rov_youtube | 3,381 | Selected-channel archive; original collection time unknown |
| Firestore mlbb_youtube | 2,445 | Same rules; cumulative views, not monthly view increments |
| Firestore rov_google_play | 11,613 | NEWEST; filtered request language th and non-null appVersion |
| Firestore mlbb_google_play | 4,675 | MOST_RELEVANT; same later filtering, different sampling order |
| Firestore rov_google_trends | 1,720 | Legacy window stitching; audit only, excluded from final metrics |
| Firestore mlbb_google_trends | 1,576 | Legacy window stitching; excluded from final metrics |
| Firestore rov_mlbb_google_trends | 1,720 | Joint terms but separately scaled weekly requests; excluded |
| New historical joint Trends | 126 | One shared query; 124 accepted, two partial intervals quarantined |
| October 2026 pilot | 342 accepted | 62 Trends + 280 reviews; connectivity evidence only |
| Synthetic sample | 28 accepted unique | Offline system demo only |

Seven Firestore collections were read to exhaustion, totaling 27,130 documents. Native typed responses, decoded JSONL, hashes and manifests are indexed in firestore_full_export.json (local reference: `../data/imports/firestore_full_export.json`). Counts match the notebook's saved summary. This does not prove byte-for-byte identity with the historical data at notebook execution time.

New Trends packet: `data/imports/cda0b86d18cd4d3c86b255ad486b54e2/trends.json`. Collection time: `2026-11-02T15:26:51.407431+00:00`. Query ID: `bf72300156429cd192c61229d1dc9b8c18eefb5792a927227d5c6ee3ff41efa4`.

Main adapter config: `data/imports/historical-ec4ce616ddb2466a8b9b65ea03e29e9e/pipeline_config.json`.
Alternative review-timezone config: `data/imports/historical-a25e9efffce64281b8e4c1688c4aa39f/pipeline_config.json`.

Main run: `fd1a7d895cb3477ea72591e4199e5e38`.
Same-input rerun: `20a3ec2399584180b20d203fcf70bf54`.
Timezone sensitivity run: `97868468efa24fb986b79948cbcb4a8e` under `artifacts/timezone-sensitivity/real/runs/`.

The historical run accepts 22,238 observations and produces 30 unique game-month rows. The primary real database contains 22,580 observations including the separate 342-observation pilot. Always filter by run membership; the entire database is not one research sample.

Original collection time is null for archived YouTube/reviews. Maximum Firestore document update times give conservative batch upper bounds: YouTube `2026-03-16T07:51:01.117452+00:00`, reviews `2026-03-17T09:42:59.316150+00:00`. These are not collection dates. Export dates are separate.

Native export pages contain source review/profile fields. Canonical reviews retain identifiers, game/app, rating, event time and request language, without review text or author profiles. Raw exports and credentials remain local audit evidence and are excluded from the portable source package. No external publishing was performed.
