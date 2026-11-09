Depth advantage experiment, 7 November 2026

The supplied strategy is AST-identical to strategies/round1_depth_524k.py;
its attachment differed only in final-newline encoding. The 16-feature candidate
adds signed nonlinear transforms of touch order-count imbalance, capped-volume
touch imbalance, and capped-volume depth imbalance. All execution rules match.
Unused queue tracking was removed after exact full-replay equivalence checks.

protocol.json was written before candidate replays; selection.json was written
before any finalist full-round or transfer replay. The original protocol retains
the working logs/depth_advantage source paths. Frozen source bytes are copied
under sources/. Stage JSON files preserve every result, including rejected ideas.
Raw market datasets are intentionally excluded. Source and data hashes are saved.
The old public data is consumed data; chronological gates are robustness checks,
not a new untouched holdout. No new website submission was made.

Reproduce from the repository root with Python 3.13 and project dependencies:
python -m unittest discover -s tests -v
python -m scripts.probe_depth_advantage --prepare --root logs/depth_replay --attachment research/depth_advantage_20261107/sources/supplied_13.py --data data/round1.csv --prefix PATH_TO_6000_SECOND_PREFIX
python -m scripts.probe_depth_advantage --root logs/depth_replay --data PATH_TO_6000_SECOND_PREFIX --stage screen --workers 7
python -m scripts.probe_depth_advantage --root logs/depth_replay --select
python -m scripts.benchmark_depth_submission --strategy strategies/round1_depth_advantage.py --data data/round1.csv --output logs/depth_export.json

Prefixes must retain the complete tape from its beginning, not start mid-book.
Full and transfer runs use the same probe command with --names, --stage, --delay.
Use full_* stages for round1 boundaries, sample_* for sample_v2 boundaries.
Existing result destinations are never overwritten by the runner.
