# ThatsMyQuant: Algo Trade Arena

Start with [HANDOFF.md](HANDOFF.md). The next-round workflow is in
[docs/ROUND2_PLAN.md](docs/ROUND2_PLAN.md); the organizer's original documentation
is preserved in [docs/ORGANIZER_GUIDE.md](docs/ORGANIZER_GUIDE.md).

## Frozen round-1 result

The verified local best is **624,076.00 net PnL** on `data/round1.csv`, including
**1,700.00** in inventory penalties. The unmodified organizer CLI reproduces
every result field. The competition-server result has not been recorded here.

- Submission: [strategies/round1_submission.py](strategies/round1_submission.py).
- Immutable named copy: [strategies/round1_quote_flow_624076.py](strategies/round1_quote_flow_624076.py).
- Metrics, hashes and verification: [results/round1_624076.json](results/round1_624076.json).
- Git tag: `round1-624076`; final round-1 commit: `77bc241`.

This improved the supplied 595,441.83 strategy by **28,634.17**. The reported
650K competitor target was not reached. Round-1 data was repeatedly consumed;
later tuning results are sample-tuned, not independent holdouts.

[Strategies index](strategies/README.md) lists preserved versions, including
498,056, 523,999 and 605,752.82. Full historical notes are archived in
[docs/ROUND1_RESEARCH.md](docs/ROUND1_RESEARCH.md).

## Round-2 preparation

Six standalone candidates are prepared under [strategies/round2/](strategies/round2/):
direct transfer, strict-100 maker, faster adaptation, dual-memory maker,
guarded IOC trend, and a no-trade control. They are hypotheses for new data;
**no round-2 winner has been selected**.

After the new tape arrives, run these commands from the repository root:

```bash
.venv/bin/python -m scripts.round2_workbench prepare --backtest data/round2.csv
.venv/bin/python -m scripts.profile_round --backtest logs/round2/development.csv --output logs/round2/profile
.venv/bin/python -m scripts.round2_workbench screen --workers 3
.venv/bin/python -m scripts.round2_workbench select --workers 3
.venv/bin/python -m scripts.round2_workbench final
```

The workflow snapshots source files, screens the first 60%, selects using the
next 20%, freezes the winner, and then evaluates the final 20%. Model state and
inventory remain continuous within each replay. Final evaluation also invokes
the unmodified organizer CLI and checks every result field exactly.

`final` writes `logs/round2/frozen_submission.py` and `final_report.json`.
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
