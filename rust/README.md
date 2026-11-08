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
`python/bots/prosperity/zoo/claude/opus-5.5_baseline.py` → `src/bots/zoo/claude/opus-5.5_baseline.rs`), and
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
| `python/arena/stats.py` | `src/arena/stats.rs` | the grid's statistics whose cost grows with the cells: `cscv` (PBO; every halving, or 4,000 sampled with `random.sample`), `mean_correlation` (the DSR's independent trials), and `snooping` (Hansen's `omega2` and stationary bootstrap, SPA, StepM, each resample studentized by its own `omega2` or by the original's), and `spa`, `stepm` and `_scales` each on its own, with its own seed (`experiments/prosperity/snooping_tests.py`). Each resample's own `omega2` takes every lag of every column: Rust sums four lags at once, each sum compensated in Python's order, so it stays the same to the bit. `expected_max_sharpe`, `deflated_sharpe` and `standardized` stay Python only, being cheap | 23 cases (`stats_parity`): every halving and sampled ones, ties in the ranks, a constant cell, one cell; correlated and independent cells; no gain, planted gains, 400 cells, whole numbers, each resample studentized both ways, a kernel that skips lags, lags left over from the chunks of four; and `arena.grid` prints the same on either engine |
| `python/bots/mm.py` | `src/bots/mm.rs` | a plain wall-mid market maker, the benchmark's bot | 19 engine configurations (`CONFIGS`) |
| `python/bots/template.py` | `src/bots/template.rs` | STRATEGY and EXECUTION function for function, and ADAPTER as the Prosperity plug-in presents a tick to it; the settings come from the Python file's own DEFAULTS and PARAMS | 18 variants, one per part of STRATEGY, alone and in a resting market with a rival; the committed settings in 6 more configurations; 10 real days (P2, P3, P4) under two configurations |
| `python/bots/drill/template.py` | `src/bots/drill/template.rs` (`Template::drill`, a child module of `src/bots/template.rs`: the template with `Adapter::DRILL`) | the same STRATEGY and EXECUTION behind the drill format's ADAPTER (`drill_step`): prices converted from the format's units to each product's ticks and back as `python/arena/formats/drill.py` and the ADAPTER do, products in the exchange's order, trades without names, the limit from the exchange. Its days carry `Day.info`'s ticks and unit in the day file | on two drill-format days (`format_drill`'s, prices in cents on ticks of 0.05, 0.01 and 0.25): as committed in each queue model, per tick, against a copy, and the 17 variants of STRATEGY (44 cases); inside `arena.sim`'s market, where it sees prices in its unit |
| `python/bots/prosperity/rivals/sniper.py`, `python/bots/prosperity/rivals/spoofer.py`, `python/bots/prosperity/rivals/taker.py`, `python/bots/prosperity/rivals/trapper.py` | `src/bots/rivals/sniper.rs`, `src/bots/rivals/spoofer.rs`, `src/bots/rivals/taker.rs`, `src/bots/rivals/trapper.rs` (what they share in `rivals/mod.rs`) | the adversarial `--vs` rivals | 17 cases: against the template and `mm`, resting and per tick, with their constants changed by `--set`, all four at once |
| the 32 zoo bots, `python/bots/prosperity/zoo/<provider>/<name>.py` | `src/bots/zoo/<provider>/<name>.rs`, one file each, the names kept (dots and dashes too, through `#[path]` in `src/bots/zoo/mod.rs`, which holds what they share) | translated line by line, never edited on either side; they don't read settings from the file, so `--set` on one is refused | each alone (all, worse, a fill ratio, resting as written, resting requoted) and all of them with the template in one market, per tick and resting, on a simulated day, the same day trending hard up and down, a day with products their prompt never named (where most raise, or trade with limits they made up), and the first day of P2, P3 and P4 round 1: 1,134 cases |

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
- `python/experiments/prosperity/p4_levels.py` (other teams' bots, which have no twins) and `format_drill.py` (three simulated days);
- `arena.sim`'s specs, presets, `--spec` overrides and regimes, and its command line, which prints from the results Rust hands back;
- `python/bots/probe.py`, the zoo's tooling (`bundle.py`, `local.py`), and `python/experiments/`.

`python/arena/rust.py` is the bridge. It exports days, turns a twin's Python file into its Rust bot's settings (`bot_spec`, with any `--set` overrides), runs `arena-rs run`, `batch`, `sim` and `stats`, and reads what Rust writes back as Python's own `Day` and `DayResult` (`read_day`, `read_results`), so the reports and CSVs work unchanged. A Rust bot has no step timings, so a report from Rust leaves out the "bot time per tick" line (and `python/experiments/prosperity/zoo.py` its slowest-tick column).

Every tool that runs our bots takes `--engine rust`: `arena.backtest`, `arena.grid`, `arena.compare`, `arena.stress`, `arena.sim`, and the experiments, which go through `arena.cli.backtest` (one market on one day on either engine; `fields` limits what is read back, `arena.rust.sim_day_file` has Rust write a simulated day straight to a file, and `arena.rust.prosperity_day` a Prosperity day read from its CSVs, so a worker loads nothing in Python).

**Only in Rust** (`src/support/`, `src/commands/`): the day-file reader (`src/support/dayfile.rs`, for days `python/arena/rust.py` exports after the plug-ins have loaded them: simulated, perturbed, permuted and drill days), the thread pools of `arena-rs run`, `batch`, `sim` and `grid` (and the days loaded on a thread each), the grid's batch protocol (one spec for every cell, each task a cell and an engine config by index into the batch's own tables, every distinct override checked before the run, and the results streamed to a binary file as they finish, each after its task's index: `rust.run_batch`, `rust.read_pieces`), the statistics' threads (CSCV's halvings, the bootstrap's means and StepM's steps, each in a fixed order so the numbers don't depend on the thread count), SHA-512 (string seeds, as CPython hashes them), and a JSON reader.

## Layout

`src/` is laid out as the Python code is, so each twin is where its Python file would be; what has
no Python file of its own is in `support/` and `commands/`. One exception: the zoo and the rivals moved to
`python/bots/prosperity/` on 7 Nov, and their twins stayed in `src/bots/zoo/` and `src/bots/rivals/` (`rust/twins.json`).

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

## arena_sim: the Arena's exchange simulator

`rust/arena_sim/` is a second crate in the workspace (`cargo build --release --workspace` builds both; the
`arena-rs` crate is unchanged): the competition's own simulator, `simulator/simulator.py` with `models.py`,
`strategy.py` and `main.py`'s rules (5 ms accept delay, limit 100, potential-position cap 1,000, 10,000 a second
over the limit), ported step for step, and Rust versions of strategies behind a `Strategy` trait
(`on_book(snapshot, trades, ctx)`, `on_private(event, ctx)`; `ctx.send_order`, `cancel_order`, `modify_order`,
`now_us`). It is not a twin in `rust/twins.json`: its Python is theirs, and `python/tests/test_arena_rust.py` is
its parity check.

