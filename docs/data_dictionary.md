# Data dictionary and metric contracts

## Input packet v1

Each source is one JSON object with `schema_version=1`, `source`, `data_kind`, `collected_at`, `context`, `coverage` and `records`. `source` is `trends`, `youtube` or `playstore`. `data_kind` is `sample` or `real`; mixing is a hard failure.

`collected_at` must include a UTC offset. Event timestamps also require offsets, then event dates/months use the configured timezone (default Asia/Bangkok). Importing a naive timestamp requires an explicit source timezone.

`coverage` has one entry for each game (`rov`, `mlbb`) with inclusive `start`, `end`, `status` and a human-readable `note`. Status is `complete`, `partial` or `missing`. Completeness is relative to a documented sampling frame, not the universe of players/content.

| Source | Required record fields | Grain and key |
|---|---|---|
| Trends | `game`, `date`, `period_end`, `interest`, `is_partial` | Joint query × game × interval. Key includes `query_id`, game and both interval endpoints |
| YouTube | `game`, `video_id`, `channel_id`, `title`, `published_at`, `views`; nullable `likes` | Video × collection timestamp; repeated snapshots are intentional history |
| Play Store | `game`, `app_id`, `review_id`, `reviewed_at`, `rating`, `language` | App × review ID; content versions retain changes without duplicating current run membership |

Trends additionally requires `context.scale=joint_request`, `context.query_id` and the mapping `context.terms` for both games. Interest must be finite in [0,100]; intervals must not overlap within a game. Partial intervals are quarantined.

Ratings must be integers in [1,5]. Views/likes must be nonnegative integers when present. Required identifiers and game names must be valid. Events after collection or outside the configured study are rejected.

## Summary: one game per calendar month per run

### Historical input packet v2

For an archive without original collection time, `schema_version=2` requires `collected_at=null`. Provenance must declare `collection_time_status=unknown`, a stable SHA-256 `snapshot_id`, timezone-aware `collected_no_later_than` and `exported_at`, a `timing_basis` explanation, and nonempty `source_exports`. The upper bound cannot follow export time. It validates that events/coverage are not later than the available bound; it does not establish the exact fetch time.

The Firestore adapter checks exhausted exports, native page hashes, decoded-record hashes and counts before conversion. It records the original notebook hash and source export references. YouTube keys use video ID × unknown snapshot ID; re-exporting unchanged content does not create a new observation merely because export time changed. Review keys remain app × review ID. Naive review timestamps require an explicit source-timezone assumption in context; UTC and Asia/Bangkok sensitivity runs are kept separate.

Firestore document updateTime is only a conservative upper bound on the archived observation, not the original collection time. API collection uncertainty and original filtering remain in coverage/context. Historical Trends cannot bypass the shared-query-scale requirement.

### Monthly columns

| Field | Definition |
|---|---|
| `run_id`, `data_kind` | Provenance and sample/real identity |
| `month`, `game` | Unique within a run; full calendar grid includes missing source months |
| `study_days_in_month` | Number of days included by study bounds; partial study months cannot be marked fully covered by Trends |
| `search_interest` | Sum of interest × overlapping interval days, divided by observed days |
| `trends_observed_days` | Number of nonoverlapping accepted days contributing to the month |
| `trends_query_id` | Identity of the common query scale; values from different IDs must not be stitched without a separate validated method |
| `published_video_count` | Distinct accepted videos published in the month, within the selected channels/title rules |
| `median_views_at_collection` | Median cumulative views of those videos at collection; not views earned during this month |
| `sampled_channel_count` | Distinct channels with accepted videos in that month |
| `review_count` | Distinct accepted reviews whose current source timestamp falls in the month |
| `mean_review_rating` | Arithmetic mean of accepted scores; show with review_count |
| `<source>_coverage` | `complete`, `filtered`, `partial` or `missing` |
| `<source>_collected_at` | Timestamp for the source snapshot used in this run |
| `<source>_collection_time_status` | known, unknown or missing; unknown has null collected_at |
| `<source>_collected_no_later_than` | Historical bound only, nullable; never label as fetch date |
| `<source>_exported_at` | Archive-copy time, nullable; not original source collection time |
| `all_sources_complete` | True only when all three coverage flags are `complete` |

Unknown counts stay null. A count can be zero only when the sampling frame/month is declared complete and no qualifying observations exist. A mean/median with no observations is null even for a known zero count. Observed values in partial months are retained and visibly flagged; they are not estimates of the missing part.

Weekly-to-month allocation assumes a weekly interest index applies equally to its represented days. The result is a day-weighted approximation. It is not an exact monthly search-volume measure.

## SQLite tables

| Table | Key | Purpose |
|---|---|---|
| `metadata` | `key` | Namespace identity |
| `runs` | `run_id` | Configuration, start/end, status, error, artifact directory |
| `run_sources` | run × source | Raw file path/hash and quality counts |
| `observations` | source × record_key × payload_hash | Immutable deduplicated content versions |
| `run_records` | run × source × record_key | Exactly one accepted version per logical record in a run |
| `monthly_metrics` | run × month × game | Summary JSON preserving nulls |
| `latest_complete_monthly` | View | Latest complete run; may be empty when only partial data exist |

Repeated runs intentionally add run/membership/summary history; unchanged rows do not add observation versions. Consumers must filter by run. Counting all run_records across every historical run is not a population count.

## Quality accounting

`input_rows = accepted_rows + duplicate_rows + rejected_rows`.

Exact duplicate keys/content retain one accepted record. Conflicting duplicates quarantine the entire group. Overlapping Trends intervals quarantine the affected interval groups to prevent double weighting. Rejected files contain input row indices and reasons, with full original values in raw.

Any rejection conservatively changes otherwise complete coverage to `filtered`. Exceeding `max_rejected_fraction` fails the run entirely. This threshold is a software gate, not a scientific claim that a certain amount of missing data is harmless.
