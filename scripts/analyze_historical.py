"""Reproduce descriptive historical findings and uncertainty checks offline."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

import pandas as pd

from rov_mlbb.common import write_json
from rov_mlbb.report import load_run


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def analyze(run_dir, alternative_dir, notebook):
    run_dir, alternative_dir, notebook = map(Path, (run_dir, alternative_dir, notebook))
    manifest, frame = load_run(run_dir)
    alternative, alt = load_run(alternative_dir)
    if manifest['data_kind'] != 'real' or alternative['data_kind'] != 'real':
        raise ValueError('Historical findings require real runs')
    if frame[['month', 'game']].to_dict('records') != alt[['month', 'game']].to_dict('records'):
        raise ValueError('Sensitivity runs must have the same month/game grid')
    videos = pd.DataFrame(read(run_dir / 'clean/youtube.json'))
    reviews = pd.DataFrame(read(run_dir / 'clean/playstore.json'))
    alt_reviews = pd.DataFrame(read(alternative_dir / 'clean/playstore.json'))
    if set(reviews.record_key) != set(alt_reviews.record_key):
        raise ValueError('Sensitivity runs must contain the same reviews')
    joined = reviews.merge(alt_reviews, on='record_key', suffixes=('_base', '_alternative'), validate='one_to_one')
    if not (joined.rating_base == joined.rating_alternative).all():
        raise ValueError('Sensitivity runs changed review scores')
    before = ('2025-04', '2025-07')
    after = ('2025-08', '2025-11')
    windows = []
    for game in ('rov', 'mlbb'):
        for period, (start, end) in [('before', before), ('after', after)]:
            selected = frame.loc[(frame.game == game) & frame.month.between(start, end)]
            if len(selected) != 4 or selected.review_count.isna().any():
                raise ValueError('Matched windows need four observed months per game')
            n = selected.review_count.sum()
            windows.append(dict(game=game, period=period, start=start, end=end,
                                calendar_days=int(selected.study_days_in_month.sum()),
                                search_interest=float((selected.search_interest * selected.trends_observed_days).sum() / selected.trends_observed_days.sum()),
                                videos=int(selected.published_video_count.sum()), reviews=int(n),
                                mean_rating=float((selected.mean_review_rating * selected.review_count).sum() / n)))
    comparison = frame[['month', 'game', 'review_count', 'mean_review_rating']].merge(
        alt[['month', 'game', 'review_count', 'mean_review_rating']], on=['month', 'game'],
        suffixes=('_utc', '_bangkok'), validate='one_to_one')
    comparison['count_difference'] = comparison.review_count_utc - comparison.review_count_bangkok
    comparison['rating_difference'] = comparison.mean_review_rating_utc - comparison.mean_review_rating_bangkok
    interior = comparison.loc[comparison.month.between('2025-04', '2026-01')]
    sensitivity = dict(total_reviews=len(joined),
                       changed_month_reviews=int((joined.event_date_base.str[:7] != joined.event_date_alternative.str[:7]).sum()),
                       max_month_game_count_difference=float(comparison.count_difference.abs().max()),
                       max_month_game_rating_difference=float(comparison.rating_difference.abs().max()),
                       interior_months='2025-04 through 2026-01; archive sampling remains partial',
                       interior_max_count_difference=float(interior.count_difference.abs().max()),
                       interior_max_rating_difference=float(interior.rating_difference.abs().max()))
    # Parse literal constants only; never execute original notebook cells or expose credentials.
    constants = {}
    for node in ast.parse(''.join(read(notebook)['cells'][16]['source'])).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('ALL_CHANNELS', 'ROV_KEYWORDS_TITLE', 'MLBB_KEYWORDS_TITLE'):
                    constants[target.id] = ast.literal_eval(node.value)
    def classify(title):
        r = any(word in title for word in constants['ROV_KEYWORDS_TITLE'])
        m = any(word in title for word in constants['MLBB_KEYWORDS_TITLE'])
        return 'rov' if r and not m else 'mlbb' if m and not r else None
    videos['original_rule_game'] = videos.title.map(classify)
    videos['channel_in_notebook'] = videos.channel_id.isin(constants['ALL_CHANNELS'])
    videos['month'] = videos.event_date.str[:7]
    videos['casefold_both_games'] = videos.title.map(lambda t: ('rov' in t.casefold()) and any(k in t.casefold() for k in ('mlbb', 'mobile legends')))
    channel_checks = []
    for game in ('rov', 'mlbb'):
        group = videos.loc[videos.game == game]
        pre = group.loc[group.month.between(*before)]
        post = group.loc[group.month.between(*after)]
        shared = set(pre.channel_id) & set(post.channel_id)
        channel_checks.append(dict(game=game, before_active_channels=int(pre.channel_id.nunique()),
                                   after_active_channels=int(post.channel_id.nunique()), shared_active_channels=len(shared),
                                   before_videos_in_shared_channels=int(pre.channel_id.isin(shared).sum()),
                                   after_videos_in_shared_channels=int(post.channel_id.isin(shared).sum())))
    audit = dict(total_videos=len(videos), declared_channels=len(constants['ALL_CHANNELS']),
                 observed_channels=int(videos.channel_id.nunique()),
                 videos_outside_declared_channels=int((~videos.channel_in_notebook).sum()),
                 original_rule_mismatches=int((videos.original_rule_game != videos.game).sum()),
                 titles_mentioning_both_games_ignoring_case=int(videos.casefold_both_games.sum()),
                 limitation='Rule consistency only, not semantic accuracy or recall. Excluded/uncollected videos cannot be audited from this archive.',
                 channel_sensitivity=channel_checks)
    # A stable small sample is an inspection aid, never an estimated accuracy score.
    sample = videos.groupby('game', group_keys=False).sample(n=8, random_state=2026)
    destination = run_dir / 'report'
    destination.mkdir(exist_ok=True)
    pd.DataFrame(windows).to_csv(destination / 'matched_windows.csv', index=False, encoding='utf-8-sig')
    comparison.to_csv(destination / 'timezone_sensitivity.csv', index=False, encoding='utf-8-sig')
    sample[['game', 'video_id', 'channel_id', 'title', 'original_rule_game', 'casefold_both_games']].to_csv(destination / 'title_inspection_sample.csv', index=False, encoding='utf-8-sig')
    videos.loc[(videos.original_rule_game != videos.game) | videos.casefold_both_games,
               ['game', 'video_id', 'title', 'original_rule_game', 'casefold_both_games']].to_csv(destination / 'title_rule_exceptions.csv', index=False, encoding='utf-8-sig')
    evidence = dict(run_id=manifest['run_id'], alternative_run_id=alternative['run_id'],
                    original_notebook_sha256=hashlib.sha256(notebook.read_bytes()).hexdigest(),
                    matched_windows=windows, timezone_sensitivity=sensitivity, title_audit=audit,
                    design='Post hoc descriptive equal-length windows, not a pre-registered causal analysis. All archival API sampling remains unverified/partial.')
    write_json(destination / 'historical_analysis.json', evidence)
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--alternative-run-dir', required=True)
    parser.add_argument('--notebook', default='RovVsMlbb_Pipeline.ipynb')
    args = parser.parse_args()
    print(json.dumps(analyze(args.run_dir, args.alternative_run_dir, args.notebook), indent=2))
