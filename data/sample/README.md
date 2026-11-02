# Synthetic demonstration data

Every record in this directory is **invented for software testing**. The dates,
interest values, video IDs, views and ratings are not findings about either game.
The app identifiers are real identifiers used to exercise validation only.

Regenerate deterministically with `python scripts/build_sample.py`.
January RoV has interest 60, two videos with median lifetime views 200, and two
unique reviews averaging 3.0. One repeated review tests deduplication.
March MLBB has a known zero videos within the synthetic sampling frame.
