# Verification evidence

Checked on 2026-11-02 on Windows with Python 3.13.7. Tests exercise system behavior; they do not establish statistical representativeness of the source data.

## Environment and automated tests

An independent environment at `tmp/verify-venv` was built from requirements-lock.txt and the editable project. After adding Firestore dependencies, the current lock has 152 pinned distributions. `pip check` reports no broken requirements. The complete test suite passes **45 tests**; [JUnit output](../artifacts/verification/final-tests.xml) records the result. [Environment evidence](../artifacts/verification/final_environment.json) records versions and hashes of the checked implementation.

Tests cover idempotency, unchanged-observation reuse, changed-content versions, source separation, grain/aggregation, invalid values, timezone and missing data, overlapping Trends periods, conflicting duplicates, retries/caps, import aliases, partial/failed states, transactional rollback, post-commit pointer failures, Firestore pagination and archive integrity. They use controlled fixtures/mocked services unless stated otherwise.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
```

## Real archive and rerun

[Notebook reconciliation](../artifacts/verification/firestore_notebook_reconciliation.json) matches all seven collections and 27,130 documents with the notebook's saved output. Native pages and decoded hashes remain in local imports.

Historical run `fd1a7d895cb3477ea72591e4199e5e38` accepted 22,238 real records and produced 30 game-month rows. Run `20a3ec2399584180b20d203fcf70bf54` repeated the same inputs. SQLite observations stayed **22,580 → 22,580**, including the separate 342-observation pilot. Both runs are partial. [Rerun evidence](../artifacts/verification/historical_rerun.json)

The alternative-timezone run `97868468efa24fb986b79948cbcb4a8e` used the same reviews under the Asia/Bangkok interpretation. The analysis script checks identity and scores before comparison. Results are in [historical findings](historical_findings.md).

## Timer-triggered orchestration

Two actual Prefect timer runs executed on localhost with `auto_scheduled=true`:

| Flow run | Expected UTC | Actual start UTC | Outcome |
|---|---|---|---|
| 01a19cc6-2c7c-7bc7-883c-570cb5ff4a5b | 2026-11-02 15:00:53.573361 | 15:00:53.562070 | Completed |
| 01a19cc6-2c7c-7fc7-93ba-ec928c25e444 | 2026-11-02 15:01:53.573361 | 15:01:54.063195 | Completed |

The isolated sample database had two runs, 28 observations, 56 memberships and 12 monthly rows. The test paused its deployment and stopped its owned processes. This proves local scheduled sample execution, not live collection from all APIs. [Scheduler evidence](../artifacts/verification/schedule-9c352aea53f046059815c81cd59ca14f/evidence.json)

Reproduce with `python scripts/verify_schedule.py` using the project environment. Allow 2–5 minutes. No scheduler is left running as a production service by this verification.

## Failure/recovery demonstration

`scripts/demo.py` creates isolated sample data, runs twice without duplicating observations, injects rating 99, checks failed state and unchanged latest_complete, restores valid input and recovers. A separate mocked HTTP operation fails twice then succeeds with recorded 2/4-second backoff values (no real wait in this demo).

Previously verified demo ID: `f918efaacbd8497ba7951cfb670bafb4`; recovery run: `bcb4a5051b474accab0804d655a71f1f`. Each new demo gets a unique directory. This is intentionally synthetic and must not be presented as research findings.

## Notebook and visual review

The real historical notebook executed all five code cells in the independent environment. [Executed notebook](../artifacts/real/historical_analysis.executed.ipynb) is an output artifact; the source notebook is output-free and defaults to sample. The generated overview was visually checked for labels, readability, missing data and truncated boundary months. Crosses mark those boundary observations and are not joined into the full-month line.

No additional rubric/template was available to verify. The report records uncertainty rather than treating unknown collection time, filtered reviews or partial coverage as complete.

## Relocated portfolio checkout

The explicit delivery allowlist was copied into a separate Git checkout. Running scripts/demo.py from that directory with its own src on PYTHONPATH succeeded, producing demo d0bd001a7db048fe8ca309e00491a802 and recovery 5a0fb4ac28ee4069ad623ee52f4ba2d0. Observations remained 28 across reruns; failure and recovery checks passed. This exercises relocated source/sample paths without including original team data.

DELIVERY_MANIFEST.json lists the included files and hashes. The package excludes raw imports, original notebooks, course files, databases, SDKs and credentials. Included text is scanned for common Google/GitHub/private-key/database-URL credential patterns. That scan is a bounded check, not proof that every possible secret format is detectable.
