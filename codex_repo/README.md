# ThatsMyQuant: Algo Trade Arena

Current user objective: **250,000 local net PnL**. The previous 150k objective
was achieved; the higher objective is still active. See
[250k research](docs/ROUND2_250K_RESEARCH.md). Competition server access remains off.
Current verified local best: **230,611**, with zero penalties; see
[the exact candidate](strategies/round2/round2_local_230611.py).

Start with [HANDOFF.md](HANDOFF.md). The next-round workflow is in
[docs/ROUND2_PLAN.md](docs/ROUND2_PLAN.md); the organizer's original documentation
is preserved in [docs/ORGANIZER_GUIDE.md](docs/ORGANIZER_GUIDE.md).

## Frozen round-1 result

The verified local best is **624,076.00 net PnL** on `data/round1.csv`, including
**1,700.00** in inventory penalties. The unmodified organizer CLI reproduces
every result field. The user subsequently reported **8th of 61**, with **602,526.53** on the server.
The exact uploaded source and scored dataset have not been matched to that score.

- Submission: [strategies/round1_submission.py](strategies/round1_submission.py).
- Immutable named copy: [strategies/round1_quote_flow_624076.py](strategies/round1_quote_flow_624076.py).
- Metrics, hashes and verification: [results/round1_624076.json](results/round1_624076.json).
- Git tag: `round1-624076`; final round-1 commit: `77bc241`.

This improved the supplied 595,441.83 strategy by **28,634.17**. The reported leaderboard winner scored **792,696.00**, leaving a **190,169.47**
gap to our reported server score. The earlier 650K target was not reached. Round-1 data was repeatedly consumed;
later tuning results are sample-tuned, not independent holdouts.

[Strategies index](strategies/README.md) lists preserved versions, including
498,056, 523,999 and 605,752.82. Full historical notes are archived in
[docs/ROUND1_RESEARCH.md](docs/ROUND1_RESEARCH.md).

## Round-2 preparation

**Current local research:** best full replay **167,412 net PnL**, supplied M2
**116,620**, adaptive maker **105,829**, all with zero penalties. The updated
**150,000 local target is exceeded**. All public data has now been consumed.
Competition website/server access is prohibited by the user. See
[current progress](docs/ROUND2_LOCAL_PROGRESS.md). The preparation notes below
describe earlier experiments and are retained as history.

Latest research-branch finding: a composite conditional-fill model reached
85,435 on the development hour (including its first 30 minutes of training),
but lost **21,593** on the previously reserved next 20 minutes. It was rejected;
the **100,000 target remains unmet**. The first 80% of the public tape is now
consumed; the last 20% remains unreplayed. See
[the development and validation findings](docs/ROUND2_COMPOSITE_FINDINGS.md).
No round-2 submission is promoted and no server score is claimed.

Six standalone candidates are prepared under [strategies/round2/](strategies/round2/):
direct transfer, strict-100 maker, faster adaptation, dual-memory maker,
guarded IOC trend, and a no-trade control. They are hypotheses for new data;
**no round-2 winner has been selected**.

The public tape has arrived at `data/round2_public.csv` (100 minutes, 2.19M
events). Its first-hour diagnostics show about **3.65x** the old 25-second
price volatility; all active reference strategies lost on that prefix. Read
[the initial findings](docs/ROUND2_INITIAL_FINDINGS.md). The later public
segments are still unreplayed; no server score has been received.

The reference workflow below is for a fresh study directory. The default
`logs/round2` intake, profile and screen have already completed; do not overwrite
it or freeze a no-trade winner prematurely while developing new policies:

```bash
.venv/bin/python -m scripts.round2_workbench prepare --backtest data/round2_public.csv --output logs/round2_next_study
.venv/bin/python -m scripts.profile_round --backtest logs/round2_next_study/development.csv --output logs/round2_next_study/profile
.venv/bin/python -m scripts.round2_workbench screen --output logs/round2_next_study --workers 3
.venv/bin/python -m scripts.round2_workbench select --output logs/round2_next_study --workers 3
.venv/bin/python -m scripts.round2_workbench public-check --output logs/round2_next_study
```

These are internal splits of the **public** tape. The organizer separately
provides server validation PnL and scores an unseen private tape after the
deadline. Public data is roughly half their size; size does not imply duration.
The local workflow screens 60%, selects on 20%, and checks the remaining 20%. Model state and
inventory remain continuous within each replay. Final evaluation also invokes
the unmodified organizer CLI and checks every result field exactly.

`public-check` (legacy alias `final`) writes `logs/round2/frozen_submission.py` and `final_report.json`.
It does not overwrite the round-1 submission. Do not profile the full new tape
before preserving the final evaluation segment. Read the plan before tuning
beyond the predeclared candidates.

## Checks and tools

```bash
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python -m scripts.build_round2_candidates --check
.venv/bin/python scripts/check_submission.py strategies/round1_submission.py
```

The existing `.venv` works. A fresh checkout can follow the organizer's setup
instructions. Offline `uv sync` previously failed despite cached packages;
use the existing interpreter in this workspace.

[Scripts index](scripts/README.md) identifies the active tools and historical
search scripts. Raw CSVs, simulation logs, caches and Finder metadata are
ignored by Git. Preserved strategies, tests, source manifests and compact
result reports are tracked.

## Repository and team

Origin is `git@github.com:jakub-kucera/qminers-arena-hachathon-final-v2.9-fr-fr.git`.
The repository retains organizer history and the original simulator. Direct
pushes last failed here because DNS could not resolve `github.com`; the GitHub
connector also returned 404 for this repository. From an authorized terminal:

```bash
git push origin main --follow-tags
```

[TEAM.txt](TEAM.txt) covers ThatsMyQuant and this session's Astra/Sol usage only.

## Earlier research branch studies

Preserved [penalty study](research/penalty_tradeoff_20261107/report.html),
[future-round burst hypothesis](research/penalty_tradeoff_20261107/FUTURE_ROUNDS.md),
and [bounded augmentation study](research/robust_augmentation_20261107/report.html)
describe earlier round-1 baselines; they do not supersede the later 624,076 result.
