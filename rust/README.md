# rust/: the Arena's exchange simulator in Rust

`arena_sim/` is a port of the organisers' exchange simulator (`simulator/simulator.py`) that gives the same results to the
bit, with Rust versions of our strategies (`arena_sim/src/strategies/`, `ridge_maker.rs` above all) for fast parameter
grids. It is the workspace's only crate here; the Rust twins of the Prosperity-era engine and bots (the crate
`arena_rs`, which the text below sometimes compares with) are in the prep repository.

```sh
cargo build --release -p arena_sim --manifest-path rust/Cargo.toml
uv run python -m arena.qsim_rust ridge_maker data/arena/round4/round4_public.csv --grid FT_EDGE=0.15,0.25 --threads 4
```

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
| `src/strategies/` | `trend_follower.rs` (`strategies/trend_follower.py`; Rust-only `QUANTITY`, `MIN_NET`), `fallback_maker.rs` (`python/bots/qminers/candidates/round0/r0_F1_fallback.py`: `QUOTE`, `LIMIT`, `SKEW`, `WIND_DOWN_S`, `SESSION_S`, Rust-only `INSIDE_SPREAD`), `room_maker.rs` (`python/bots/qminers/families/room_maker.py`, family 7, its defaults F3: all 24 globals, `LEVELS` to `FLAT_S`; as `shrink_maker`, `python/bots/qminers/families/shrink_maker.py`, family 10: the same struct with its `DEPL_FRAC`, `REACT_CANCEL` and `MOM_LOTS` / `MOM_MS`, off by default; as `alloc_maker` and `signal_maker`, family 12's `python/bots/qminers/families/alloc_maker.py` and `signal_maker.py`: the same struct at their defaults (R1-F6's cell: `LEVELS` 2, `KEEP_DEPTH` 2, `SIZE_TOUCH` 65, `SIZE_DEEP` 80, `TOPUP` 1, `SESSION_S` 1e9, `SIZE_NARROW` 115, `DEPLETE_LOTS` 100, `REACT_CANCEL` 1, `DEPL_FRAC` 0.06) with each file's knobs, off by default: `ALLOC_K`, `INV_K`, `ALLOC_UP`, `ALLOC_HI`, `ALLOC_KU`, `ALLOC_TH`, `ALLOC_DEEP`, `ADV_TH`, `ADV_MIN`, `ADV_MS`, `ADV_SCOPE` (no MOM hold, as the file); `MOM_LOTS`, `MOM_MS`, `MOM_SIZE`, `IMB_TRIM`, `IMB_SIZE`, `MOM_BLOCK`, `MOM_JOIN`, `DYING_DEEP`, `SIZE_SKEW`, `SKEW_TRIM`; as `take_maker`, `python/bots/qminers/candidates/round1/r1_F8_take_join.py` (R1-F8) at its own defaults (every global of the file: signal_maker's at R1-F7's values, `ALLOC_K` -0.5 with `ALLOC_UP`, `ALLOC_HI`, `ALLOC_DEEP`, applied before `SIZE_SKEW` as that file does) with its knobs: `TAKE_LOTS`, `TAKE_MAX`, `TAKE_OWN`, `TAKE_RATIO` (reads the market's lots at each side's second price level), `TAKE_DEPLETE`, `TAKE_MS`, `JOIN_LOTS`, `JOIN_MS`, `JOIN_OWN`, `ANY_CLEAR`, the take and join orders exempt from `CANCEL_ALONE` for their ms (the order's 7th field); each name takes only its file's globals; it reads the touch with `Snapshot::market_touch`, the Python loop's answer without the iterator chain, checked against that loop in debug builds), `ridge_maker.rs` (`python/bots/qminers/candidates/round1/r1_C1_codex_ridge.py`, R1-C1's online ridge maker: its class constants `HORIZON_US`, `OBSERVATION_INTERVAL_US`, `MIN_LABELS`, `MODEL_MEMORY_US`, `POSITION_LIMIT`, `QUOTE_SIZE`, `REQUOTE_US`, and Rust-only knobs for its literals, `INSIDE_TH` 0.3, `FLOW_CUT` 1.1, `SKEW_K` 0.025, `DEAD_ZONE` 0.1, `MAX_ORDERS` 8, `FAST_US` 500000, `SLOW_US` 2000000, `FLOW_US` 500000, `OFI_US` 500000, `RIDGE_MIN` 10, `RIDGE_FRAC` 0.001, `FIT_US` 1000000, `REPLENISH_US` 5000, `PRED_MIX` 1.0; the prediction's `sum()` compensated as CPython's; and, off by default, R1-F8's depletion guard, `DEPLETE_LOTS` / `DEPL_FRAC`, a quote at a dying touch moved a tick back, and its take, `TAKE_LOTS`, `TAKE_OWN`, `TAKE_DEPLETE`, `TAKE_MAX`, `TAKE_MS`, take_maker's logic, Rust only: no Python file has them yet; the round-1 and round-2 candidates built on it, C5 to C12 and R2-FT1 to R2-L9, by knobs off by default, each one's `--set` line in the file's doc comment; R3-J1's burst sizing over the 100-lot limit, `BURST_TH` to `BURST_JUMP_MS`, off by default, every trigger a loss against L9: IDEAS.md, "Burst sizing on R2-L9"), `probe.rs` (`python/tests/fixtures/qsim_probe.py`, the parity test's random orders, cancels and modifies). Parameters are a flat JSON object named as the Python file's globals; an unknown key is an error |
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
R1-F6b (`candidates/round1/r1_F6b_alloc.py`, `ALLOC_K` -0.5: 489844.00, 60,487 fills), `INV_K` 0.5 / `ALLOC_K` -0.3 /
`ALLOC_UP` 0 (486179.00, 54,344), `ADV_TH` 0 / `ADV_MIN` 200 / `ADV_SCOPE` 2 (482413.00, 49,097); R1-F7
(`candidates/round1/r1_F7_signal.py`, `MOM_LOTS` 400 / `MOM_MS` 50 / `MOM_BLOCK` 0 / `MOM_JOIN` 1 / `DYING_DEEP` 80 /
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
loses on round3_public. R3-F4's bank (8 Nov, `r3_F4_filter_bank.py`, byte for byte on round3_public, 512175.00):
`FILTER_IMP2` / `FILTER_IMP3` (0: off) run more copies of the filter at those impact scales and take the features from
the copy whose inserts' log-likelihood (decayed over `FILTER_LL_N` inserts, 100000) is highest, ahead of F3's own by
`FILTER_LL_MARGIN` nats (0). `FILTER_XGAP` 1 / 2 (0: off) adds the first copy's gap as features instead; `FILTER_CLIP`
(5.0) is the gap's clip. `FILTER_VRATE` / `FILTER_VIMPACT` (0: off) are the walk's rate and the impact scale while
FILTER_VQS's speed switch is on. `FILTER_LADDER` (0: off) leaves out of the filter's update a new market order 2-7 ticks behind its
touch that comes 2 ms after a same-side one 2-7 ticks behind (round 3's ladders, `experiments.generator.gen_ladders`). All off by default (F3 505212.00 unchanged); none beat F3 on round 3 (IDEAS.md, "A better
state for R3-F3's latent-price filter").

R3-G1's early exit (8 Nov, Rust only, off by default: `FT_EXIT` 99.0, `FT_EXIT_SZ` 0, `FT_EXIT_WIDE` 0, `FT_EXIT_KEEP`
99.0): a reduce-only IOC at the touch when the forecast is against the position by more than FT_EXIT plus half the
spread and the forecast take does not fire, or at a spread of FT_EXIT_WIDE+ unless the forecast is with the position by
FT_EXIT_KEEP. On R3-F3 (`$B1 --set FILTER=1`, 505212.00 on round3_public, unchanged with the knob off) every setting tied or
lost, so no Python file was written (IDEAS.md, "R3-F3's loss anatomy").

R3-F5's state-dependent take bar and flip size (8 Nov, Rust only, off by default: `FT_JUMP` 0.0 with `FT_JUMP_MS` 200,
`FT_JUMP_HOLD_MS` 5000, `FT_JUMP_EDGE` 0.15; `FT_LGAP` 99.0 with `FT_LGAP_EDGE` 0.15; `FT_FLIP_M` 99.0): each side's take
bar is the lowest of FT_EDGE, FT_JUMP_EDGE for FT_JUMP_HOLD_MS after a move of FT_JUMP+ ticks within FT_JUMP_MS, and
FT_LGAP_EDGE while the filter's gap that way is FT_LGAP+; FT_FLIP_M stops a flip at flat unless the signal clears its
bar by that much; `FT_EDGE_CALM` (-1.0: off) the base bar while L8's rate is under `FT_CALM_RATE` (0: QS_RATE);
`FT_JUMP_DIR` (0: both sides) 1 / -1 lowers only the bar the jump's way / against it. F3 unchanged with them off
(505212.00); results in IDEAS.md, "R3-F5". R3-F5
(`r3_F5_jump_bar.py`) is `$B1 --set FILTER=1 --set FT_EDGE=0.25 --set FT_JUMP=3 --set FT_JUMP_HOLD_MS=5000 --set
FT_JUMP_EDGE=0.15`: round3_public 515670.00 and round2_public 330980.00, the Python file's result.json and pnl.csv byte
for byte on round3_public (`test_ridge_maker_round2_takers` keeps F3 and F5 on round2_public). Grids with
`uv run python -m experiments.rounds.paired_rust TAPE ... --bot F3=B1:'--set FILTER=1' --bot X=B1:'--set FILTER=1 --set ...'`.

R3-P1's two more take-bar states (8 Nov, Rust only, off by default: `FT_EDGE_FLIP` -1.0; `FT_SD` 99.0 with `FT_SD_EDGE`
0.15): FT_EDGE_FLIP is the base bar of a take against the position (a reduce or a flip), FT_SD_EDGE caps the bar while the
latent filter's posterior sd is FT_SD+; the jump and gap rules lower either further. F3 505212.00 and F5 515670.00
unchanged with them off. `experiments.rounds.policy_search` tunes them with the rest of the policy (IDEAS.md, "R3-P1").

