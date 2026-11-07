# Repository orientation

Read [HANDOFF.md](HANDOFF.md) first and [docs/ROUND2_PLAN.md](docs/ROUND2_PLAN.md)
before evaluating new round data. The existing `.venv/bin/python` works.
Round 2 has three organizer datasets: public training, server validation with
PnL-only feedback, and post-deadline private scoring. Local public splits are
only internal diagnostics. Do not call a local `public-check` private evaluation.
Record server feedback separately, tied to exact source snapshots; validation
feedback used for tuning is not an untouched final assessment.

Preserve the round-1 submission, immutable named strategies, result manifests,
Git history, and data. Its final verified source is
`strategies/round1_quote_flow_624076.py`; `round1_submission.py` is byte-identical.
New work belongs in the round-2 candidates and a separate experiment directory.

Strategy exports must be standalone files with exactly one no-argument
`BaseStrategy` subclass and only the documented imports/APIs. The simulator's
engine, latency, acceptance wall and penalties are authoritative. Compare net
PnL including all native penalties. The old strict-only search runners reject
the paid overlap used by the final round-1 model; use the round-2 workbench.

Keep candidate source hashes and dataset hashes with results. Preserve fresh
chronological evaluation data before tuning; round-1 data is already consumed.
The workbench freezes sources and verifies final results against the unmodified
organizer CLI. Its boundary marks do not advance or mutate the native clock.

Useful checks are `python -m unittest discover -s tests -q`,
`python -m scripts.build_round2_candidates --check`, and
`python scripts/check_submission.py PATH`. Use the existing virtual environment.
Do not regenerate over edited candidates: inspect/review changes and update the
registry deliberately. Keep all promoted models in Git and retain their archives.

TEAM.txt is scoped to this repository/session. Do not add AI usage from the
user's other repositories. Network push failures must be reported honestly;
local commits and Git bundles are not evidence that origin was updated.
