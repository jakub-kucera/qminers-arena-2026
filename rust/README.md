# rust/: the engine and the bots in Rust

A Rust port of `python/arena/engine.py`, `python/arena/sim.py`'s market, the grid's statistics, the Prosperity
loader and every bot we run, kept apart from the Python code. It gives the same results as the
Python, to the bit, about 130 times faster per backtest on one core (a whole grid 40–80 times; README.md, "The engine in Rust"). Every tool that runs our bots takes
`--engine rust` (`arena.backtest`, `grid`, `compare`, `stress`, `sim`, and the experiments); the
reports, the plots and the format plug-ins stay Python. The submitted bot is still a Python file:
a Rust bot is a twin for searching, never for submitting.

```sh
brew install rust                                     # or rustup; any recent stable toolchain
uv run python -m arena.grid python/bots/template.py 1 --grid PARAMS.KELP.make_edge=0..7 --engine rust
uv run python -m arena.sim run python/bots/template.py --days 20 --engine rust
uv run python -m experiments.rust_bench               # build, check every twin, then time both engines
uv run python -m experiments.rust_bench --parity-only --record   # after changing a twin: check, then record its hash
uv run pytest python/tests/test_rust.py                      # the parity checks, shorter, and `cargo test`
```

## What is in Python, in Rust, and in both

**In both**: every Rust file below has a Python twin, and the two must stay equal. A twin sits at
its Python file's path under `src/`, `.py` becoming `.rs` (`python/arena/engine.py` → `src/arena/engine.rs`,
`python/bots/zoo/claude/opus-5.5_baseline.py` → `src/bots/zoo/claude/opus-5.5_baseline.rs`), and
`python/tests/test_rust.py` checks that every pair keeps to it.
`rust/twins.json` lists the pairs with the hash of the Python code the port was last checked
against: the file's syntax tree without its docstrings, so comments, docstrings and layout don't
count (`python/arena/rust.py` `code_hash`). A bot whose Rust twin reads settings from the file lists
those globals under `reads` (the template's `DEFAULTS` and `PARAMS`, a rival's constants), and the
statements that only set them are left out of the hash too, since Rust reads their values at run
time. `python/tests/test_rust.py` fails when a twin's code changes until the Rust side is updated and
`experiments.rust_bench --record` has checked the pair again.

