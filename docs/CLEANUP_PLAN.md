# Cleanup plan (7 Nov, before round 1): a plan only, nothing changed yet

The repository grew for six weeks around IMC Prosperity as a stand-in. Since the Arena's real API arrived (the starter
merged at the root, 7 Nov), only part of it is on the day's path. This plan says what to change, in what order, and
what not to touch. The user decides when (`TODO.md`, "Decisions": "The cleanup plan"); nothing here runs during a round.

## What the Arena uses now
- Their `simulator/`, `explorer/`, `strategies/`, `data/sample.csv.gz` (the root, as they wrote them).
- `python/bots/qminers/`: `template.py` (ArenaBot), `families/` (five strategies in their style), `candidates/`.
- `python/arena/qgrid.py`, `python/arena/qsim_rust.py`, `rust/arena_sim/` (the Rust port, byte-identical to theirs).
- `python/experiments/rounds/round_start.py`, `python/experiments/rounds/run_review.py`.
- `python/arena/validate.py`'s source checks with `python/arena/formats/qminers.py`'s `SANDBOX` (its loader half is unused).
- The day's docs: RUNBOOK, ON_THE_DAY's 7 Nov blocks, KICKOFF's prompts, `data/arena/round*/`.

## What is ballast for the Arena (but is research the organisers read)
- Our own engine and its tools on Prosperity-format data: `arena.backtest/grid/compare/stress/diagnose/sim/analysis`,
  most of `python/experiments/day/` (32 modules) and `study/` (26), the Rust twins in `rust/src` (65 files, 11k lines,
  `rust/twins.json`), the formats `prosperity`, `snapshots`, `drill`, `orderlog`.
- `python/bots/zoo/` (58 bots), `python/bots/rivals/`, the mock rounds (`python/experiments/mock_round/`, 71 files),
  `docs/guidebook/` (157 files), `references/wiki/` (126 pages, ~1,900 line citations into our code and the clones).
- The docs' size: IDEAS 331 KB (94 Prosperity rows, 5 Arena rows), README 76 KB, ON_THE_DAY 96 KB, ARCHITECTURE 39 KB.

## Principles
- **Delete nothing that is research.** The organisers review the history and say "keep research reusable: behind a
  parameter or flag instead of deleting it" (the info page). Ballast is moved out of the way or labelled, not removed.
- **No rewrite of history** (the repository is shared): every step is an ordinary commit.
- **Each step on its own commit**, the tests (`uv run pytest`) and the wiki lint passing, during a break between rounds.
- **Don't move cited files**: the wiki's ~1,900 citations and IDEAS' reproduce-commands name paths; a move costs a
  re-mapping pass per moved file (the 7 Nov `template.py` re-map took 63 citations). Prefer labels over moves.

## Steps, most value first
1. **The front door (docs only, ~30 min).** README.md and CLAUDE.md open with the Arena: their simulator, our bot and
   families, `round_start`, `qgrid`/`qsim_rust`, `run_review`, `validate`; the Prosperity tooling becomes one section
   "Prosperity-era tools (priors)". ARCHITECTURE gains a first section "The Arena path" (the list above) and labels
   the rest. Risk: low (test_docs checks the links).
2. **`formats/qminers.py` reduced to what is used** (~200 lines of an unused snapshots loader): keep `SANDBOX`,
   `PROVIDED_MODULES`, `check_source` (made to accept one `BaseStrategy` subclass) and the registration; move the
   loader-half tests (`test_skeletons.py`'s qminers cases, `test_qminers_scaffold.py`) to skip or drop. Then
   `arena.validate BOT` runs its source checks without data and stops (no replay), so the docs' "ignore the
   entry-point FAIL" note goes. Risk: low-medium (tests).
3. **IDEAS.md: the Arena first.** A section "On the Arena (7 Nov on)" above the Prosperity rows, with the five
   families' rows and the template grids moved there; the index (`experiments.ideas_index`) regenerated. No row
   deleted. Risk: low (the index tool, test_docs).
4. **The Rust port extended** (an improvement more than a cleanup): the momentum runner and the protected maker in
   `rust/arena_sim` with parity tests, so round 2's grids run on the real tape in seconds. Risk: medium (parity).
5. **Optional, after the event:** move the Prosperity-only experiments under `python/experiments/prosperity/` with a
   citation re-map script (like the 7 Nov one for `template.py`), and the zoo and rivals under
   `python/bots/prosperity/`. Only worth it if the repository lives on after the Arena.

## Not planned
- Rewriting our engine to match theirs: their simulator (and its Rust port) is the engine now.
- Deleting the wiki, the guidebook, the mock rounds or the zoo.
