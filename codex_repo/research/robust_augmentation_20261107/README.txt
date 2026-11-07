Bounded augmentation of upstream 554347 model, 7 November 2026

protocol.json was written before all candidate replays; selection.json froze
the one candidate before later-period, transfer and latency confirmation.
If screening fails, the diagnostic finalist cannot be promoted afterwards.
decision.json records every gate. summary.json adds exact-export verification.
All datasets are previously consumed. Results are robustness checks, not a new
holdout. No website/private leaderboard result is claimed.

Source paths in the protocol describe the original logs/robust_augmentation
working directory. Frozen source bytes are retained in sources/. The untouched
upstream strategy remains strategies/round1_submission.py. Reproduction:

python -m unittest discover -s tests -v
python -m scripts.probe_robust_augmentation --prepare --root logs/augmentation_replay --source strategies/round1_submission.py --data data/round1.csv --prefix PATH_TO_6000_SECOND_PREFIX --transfer data/sample_v2.csv
python -m scripts.probe_robust_augmentation --root logs/augmentation_replay --data PATH_TO_6000_SECOND_PREFIX --stage screen --workers 8
python -m scripts.probe_robust_augmentation --root logs/augmentation_replay --select

Use full_* stages for round1 and sample_* for sample_v2, --names for the frozen
controls/finalist and --delay 20 or 50 for stress. Every prefix must retain the
full event tape from its beginning; do not restart mid-book.
python -m scripts.benchmark_depth_submission --strategy strategies/round1_robust_candidate.py --data data/round1.csv --output logs/augmentation_export.json

Matching engine files are unchanged. New feature transforms are pure arithmetic
over existing depth aggregates; all execution/risk methods remain unchanged.
