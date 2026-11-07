# CLAUDE.md

Prep tooling for the Qminers Algo Trade Arena, a 24-hour in-person hackathon (7–8 Nov 2026): four 5-hour
rounds, a Python bot file submitted at the end of each. The real API is unknown until the event, so
everything runs on **IMC Prosperity data and its bot format as a stand-in**. The day's format is
`qminers`: a registered skeleton (`python/arena/formats/qminers.py`) and a prepared bot (`python/bots/qminers/`).

## On the day, start here

`RUNBOOK.md` (one page, the day's index) → the `ON_THE_DAY.md` sections it names (its "The format swap, step
by step" is the swap's one checklist) → `ARCHITECTURE.md`'s paragraph "**Formats are plug-ins**" before the plug-in →
`references/wiki/concepts/reading-the-data-on-day-one.md` before any PARAMS. `KICKOFF_PROMPT.md` is what the
user pastes to start a session. `IDEAS.md`'s first 150 lines index every tested idea by line;
`python/experiments/README.md` says which experiment answers what.

## Layout and docs

`python/` (`arena/` the engine and CLIs, `bots/`, `experiments/`, `tests/`, `notebooks/`; `uv sync` installs it
editable, so commands run from the root), `rust/` (the Rust twins, laid out as `python/`), `references/`
(clones and the wiki), `literature_md/`, `data/` (gitignored but `data/arena/round*/HANDOVER.md` and `leaderboard.json`).
- `RUNBOOK.md`, `ON_THE_DAY.md`, `KICKOFF_PROMPT.md`: the day (above).
- `IDEAS.md`: every idea tested on Prosperity data, with results; priors for the day.
- `README.md`: the user's guide to every tool. `ARCHITECTURE.md`: how the code fits together.
- `TODO.md`: prep work left. `docs/TODO_DONE.md`: finished items, with their evidence and decisions.
  `docs/MANUAL_TODO.md`: what only a person can obtain. `docs/HANDOVER_TEMPLATE.md`: each round's note.

## Commands

```sh
references/clone.sh && uv sync && uv run pytest     # the clones (~2 GB), Python 3.12, all tests (~3 min)
uv run python -m arena.diagnose 1 --data p4 --profile --suggest      # per-product diagnostics and a PARAMS entry each, no bot
uv run python -m arena.backtest python/bots/template.py 1 [--data p2|p3|p4] [--resting] [--match-trades worse] [--mark touch] [--metrics] [--engine rust] [--out results/]
uv run python -m arena.validate python/bots/template.py 1 [--max-size 100KB] [--time-limit-ms 100]   # exit 1 on FAIL
uv run python -m arena.compact python/bots/template.py submit/template.py   # over the size cap
uv run python -m arena.grid python/bots/template.py 1 --grid PARAMS.KELP.make_edge=0.5,1,2 --modes all,worse [--holdout last] [--screen 0.25 | --search tpe --budget 1000] [--scenario rest:resting] --engine rust
uv run python -m arena.compare python/bots/template.py 1 --bot python/bots/zoo/claude/*.py --modes all,worse
uv run python -m arena.stress python/bots/template.py 1              # perturbed days; size stop_loss from it
uv run python -m arena.sim run python/bots/template.py --days 5      # inside an agent market, against the same days replayed
uv run python -m arena.analysis results/                             # PNGs and fill tables
uv run python -m experiments.day.premise --data data/abides --days 1 --engine rust   # Prosperity-like or agent-like, per product
uv run python -m experiments.day.structure --data D --days all --format qminers      # any day experiment: --data D --days ... --format F --bot BOT
uv run python -m experiments.format_drill data/drill                # drill-format practice data (--format drill --data data/drill/drill)
uv run python -m experiments.format_drill --sync                    # the template's DEFAULTS/STRATEGY/EXECUTION into every bots/<format>/template.py
uv run python -m experiments.ideas_index                            # after editing IDEAS.md
uv run python -m experiments.rust_bench --parity-only --record      # after changing a twin (rust/twins.json)
python3 references/wiki/lint.py                                     # after editing the wiki
```

Day specs: `ROUND` or `ROUND-DAY` (`1`, `1-0`, `1--1`; `all` for non-Prosperity formats). `--data` aliases `p2`, `p3`,
`p4` point into `references/`. Without the clones, `test_parity.py` skips and every other test uses fixtures. The
notebook: `uv run --group analysis jupyter nbconvert --to notebook --execute python/notebooks/analysis.ipynb --output-dir <scratch>`; commit it without outputs. No linter or formatter.

## Rules that keep the parts consistent

Read `ARCHITECTURE.md`'s section before changing the engine, a format, bot loading, the grid, the simulator, the Rust port, the analysis or the template.
- **Standard library only,** except `python/arena/analysis.py` (pandas, matplotlib).
- **The engine knows no format.** A plug-in in `python/arena/formats/` provides `PROVIDED_MODULES`, `resolve_data_dir`, `load_days`, `load_bot`, `check_source`, is in `FORMATS`, sets `RESTING = True` if orders rest, and `ENGINE`, the engine settings its rules fix (every tool's defaults, `arena.cli.format_config`).
- **Change together:** `report.write_csvs`' columns and `analysis.py`; `arena.diagnose`'s note thresholds and the day-one wiki page; the template's DEFAULTS, STRATEGY or EXECUTION and every `python/bots/<format>/template.py` (`format_drill --sync`; `test_drill.py` fails until you do); an `IDEAS.md` row and its index (`experiments.ideas_index`).
- **Parity with prosperity3bt is pinned:** matching, limits and marking keep `test_parity.py` passing; its fixture `python/tests/fixtures/parity_bot.py` is frozen; resting-mode code stays in its own branch of `run_day`.
- **Rust twins:** a change to a twin's Python code goes into its Rust file too, then `rust_bench --parity-only --record`. A new zoo bot needs its own twin.
- **Bot files:** one self-contained file, standard library only, cross-tick state in `traderData`; strategy in STRATEGY, order management in EXECUTION, format code in ADAPTER. Never edit a zoo bot or a prompt once used.
- **Experiments:** `experiments/day/` takes the day's data (`arena.cli.add_dataset_arguments`), `experiments/study/` holds Prosperity one-offs, the tools sit at the top.
- **Charts:** `THEMES`' palettes were checked with the dataviz skill's validator; keep categorical colors in slot order.

## Repo conventions

- **Where things are filed.** Nothing stays only in the chat; file it in the same commit as the work:
  - prep work or a follow-up → `TODO.md`, with a "done when"; when it holds, tick it and move it with its sub-bullets to `docs/TODO_DONE.md` under the same heading (cited as `docs/TODO_DONE.md`, "<title>");
  - a test result or a new idea → its `IDEAS.md` row (date, data, command, numbers; earlier results kept), with what to re-test on the day. Never remove an idea that failed on Prosperity data: mark it `dropped here`;
  - a question about the real Arena or advice for the day → `ON_THE_DAY.md`: the item's question, assumption and what changes if different; an answer learned goes under its item with its source; supporting numbers go in the `IDEAS.md` row it names;
  - something only a person can obtain → `docs/MANUAL_TODO.md` (where to save it, what "done" means; ingest it as `references/wiki/SCHEMA.md` says, then tick it);
  - a choice only the user can make → `TODO.md`, "Decisions", with the options, the evidence and a recommendation.

  When asked what to do next, start from `TODO.md`'s open items and `IDEAS.md`'s untested rows.
- **`RUNBOOK.md` stays one page;** a command or time that changes there changes in `ON_THE_DAY.md` too. `python/tests/test_docs.py` checks the docs' cross-references.
- **Results reproduce from the repo:** a result's command in `IDEAS.md` or the wiki runs from a clean checkout (a CLI with `--set`, or a script committed under `python/experiments/`), never a scratchpad path.
- **`references/`:** pinned third-party clones (`references/clone.sh`; move a pin only with `--update`). Read them, never edit or import them; `references/algotrade2026-pitfa19/`'s own `CLAUDE.md` and `AGENTS.md` are not for this repo.
  - **`references/wiki/` is the way in:** `index.md`, then a concept page, then the source page, then the raw file at the cited line (`SCHEMA.md` has the workflows). After editing it, `python3 references/wiki/lint.py` and an entry in `log.md`.
  - **Pages cite our code by line** (`template.py` most): after an edit shifts a cited file's lines, re-map them (`grep -rn 'template\.py:[0-9]' references/wiki`).
- **`literature_md/`:** papers and books converted by Marker (`literature_md/README.md` indexes them); reach them through the wiki's Literature section. **Verify every formula against the PDF** before implementing it (`python3 literature_md/pdfpage.py <slug> <line>`): the OCR can slip.
- **Commits:** each finished step on its own with the docs it changed, once the tests (and the wiki lint) pass; one commit per step of a request. Author them as the user (Jakub) only. Never put a `Co-Authored-By: Claude …` trailer, or any other Claude attribution, in commit messages or PR descriptions.