```sh
cargo run --release -p arena_sim --manifest-path rust/Cargo.toml -- --backtest data/sample.csv --strategy fallback_maker \
    [--params '{"QUOTE": 3}'] [--log-dir DIR] [--repeat 20]    # their CLI's lines; result.json and pnl.csv with --log-dir
uv run python -m arena.qsim_rust fallback_maker data/sample.csv.gz --grid QUOTE=2,3,5,8 --grid LIMIT=20,30,50,80 --threads 4
```

| File | What it copies |
|---|---|
| `src/data.rs` | `iter_backtest`: `Time` to µs as `int(round(float(t) * 1_000_000))`, `Insert`/`Cancel`, `B`/`A`, `Lifespan` `F` an IOC (else resting); the tape is read once and shared by a grid's runs. Plain CSV only, as theirs (`arena.qsim_rust` unpacks a `.gz`) |
| `src/sim.rs` | `OrderBook` and `ExchangeSimulator`: per row, our pending sends, cancels and modifies due by its time in ready order at their ready time (what the strategy queues meanwhile waits for the next row, as theirs does), the penalty integral and 1-s PnL samples, the row (every insert a taker first, then resting if `G`), then `on_book`. Price-time FIFO, our orders at the back, our takers skip our own resting orders, a modify shrinks in place, a tape cancel of an order already consumed is ignored; the private events in the same order with the same fields, during matching; the cap `\|I + s(R+q)\| > 1000`; the markout, `mark_price`, the quantiles, `fills`, `traded_volume`, `pnl_curve`. The run and CSV logs are not ported (a `--no-logs` run) |
| `src/py.rs` | `repr(float)`, `f"{x:.2f}"`, and `statistics.stdev`, which is exact: the variance of the floats as fractions (a small big-integer), its square root correctly rounded, as CPython's `_float_sqrt_of_frac` |
| `src/strategies/` | `trend_follower.rs` (`strategies/trend_follower.py`; Rust-only `QUANTITY`, `MIN_NET`), `fallback_maker.rs` (`python/bots/qminers/candidates/r0_F1_fallback.py`: `QUOTE`, `LIMIT`, `SKEW`, `WIND_DOWN_S`, `SESSION_S`, Rust-only `INSIDE_SPREAD`), `room_maker.rs` (`python/bots/qminers/families/room_maker.py`, family 7, its defaults F3: all 24 globals, `LEVELS` to `FLAT_S`; as `shrink_maker`, `python/bots/qminers/families/shrink_maker.py`, family 10: the same struct with its `DEPL_FRAC`, `REACT_CANCEL` and `MOM_LOTS` / `MOM_MS`, off by default; as `alloc_maker` and `signal_maker`, family 12's `python/bots/qminers/families/alloc_maker.py` and `signal_maker.py`: the same struct at their defaults (R1-F6's cell: `LEVELS` 2, `KEEP_DEPTH` 2, `SIZE_TOUCH` 65, `SIZE_DEEP` 80, `TOPUP` 1, `SESSION_S` 1e9, `SIZE_NARROW` 115, `DEPLETE_LOTS` 100, `REACT_CANCEL` 1, `DEPL_FRAC` 0.06) with each file's knobs, off by default: `ALLOC_K`, `INV_K`, `ALLOC_UP`, `ALLOC_HI`, `ALLOC_KU`, `ALLOC_TH`, `ALLOC_DEEP`, `ADV_TH`, `ADV_MIN`, `ADV_MS`, `ADV_SCOPE` (no MOM hold, as the file); `MOM_LOTS`, `MOM_MS`, `MOM_SIZE`, `IMB_TRIM`, `IMB_SIZE`, `MOM_BLOCK`, `MOM_JOIN`, `DYING_DEEP`, `SIZE_SKEW`, `SKEW_TRIM`; as `take_maker`, `python/bots/qminers/candidates/r1_F8_take_join.py` (R1-F8) at its own defaults (every global of the file: signal_maker's at R1-F7's values, `ALLOC_K` -0.5 with `ALLOC_UP`, `ALLOC_HI`, `ALLOC_DEEP`, applied before `SIZE_SKEW` as that file does) with its knobs: `TAKE_LOTS`, `TAKE_MAX`, `TAKE_OWN`, `TAKE_RATIO` (reads the market's lots at each side's second price level), `TAKE_DEPLETE`, `TAKE_MS`, `JOIN_LOTS`, `JOIN_MS`, `JOIN_OWN`, `ANY_CLEAR`, the take and join orders exempt from `CANCEL_ALONE` for their ms (the order's 7th field); each name takes only its file's globals; it reads the touch with `Snapshot::market_touch`, the Python loop's answer without the iterator chain, checked against that loop in debug builds), `ridge_maker.rs` (`python/bots/qminers/candidates/r1_C1_codex_ridge.py`, R1-C1's online ridge maker: its class constants `HORIZON_US`, `OBSERVATION_INTERVAL_US`, `MIN_LABELS`, `MODEL_MEMORY_US`, `POSITION_LIMIT`, `QUOTE_SIZE`, `REQUOTE_US`, and Rust-only knobs for its literals, `INSIDE_TH` 0.3, `FLOW_CUT` 1.1, `SKEW_K` 0.025, `DEAD_ZONE` 0.1, `MAX_ORDERS` 8, `FAST_US` 500000, `SLOW_US` 2000000, `FLOW_US` 500000, `OFI_US` 500000, `RIDGE_MIN` 10, `RIDGE_FRAC` 0.001, `FIT_US` 1000000, `REPLENISH_US` 5000, `PRED_MIX` 1.0; the prediction's `sum()` compensated as CPython's; and, off by default, R1-F8's depletion guard, `DEPLETE_LOTS` / `DEPL_FRAC`, a quote at a dying touch moved a tick back, and its take, `TAKE_LOTS`, `TAKE_OWN`, `TAKE_DEPLETE`, `TAKE_MAX`, `TAKE_MS`, take_maker's logic, Rust only: no Python file has them yet; the round-1 and round-2 candidates built on it, C5 to C12 and R2-FT1 to R2-L9, by knobs off by default, each one's `--set` line in the file's doc comment; R3-J1's burst sizing over the 100-lot limit, `BURST_TH` to `BURST_JUMP_MS`, off by default, every trigger a loss against L9: IDEAS.md, "Burst sizing on R2-L9"), `probe.rs` (`python/tests/fixtures/qsim_probe.py`, the parity test's random orders, cancels and modifies). Parameters are a flat JSON object named as the Python file's globals; an unknown key is an error |
| `src/main.rs` | `arena-sim` (one run, their CLI's lines) and `arena-sim batch` (parameter sets × files on N threads, a JSON line per run with its curve and reject counts, which `python/arena/qsim_rust.py` reads into `arena.qgrid`'s table) |

**Parity** (`python/tests/test_arena_rust.py`, on `data/sample.csv.gz`): trend_follower and F1 as written give
their CLI's lines and `result.json` and `pnl.csv` byte for byte (pnl 1878.00, 305 fills; -5877.00, 303 fills); F1
with 60-lot quotes (the penalty and the cap), F1 winding down from half time, and three probe settings (modifies
valid and not, cancels that lose the race, orders sent mid-activation, over 6,000 fills and a 30M penalty) give
every result field, the whole PnL curve and both reject counts identical. The room maker, against
`uv run exchange-simulator --strategy <room_maker.py with the globals set> --backtest DATA --no-logs` (7 Nov): the
CLI's lines, `result.json` and `pnl.csv` byte for byte on `data/arena/playground/sample_v2.csv` (2.0M rows; F3 as
written: pnl 263282.00, 7,764 fills) and `data/arena/round1/round1.csv` (4.4M rows; `SESSION_S` 1e9: 425553.00,
30,452 fills, volume 2,645,992), for the defaults and nine settings each (`LEVELS` 2 / `SIZE_DEEP` 30 /
`KEEP_DEPTH` 2; `DEPLETE_LOTS` 20; `DEPLETE_LOTS` 30 / `DEPLETE_SIZE` 40; `BACK_POS` 95; `SIZE_NARROW` 150 /
`SHRINK_NARROW` 1; `UNWIND` 100 / `UNWIND_TO` 90, a no-op, and 60 / 30; `FLAT_S` 30 with `SESSION_S` 5700; and one
setting of every other knob: `IMB`, `MIN_QUEUE`, `REBALANCE`, `LEVELS` 3, `CANCEL_ALONE` 0, `SKEW_CANCEL` 0,
`INSIDE_POS`, `TOPUP` 0, `WIND_DOWN_S`): 20 of 20 identical. The test keeps ten settings on a 900-s synthetic tape
with one- and two-tick spreads (always on, 1 s) and nine of the real-tape cases behind `ARENA_SIM_FULL=1` (with
`ARENA_SIM_DATA` pointing at `data/arena/` from a worktree; about 30 s a Python run). The shrink maker
(7 Nov): five settings on the synthetic tape, and on round 1 byte for byte R1-F5's (`DEPLETE_LOTS` 100, `DEPL_FRAC`
0.06, `REACT_CANCEL` 1: 455822.00, 37,847 fills), `DEPLETE_LOTS` 60 / `DEPL_FRAC` 0.2 / `DEPLETE_SIZE` 30 (437654.00,
32,131) and `REACT_CANCEL` 1 / `SIZE_NARROW` 150 / `SHRINK_NARROW` 1 / `BACK_POS` 95 (393824.00, 53,530): 3 of 3
identical, in the same test; `MOM_LOTS` 40 / `MOM_MS` 500 on the synthetic tape. Family 12 (7 Nov), against
`exchange-simulator` on the family file with the globals set: seven `alloc_maker` and eight `signal_maker` settings
on the synthetic tape (every knob's path), and on round 1 byte for byte (the CLI's lines, `result.json`, `pnl.csv`)
R1-F6b (`candidates/r1_F6b_alloc.py`, `ALLOC_K` -0.5: 489844.00, 60,487 fills), `INV_K` 0.5 / `ALLOC_K` -0.3 /
`ALLOC_UP` 0 (486179.00, 54,344), `ADV_TH` 0 / `ADV_MIN` 200 / `ADV_SCOPE` 2 (482413.00, 49,097); R1-F7
(`candidates/r1_F7_signal.py`, `MOM_LOTS` 400 / `MOM_MS` 50 / `MOM_BLOCK` 0 / `MOM_JOIN` 1 / `DYING_DEEP` 80 /
`DEPL_FRAC` 0.12: 496564.00, 53,919), `MOM_LOTS` 300 / `MOM_MS` 100 / `MOM_SIZE` 20 / `MOM_BLOCK` 0 (473635.00,
53,169), `MOM_LOTS` 400 / `MOM_MS` 200 / `MOM_BLOCK` 1 / `IMB_TRIM` 0.2 / `IMB_SIZE` 10 / `SIZE_SKEW` 0.5 /
`SKEW_TRIM` 1 (378914.00, 57,080): 6 of 6 identical, in the same test. R1-F8 as `take_maker` (7 Nov): eight settings on the synthetic tape (the take, its gates and `TAKE_RATIO`, the extra join order, the gated `MOM_JOIN`, `ANY_CLEAR`, `SIZE_SKEW` after `ALLOC_K`), and as written byte for byte on round 1 (519027.00, 66,371 fills, volume 1,877,776, inventory +82) and on sample_v2 (234661.00, 28,134), the earlier families' real-tape cases unchanged. R1-C1 as `ridge_maker` (7 Nov): byte for byte on round 1 (554347.00, 37,087 fills, volume 2,192,606, inventory +100; result.json and pnl.csv identical) and on data/sample.csv.gz (-91974.00, 1,316), about 3 s a run against ~2 min in Python. The codex v4-v6 candidates as `ridge_maker` (7 Nov, the knobs `FLOWGRP` 1 / 2 with `FLOWGRP_CAP` and `FLOWGRP_US`, `QUOTEFEAT` with `QUOTEFEAT_US`, off by default; the `--set` line of each in the file's doc comment): on C5's knobs, byte for byte on round 1 (pnl.csv and result.json), R1-C5 595441.83 (21,120 fills), R1-C9 605752.82 (`FLOWGRP` 1, 21,371), R1-C10 616534.83 (`FLOWGRP` 2, 21,436), R1-C11 619281.99 (`QUOTEFEAT` 1, `FLOWGRP` 2, `FLOWGRP_CAP` 1, 21,460), R1-C12 622920.99 (the same with `FLOWGRP_CAP` 20, `FLOWGRP_US` 1000000, 21,462), R1-C1 at the defaults unchanged (`test_ridge_maker_codex_features`). Round 2's forecast takers as `ridge_maker` (8 Nov, the knobs `FT_MAXSPREAD`, `FT_ROOM_LIVE`, `LIQ`, `IMPACT_US`, `HUBER`, `QS_RATE` / `QS_US`, off by default; what each does in the file's doc comment): byte for byte on round 2's public tape against `exchange-simulator` on the candidate file (the CLI's lines, pnl.csv, result.json), R2-T2 194391.00 (119,403 fills), R2-L1 269920.00 (117,072), R2-L3 294098.00 (2,492), R2-L8 296181.00 (75,762), R2-L9 317057.00 (2,803), with R1-C1, C12, FT1 and Q1 on round 1 and T1, V1, E2 and FT1 on round 2 unchanged to the byte (`test_ridge_maker_round2_takers`; `ARENA_SIM_FULL=1` reruns the Python); 10-13 s a run against 140-180 s in Python (a machine at load 16 on 14 cores). Each one's settings, every candidate (`python/bots/qminers/candidates/`) the one before it plus knobs:

```sh
T2="--set POSITION_LIMIT=1000 --set EXPOSURE=100 --set HEDGE=1 --set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000
    --set DEAD_ZONE=0.18 --set QUOTEFEAT=1 --set FLOWGRP=2 --set FLOWGRP_CAP=20 --set FLOWGRP_US=1000000 --set FT_EDGE=0.15
    --set FT_SZ=200 --set FT_GAP_MS=50 --set QUOTE_SIZE=1 --set KEEP_LOTS=20 --set KEEP_TH=0.3 --set FT_MAXSPREAD=1 --set FT_ROOM_LIVE=1"
L1="$T2 --set LIQ=1";  L3="$L1 --set QUOTE_SIZE=0";  L8="$L1 --set QS_RATE=2.5"
L9="$L3 --set POSITION_LIMIT=100 --set IMPACT_US=500000 --set HUBER=6.0 --set RIDGE_MIN=30 --set RIDGE_FRAC=0.003"
uv run python -m arena.qsim_rust ridge_maker data/arena/round2/round2_public.csv ${=L9} --grid HUBER=4,6,9 --threads 4 --holdout 0.25
F1="$L9 --set FILTER=1"   # R3-F1 (r3_F1_latent_filter.py): the latent-price filter's three features (FILTER_* knobs)
```

R3-F1 as `ridge_maker` (8 Nov, the knob `FILTER` with `FILTER_W`, `FILTER_RATE`, `FILTER_EPS`, `FILTER_PI0`-`2`,
`FILTER_IMPACT`, `FILTER_SQRT_C`, `FILTER_DEPTH`, off by default; what each does in the file's doc comment). It gives
the Python file's numbers: round3_public 480469.00 (volume 571,820; FILTER 0 is L9's 424730.00), and round2_public
303720.00 with pnl.csv and result.json byte for byte (`test_ridge_maker_round2_takers`); R3-F3 (B1's line and
`--set FILTER=1`) 505212.00 on round3_public, byte for byte too. FILTER needs `QUOTEFEAT` 1. `FILTER_JUMP` (with
`FILTER_JUMP_MED`, `FILTER_JUMP_SD`, off by default) is Rust only: it adds lognormal jumps to the latent's walk and
loses on round3_public.

R3-G1's early exit (8 Nov, Rust only, off by default: `FT_EXIT` 99.0, `FT_EXIT_SZ` 0, `FT_EXIT_WIDE` 0, `FT_EXIT_KEEP`
99.0): a reduce-only IOC at the touch when the forecast is against the position by more than FT_EXIT plus half the
spread and the forecast take does not fire, or at a spread of FT_EXIT_WIDE+ unless the forecast is with the position by
FT_EXIT_KEEP. On R3-F3 (`$B1 --set FILTER=1`, 505212.00 on round3_public, unchanged with the knob off) every setting tied or
lost, so no Python file was written (IDEAS.md, "R3-F3's loss anatomy").

**Speed** (the sample, 53,758 rows, one core, measured 7 Nov): trend_follower 151 ms a run in Python, 1.7 ms in
Rust (90x); F1 274 ms, 3.9 ms (70x); parsing the CSV once is 5 ms more. On 4 threads, F1's 16-cell grid
(plus the baseline) takes 1.6 s in `arena.qgrid --jobs 4` and 0.2 s in `arena.qsim_rust`, the same table to the
character; 100 cells take 0.4 s, most of it reading the runs' PnL curves back into Python. The room maker on
round 1 (4.4M rows, F3 with `SESSION_S` 1e9, 7 Nov, a loaded machine): 0.55 s a run in Rust (parsing the CSV 0.4 s
more, once a grid) against 26-40 s in Python (`exchange-simulator`), 50-70x; a 6-cell grid on 8 threads takes 1.4 s.
Family 12 on round 1 (7 Nov, `--repeat 5`): R1-F7 as `signal_maker` 0.68 s a run, R1-F6b as `alloc_maker` 0.70 s,
against 32-38 s in Python (about 50x); R1-F8 as `take_maker` 1.3 s a run (parsing included), a 9-run grid on 3 threads 4.5 s (a loaded machine):

```sh
uv run python -m arena.qsim_rust python/bots/qminers/families/room_maker.py data/arena/round1/round1.csv \
    --set SESSION_S=1000000000 --grid DEPLETE_LOTS=0,10,20 --grid BACK_POS=95,1000 --threads 8 --holdout 0.25
uv run python -m arena.qsim_rust python/bots/qminers/families/signal_maker.py data/arena/round1/round1.csv \
    --set MOM_LOTS=400 --set MOM_MS=50 --set MOM_BLOCK=0 --set MOM_JOIN=1 --set DEPL_FRAC=0.12 \
    --grid DYING_DEEP=0,40,80 --grid MOM_SIZE=-1,20 --threads 6     # R1-F7 is the cell DYING_DEEP 80, MOM_SIZE -1
uv run python -m arena.qsim_rust python/bots/qminers/candidates/r1_F8_take_join.py data/arena/round1/round1.csv \
    --grid TAKE_LOTS=0,60 --grid TAKE_OWN=400,800 --grid JOIN_OWN=0,400 --threads 3   # R1-F8 is the baseline (as is)
```

**A new strategy**: a `Strategy` impl in `src/strategies/`, a name in `strategies::make`, its Python file in
`arena.qsim_rust.STRATEGIES`, and a case in `python/tests/test_arena_rust.py` comparing it with the Python one.
A change to `simulator/` (a new starter) needs the port checked again: run that test.
