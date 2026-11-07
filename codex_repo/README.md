# ThatsMyQuant: Algo Trade Arena

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

Six standalone candidates are prepared under [strategies/round2/](strategies/round2/):
direct transfer, strict-100 maker, faster adaptation, dual-memory maker,
guarded IOC trend, and a no-trade control. They are hypotheses for new data;
**no round-2 winner has been selected**.

The public tape has arrived at `data/round2_public.csv` (100 minutes, 2.19M
events). Its first-hour diagnostics show about **3.65x** the old 25-second
price volatility; all active reference strategies lost on that prefix. Read
[the initial findings](docs/ROUND2_INITIAL_FINDINGS.md). The later public
segments were initially unreplayed; no server score has been received.

Follow-up development research has reached **93,679 net** using exposure
inversely proportional to absolute realized volatility, versus **45,698**
for the corresponding fixed-50-lot jump-aware maker. This is first-60%
sample tuning, not a selected submission or a server result. The source is
[round2_absolute_vol_93679.py](strategies/round2_research/round2_absolute_vol_93679.py);
its evidence is [round2_development_93679.json](results/round2_development_93679.json).
The current development best is **112,379** with inverse-variance sizing
and three-second adaptation. Six candidates were frozen before selection on
the middle public20% at `logs/round2_selection_v1`; that comparison is now
running. The last public20% remains untouched.

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
