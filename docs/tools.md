# Tools for the Arena

How to run the Arena's tools: the organisers' `exchange-simulator`, our bot template `python/bots/qminers/template.py`
(`ArenaBot`) and the tools around it, the grid on their simulator and its Rust port, and the source check before an
upload. This is the Arena part of the guide the repository had during the event (the old README); its
Prosperity-era part, the backtester and its CLIs on IMC Prosperity data, is in the prep repository. Paths and
commands are as they were on 7-8 Nov.

## The Arena path

What the day runs on, in the order a round uses it (since 7 Nov; everything after
[Prosperity-era tools (priors)](#prosperity-era-tools-priors) was built on the stand-in and gives priors only):

| Path | What it is |
|---|---|
| `simulator/`, `explorer/`, `strategies/`, `data/sample.csv.gz` | The organisers' starter as they wrote it ([`STARTER.md`](../STARTER.md)): `uv run exchange-simulator --strategy BOT --backtest D/<file>.csv --log-dir logs/<run> [--no-logs]` is the engine; `uv run backtest-explorer --log-dir logs/<run>` its Dash app |
| `python/bots/qminers/template.py` | `ArenaBot`, a `BaseStrategy` subclass: the template's STRATEGY and EXECUTION with an ADAPTER for their API (set `PARAMS["ASSET"]`) |
| `python/bots/qminers/families/` | Five strategies in their style: `momentum_runner.py`, `momentum_taker.py`, `momentum_maker.py`, `protected_maker.py`, `run_fade.py` (`IDEAS.md`, "On the Arena (7 Nov on)") |
| `python/bots/qminers/candidates/` | The files ready to submit, `r<round>_<id>_<name>.py` (M1, M2 the runners, F1 the fallback maker, A0-A6 the playground's) |
| `python -m experiments.rounds.round_start DATA.csv[.gz]` | A round's first look: the tape's profile and markouts, every candidate ranked on it, the next grids |
| `python -m arena.qgrid BOT DATA` | A parameter grid on their simulator ([below](#grid-on-the-arenas-simulator)) |
| `python -m arena.qsim_rust STRATEGY DATA` | The same grid on `rust/arena_sim`, their simulator ported to Rust: the same numbers to the bit, 50-100 times faster |
| `python -m experiments.rounds.run_review LOG_DIR` | A full-logs run (ours or the portal's results folder): our fills' edge and the mid's move after them |
| `python -m arena.validate BOT all --format qminers` | The source checks before an upload, no `--data`, no replay ([below](#validate-before-submitting)) |
| [`RUNBOOK.md`](day/RUNBOOK.md), `data/arena/round*/` | The day's one page, and each round's `HANDOVER.md` and `CANDIDATES.md` |

## Setup

```sh
references/clone.sh   # reference repos + Prosperity data (~2 GB)
uv sync               # Python 3.13; installs the starter's packages and ours, python/ as the project (editable), so `python -m arena...` runs from here; the engine needs only the standard library, dev adds pytest and matplotlib
uv run pytest
uv run --group analysis jupyter lab python/notebooks/analysis.ipynb   # optional: Jupyter
```

## Grid on the Arena's simulator

`arena.grid` runs on the stand-in engine; `arena.qgrid` runs a grid on the Arena's own exchange simulator
(`simulator/`, [STARTER.md](../STARTER.md)) at the rules' settings (`simulator.main`'s 5 ms accept delay,
position limit 100, potential-position cap 1,000, 10,000 a second over the limit):

```sh
uv run python -m arena.qgrid python/bots/qminers/template.py data/sample.csv.gz \
    --set 'PARAMS.ASSET={"fair": "mid"}' \
    --grid PARAMS.ASSET.make_edge=0,1,2 --grid PARAMS.ASSET.make_size=5,10 \
    [--jobs N] [--holdout 0.25] [--sort pnl|holdout|nbhd] [--top 15] [--out results/qgrid.csv]
```

The bot is any file with a `BaseStrategy` subclass (the alphabetically first is run, as their loader does),
loaded fresh for each run, `--set` then the cell's `--grid` values applied to its globals (`--grid` takes
`V1,V2,...` or `START..STOP[..STEP]`, as in `arena.grid`). The template's `PARAMS` is empty, so
`--set 'PARAMS.ASSET={...}'` creates the asset's entry that the grid's `PARAMS.ASSET.*` keys go into. Data
files are the starter's CSVs (a `.csv.gz` is unpacked to a temporary file). Every cell, and the bot as is with
only `--set` (the `base` row, shown first), runs on each file in a process pool (`--jobs`, default the CPU
count). The columns, summed over the files unless noted:

| Column | Meaning |
|---|---|
| `pnl` | the simulator's PnL (cash + inventory marked out − breach penalty); with several files, one column per file follows |
| `in 75%`, `out 25%` | from the 1-second PnL curve, the PnL over each file's first 1 − `--holdout` of the time and over the last share: a time-split held-out check (`--sort holdout` ranks by the held-out part) |
| `nbhd` | mean `pnl` of the cell and its one-step neighbours on each axis (`arena.grid`'s rule): prefer a plateau to a peak |
| `max dd` | the largest fall from a peak of the PnL curve, the files' curves chained |
| `breach` | the position-breach penalty, already in `pnl` |
| `fills`, `volume` | our orders that filled, and the lots traded |
| `\|inv\| q997` | the time-weighted 99.7% quantile of the absolute inventory (the largest over the files) |
| `pnl se` | the simulator's standard error of the PnL (stdev × √n of its 1-second increments) |
| `rej`, `cxl rej` | orders the exchange rejected (over the potential-position cap), and cancels or modifies rejected (the order had filled first) |

Below the table: the best cell by each of `pnl`, `holdout` and `nbhd` and whether they agree, a `!` line
naming the cells with a breach penalty or rejected orders, and `arena.grid`'s axis-end note (the best cell
on the lowest or highest of a numeric axis' three or more values: widen it). `--out` writes one row per cell
and the baseline with every number above and the per-file PnL. A cell whose bot raises shows its error.

**The same grid in Rust**, for a strategy with a Rust version (`trend_follower`, `fallback_maker`, the F1
candidate, `room_maker`, family 7, whose defaults are F3, `shrink_maker`, family 10, the same with `DEPL_FRAC`,
`REACT_CANCEL` and `MOM_LOTS`, and family 12's `alloc_maker` and `signal_maker` at R1-F6's defaults with their knobs,
so R1-F6b and R1-F7 are a `--set` away, and `take_maker`, R1-F8's file `candidates/round1/r1_F8_take_join.py` at its own
defaults with its `TAKE_*`, `JOIN_*` and `ANY_CLEAR` knobs): `uv run python -m arena.qsim_rust fallback_maker
data/sample.csv.gz --grid QUOTE=2,3,5 --grid LIMIT=30,50 --threads 4` prints this table from `rust/arena_sim`, the
simulator ported to give the same numbers to the bit, 50-90 times faster a run ([rust/README.md](../rust/README.md),
"arena_sim"). The keys are the Python file's globals (`QUOTE`, `LIMIT`, `SKEW`, `WIND_DOWN_S`, `SESSION_S`; the room
maker's all 24, `LEVELS` to `FLAT_S`).

## Validate before submitting

```sh
uv run python -m arena.validate python/bots/template.py 1
uv run python -m arena.validate python/bots/my_bot.py 1 --allow numpy --time-limit-ms 900
uv run python -m arena.validate python/bots/template.py 1 --max-size 100KB     # the cap as the dashboard shows it
uv run python -m arena.compact python/bots/template.py submit/template.py      # over the cap: the same code, no comments or docstrings
```

It fails (exit code 1) on:
- what the portal's upload form refuses: a name not ending in `.py`, an empty file, or one bigger than `--max-size` (bytes, or the dashboard's figure: `100KB`, `1.5MB`; the dashboard rounds to a tenth of a binary unit, so `100KB` is checked as 99.95 × 1,024 bytes). Without `--max-size` it prints the size.
- a syntax error, or a missing entry point (`class Trader` with `run`)
- imports from outside the standard library that aren't listed in `--allow`
- what the format's sandbox rejects before a bot runs, where the plug-in lists it (`SANDBOX`; `--format qminers` has the Arena's, from their info page and `STARTER.md`: `os`, `sys`, `subprocess`, `socket`, `io`, `pathlib`, `threading`, `importlib`, `inspect`, `gc` and private modules; `open`, `getattr`, `type`, `eval`, `exec`; dunder attributes and names; `str.format`; from `simulator` only `simulator.models`' public names and `simulator.strategy.BaseStrategy`), each with its lines. `__future__` and `__init__` are allowed, as their own examples use `from __future__ import annotations` and `super().__init__()` and pass. It warns on builtins a sandbox often bans as well (`globals`, `setattr`, ...).
- any exception, or malformed orders (e.g. float prices)
- orders the engine cancels for possibly breaching a position limit
- a tick slower than `--time-limit-ms`, timed without the garbage collections that run inside the call (the backtester's objects, not the bot's work; the line says when it left some out, and the bot's own garbage is left out with them; a WARN when the figure with them is over the limit, since their clock may count them)
- a traded product with no `limit` in PARAMS (the template refuses it: DEFAULTS' is a placeholder)
- a gray-area bot: one that sets `GRAY_AREA = "<what it does>"` at module level because it games the exchange or other teams (spoofing, moving the mark, an exchange bug) rather than trading. It can be built and backtested, but validate FAILs it in capitals (and `arena.compact` warns), so it can't go up by accident; `--allow-gray-area` turns that into a WARN, only after an organiser has said it's allowed
- errors or breaches when the first day is replayed with every order a step late (`--late 1`, the default while the run's own `--delay` is 0; `--late 0` where the rules say orders arrive at once): a bot that doesn't count what it sent and can't see listed yet re-posts it into the caps and its limits, as both 2026-10-30 rehearsal bots did after passing. The template passes once its `DELAY` (and `ORDERS_REST`) are set; race ticks are printed, not failed

**The Arena bot** (`--format qminers`) needs no `--data`: `uv run python -m arena.validate
python/bots/qminers/candidates/round0/r0_M2_runner_safe.py all --format qminers [--max-size 1MiB]` runs the file and source
checks only (the size; exactly one `BaseStrategy` subclass, 0 or 2+ FAIL; imports; the sandbox; the environment; a
gray-area mark), prints `replay: run exchange-simulator` and exits 0 on a clean file. The format has no loader here
(`REPLAY = False` in `python/arena/formats/qminers.py`; `--data`, if given, is not read): the replay is a full
`uv run exchange-simulator --strategy BOT --backtest D/<file>.csv --log-dir logs/<run> --no-logs`. The replay checks
listed above apply to the Prosperity-format plug-ins.

Over the cap, `arena.compact` writes a copy without comments or docstrings (the template's 49 KB become about 26 KB) and checks that it parses back to the same code; it trades exactly as the original (`python/tests/test_compact.py`). Validate and upload the copy, and keep editing the original. Delete the probe bot's RISKY PROBES block before compacting it, since its markers are comments.

It warns about:
- use of environment variables, files, subprocesses or the network
- with `--max-state CHARS`, a `traderData` longer than the exchange keeps (Prosperity cut it at 50,000 characters, and the bot read back a broken string); without it the largest state is printed
- results that change on a repeat run, or when the first day is replayed in two other Python processes with other hash seeds (`PYTHONHASHSEED`), which catches a bot that iterates a set of strings: the organisers rerun the top bots, and such a bot wouldn't reproduce
- results that change when the bot is reloaded every tick, which means it keeps state outside `traderData` that the real engine may not preserve
- settings that can't matter, if the bot lists them (the template's `param_conflicts`): two target modes on one product (the first in `trade_product`'s order wins), a static `target` that a mode replaces, or a mode's own setting while the mode is off
- a product's limit in PARAMS unlike the data's, and a product on `fair: "sized_mid"` whose book sides lack a level of its `wall_size` more than 20% of the time, where it falls back to the plain mid (set `wall_size` near `arena.diagnose`'s `wall` column)

## On the day: adapting to the real format

Start from [`RUNBOOK.md`](day/RUNBOOK.md), one page of the day's commands, each line naming the [`ON_THE_DAY.md`](day/ON_THE_DAY.md) section behind it. The format swap is done (7 Nov; "The format swap, step by step" keeps what is left each round): `python/bots/qminers/template.py` runs on their `exchange-simulator`, and `python/arena/formats/qminers.py` serves only `arena.validate`'s import and sandbox checks. (The drill format that practised the swap, `format_drill`, is in the prep repository.) `python/experiments/README.md` says which experiment answers what on the day's data.