R4-E1's online ensemble selector (8 Nov, Rust only, off by default: `ENS` 0; F5 515670.00 unchanged with it off) runs
up to five more ridges beside the first model (`ENS_H1` / `ENS_H2` / `ENS_H3` at other horizons, `ENS_NOFILT` without the
filter's features, `ENS_FIMP` on FILTER_IMP2's copy), gives each a paper position under the take rule marked to the
mid net of half the spread a paper trade, decays each paper PnL over `ENS_W_S` seconds, and takes on the leader's
forecast (ENS 1, past `ENS_MARGIN`), the Hedge average (2, `ENS_ETA`) or a majority vote (3). `ENS_DEBUG=path` appends
each run's switches and leaders' time shares. Results in IDEAS.md, "R4-E1".

The round-3 audit's quote knobs (8 Nov, Rust only, off by default: `QS_PULL` 0, `QUOTE_GAP` 99.0) withdraw the
quotes while QS_RATE's switch is off, or on the side the latent filter's gap is against; both lose on R3-F3 (IDEAS.md,
"Round 3 audit"). `RIDGE_PRED_EXTRA` (an environment variable, with `RIDGE_PRED_LOG`) adds the filter's gap and
QS_RATE's speed to the prediction log, for `experiments.taker.quote_audit`.

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
uv run python -m arena.qsim_rust python/bots/qminers/candidates/round1/r1_F8_take_join.py data/arena/round1/round1.csv \
    --grid TAKE_LOTS=0,60 --grid TAKE_OWN=400,800 --grid JOIN_OWN=0,400 --threads 3   # R1-F8 is the baseline (as is)
```

**A new strategy**: a `Strategy` impl in `src/strategies/`, a name in `strategies::make`, its Python file in
`arena.qsim_rust.STRATEGIES`, and a case in `python/tests/test_arena_rust.py` comparing it with the Python one.
A change to `simulator/` (a new starter) needs the port checked again: run that test.
