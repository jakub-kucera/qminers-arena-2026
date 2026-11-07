Inventory penalty tradeoff, 7 November 2026

The exchange configuration remains max_position=100, max_potential_position=1000,
and penalty=10000 per second above the soft limit. Strategy caps do not alter
those settings. Net PnL always includes the actual engine penalty.

protocol.json freezes the first nine candidates plus two controls. The initial
guarded candidates produced no realized breaches, so activation_protocol.json
preregisters five additional activation probes. It records that deviation and
expands the joint selection family to fourteen. No candidate passed screening.
selection.json freezes one active diagnostic; it cannot be promoted afterwards.
baseline_references.json records reused source/data/engine-verified controls.
All public data has been consumed before; no new holdout or website score exists.

Frozen source bytes are in sources/. Original working paths under logs/ are
retained in metadata. Raw tapes and large per-event traces are excluded.

From repository root:
python -m unittest discover -s tests -v
python -m scripts.probe_penalty_tradeoff --prepare --root logs/penalty_replay --source strategies/round1_robust_candidate.py --data data/round1.csv --prefix PATH_TO_6000_SECOND_PREFIX --transfer data/sample_v2.csv
python -m scripts.probe_penalty_tradeoff --root logs/penalty_replay --data PATH_TO_6000_SECOND_PREFIX --stage screen --workers 8
python -m scripts.probe_penalty_tradeoff --root logs/penalty_replay --prepare-activation
Run activation_screen with the five active_* names from activation_protocol.json,
then --select. Full_* stages use round1 boundaries; sample_* use sample_v2.
--delay 20 and --delay 50 supply latency stress. Use a complete prefix from tape
start, never an empty-book restart in the middle of a tape.

python -m scripts.benchmark_depth_submission --strategy strategies/round1_penalty_experimental.py --data data/round1.csv --output logs/penalty_export.json
