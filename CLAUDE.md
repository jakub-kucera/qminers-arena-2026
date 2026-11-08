# CLAUDE.md

Prep tooling for the Qminers Algo Trade Arena, a 24-hour in-person hackathon (7–8 Nov 2026): four 5-hour
rounds, a Python bot file submitted at the end of each. The real API is the organisers' starter (`STARTER.md`).
Our engine and tools were built before it on **IMC Prosperity data as a stand-in**: their results are priors.

## The Arena path (start here)

`RUNBOOK.md` (one page, the day's index) → the `ON_THE_DAY.md` sections it names → `STARTER.md` and `ON_THE_DAY.md`'s
"Known so far" (7 Nov) before any PARAMS; `data/arena/round*/` holds each round's `HANDOVER.md` and `CANDIDATES.md`;
`KICKOFF_PROMPT.md` is what the user pastes to start a session; `ARCHITECTURE.md`'s "The Arena path" says how it fits.
- Their `simulator/`, `explorer/`, `strategies/`, `data/sample.csv.gz` at the root, as they wrote them: the engine.
- `python/bots/qminers/`: `template.py` (`ArenaBot`), `families/` (five strategies in their style), `candidates/`.
- **Rust first:** grid and compare in the Rust port (`arena.qsim_rust`, about 10 s a 6,000-s tape against 150-200 s in
  Python); a new idea gets its knob in `rust/arena_sim/src/strategies/ridge_maker.rs` (off by default, byte-identical)
  before it is tuned. Python's `exchange-simulator` is for the upload file's last check and full-logs runs.
- **Judge on the round's own tapes:** its public tape (first 75% / last 25%), its mirror and tapes stitched from its own
  segments (`tape_character stitch`); earlier rounds' tapes only as extra regimes, the last round's pick only a start.
  Each upload is a paired test: read its validation score against the local table in `data/arena/round*/CANDIDATES.md`.
- **14 cores, shared with the agents** (at most five at once): keep the total of parallel runs near 14 (load 53 on 8 Nov).
- The generator's structure (latent price, √-impact, calm / volatile regimes, jumps): `docs/GENERATOR_PLAN.md`.

```sh
uv run exchange-simulator --strategy BOT --backtest D/<file>.csv --log-dir logs/<run> [--no-logs]   # their simulator (unzip first)
uv run backtest-explorer --log-dir logs/<run>                        # their Dash app on a full-logs run
uv run python -m experiments.day.round_start data/round1.csv.gz [--jobs N] [--out DIR]   # the round's first look: tape profile, markouts, every candidate ranked, next grids
uv run python -m arena.qgrid python/bots/qminers/template.py data/sample.csv.gz --set 'PARAMS.ASSET={"fair": "mid"}' --grid PARAMS.ASSET.make_edge=0,1,2 [--holdout 0.25] [--out results/qgrid.csv]
uv run python -m arena.qsim_rust fallback_maker data/sample.csv.gz --grid QUOTE=2,5 --threads 4   # the same, its Rust port (rust/arena_sim)
uv run python -m experiments.day.family_rust D/<tape>.csv [MORE.csv ...] [--bot NAME=L8:'--set K=V']   # the forecast takers in Rust, every bot on every tape
uv run python -m experiments.day.tape_character stitch D/<tape>.csv --dir DIR --only hi_vol_fast1.25 --keep   # a validation-like tape from the round's own segments
uv run python -m experiments.day.run_review logs/<run>               # our fills against the mid, from a full-logs run
uv run python -m arena.validate BOT all --format qminers             # the sandbox's source checks; exit 1 on FAIL
```

## Prosperity-era tools (priors)

`python/` (`arena/` our engine and CLIs, `bots/`, `experiments/`, `tests/`, `notebooks/`; `uv sync` installs it
editable, so commands run from the root), `rust/` (the Rust twins, laid out as `python/`), `references/`
(clones and the wiki), `literature_md/`, `data/` (gitignored but `data/arena/round*/HANDOVER.md` and `leaderboard.json`).
`IDEAS.md`'s first 150 lines index every tested idea by line; `python/experiments/README.md` says which experiment
answers what. `README.md`: the user's guide to every tool. `TODO.md`: prep work left; `docs/TODO_DONE.md`: finished
items; `docs/MANUAL_TODO.md`: what only a person can obtain; `docs/HANDOVER_TEMPLATE.md`: each round's note.

```sh
references/clone.sh && uv sync && uv run pytest     # the clones (~2 GB), Python 3.13, all tests (~4 min)
uv run python -m arena.diagnose 1 --data p4 --profile --suggest      # per-product diagnostics and a PARAMS entry each, no bot
uv run python -m arena.backtest python/bots/template.py 1 [--data p2|p3|p4] [--resting] [--match-trades worse] [--mark touch] [--metrics] [--engine rust] [--out results/]
uv run python -m arena.compact python/bots/template.py submit/template.py   # over the size cap
uv run python -m arena.grid python/bots/template.py 1 --grid PARAMS.KELP.make_edge=0.5,1,2 --modes all,worse [--holdout last] [--screen 0.25 | --search tpe --budget 1000] --engine rust
uv run python -m arena.compare python/bots/template.py 1 --bot python/bots/prosperity/zoo/claude/*.py --modes all,worse
uv run python -m arena.stress python/bots/template.py 1              # perturbed days; size stop_loss from it
uv run python -m arena.sim run python/bots/template.py --days 5      # inside an agent market, against the same days replayed
uv run python -m arena.analysis results/                             # PNGs and fill tables
uv run python -m experiments.prosperity.structure --data D --days all --format F            # any day experiment: --data D --days ... --format F --bot BOT
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
- **Standard library only,** except `python/arena/analysis.py` (pandas, matplotlib) and `python/arena/qgrid.py` (the Arena's `simulator`).
- **The engine knows no format.** A plug-in in `python/arena/formats/` provides `PROVIDED_MODULES`, `resolve_data_dir`, `load_days`, `load_bot`, `check_source`, is in `FORMATS`, sets `RESTING = True` if orders rest, and `ENGINE`, the engine settings its rules fix (every tool's defaults, `arena.cli.format_config`).
- **Change together:** `report.write_csvs`' columns and `analysis.py`; `arena.diagnose`'s note thresholds and the day-one wiki page; the template's DEFAULTS, STRATEGY or EXECUTION and every `python/bots/<format>/template.py` (`format_drill --sync`; `test_drill.py` fails until you do); an `IDEAS.md` row and its index (`experiments.ideas_index`).
- **Parity with prosperity3bt is pinned:** matching, limits and marking keep `test_parity.py` passing; its fixture `python/tests/fixtures/parity_bot.py` is frozen; resting-mode code stays in its own branch of `run_day`.
- **Rust twins:** a change to a twin's Python code goes into its Rust file too, then `rust_bench --parity-only --record`. A new zoo bot needs its own twin.
- **Bot files:** one self-contained file, standard library only, cross-tick state in `traderData` (the Arena bot: also numpy, pandas, scipy, sklearn, `simulator.models`, `BaseStrategy`; state on the instance); strategy in STRATEGY, order management in EXECUTION, format code in ADAPTER. Never edit a zoo bot or a prompt once used.
- **Experiments:** `experiments/day/` holds the Arena's round tools (`round_start`, `run_review`), `experiments/prosperity/` the Prosperity-era ones (`arena.cli.add_dataset_arguments`), the tools sit at the top.
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
- **`literature_md/`:** papers and books converted by Marker (`literature_md/README.md` indexes them), on disk only: the conversions are ignored, and out of the history since 2026-11-07, because the repository is shared; reach them through the wiki's Literature section. **Verify every formula against the PDF** before implementing it (`python3 literature_md/pdfpage.py <slug> <line>`): the OCR can slip.
- **Commits:** each finished step on its own with the docs it changed, once the tests (and the wiki lint) pass; one commit per step of a request. During the Arena the repository is shared with the organisers, who read its history: commit at least every 30 minutes, failed experiments too with a note, and never squash, rebase or force-push. Author them as the user (Jakub) only. Never put a `Co-Authored-By: Claude …` trailer, or any other Claude attribution, in commit messages or PR descriptions.