| Python | Rust | What it is | How they're checked |
|---|---|---|---|
| `python/arena/engine.py` | `src/arena/engine.rs` | `run_market` / `run_day` function for function (`_take` is `take`, ...): both modes, the three queue models, the fill ratio, several bots in one market, the marks, the limit penalty and the decision delay, every per-tick record of a `DayResult` | every field a `DayResult` records, under every engine configuration, by all the bots below |
| `python/arena/formats/prosperity.py` (`load_day`) | `src/arena/formats/prosperity.rs` | the Prosperity CSVs read as the plug-in reads them, for a day reference (`.json`: data folder, round, day, the limits Python gives, and `only` some products), which `python/arena/rust.py` `write_day` writes instead of exporting a day the plug-in loaded (`prosperity.reference`); the bot adapter in that file is twinned by the template's ADAPTER | every Prosperity day (P2, P3, P4: 69, the price files the clones hold; an earlier count said 71) and two restricted ones, books, trades, marks and limits; arena.sim days in the Prosperity layout (`limits.json` included); and every real-day parity case reads its day this way |
| `python/arena/sim.py` | `src/arena/sim.rs` | the market: the book, the fundamental (reversion, jumps and their bursts, regimes), the five agent kinds drawing from their own seeded `random.Random`s, bots trading inside it in both modes. The specs, presets, `--spec` and regimes stay in Python, which passes the spec as JSON; the Prosperity CSVs of `generate` are written by both | the recording (books, trades and their order, marks, ints kept apart from floats), the fundamental, and every bot's DayResult in the market and in its replays: every preset, both modes, two regimes, agents shown by name, the maker among the takers with skew, the rivals, and all 32 zoo bots racing (13 cases); `arena.sim run` and `generate` print and write the same, byte for byte |
| `python/arena/stress.py` | `src/arena/stress.rs` | the perturbations (`perturb`: vol2, trends, shifts, spikes, no_wall, on each product's tick grid) and `permute` (the grid's permutation test), as a task's or a run's `transform` ("trend_up:2.5", "permuted:SEED:BLOCK"), so Rust makes each copy itself; the command line and the running stay in Python | every perturbation at size 1, three at other sizes, and `permute` at four seeds and block lengths, on a simulated day, a drill day (a tick of 5 cents), and P3 r1d0 and P4 r3d0 whole (60 cases); `arena.stress` and `arena.grid --permute` print the same on either engine |
| `python/arena/stats.py` | `src/arena/stats.rs` | the grid's statistics whose cost grows with the cells: `cscv` (PBO; every halving, or 4,000 sampled with `random.sample`), `mean_correlation` (the DSR's independent trials), and `snooping` (Hansen's `omega2` and stationary bootstrap, SPA, StepM, each resample studentized by its own `omega2` or by the original's), and `spa`, `stepm` and `_scales` each on its own, with its own seed (`experiments/study/snooping_tests.py`). Each resample's own `omega2` takes every lag of every column: Rust sums four lags at once, each sum compensated in Python's order, so it stays the same to the bit. `expected_max_sharpe`, `deflated_sharpe` and `standardized` stay Python only, being cheap | 23 cases (`stats_parity`): every halving and sampled ones, ties in the ranks, a constant cell, one cell; correlated and independent cells; no gain, planted gains, 400 cells, whole numbers, each resample studentized both ways, a kernel that skips lags, lags left over from the chunks of four; and `arena.grid` prints the same on either engine |
| `python/bots/mm.py` | `src/bots/mm.rs` | a plain wall-mid market maker, the benchmark's bot | 19 engine configurations (`CONFIGS`) |
| `python/bots/template.py` | `src/bots/template.rs` | STRATEGY and EXECUTION function for function, and ADAPTER as the Prosperity plug-in presents a tick to it; the settings come from the Python file's own DEFAULTS and PARAMS | 18 variants, one per part of STRATEGY, alone and in a resting market with a rival; the committed settings in 6 more configurations; 10 real days (P2, P3, P4) under two configurations |
| `python/bots/drill/template.py` | `src/bots/drill/template.rs` (`Template::drill`, a child module of `src/bots/template.rs`: the template with `Adapter::DRILL`) | the same STRATEGY and EXECUTION behind the drill format's ADAPTER (`drill_step`): prices converted from the format's units to each product's ticks and back as `python/arena/formats/drill.py` and the ADAPTER do, products in the exchange's order, trades without names, the limit from the exchange. Its days carry `Day.info`'s ticks and unit in the day file | on two drill-format days (`format_drill`'s, prices in cents on ticks of 0.05, 0.01 and 0.25): as committed in each queue model, per tick, against a copy, and the 17 variants of STRATEGY (44 cases); inside `arena.sim`'s market, where it sees prices in its unit |
| `python/bots/rivals/sniper.py`, `python/bots/rivals/spoofer.py`, `python/bots/rivals/taker.py`, `python/bots/rivals/trapper.py` | `src/bots/rivals/sniper.rs`, `src/bots/rivals/spoofer.rs`, `src/bots/rivals/taker.rs`, `src/bots/rivals/trapper.rs` (what they share in `rivals/mod.rs`) | the adversarial `--vs` rivals | 17 cases: against the template and `mm`, resting and per tick, with their constants changed by `--set`, all four at once |
| the 32 zoo bots, `python/bots/zoo/<provider>/<name>.py` | `src/bots/zoo/<provider>/<name>.rs`, one file each, the names kept (dots and dashes too, through `#[path]` in `src/bots/zoo/mod.rs`, which holds what they share) | translated line by line, never edited on either side; they don't read settings from the file, so `--set` on one is refused | each alone (all, worse, a fill ratio, resting as written, resting requoted) and all of them with the template in one market, per tick and resting, on a simulated day, the same day trending hard up and down, a day with products their prompt never named (where most raise, or trade with limits they made up), and the first day of P2, P3 and P4 round 1: 1,134 cases |

Supporting pieces that copy Python exactly but have no file of their own to hash:

| Python | Rust | |
|---|---|---|
| `python/arena/model.py` | `src/arena/model.rs` | the types; products are indices into the day's list (sorted by name), trader names into its name table |
| `random.Random` (CPython 3.12) | `src/support/pyrandom.rs` | MT19937, int and str seeding, `random`, `shuffle`, `randint`, `uniform`, `gauss`, `binomialvariate`, draw for draw (`cargo test` has CPython's vectors) |
| `arena.cli.Requote` | `Requote` in `src/bots/mod.rs` | `--requote` for rivals |
| `arena.grid.block_pnl`, `report.total_pnl`, `product_stats`, `report.max_drawdown` | `block_pnl`, `piece`, `piece_binary`, `max_drawdown` in `src/commands/batch.rs` | what a grid task returns (`arena-rs batch`; `--binary` for the grid) |
| `arena.botfile._apply_override` | `apply_override` in `src/commands/mod.rs` | a grid cell's `--set` overrides applied in Rust, with the same errors |
| `math.erf`, `x ** 2`, `math.exp`, `math.log` | libm's `erf`, `pow`, `exp`, `log` | CPython calls the C library for these, so the Rust does too. On macOS `pow(x, 2)` isn't always `x * x`. |
| `math.fsum`, `statistics.fmean`, `random.sample` | `fsum`, `fmean`, `sample` in `src/arena/stats.rs` | Shewchuk's partials as `mathmodule.c` has them; `sample`'s two branches as `Lib/random.py` |
| `sum()` of floats, and of ints and floats mixed; `round(x, n)`, `//`, `max`/`min`; numpy's `mean`, `std` | `src/support/py.rs` | CPython 3.12's `sum` is compensated (Neumaier), not a plain loop, and adds ints after the first float uncompensated; numpy's sums are pairwise from 0.0. Each checked against the real thing on random inputs, and `cargo test` holds CPython's vectors |
| an exception in `Trader.run` | `Bot::failed` | the twin reports the traceback's last line, word for word (`KeyError: 'SQUID_INK'`, `ValueError: min() iterable argument is empty`, NameError's "Did you mean"), and the engine drops the tick's orders and records it, as `call_bot` does. The twin keeps what the Python keeps: traderData as last returned, the instance's changes up to the error |
| what an experiment reads from a bot's traderData | `Bot::memory` | the template's: which products' loss stop fired (`python/experiments/study/sim_regimes.py`) |

**Only in Python**:
- the format plug-ins (`python/arena/formats/`), which load the data for Python (Rust reads the Prosperity CSVs itself, above; the drill's days are exported);
- `arena.validate`, which checks the Python file itself;
- everything in `arena.grid` but the backtests, the heavy statistics and the permuted copies (`src/arena/stress.rs` makes those from each task's `transform`): the axes, `--sample`'s draw, the screen and `--halving`'s steps, the scenarios (each task carries its config and rivals), held-out days, and the DSR's own formula;
- `arena.analysis`, `arena.diagnose`, `arena.stress`'s command line, and `arena.report`'s CSVs (written from the results Rust hands back);
- `python/experiments/study/p4_levels.py` (other teams' bots, which have no twins) and `format_drill.py` (three simulated days);
- `arena.sim`'s specs, presets, `--spec` overrides and regimes, and its command line, which prints from the results Rust hands back;
- `python/bots/probe.py`, the zoo's tooling (`bundle.py`, `local.py`), and `python/experiments/`.

`python/arena/rust.py` is the bridge. It exports days, turns a twin's Python file into its Rust bot's settings (`bot_spec`, with any `--set` overrides), runs `arena-rs run`, `batch`, `sim` and `stats`, and reads what Rust writes back as Python's own `Day` and `DayResult` (`read_day`, `read_results`), so the reports and CSVs work unchanged. A Rust bot has no step timings, so a report from Rust leaves out the "bot time per tick" line (and `python/experiments/study/zoo.py` its slowest-tick column).

Every tool that runs our bots takes `--engine rust`: `arena.backtest`, `arena.grid`, `arena.compare`, `arena.stress`, `arena.sim`, and the experiments, which go through `arena.cli.backtest` (one market on one day on either engine; `fields` limits what is read back, `arena.rust.sim_day_file` has Rust write a simulated day straight to a file, and `arena.rust.prosperity_day` a Prosperity day read from its CSVs, so a worker loads nothing in Python).

**Only in Rust** (`src/support/`, `src/commands/`): the day-file reader (`src/support/dayfile.rs`, for days `python/arena/rust.py` exports after the plug-ins have loaded them: simulated, perturbed, permuted and drill days), the thread pools of `arena-rs run`, `batch`, `sim` and `grid` (and the days loaded on a thread each), the grid's batch protocol (one spec for every cell, each task a cell and an engine config by index into the batch's own tables, every distinct override checked before the run, and the results streamed to a binary file as they finish, each after its task's index: `rust.run_batch`, `rust.read_pieces`), the statistics' threads (CSCV's halvings, the bootstrap's means and StepM's steps, each in a fixed order so the numbers don't depend on the thread count), SHA-512 (string seeds, as CPython hashes them), and a JSON reader.

## Layout

`src/` is laid out as the Python code is, so each twin is where its Python file would be; what has
no Python file of its own is in `support/` and `commands/`.

| Path | What it is |
|---|---|
| `src/arena/` | twins of `python/arena/`: `engine.rs`, `model.rs`, `sim.rs`, `stats.rs`, and `formats/prosperity.rs` (above) |
| `src/bots/` | twins of `python/bots/`: `template.rs`, `drill/template.rs`, `mm.rs`, `rivals/`, `zoo/<provider>/`; `mod.rs` builds one by its kind (`rust/twins.json`) from its Python file's globals, and holds `Requote` |
| `src/support/` | Rust only: `py.rs` (Python's arithmetic where it isn't IEEE's), `pyrandom.rs` and `sha512.rs` (Python's random numbers and string seeding), `json.rs`, and `dayfile.rs` (the exported day format, version 3, or a day reference) |
| `src/main.rs`, `src/commands/` | the `arena-rs` binary: `run.rs` (one market; `--dump` writes every recorded field, a JSON line per participant), `batch.rs` (arena.grid's, compare's and stress's backtests on N threads), `sim.rs` (arena.sim's market on N seeds at once, its replays and files), `stats.rs` (the grid's statistics), `day.rs` (days and references written back as day files), `grid.rs` (`mm`'s make × take grid, for timing); `mod.rs` holds what they share |

## What is and isn't ported

- **The engine.** Ported: every rule in `python/arena/engine.py`'s docstring, in the same order of operations, the decision delay (`EngineConfig.delay`, `--delay`) included. Not ported:
  - order tags (a format's own ids);
  - a bot's exceptions, prints and step timings;
  - fractional prices (the day file holds whole prices, as Prosperity's are; a format with decimal prices loads them as whole units, as the drill's does);
  - CPython's own `lgamma`: `binomialvariate` calls the C library's. They differ by a few ulps, which could flip a fill-ratio draw only when its test lands that close to the bound.
- **The template.** Ported: all of STRATEGY and EXECUTION. Not ported: `STRICT`, and the per-product try/except (a Rust bot can't raise). Settings that the Python would only fail on while running are refused when the bot is built, so its grid cell fails before it starts. That covers an unknown key, an unknown fair method, and a float where an integer is needed (`limit`, `target`, `make_size`, `cpd_block`).
- **A bot's state across ticks.** The Python bots keep it in `traderData` as JSON. The Rust ones keep the same values in fields, which is equivalent because JSON gives every float back exactly.

## Keeping it in step

1. Change the rule or the strategy in Python, and port the change to the file `rust/twins.json` names.
2. Run `uv run python -m experiments.rust_bench --parity-only --record`. It compares every recorded field in every case, and records the new hashes only if every case is identical.
3. Run `uv run pytest python/tests/test_rust.py`.

Python files without a Rust twin need nothing. Every tool with `--engine rust` refuses a bot without a twin, and refuses to run when a twin it uses (the bots, and the engine's own twins) was last checked against older Python code; an experiment refuses if any twin is. `--allow-stale` runs anyway, with a warning, since Rust then runs the older code.

A new twin needs four things:
- a Rust file at its Python file's path under `src/` (a zoo bot: its `#[path]` module in `src/bots/zoo/mod.rs`);
- a kind in `src/bots/mod.rs`;
- a row in `rust/twins.json` (with `"format"` if it isn't Prosperity's) and in the table above;
- cases in `python/experiments/rust_bench.py`, run by `python/tests/test_rust.py`.

**A new format's template is a twin by config instead**, with no Rust file of its own, when its ADAPTER makes the same choices as one of ours (`Adapter` in `src/bots/template.rs`). There are six: `units` (the engine's prices are in `Day.info`'s unit, so STRATEGY sees ticks), `names` (trades name their traders), `own_trades` (our fills join the trades, as Prosperity's `own_trades`), `exchange_limit` (the limit from the exchange, not PARAMS), `exchange_order` (products in the exchange's order) and `sorted_resting` (resting orders sorted by time and id). `"prosperity"` and `"drill"` are presets. Its row is `{"kind": "template", "format": "<name>", "adapter": "drill" or {the choices}, "rust": "rust/src/bots/template.rs", "reads": ["DEFAULTS", "PARAMS"], "sha256": ""}`. Then `uv run python -m experiments.rust_bench --twin FILE --data D --days ... --format F --record` runs 32 cases on its own data, in both engines: the committed settings in five modes and against a copy (6), and each part of STRATEGY on its first two products (26). It records the hash only if every case is identical. A test rehearses it on a copy of the drill template, and shows that one wrong choice is caught.
