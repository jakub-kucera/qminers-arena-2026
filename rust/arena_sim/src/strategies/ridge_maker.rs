//! python/bots/qminers/candidates/r1_C1_codex_ridge.py (`PassiveStrategy`, round 1's candidate R1-C1), line for
//! line: an online ridge regression of the mid HORIZON_US ahead on 15 features (trade flow, the 500 ms / 2 s mid
//! EWMA gap, touch and near-touch imbalances, order counts, capped lots, signed squares), an observation every
//! OBSERVATION_INTERVAL_US, labels decayed over MODEL_MEMORY_US, refit by Gauss-Jordan once a second; quotes at
//! min(touch, floor(fair - 0.5)) / mirror, a tick inside when the edge clears INSIDE_TH, up to MAX_ORDERS orders
//! a side, the limit counting every live order, and re-quoting on a cancel landing within 5 ms.
//! The floating-point operations are in the Python's order, so the results are the same to the bit.
//!
//! Parameters, the class constants: `HORIZON_US` (100000), `OBSERVATION_INTERVAL_US` (20000), `MIN_LABELS` (200),
//! `MODEL_MEMORY_US` (300000000), `POSITION_LIMIT` (100), `QUOTE_SIZE` (200), `REQUOTE_US` (0); Rust-only knobs
//! for the file's literals: `INSIDE_TH` (0.3, the predicted edge for a tick inside), `FLOW_CUT` (1.1, the flow
//! beyond which a side is withdrawn), `SKEW_K` (0.025, the inventory skew per spread), `DEAD_ZONE` (0.1, |fair -
//! mid| at or below which fair is the mid), `MAX_ORDERS` (8, a side), `FAST_US` (500000) and `SLOW_US` (2000000),
//! the mid EWMAs, `FLOW_US` (500000, the trade flow's decay), `OFI_US` (500000, the OFI's), `RIDGE_MIN` (10.0) and
//! `RIDGE_FRAC` (0.001): ridge = max(RIDGE_MIN, RIDGE_FRAC * mass), `FIT_US` (1000000, between refits),
//! `REPLENISH_US` (5000, how long after a quote a landed cancel re-quotes), `PRED_MIX` (1.0, the model's weight in
//! fair).
//!
//! Rust-only additions from R1-F8 (python/bots/qminers/candidates/r1_F8_take_join.py, `take_maker`), off by
//! default, so the defaults are R1-C1 as written: the depletion guard, `DEPLETE_LOTS` (0: off) and `DEPL_FRAC`
//! (0.12): when the market's lots at its touch are under DEPLETE_LOTS and under DEPL_FRAC of their peak since that
//! price became the touch (DEPL_FRAC 0: the lots alone), a quote of ours at that touch moves a tick back (ours there
//! cancelled, the room posted behind); the take, `TAKE_LOTS` (0: off), `TAKE_OWN` (800), `TAKE_DEPLETE` (150),
//! `TAKE_MAX` (1000), `TAKE_MS` (250): at a one-tick spread, when the other side's touch is dying (under TAKE_DEPLETE
//! lots and under DEPL_FRAC of its peak; without both, the guard's test) with at most TAKE_MAX lots while ours holds
//! TAKE_OWN or more and we still quote our side, a limit order of TAKE_LOTS (within the limit) at the other side's
//! touch, at most one a side per TAKE_MS, exempt from the re-quote's cancels for TAKE_MS (take_maker's `take`).
//!
//! Learned-model knobs, all off by default (C1 to the bit): `PLACE` (0; 1 adds two features: the share of new market
//! orders landing at/inside the previous touch, bids minus asks, decayed over `PLACE_US1` 100000 and `PLACE_US2` 300000),
//! `DEPTH5` (5-level lots imbalance), `FLOW2` (signed flow over 0.1 s and 2 s), `LAST_AGG` (signed ln(1+lots) of the
//! last aggressive order), `STD` with `STD_US` (scale each feature by its running RMS), `BLEND_W` (0) with `H2_US`
//! (500000): a second ridge on the same features at the H2_US horizon, prediction = (1-W) p1 + W p2.
//! Rust-only additions from v2 (strategy_codex_best_v2_571k.py, 571k), off by default: `EXPOSURE` (0: the
//! POSITION_LIMIT), the lots the quoting, the skew and the withdrawal aim at, while POSITION_LIMIT stays the
//! acceptance wall (v2: POSITION_LIMIT=1000 EXPOSURE=100); `CANCEL_FREE` (0.0): the share of an order being
//! cancelled that no longer counts toward EXPOSURE (v2: 1.0, `ceil(q * (1 - CANCEL_FREE))`); `HEDGE` (0: off), an
//! IOC HEDGE_TICKS (10) through the cached touch (at most HEDGE_STALE_US, 100000, old) for |inventory| - EXPOSURE
//! whenever |inventory| > EXPOSURE, one at a time, from book updates and from private fills (v2's `_hedge`).
//! The dead zone learned from our own fills, off by default: `FILL_LEARN` (0), `FILL_H_US` (400000, the markout
//! horizon), `FILL_MIN` (0.0, ticks), `FILL_WARM` (50.0, fills a bin needs), `FILL_MEM_US` (0: no decay), `FILL_BIN`
//! (0.05), `FILL_Q` (0: off; else the lots ahead that count as the queue's front): each maker fill at a 1-tick touch
//! is binned by the latest forecast toward our side (fair - mid, signed) and our queue class, its markout averaged
//! by lots; at a 1-tick spread a side whose bin is warm steps back only when that mean is below FILL_MIN.
//! Event-time labels (R1-C7), off by default: `LABEL_MODE` (0: clock time; 1: the first model's label is the mid's
//! change at its `LABEL_K`-th (1) change after the observation, dropped if not within `LABEL_CAP_US` (5000000), its
//! observations unbounded by the 64 cap; 2: the sign of that change), the blend's second model staying on clock
//! time; `PRED_SCALE` (1.0), a multiplier on the first model's output before its clamp.
//! The codex v4-v6 features (R1-C9..C12), off by default, appended after the features above, quotes first:
//! `QUOTEFEAT` (0; 1 adds six: fresh market orders within 3 ticks of the touch, counts and price centres, bids /
//! asks, all and those of at most 50 lots, and the cancels within 3 ticks, decayed over `QUOTEFEAT_US` 500000
//! between valid books); `FLOWGRP` (0; 1 adds eight, C9's per-trade groups: market takers still resting after
//! executing, those gone, and those that hit us, their signed lots, share and price offset, decayed over
//! `FLOWGRP_US` 500000; 2, C10's per-taker-order groups, each order's lots capped at `FLOWGRP_CAP` 100).
//! Inventory and room knobs (round 2, IDEAS.md "Inventory and room on R1-C12"), all off by default (C12 to the bit):
//! `SKEW2_K` (0) / `SKEW2_X` (50), an extra skew of SKEW2_K spreads x max(0, |inv| - X) / (EXPOSURE - X);
//! `REDUCE_IN` (0) / `REDUCE_AT` (0: EXPOSURE), the reducing side a tick inside at a 2+ tick spread once |inv| >=
//! REDUCE_AT; `CONF_EXP` (0) / `CONF_TH` (0.3), a side's exposure CONF_EXP unless the forecast its way is >= CONF_TH;
//! `UNWIND_LOTS` (0: off) / `UNWIND_AT` (0: EXPOSURE) / `UNWIND_TH` (0.5) / `UNWIND_US` (100000) / `UNWIND_THRU` (0) /
//! `UNWIND_SAFE` (0): when |inv| >= UNWIND_AT and the forecast is against the position by more than UNWIND_TH
//! spreads, an IOC UNWIND_THRU ticks through the touch for min(UNWIND_LOTS, |inv|), one at a time and one per
//! UNWIND_US; SAFE 1 caps it so every lot on that side fits EXPOSURE, 2 cancels that side first, 3 cancels that
//! side's newest orders until they and the IOC fit (R2-U1, python/bots/qminers/candidates/r2_U1_unwind.py:
//! C12's and --set UNWIND_LOTS=100 --set UNWIND_SAFE=3 --set UNWIND_TH=0.7 --set UNWIND_AT=50 --set UNWIND_US=500000).
//! `RIDGE_DEBUG` in the environment prints, at the end, the maker lots' edge against the mid at the fill, the IOC
//! lots' edge, the time-weighted mean |inventory| and the 25-s PnL steps' mean and sd.
//! Round-2 learned-model knobs (Rust-only, off by default: C12 622920.99 / 21,462 fills unchanged), appended after
//! the features above: `PRIOR_MASS` (0; the warm start: with the env var RIDGE_WARM naming a stats file, each model
//! starts from its X'X / X'y scaled to PRIOR_MASS labels and fits on its first book; RIDGE_DUMP writes that file at
//! `DUMP_US`, else at the run's end); `BUCKET` (0; a mask over 17 more features: 1 six touch-imbalance buckets at a
//! 1-tick spread and six at 2+, 2 our inventory's sign and it times the imbalance, 4 ln(1 + ms since the mid moved)/8
//! and it times the imbalance, 8 the imbalance at a 1-tick spread); `SIDE2` (0; 1 two more ridges on the next bid and
//! the next ask move, each side quoting from mid + (1 - `SIDE_W`) p + SIDE_W p_side; 2 linear-probability models of
//! the bid falling / the ask rising within the horizon, a side a tick back when its probability is over `CLEAR_TH`
//! 0.5); `MH` (0; 1 the forecasts of two more ridges at `MH_US1` 100 ms and `MH_US2` 1 s on the base features as two
//! inputs of the main model).
//! Each candidate on round1.csv, pnl.csv and result.json the same bytes as its Python run (7 Nov):
//!   C5  (r1_C5_long_horizon.py, 595441.83, 21,120 fills): --set POSITION_LIMIT=1000 --set EXPOSURE=100
//!       --set CANCEL_FREE=1.0 --set HEDGE=1 --set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000
//!       --set DEAD_ZONE=0.18
//!   C9  (r1_C9_codex_v4_flow_groups.py, 605752.82, 21,371): C5's and --set FLOWGRP=1
//!   C10 (r1_C10_codex_v4_capped.py, 616534.83, 21,436): C5's and --set FLOWGRP=2 --set FLOWGRP_CAP=100
//!   C11 (r1_C11_codex_v5_29feat.py, 619281.99, 21,460): C5's and --set QUOTEFEAT=1 --set FLOWGRP=2
//!       --set FLOWGRP_CAP=1
//!   C12 (r1_C12_codex_v6.py, 622920.99, 21,462): C5's and --set QUOTEFEAT=1 --set FLOWGRP=2 --set FLOWGRP_CAP=20
//!       --set FLOWGRP_US=1000000
//! The forecast take (R2-FT1), off by default (`FT_SZ` 0): once the model has MIN_LABELS labels, when the
//! prediction net of the skew (`FT_NET` 1; 0: the raw prediction) exceeds `FT_EDGE` (1.0) ticks plus half the
//! spread, an IOC at the far touch (`FT_THRU` 0 ticks through) for min(FT_SZ, the room) lots, at most one per
//! `FT_GAP_MS` (100), exempt from the re-quote's cancels for 1 s; the room is EXPOSURE minus the position its way
//! (`FT_MODE` 0), only the position against it (1: reduce, if at least `FT_INV` 0 lots) or only when not against it
//! (2: open). `RIDGE_PRED_LOG` (an environment variable, a path) writes each book event's time, mid, prediction,
//! skew, spread and inventory, for measuring the forecast.
//!   FT1 (r2_FT1_forecast_take.py, 688311.10, 23,522): C12's and --set FT_EDGE=0.25 --set FT_SZ=200 --set FT_GAP_MS=50
//! Queue preservation (R2-Q, 7 Nov), off by default: an accepted order resting at the market's touch that the
//! quoting would cancel (its price no longer the desired one) keeps its queue place: whole while the market lots
//! ahead of it are at most `FRONT_LOTS` (-1: off) and the forecast toward its side (fair before the dead zone
//! minus the mid, signed) is at least -`FRONT_TH` (99); else shrunk by modify_order to `KEEP_LOTS` (0: off) while
//! that forecast is at least -`KEEP_TH` (99), its target lots counting toward EXPOSURE while the modify is in flight;
//! `FRONT_NONE` (0) applies it when the side is withdrawn too; `LADDER_LOTS` (0) keeps an order one tick behind the
//! desired price, shrunk to that; `SLICE_LOTS` (0) caps each new order, `SLICE_US` (0) between new orders at a price
//! that already holds one; `KEEP_FREE` (0.0) the share of a kept order's lots off the exposure, `KEEP_AHEAD` (-1: any)
//! the most market lots ahead for KEEP, `KEEP_NOBACK` (0) no new order while a kept one rests. QP_STATS=file appends,
//! per run, the maker lots by the market lots ahead at the last book.
//!   R2-Q1 (r2_Q1_keep_slice.py): C12's and --set KEEP_LOTS=20 --set KEEP_TH=0.3
//! Trend and volatility knobs (R2-T, 7 Nov), off by default (every result above unchanged): `OBS_CAP` (0: 64), the
//! observations a clock-time model holds before its oldest is dropped unlabelled (64 at the 20-ms interval is 1.28 s:
//! a HORIZON_US or H2_US past it needs OBS_CAP >= horizon / OBSERVATION_INTERVAL_US); `TREND` (0; 1 adds two base
//! features, mid minus its EWMA over `TREND_US1` 10000000 and over `TREND_US2` 60000000, each clamped to 20 ticks);
//! `VOL_EXP` (0: off): the exposure becomes clip(EXPOSURE * (base / fast)^VOL_EXP, `VOL_MIN` 10, `VOL_MAX` 100) at
//! every valid book, fast the decayed |mid change| ticks a second over `VOL_US` (10000000), base the same over
//! `VOL_BASE_US` (600000000), or the fixed `VOL_REF` ticks a second when VOL_REF > 0 (round 1 runs at 1.23, round 2
//! public at 3.22); it moves the quoting, the skew, the withdrawal, the take's room and the hedge, unless
//! `VOL_NOHEDGE` (0) is 1: the hedge then waits for max(the scaled exposure, EXPOSURE); `LEAN_K` (0: off): the skew
//! aims at the inventory clip(LEAN_K * forecast, +-exposure) instead of 0, the forecast the second model's own
//! (`LEAN_SRC` 0: m2 at H2_US, learning even with BLEND_W 0), the quoting's (1), or the side of the last market
//! order of at least `BIG_LOTS` (500) lots, decayed over `BIG_US` (10000000) (2); `FT_SRC` (0: the quoting's
//! prediction, the blend included; 1: the second model's alone) drives the forecast take.
//!   R2-V1 (r2_V1_vol_exposure.py; round2_public.csv 169262.76 / 19,249 fills, round1.csv 670461.77 / 32,167, pnl.csv
//!       the same bytes): FT1's sets with --set DEAD_ZONE=0.3 --set SKEW_K=0.025 --set QUOTE_SIZE=200 --set KEEP_LOTS=20
//!       --set KEEP_TH=0.3 --set OBS_CAP=2000 --set TREND=1 --set TREND_US1=2000000 --set TREND_US2=60000000
//!       --set EXPOSURE=100 --set VOL_EXP=2 --set VOL_REF=2.5 --set VOL_US=5000000 --set VOL_MAX=100 --set VOL_NOHEDGE=1

use std::collections::{HashMap, HashSet, VecDeque};

use crate::params::Params;
use crate::sim::{BookOrder, Ctx, Owner, PrivateEvent, Side, Snapshot, Status, Strategy, Trade};

const N: usize = 15;
const NM: usize = 64;
const OBS_MAXLEN: usize = 64;

struct Record {
    id: u64,
    sign: i64,
    price: i64,
    quantity: i64,
    accepted: bool,
    cancelling: bool,
    /// a take order: not cancelled by the quoting before this time
    exempt_until: i64,
    /// a modify in flight to these lots (0: none)
    target: i64,
    /// kept by KEEP_LOTS / LADDER_LOTS at a price no longer the desired one
    kept: bool,
}

/// CPython 3.12's `sum()` of floats, start 0 (rust/src/support/py.rs `sum`).
fn py_sum(xs: impl IntoIterator<Item = f64>) -> f64 {
    let mut it = xs.into_iter();
    let Some(first) = it.next() else { return 0.0 };
    let mut f = 0.0 + first;
    let mut c = 0.0f64;
    for x in it {
        let t = f + x;
        if f.abs() >= x.abs() {
            c += (f - t) + x;
        } else {
            c += (x - t) + f;
        }
        f = t;
    }
    if c != 0.0 && c.is_finite() {
        f += c;
    }
    f
}

/// Python's max(lo, min(hi, x)) on floats (equal values keep the first, which is the same number).
fn clamp(x: f64, lo: f64, hi: f64) -> f64 {
    let m = if x < hi { x } else { hi };
    if m > lo {
        m
    } else {
        lo
    }
}

struct Model {
    horizon_us: i64,
    n: usize,
    /// 0 the change; 1 the indicator of a fall, 2 of a rise (SIDE2 2's linear-probability classifiers)
    label: i64,
    observations: VecDeque<(i64, f64, [f64; NM], i64)>,
    last_fit_us: Option<i64>,
    last_label_us: Option<i64>,
    labels: i64,
    mass: f64,
    xx: [[f64; NM]; NM],
    xy: [f64; NM],
    weights: [f64; NM],
}

impl Model {
    fn new(horizon_us: i64, n: usize) -> Model {
        Model {
            horizon_us,
            n,
            label: 0,
            observations: VecDeque::with_capacity(OBS_MAXLEN),
            last_fit_us: None,
            last_label_us: None,
            labels: 0,
            mass: 0.0,
            xx: [[0.0; NM]; NM],
            xy: [0.0; NM],
            weights: [0.0; NM],
        }
    }
}

pub struct RidgeMaker {
    horizon_us: i64,
    observation_interval_us: i64,
    min_labels: i64,
    model_memory_us: i64,
    position_limit: i64,
    quote_size: i64,
    requote_us: i64,
    inside_th: f64,
    flow_cut: f64,
    skew_k: f64,
    dead_zone: f64,
    max_orders: usize,
    fast_us: i64,
    slow_us: i64,
    flow_us: i64,
    ofi_us: i64,
    ridge_min: f64,
    ridge_frac: f64,
    fit_us: i64,
    replenish_us: i64,
    pred_mix: f64,
    deplete_lots: i64,
    depl_frac: f64,
    take_lots: i64,
    take_own: i64,
    take_deplete: i64,
    take_max: i64,
    take_ms: i64,
    take_block: [i64; 2],
    exposure: i64,
    cancel_free: f64,
    hedge: bool,
    hedge_ticks: i64,
    hedge_stale_us: i64,
    hedge_id: Option<u64>,
    cached: Option<(i64, i64, i64)>,
    /// per side (bid, ask): [touch price, the market's lots there at their most since]
    peak: [Option<(i64, i64)>; 2],

    inventory: i64,
    orders: Vec<Record>,
    desired_buy: Option<i64>,
    desired_sell: Option<i64>,
    desired_time: Option<i64>,
    m1: Model,
    m2: Model,
    n: usize,
    last_observation_us: i64,
    place: i64,
    place_us1: i64,
    place_us2: i64,
    depth5: i64,
    flow2: i64,
    last_agg: i64,
    std_on: i64,
    std_us: i64,
    blend_w: f64,
    label_mode: i64,
    label_k: i64,
    label_cap_us: i64,
    pred_scale: f64,
    /// the number of mid changes seen so far and the last mid
    mid_changes: i64,
    last_mid: Option<f64>,
    seen: HashSet<u64>,
    seen_next: HashSet<u64>,
    /// per tau: [bid at/inside, bid all, ask at/inside, ask all]
    place_acc: [[f64; 4]; 2],
    flow_fast: (f64, f64),
    flow_slow: (f64, f64),
    last_agg_value: f64,
    std_m2: [f64; NM],
    std_mass: f64,
    fast_mid: f64,
    slow_mid: f64,
    model_time: Option<i64>,
    ofi: f64,
    ofi_time: Option<i64>,
    previous_touch: Option<(i64, i64, i64, i64)>,
    last_action: [i64; 2],
    last_us: Option<i64>,
    net: f64,
    volume: f64,
    invalid_since: Option<i64>,
    fill_learn: bool,
    fill_h_us: i64,
    fill_min: f64,
    fill_warm: f64,
    fill_mem_us: i64,
    fill_bin: f64,
    last_d: Option<f64>,
    /// maker fills at a 1-tick touch awaiting their markout: (time, sign, price, lots, forecast toward our side)
    pending: VecDeque<(i64, i64, i64, i64, f64, usize)>,
    /// per bin of the signed forecast: [fills, lots, lots * markout], decayed together
    bins: Vec<[f64; 3]>,
    bins_time: Option<i64>,
    fill_q: i64,
    /// per side: the market lots ahead of our first order at the touch, from the last book
    front_ahead: [Option<i64>; 2],
    /// R1-C9..C12's aggressive-flow groups: 0 off, 1 v4 (per trade, the visible remainder once), 2 v4 capped
    flowgrp: i64,
    flowgrp_cap: i64,
    flowgrp_us: i64,
    /// per group (taker still visible, taker gone, our makers): signed lots, lots, lots * price, decayed together
    grp_net: [f64; 3],
    grp_vol: [f64; 3],
    grp_price: [f64; 3],
    rest_net: f64,
    rest_cnt: f64,
    /// R1-C11's fresh quote-price centres and cancellation pressure
    quotefeat: i64,
    quotefeat_us: i64,
    known: Vec<BookOrder>,
    known_ids: HashSet<u64>,
    /// [bid new, ask new, bid new <= 50 lots, ask new <= 50 lots]: counts and price sums
    new_counts: [f64; 4],
    new_values: [f64; 4],
    cancel_net: f64,
    cancel_mass: f64,
    new_quote_time: Option<i64>,
    /// R2 inventory knobs, all off by default
    skew2_k: f64,
    skew2_x: i64,
    reduce_in: i64,
    reduce_at: i64,
    conf_exp: i64,
    conf_th: f64,
    side_exp: [i64; 2],
    unwind_lots: i64,
    unwind_at: i64,
    unwind_th: f64,
    unwind_us: i64,
    unwind_thru: i64,
    unwind_safe: i64,
    unwind_id: Option<u64>,
    unwind_block: i64,
    /// RIDGE_DEBUG: [maker lots, maker edge vs the mid, IOC lots, IOC edge, books at the limit, books]
    dbg: [f64; 6],
    /// RIDGE_DEBUG: cash, time-weighted |inventory| (sum, time), the 25-s PnL steps (n, sum, sum of squares, last pnl, next sample)
    dbg_cash: f64,
    dbg_inv: [f64; 2],
    dbg_inv_t: Option<i64>,
    dbg_steps: [f64; 5],
    /// the forecast take (R2-FT), off by default (FT_SZ 0)
    ft_edge: f64,
    ft_sz: i64,
    ft_gap_ms: i64,
    ft_mode: i64,
    ft_inv: i64,
    ft_thru: i64,
    ft_net: i64,
    ft_last: i64,
    /// RIDGE_PRED_LOG (env var, a path): each book event's time, mid, prediction, skew, spread, inventory
    pred_log: Option<std::io::BufWriter<std::fs::File>>,
    /// round-2 learned-model knobs (all off by default)
    prior_mass: f64,
    dump_us: i64,
    dump_snap: Option<String>,
    bucket: i64,
    side2: i64,
    side_w: f64,
    clear_th: f64,
    mh: i64,
    n_base: usize,
    /// extra models: 0 the next bid move, 1 the next ask move (SIDE2), 2 / 3 the MH_US1 / MH_US2 mid models (MH)
    ex: Vec<Model>,
    last_mid_change_us: i64,
    /// round-2 trend knobs (all off by default)
    obs_cap: usize,
    trend: i64,
    trend_us: [i64; 2],
    trend_e: [f64; 2],
    trend_time: Option<i64>,
    exposure_base: i64,
    vol_exp: f64,
    vol_us: [i64; 2],
    vol_min: i64,
    vol_max: i64,
    /// per window (fast, base): [decayed |mid change| ticks, decayed microseconds]
    vol_acc: [[f64; 2]; 2],
    vol_last: Option<(i64, f64)>,
    vol_ref: f64,
    vol_nohedge: bool,
    big_lots: i64,
    big_us: i64,
    /// the last market order of at least BIG_LOTS: (time, sign)
    big_last: Option<(i64, f64)>,
    lean_k: f64,
    lean_src: i64,
    ft_src: i64,
    /// queue preservation (R2-Q): KEEP_LOTS, KEEP_TH, FRONT_LOTS, FRONT_TH, FRONT_NONE, SLICE_LOTS, SLICE_US
    keep_lots: i64,
    keep_th: f64,
    front_lots: i64,
    front_th: f64,
    front_none: bool,
    slice_lots: i64,
    slice_us: i64,
    ladder_lots: i64,
    keep_free: f64,
    keep_ahead: i64,
    keep_noback: bool,
    qp: bool,
    /// our orders at the market's touch: id -> the market lots ahead of it
    ahead: HashMap<u64, i64>,
    qp_touch: [i64; 2],
    qp_d: f64,
    /// diagnostics (env QP_STATS=file, appended on drop): maker lots by the lots ahead at the last book
    /// [front 0, 1-100, 101-300, 300+, not at the touch], sum of |inventory| over books, books
    stats: Option<String>,
    stat_lots: [i64; 5],
    stat_inv: (f64, f64),
    stat_tag: String,
}

impl RidgeMaker {
    /// RIDGE_DUMP: the models' sufficient statistics (at DUMP_US, else at the end) to that file, for a warm start
    fn dump_on_drop(&mut self) {
        if std::env::var("RIDGE_DEBUG").is_ok() {
            eprintln!(
                "RIDGE_DEBUG maker_lots={} maker_edge={:.1} ioc_lots={} ioc_edge={:.1} at_limit_share={:.3} final_inv={}",
                self.dbg[0], self.dbg[1], self.dbg[2], self.dbg[3], self.dbg[4] / self.dbg[5].max(1.0), self.inventory
            );
            let st = self.dbg_steps;
            let mean = st[1] / st[0].max(1.0);
            eprintln!(
                "RIDGE_DEBUG mean_abs_inv={:.1} step25_n={} step25_mean={:.1} step25_sd={:.1}",
                self.dbg_inv[0] / self.dbg_inv[1].max(1.0), st[0], mean, (st[2] / st[0].max(1.0) - mean * mean).max(0.0).sqrt()
            );
        }
        let Ok(path) = std::env::var("RIDGE_DUMP") else { return };
        let text = match self.dump_snap.take() {
            Some(t) => t,
            None => self.stats_text(),
        };
        let tmp = format!("{path}.{}.tmp", std::process::id() as u64 * 1000 + (self as *const _ as u64 % 997));
        if std::fs::write(&tmp, text).is_ok() {
            let _ = std::fs::rename(&tmp, &path);
        }
    }
}

impl Drop for RidgeMaker {
    fn drop(&mut self) {
        self.dump_on_drop();
        let Some(path) = &self.stats else { return };
        use std::io::Write;
        let total: i64 = self.stat_lots.iter().sum();
        let line = format!(
            "{}\tmaker_lots={}\tfront={:.3}\t1-100={:.3}\t101-300={:.3}\t300+={:.3}\toff={:.3}\tmean_abs_inv={:.1}\n",
            self.stat_tag,
            total,
            self.stat_lots[0] as f64 / total.max(1) as f64,
            self.stat_lots[1] as f64 / total.max(1) as f64,
            self.stat_lots[2] as f64 / total.max(1) as f64,
            self.stat_lots[3] as f64 / total.max(1) as f64,
            self.stat_lots[4] as f64 / total.max(1) as f64,
            self.stat_inv.0 / self.stat_inv.1.max(1.0),
        );
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
            let _ = f.write_all(line.as_bytes());
        }
    }
}

pub const KEYS: [&str; 114] = [
    "HORIZON_US", "OBSERVATION_INTERVAL_US", "MIN_LABELS", "MODEL_MEMORY_US", "POSITION_LIMIT", "QUOTE_SIZE",
    "REQUOTE_US", "INSIDE_TH", "FLOW_CUT", "SKEW_K", "DEAD_ZONE", "MAX_ORDERS", "FAST_US", "SLOW_US", "FLOW_US",
    "OFI_US", "RIDGE_MIN", "RIDGE_FRAC", "FIT_US", "REPLENISH_US", "PRED_MIX",
    "DEPLETE_LOTS", "DEPL_FRAC", "TAKE_LOTS", "TAKE_OWN", "TAKE_DEPLETE", "TAKE_MAX", "TAKE_MS",
    "PLACE", "PLACE_US1", "PLACE_US2", "DEPTH5", "FLOW2", "LAST_AGG", "STD", "STD_US", "BLEND_W", "H2_US",
    "EXPOSURE", "CANCEL_FREE", "HEDGE", "HEDGE_TICKS", "HEDGE_STALE_US",
    "FILL_LEARN", "FILL_H_US", "FILL_MIN", "FILL_WARM", "FILL_MEM_US", "FILL_BIN", "FILL_Q",
    "LABEL_MODE", "LABEL_K", "LABEL_CAP_US", "PRED_SCALE",
    "FLOWGRP", "FLOWGRP_CAP", "FLOWGRP_US", "QUOTEFEAT", "QUOTEFEAT_US",
    "SKEW2_K", "SKEW2_X", "REDUCE_IN", "REDUCE_AT", "CONF_EXP", "CONF_TH",
    "UNWIND_LOTS", "UNWIND_AT", "UNWIND_TH", "UNWIND_US", "UNWIND_THRU", "UNWIND_SAFE",
    "FT_EDGE", "FT_SZ", "FT_GAP_MS", "FT_MODE", "FT_INV", "FT_THRU", "FT_NET",
    "PRIOR_MASS", "DUMP_US", "BUCKET", "SIDE2", "SIDE_W", "MH", "MH_US1", "MH_US2", "CLEAR_TH",
    "OBS_CAP", "TREND", "TREND_US1", "TREND_US2", "VOL_EXP", "VOL_US", "VOL_BASE_US", "VOL_MIN", "VOL_MAX",
    "LEAN_K", "LEAN_SRC", "FT_SRC", "VOL_REF", "VOL_NOHEDGE", "BIG_LOTS", "BIG_US",
    "KEEP_LOTS", "KEEP_TH", "FRONT_LOTS", "FRONT_TH", "FRONT_NONE", "SLICE_LOTS", "SLICE_US", "LADDER_LOTS", "KEEP_FREE", "KEEP_AHEAD", "KEEP_NOBACK",
];

fn side_index(sign: i64) -> usize {
    if sign > 0 {
        0
    } else {
        1
    }
}

impl RidgeMaker {
    pub fn new(params: &Params) -> Result<RidgeMaker, String> {
        params.check_keys(&KEYS)?;
        let n_base = N + if params.int("PLACE", 0)? > 0 { 2 } else { 0 }
                + if params.int("DEPTH5", 0)? > 0 { 1 } else { 0 }
                + if params.int("FLOW2", 0)? > 0 { 2 } else { 0 }
                + if params.int("LAST_AGG", 0)? > 0 { 1 } else { 0 }
                + if params.int("QUOTEFEAT", 0)? > 0 { 6 } else { 0 }
                + if params.int("FLOWGRP", 0)? > 0 { 8 } else { 0 }
                + if params.int("BUCKET", 0)? > 0 { 17 } else { 0 }
                + if params.int("TREND", 0)? > 0 { 2 } else { 0 };
        let mh = params.int("MH", 0)?;
        let n = n_base + if mh > 0 { 2 } else { 0 };
        let horizon_us = params.int("HORIZON_US", 100_000)?;
        let mut rm = RidgeMaker::build(params, n_base, n)?;
        rm.ex = vec![
            Model::new(horizon_us, n),
            Model::new(horizon_us, n),
            Model::new(params.int("MH_US1", 100_000)?, n_base),
            Model::new(params.int("MH_US2", 1_000_000)?, n_base),
        ];
        rm.mh = mh;
        if rm.side2 == 2 {
            rm.ex[0].label = 1;
            rm.ex[1].label = 2;
        }
        rm.load_warm();
        Ok(rm)
    }

    fn build(params: &Params, n_base: usize, n: usize) -> Result<RidgeMaker, String> {
        let position_limit = params.int("POSITION_LIMIT", 100)?;
        let exposure = params.int("EXPOSURE", 0)?;
        Ok(RidgeMaker {
            exposure: if exposure > 0 { exposure } else { position_limit },
            cancel_free: params.float("CANCEL_FREE", 0.0)?,
            hedge: params.int("HEDGE", 0)? != 0,
            hedge_ticks: params.int("HEDGE_TICKS", 10)?,
            hedge_stale_us: params.int("HEDGE_STALE_US", 100_000)?,
            hedge_id: None,
            cached: None,
            horizon_us: params.int("HORIZON_US", 100_000)?,
            observation_interval_us: params.int("OBSERVATION_INTERVAL_US", 20_000)?,
            min_labels: params.int("MIN_LABELS", 200)?,
            model_memory_us: params.int("MODEL_MEMORY_US", 300_000_000)?,
            position_limit,
            quote_size: params.int("QUOTE_SIZE", 200)?,
            requote_us: params.int("REQUOTE_US", 0)?,
            inside_th: params.float("INSIDE_TH", 0.3)?,
            flow_cut: params.float("FLOW_CUT", 1.1)?,
            skew_k: params.float("SKEW_K", 0.025)?,
            dead_zone: params.float("DEAD_ZONE", 0.1)?,
            max_orders: params.int("MAX_ORDERS", 8)? as usize,
            fast_us: params.int("FAST_US", 500_000)?,
            slow_us: params.int("SLOW_US", 2_000_000)?,
            flow_us: params.int("FLOW_US", 500_000)?,
            ofi_us: params.int("OFI_US", 500_000)?,
            ridge_min: params.float("RIDGE_MIN", 10.0)?,
            ridge_frac: params.float("RIDGE_FRAC", 0.001)?,
            fit_us: params.int("FIT_US", 1_000_000)?,
            replenish_us: params.int("REPLENISH_US", 5000)?,
            pred_mix: params.float("PRED_MIX", 1.0)?,
            deplete_lots: params.int("DEPLETE_LOTS", 0)?,
            depl_frac: params.float("DEPL_FRAC", 0.12)?,
            take_lots: params.int("TAKE_LOTS", 0)?,
            take_own: params.int("TAKE_OWN", 800)?,
            take_deplete: params.int("TAKE_DEPLETE", 150)?,
            take_max: params.int("TAKE_MAX", 1000)?,
            take_ms: params.int("TAKE_MS", 250)?,
            take_block: [0, 0],
            peak: [None, None],
            inventory: 0,
            orders: Vec::new(),
            desired_buy: None,
            desired_sell: None,
            desired_time: None,
            m1: Model::new(params.int("HORIZON_US", 100_000)?, n),
            m2: Model::new(params.int("H2_US", 500_000)?, n),
            n,
            last_observation_us: -100_000,
            place: params.int("PLACE", 0)?,
            place_us1: params.int("PLACE_US1", 100_000)?,
            place_us2: params.int("PLACE_US2", 300_000)?,
            depth5: params.int("DEPTH5", 0)?,
            flow2: params.int("FLOW2", 0)?,
            last_agg: params.int("LAST_AGG", 0)?,
            std_on: params.int("STD", 0)?,
            std_us: params.int("STD_US", 60_000_000)?,
            blend_w: params.float("BLEND_W", 0.0)?,
            label_mode: params.int("LABEL_MODE", 0)?,
            label_k: params.int("LABEL_K", 1)?,
            label_cap_us: params.int("LABEL_CAP_US", 5_000_000)?,
            pred_scale: params.float("PRED_SCALE", 1.0)?,
            mid_changes: 0,
            last_mid: None,
            seen: HashSet::new(),
            seen_next: HashSet::new(),
            place_acc: [[0.0; 4]; 2],
            flow_fast: (0.0, 0.0),
            flow_slow: (0.0, 0.0),
            last_agg_value: 0.0,
            std_m2: [0.0; NM],
            std_mass: 0.0,
            fast_mid: 0.0,
            slow_mid: 0.0,
            model_time: None,
            ofi: 0.0,
            ofi_time: None,
            previous_touch: None,
            last_action: [-5000, -5000],
            last_us: None,
            net: 0.0,
            volume: 0.0,
            invalid_since: None,
            fill_learn: params.int("FILL_LEARN", 0)? != 0,
            fill_h_us: params.int("FILL_H_US", 400_000)?,
            fill_min: params.float("FILL_MIN", 0.0)?,
            fill_warm: params.float("FILL_WARM", 50.0)?,
            fill_mem_us: params.int("FILL_MEM_US", 0)?,
            fill_bin: params.float("FILL_BIN", 0.05)?,
            last_d: None,
            pending: VecDeque::new(),
            bins: vec![[0.0; 3]; 2 * ((2.0 / params.float("FILL_BIN", 0.05)?).ceil() as usize + 1)],
            fill_q: params.int("FILL_Q", 0)?,
            front_ahead: [None, None],
            bins_time: None,
            flowgrp: params.int("FLOWGRP", 0)?,
            flowgrp_cap: params.int("FLOWGRP_CAP", 100)?,
            flowgrp_us: params.int("FLOWGRP_US", 500_000)?,
            grp_net: [0.0; 3],
            grp_vol: [0.0; 3],
            grp_price: [0.0; 3],
            rest_net: 0.0,
            rest_cnt: 0.0,
            quotefeat: params.int("QUOTEFEAT", 0)?,
            quotefeat_us: params.int("QUOTEFEAT_US", 500_000)?,
            known: Vec::new(),
            known_ids: HashSet::new(),
            new_counts: [0.0; 4],
            new_values: [0.0; 4],
            cancel_net: 0.0,
            cancel_mass: 0.0,
            new_quote_time: None,
            skew2_k: params.float("SKEW2_K", 0.0)?,
            skew2_x: params.int("SKEW2_X", 50)?,
            reduce_in: params.int("REDUCE_IN", 0)?,
            reduce_at: params.int("REDUCE_AT", 0)?,
            conf_exp: params.int("CONF_EXP", 0)?,
            conf_th: params.float("CONF_TH", 0.3)?,
            side_exp: [0, 0],
            unwind_lots: params.int("UNWIND_LOTS", 0)?,
            unwind_at: params.int("UNWIND_AT", 0)?,
            unwind_th: params.float("UNWIND_TH", 0.5)?,
            unwind_us: params.int("UNWIND_US", 100_000)?,
            unwind_thru: params.int("UNWIND_THRU", 0)?,
            unwind_safe: params.int("UNWIND_SAFE", 0)?,
            unwind_id: None,
            unwind_block: 0,
            dbg: [0.0; 6],
            dbg_cash: 0.0,
            dbg_inv: [0.0; 2],
            dbg_inv_t: None,
            dbg_steps: [0.0, 0.0, 0.0, 0.0, 25_000_000.0],
            ft_edge: params.float("FT_EDGE", 1.0)?,
            ft_sz: params.int("FT_SZ", 0)?,
            ft_gap_ms: params.int("FT_GAP_MS", 100)?,
            ft_mode: params.int("FT_MODE", 0)?,
            ft_inv: params.int("FT_INV", 0)?,
            ft_thru: params.int("FT_THRU", 0)?,
            ft_net: params.int("FT_NET", 1)?,
            ft_last: i64::MIN / 2,
            pred_log: std::env::var("RIDGE_PRED_LOG")
                .ok()
                .map(|p| std::io::BufWriter::new(std::fs::File::create(p).expect("RIDGE_PRED_LOG"))),
            prior_mass: params.float("PRIOR_MASS", 0.0)?,
            dump_us: params.int("DUMP_US", 0)?,
            dump_snap: None,
            bucket: params.int("BUCKET", 0)?,
            side2: params.int("SIDE2", 0)?,
            side_w: params.float("SIDE_W", 1.0)?,
            clear_th: params.float("CLEAR_TH", 0.5)?,
            mh: 0,
            n_base,
            ex: Vec::new(),
            last_mid_change_us: 0,
            obs_cap: match params.int("OBS_CAP", 0)? {
                c if c > 0 => c as usize,
                _ => OBS_MAXLEN,
            },
            trend: params.int("TREND", 0)?,
            trend_us: [params.int("TREND_US1", 10_000_000)?, params.int("TREND_US2", 60_000_000)?],
            trend_e: [0.0; 2],
            trend_time: None,
            exposure_base: if exposure > 0 { exposure } else { position_limit },
            vol_exp: params.float("VOL_EXP", 0.0)?,
            vol_us: [params.int("VOL_US", 10_000_000)?, params.int("VOL_BASE_US", 600_000_000)?],
            vol_min: params.int("VOL_MIN", 10)?,
            vol_max: params.int("VOL_MAX", 100)?,
            vol_acc: [[0.0; 2]; 2],
            vol_last: None,
            vol_ref: params.float("VOL_REF", 0.0)?,
            vol_nohedge: params.int("VOL_NOHEDGE", 0)? != 0,
            big_lots: params.int("BIG_LOTS", 500)?,
            big_us: params.int("BIG_US", 10_000_000)?,
            big_last: None,
            lean_k: params.float("LEAN_K", 0.0)?,
            lean_src: params.int("LEAN_SRC", 0)?,
            ft_src: params.int("FT_SRC", 0)?,
            keep_lots: params.int("KEEP_LOTS", 0)?,
            keep_th: params.float("KEEP_TH", 99.0)?,
            front_lots: params.int("FRONT_LOTS", -1)?,
            front_th: params.float("FRONT_TH", 99.0)?,
            front_none: params.int("FRONT_NONE", 0)? != 0,
            slice_lots: params.int("SLICE_LOTS", 0)?,
            slice_us: params.int("SLICE_US", 0)?,
            ladder_lots: params.int("LADDER_LOTS", 0)?,
            keep_free: params.float("KEEP_FREE", 0.0)?,
            keep_ahead: params.int("KEEP_AHEAD", -1)?,
            keep_noback: params.int("KEEP_NOBACK", 0)? != 0,
            qp: params.int("KEEP_LOTS", 0)? > 0 || params.int("FRONT_LOTS", -1)? >= 0 || params.int("LADDER_LOTS", 0)? > 0,
            ahead: HashMap::new(),
            qp_touch: [0, 0],
            qp_d: 0.0,
            stats: std::env::var("QP_STATS").ok(),
            stat_lots: [0; 5],
            stat_inv: (0.0, 0.0),
            stat_tag: format!(
                "KEEP_FREE={} LADDER={} KEEP_LOTS={} KEEP_TH={} FRONT_LOTS={} FRONT_TH={} FRONT_NONE={} SLICE_LOTS={} SLICE_US={} DEAD_ZONE={} EXPOSURE={}",
                params.float("KEEP_FREE", 0.0)?, params.int("LADDER_LOTS", 0)?, params.int("KEEP_LOTS", 0)?, params.float("KEEP_TH", 99.0)?, params.int("FRONT_LOTS", -1)?,
                params.float("FRONT_TH", 99.0)?, params.int("FRONT_NONE", 0)?, params.int("SLICE_LOTS", 0)?,
                params.int("SLICE_US", 0)?, params.float("DEAD_ZONE", 0.1)?, params.int("EXPOSURE", 0)?
            ),
        })
    }

    fn models_mut(&mut self) -> Vec<&mut Model> {
        let mut v: Vec<&mut Model> = vec![&mut self.m1, &mut self.m2];
        v.extend(self.ex.iter_mut());
        v
    }

    /// the sufficient statistics of every model, as text (the warm start's file format)
    fn stats_text(&mut self) -> String {
        let mut out = String::new();
        for (i, m) in self.models_mut().into_iter().enumerate() {
            if m.labels == 0 {
                continue;
            }
            out.push_str(&format!("M {} {} {:?} {}\n", i, m.n, m.mass, m.labels));
            for r in 0..m.n {
                let row: Vec<String> = (0..m.n).map(|c| format!("{:?}", m.xx[r][c])).collect();
                out.push_str(&row.join(" "));
                out.push('\n');
            }
            let row: Vec<String> = (0..m.n).map(|c| format!("{:?}", m.xy[c])).collect();
            out.push_str(&row.join(" "));
            out.push('\n');
        }
        out
    }

    /// WARM START: with PRIOR_MASS > 0 and RIDGE_WARM naming a stats file, each model whose size matches starts from
    /// those statistics scaled to PRIOR_MASS labels (and fits on its first book).
    fn load_warm(&mut self) {
        if self.prior_mass <= 0.0 {
            return;
        }
        let Ok(path) = std::env::var("RIDGE_WARM") else { return };
        let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("RIDGE_WARM {path}: {e}"));
        let (prior, min_labels) = (self.prior_mass, self.min_labels);
        let mut lines = text.lines();
        let mut models = self.models_mut();
        while let Some(head) = lines.next() {
            let f: Vec<&str> = head.split_whitespace().collect();
            let (i, n, mass): (usize, usize, f64) = (f[1].parse().unwrap(), f[2].parse().unwrap(), f[3].parse().unwrap());
            let rows: Vec<Vec<f64>> =
                (0..=n).map(|_| lines.next().unwrap().split_whitespace().map(|x| x.parse().unwrap()).collect()).collect();
            if i >= models.len() || models[i].n != n {
                continue;
            }
            let m = &mut models[i];
            let scale = prior / mass;
            for r in 0..n {
                for c in 0..n {
                    m.xx[r][c] = rows[r][c] * scale;
                }
                m.xy[r] = rows[n][r] * scale;
            }
            m.mass = prior;
            m.labels = min_labels;
        }
    }

    fn learn(&mut self, which: usize, now: i64, mid: f64) {
        let (min_labels, memory, fit_us, ridge_min, ridge_frac) =
            (self.min_labels, self.model_memory_us, self.fit_us, self.ridge_min, self.ridge_frac);
        // the event-time label is the first model's; the blend's second model stays on clock time
        let (label_mode, label_k, label_cap_us, changes) =
            (if which == 0 { self.label_mode } else { 0 }, self.label_k, self.label_cap_us, self.mid_changes);
        let m = match which {
            0 => &mut self.m1,
            1 => &mut self.m2,
            k => &mut self.ex[k - 2],
        };
        let n = m.n;
        while let Some(&(observed_us, old_mid, features, count)) = m.observations.front() {
            if label_mode > 0 {
                // event time: the label is the mid at its LABEL_K-th change after the observation
                if count + label_k <= changes {
                    m.observations.pop_front();
                    if now - observed_us > label_cap_us {
                        continue;
                    }
                } else if now - observed_us > label_cap_us {
                    m.observations.pop_front();
                    continue;
                } else {
                    break;
                }
            } else {
                if observed_us + m.horizon_us > now {
                    break;
                }
                m.observations.pop_front();
                if now - observed_us > m.horizon_us + 1_000_000 {
                    continue;
                }
            }
            let elapsed = match m.last_label_us {
                None => 0,
                Some(t) => now - t,
            };
            let decay = ((-(elapsed.max(0))) as f64 / memory as f64).exp();
            m.last_label_us = Some(now);
            let mut response = clamp(mid - old_mid, -20.0, 20.0);
            if label_mode == 2 {
                response = if response > 0.0 { 1.0 } else if response < 0.0 { -1.0 } else { 0.0 };
            }
            if m.label == 1 {
                response = if response < 0.0 { 1.0 } else { 0.0 };
            } else if m.label == 2 {
                response = if response > 0.0 { 1.0 } else { 0.0 };
            }
            m.mass = m.mass * decay + 1.0;
            for i in 0..n {
                m.xy[i] = m.xy[i] * decay + features[i] * response;
                for j in 0..n {
                    m.xx[i][j] = m.xx[i][j] * decay + features[i] * features[j];
                }
            }
            m.labels += 1;
        }
        if m.labels < min_labels {
            return;
        }
        if let Some(t) = m.last_fit_us {
            if now - t < fit_us {
                return;
            }
        }
        m.last_fit_us = Some(now);
        let r = ridge_frac * m.mass;
        let ridge = if r > ridge_min { r } else { ridge_min };
        let mut matrix = [[0.0f64; NM + 1]; NM];
        for i in 0..n {
            matrix[i][..n].copy_from_slice(&m.xx[i][..n]);
            matrix[i][n] = m.xy[i];
        }
        for i in 0..n {
            matrix[i][i] += ridge;
        }
        for col in 0..n {
            let pivot = matrix[col][col];
            if !pivot.is_finite() || pivot <= 1e-12 {
                return;
            }
            for j in col..=n {
                matrix[col][j] /= pivot;
            }
            for i in 0..n {
                if i == col {
                    continue;
                }
                let factor = matrix[i][col];
                for j in col..=n {
                    matrix[i][j] -= factor * matrix[col][j];
                }
            }
        }
        let mut weights = [0.0; NM];
        for i in 0..n {
            weights[i] = matrix[i][n];
        }
        if weights.iter().all(|w| w.is_finite()) {
            m.weights = weights;
        }
    }

    fn fill_bin_index(&self, ps: f64, back: usize) -> usize {
        let nb = self.bins.len() / 2;
        let i = ((clamp(ps, -1.0, 1.0) + 1.0) / self.fill_bin).floor() as usize;
        i.min(nb - 1) + back * nb
    }

    /// 1 when our queue on that side is behind FILL_Q lots (or we have no order at the touch), 0 at the front
    fn queue_class(&self, key: usize) -> usize {
        if self.fill_q <= 0 {
            return 0;
        }
        match self.front_ahead[key] {
            Some(a) if a <= self.fill_q => 0,
            _ => 1,
        }
    }

    /// the decay of the bins from their last update to `now` (1 without FILL_MEM_US)
    fn fill_decay(&self, now: i64) -> f64 {
        match self.bins_time {
            Some(t) if self.fill_mem_us > 0 => ((-((now - t).max(0))) as f64 / self.fill_mem_us as f64).exp(),
            _ => 1.0,
        }
    }

    fn fill_mature(&mut self, now: i64, mid: f64) {
        while let Some(&(t, sign, price, lots, ps, back)) = self.pending.front() {
            if t + self.fill_h_us > now {
                break;
            }
            self.pending.pop_front();
            let markout = sign as f64 * (mid - price as f64);
            let decay = self.fill_decay(now);
            self.bins_time = Some(now);
            if decay != 1.0 {
                for b in self.bins.iter_mut() {
                    b[0] *= decay;
                    b[1] *= decay;
                    b[2] *= decay;
                }
            }
            let i = self.fill_bin_index(ps, back);
            self.bins[i][0] += 1.0;
            self.bins[i][1] += lots as f64;
            self.bins[i][2] += lots as f64 * markout;
        }
    }

    /// the learned mean markout of a touch fill at the forecast `ps` toward our side, once its bin is warm
    fn fill_mean(&self, now: i64, ps: f64, back: usize) -> Option<f64> {
        let b = self.bins[self.fill_bin_index(ps, back)];
        if b[0] * self.fill_decay(now) < self.fill_warm || b[1] <= 0.0 {
            return None;
        }
        Some(b[2] / b[1])
    }

    /// R1-C9 / C10 / C11's aggressive-flow groups, decayed over FLOWGRP_US: each market taker's lots by whether it
    /// still rests in the book (0) or not (1), and the lots it took from us (2). FLOWGRP 1 (C9): per trade, the
    /// visible remainder added once at its price; 2 (C10): per taker order, its executed plus visible lots capped at
    /// FLOWGRP_CAP (C10 100, C11 1, C12 20), priced at the remainder's price or the executed mean.
    fn flow_groups(&mut self, snapshot: &Snapshot, trades: &[Trade], elapsed: i64) {
        let d = ((-elapsed) as f64 / self.flowgrp_us as f64).exp();
        for i in 0..3 {
            self.grp_net[i] *= d;
            self.grp_vol[i] *= d;
            self.grp_price[i] *= d;
        }
        self.rest_net *= d;
        self.rest_cnt *= d;
        if trades.is_empty() {
            return;
        }
        let mut visible: HashMap<u64, BookOrder> = HashMap::new();
        for side in [Side::Buy, Side::Sell] {
            for order in snapshot.side(side) {
                if order.owner == Owner::Market {
                    visible.insert(order.order_id, order);
                }
            }
        }
        if self.flowgrp == 1 {
            let mut counted: HashSet<u64> = HashSet::new();
            for trade in trades {
                if trade.taker_owner != Owner::Market {
                    continue;
                }
                let direction: i64 = if trade.book_side == Side::Sell { 1 } else { -1 };
                let rest = visible.get(&trade.taker_order_id).copied();
                let g = if rest.is_some() { 0 } else { 1 };
                self.grp_net[g] += (direction * trade.quantity) as f64;
                self.grp_vol[g] += trade.quantity as f64;
                self.grp_price[g] += (trade.quantity * trade.price) as f64;
                if let Some(r) = rest {
                    if counted.insert(trade.taker_order_id) {
                        self.grp_net[0] += (direction * r.quantity) as f64;
                        self.grp_vol[0] += r.quantity as f64;
                        self.grp_price[0] += (r.quantity * r.price) as f64;
                        self.rest_net += direction as f64;
                        self.rest_cnt += 1.0;
                    }
                }
                if trade.maker_owner == Owner::User {
                    self.grp_net[2] += (direction * trade.quantity) as f64;
                    self.grp_vol[2] += trade.quantity as f64;
                    self.grp_price[2] += (trade.quantity * trade.price) as f64;
                }
            }
            return;
        }
        // (taker id, direction, lots, lots * price, our lots, our lots * price), in first-seen order
        let mut arrivals: Vec<(u64, i64, i64, f64, i64, f64)> = Vec::new();
        for trade in trades {
            if trade.taker_owner != Owner::Market {
                continue;
            }
            let index = match arrivals.iter().position(|a| a.0 == trade.taker_order_id) {
                Some(i) => i,
                None => {
                    arrivals.push((trade.taker_order_id, if trade.book_side == Side::Sell { 1 } else { -1 }, 0, 0.0, 0, 0.0));
                    arrivals.len() - 1
                }
            };
            let row = &mut arrivals[index];
            row.2 += trade.quantity;
            row.3 += (trade.quantity * trade.price) as f64;
            if trade.maker_owner == Owner::User {
                row.4 += trade.quantity;
                row.5 += (trade.quantity * trade.price) as f64;
            }
        }
        let cap = self.flowgrp_cap;
        for &(oid, direction, quantity, value, own, own_value) in &arrivals {
            let rest = visible.get(&oid);
            let g = if rest.is_some() { 0 } else { 1 };
            let (price, quantity) = match rest {
                Some(r) => (r.price as f64, quantity + r.quantity),
                None => (value / quantity.max(1) as f64, quantity),
            };
            let weight = cap.min(quantity);
            self.grp_net[g] += (direction * weight) as f64;
            self.grp_vol[g] += weight as f64;
            self.grp_price[g] += weight as f64 * price;
            if g == 0 {
                self.rest_net += direction as f64;
                self.rest_cnt += 1.0;
            }
            if own != 0 {
                let weight = cap.min(own);
                self.grp_net[2] += (direction * weight) as f64;
                self.grp_vol[2] += weight as f64;
                self.grp_price[2] += weight as f64 * own_value / own as f64;
            }
        }
    }

    /// R1-C11's new market orders within 3 ticks of the touch (counts and price sums, bids / asks, all and those of
    /// at most 50 lots) and the cancels within 3 ticks (vanished, not traded), decayed over QUOTEFEAT_US between
    /// valid books.
    fn quote_centres(&mut self, snapshot: &Snapshot, trades: &[Trade], now: i64, bid: i64, ask: i64) {
        let dt = match self.new_quote_time {
            None => 0,
            Some(t) => (now - t).max(0),
        };
        self.new_quote_time = Some(now);
        let d = ((-dt) as f64 / self.quotefeat_us as f64).exp();
        for i in 0..4 {
            self.new_counts[i] *= d;
            self.new_values[i] *= d;
        }
        self.cancel_net *= d;
        self.cancel_mass *= d;
        let mut current: Vec<BookOrder> = Vec::new();
        let mut current_ids: HashSet<u64> = HashSet::new();
        for side in [Side::Buy, Side::Sell] {
            for order in snapshot.side(side) {
                if order.owner == Owner::Market && current_ids.insert(order.order_id) {
                    current.push(order);
                }
            }
        }
        for order in &current {
            if self.known_ids.contains(&order.order_id) {
                continue;
            }
            let distance = if order.side == Side::Buy { bid - order.price } else { order.price - ask };
            if distance > 3 {
                continue;
            }
            let index = if order.side == Side::Buy { 0 } else { 1 };
            self.new_counts[index] += 1.0;
            self.new_values[index] += order.price as f64;
            if order.quantity <= 50 {
                self.new_counts[index + 2] += 1.0;
                self.new_values[index + 2] += order.price as f64;
            }
        }
        let traded: HashSet<u64> =
            trades.iter().filter(|t| t.maker_owner == Owner::Market).map(|t| t.maker_order_id).collect();
        for order in &self.known {
            if current_ids.contains(&order.order_id) || traded.contains(&order.order_id) {
                continue;
            }
            let distance = if order.side == Side::Buy { bid - order.price } else { order.price - ask };
            if distance.abs() > 3 {
                continue;
            }
            self.cancel_net += if order.side == Side::Buy { -1.0 } else { 1.0 };
            self.cancel_mass += 1.0;
        }
        self.known = current;
        self.known_ids = current_ids;
    }

    fn cancel(&mut self, index: usize, ctx: &mut Ctx) {
        let record = &mut self.orders[index];
        if record.accepted && !record.cancelling {
            record.cancelling = true;
            ctx.cancel_order(record.id);
        }
    }

    /// R2-Q: whether an order the quoting would cancel keeps its queue place instead (whole when at the front,
    /// else shrunk by a modify to KEEP_LOTS)
    fn preserve(&mut self, index: usize, sign: i64, price: Option<i64>, ctx: &mut Ctx) -> bool {
        if price.is_none() && !self.front_none {
            return false;
        }
        let r = &self.orders[index];
        if !r.accepted || r.cancelling || self.hedge_id == Some(r.id) {
            return false;
        }
        if self.ladder_lots > 0 && price.map_or(false, |p| p - sign == r.price) {
            // one tick behind the desired price: kept (shrunk to LADDER_LOTS) as the next level's place
            let (id, quantity, target) = (r.id, r.quantity, r.target);
            if quantity > self.ladder_lots && (target == 0 || target > self.ladder_lots) {
                ctx.modify_order(id, self.ladder_lots);
                self.orders[index].target = self.ladder_lots;
            }
            self.orders[index].kept = true;
            return true;
        }
        if r.price != self.qp_touch[side_index(sign)] {
            return false;
        }
        let Some(&ahead) = self.ahead.get(&r.id) else { return false };
        let toward = sign as f64 * self.qp_d;
        if self.front_lots >= 0 && ahead <= self.front_lots && toward >= -self.front_th {
            return true;
        }
        if self.keep_lots > 0 && toward >= -self.keep_th && (self.keep_ahead < 0 || ahead <= self.keep_ahead) {
            let (id, quantity, target) = (r.id, r.quantity, r.target);
            if quantity > self.keep_lots && (target == 0 || target > self.keep_lots) {
                ctx.modify_order(id, self.keep_lots);
                self.orders[index].target = self.keep_lots;
            }
            self.orders[index].kept = true;
            return true;
        }
        false
    }

    fn quote(&mut self, now: i64, sign: i64, price: Option<i64>, ctx: &mut Ctx) {
        let mut current = 0usize;
        for index in 0..self.orders.len() {
            if self.orders[index].sign != sign {
                continue;
            }
            current += 1;
            if (price.is_none() || Some(self.orders[index].price) != price) && now >= self.orders[index].exempt_until {
                if self.qp && self.preserve(index, sign, price, ctx) {
                    continue;
                }
                self.cancel(index, ctx);
            } else {
                self.orders[index].kept = false;
            }
        }
        if current >= self.max_orders {
            return;
        }
        if self.keep_noback && self.orders.iter().any(|r| r.sign == sign && r.kept && !r.cancelling) {
            return;
        }
        let Some(price) = price else { return };
        if price <= 0 || now - self.last_action[side_index(sign)] < self.requote_us {
            return;
        }
        if self.slice_lots > 0
            && now - self.last_action[side_index(sign)] < self.slice_us
            && self.orders.iter().any(|r| r.sign == sign && r.price == price && !r.cancelling)
        {
            return;
        }
        let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
        let effective: i64 = self
            .orders
            .iter()
            .filter(|r| r.sign == sign)
            .map(|r| {
                if r.cancelling {
                    (r.quantity as f64 * (1.0 - self.cancel_free)).ceil() as i64
                } else if r.kept && self.keep_free > 0.0 {
                    let q = if r.target > 0 { r.quantity.min(r.target) } else { r.quantity };
                    (q as f64 * (1.0 - self.keep_free)).ceil() as i64
                } else if r.target > 0 {
                    r.quantity.min(r.target)
                } else {
                    r.quantity
                }
            })
            .sum();
        let mut quantity = self
            .quote_size
            .min(if self.conf_exp > 0 { self.side_exp[side_index(sign)] } else { self.exposure } - sign * self.inventory - effective)
            .min(self.position_limit - sign * self.inventory - reserved);
        if self.slice_lots > 0 {
            quantity = quantity.min(self.slice_lots);
        }
        if quantity <= 0 {
            return;
        }
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, false);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: 0, target: 0, kept: false });
        self.last_action[side_index(sign)] = now;
    }

    /// v2's `_hedge`: an IOC for |inventory| - EXPOSURE, HEDGE_TICKS through the cached touch, one at a time.
    fn hedge(&mut self, now: i64, ctx: &mut Ctx) {
        // VOL_NOHEDGE: the hedge keeps EXPOSURE's level when the scaled exposure is below it
        let exposure = if self.vol_nohedge && self.vol_exp != 0.0 { self.exposure.max(self.exposure_base) } else { self.exposure };
        if !self.hedge || self.inventory.abs() <= exposure || self.hedge_id.is_some() {
            return;
        }
        let Some((bid, ask, time)) = self.cached else { return };
        if now - time > self.hedge_stale_us {
            return;
        }
        let sign = if self.inventory > 0 { -1 } else { 1 };
        let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
        let quantity = (self.inventory.abs() - exposure).min(0i64.max(self.position_limit - sign * self.inventory - reserved));
        if quantity <= 0 {
            return;
        }
        let price = if sign > 0 { ask + self.hedge_ticks } else { 1i64.max(bid - self.hedge_ticks) };
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, true);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: 0, target: 0, kept: false });
        self.hedge_id = Some(id);
    }

    /// take_maker's `take`: TAKE_LOTS (within the limit) at `price`, one a side per TAKE_MS, exempt that long.
    fn take(&mut self, now: i64, sign: i64, price: i64, ctx: &mut Ctx) {
        let key = side_index(sign);
        if now < self.take_block[key] {
            return;
        }
        let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
        let quantity = self.take_lots.min(self.position_limit - sign * self.inventory - reserved);
        if quantity <= 0 || price <= 0 {
            return;
        }
        let until = now + self.take_ms * 1000;
        self.take_block[key] = until;
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, false);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: until, target: 0, kept: false });
    }
}

impl Strategy for RidgeMaker {
    fn on_book(&mut self, snapshot: &Snapshot, trades: &[Trade], ctx: &mut Ctx) {
        let now = snapshot.timestamp_us;
        let elapsed = match self.last_us {
            None => 0,
            Some(t) => (now - t).max(0),
        };
        self.last_us = Some(now);
        if self.flowgrp > 0 {
            self.flow_groups(snapshot, trades, elapsed);
        }
        if self.lean_k != 0.0 && self.lean_src == 2 {
            // the market orders of this event, by taker order: the last of at least BIG_LOTS sets the lean's side
            let mut lots: Vec<(u64, f64, i64)> = Vec::new();
            for trade in trades {
                if trade.taker_owner != Owner::Market {
                    continue;
                }
                let sign = if trade.book_side == Side::Sell { 1.0 } else { -1.0 };
                match lots.iter_mut().find(|(id, _, _)| *id == trade.taker_order_id) {
                    Some(entry) => entry.2 += trade.quantity,
                    None => lots.push((trade.taker_order_id, sign, trade.quantity)),
                }
            }
            for (_, sign, q) in lots {
                if q >= self.big_lots {
                    self.big_last = Some((now, sign));
                }
            }
        }
        let decay = ((-elapsed) as f64 / self.flow_us as f64).exp();
        self.net *= decay;
        self.volume *= decay;
        for trade in trades {
            if trade.taker_owner == Owner::Market {
                self.net += if trade.book_side == Side::Sell { trade.quantity as f64 } else { -(trade.quantity as f64) };
                self.volume += trade.quantity as f64;
            }
        }
        if self.flow2 > 0 {
            let df = ((-elapsed) as f64 / 100_000.0).exp();
            let ds = ((-elapsed) as f64 / 2_000_000.0).exp();
            self.flow_fast.0 *= df;
            self.flow_fast.1 *= df;
            self.flow_slow.0 *= ds;
            self.flow_slow.1 *= ds;
            for trade in trades {
                if trade.taker_owner == Owner::Market {
                    let q = trade.quantity as f64;
                    let signed = if trade.book_side == Side::Sell { q } else { -q };
                    self.flow_fast.0 += signed;
                    self.flow_fast.1 += q;
                    self.flow_slow.0 += signed;
                    self.flow_slow.1 += q;
                }
            }
        }
        if self.last_agg > 0 {
            let mut last: Option<(u64, f64, f64)> = None;
            for trade in trades {
                if trade.taker_owner != Owner::Market {
                    continue;
                }
                let sign = if trade.book_side == Side::Sell { 1.0 } else { -1.0 };
                match &mut last {
                    Some((id, _, q)) if *id == trade.taker_order_id => *q += trade.quantity as f64,
                    slot => *slot = Some((trade.taker_order_id, sign, trade.quantity as f64)),
                }
            }
            if let Some((_, sign, q)) = last {
                self.last_agg_value = sign * (1.0 + q).ln();
            }
        }
        let touch_bid = snapshot.market_touch(Side::Buy);
        let touch_ask = snapshot.market_touch(Side::Sell);
        let (bid, bq, ask, aq) = match (touch_bid, touch_ask) {
            (Some((b, bq)), Some((a, aq))) if b < a => (b, bq, a, aq),
            _ => {
                self.previous_touch = None;
                self.desired_time = None;
                let since = *self.invalid_since.get_or_insert(now);
                if now - since >= 50_000 {
                    for index in 0..self.orders.len() {
                        self.cancel(index, ctx);
                    }
                }
                return;
            }
        };
        self.invalid_since = None;
        if self.quotefeat > 0 {
            self.quote_centres(snapshot, trades, now, bid, ask);
        }
        let mid = (bid + ask) as f64 * 0.5;
        let spread = ask - bid;
        let flow = self.net / (1.0 + self.volume);
        let imbalance = (bq - aq) as f64 / (bq + aq) as f64;
        let (mut bn, mut an, mut bd_n, mut ad_n) = (0i64, 0i64, 0i64, 0i64);
        let (mut br, mut ar, mut bd_r, mut ad_r) = (0i64, 0i64, 0i64, 0i64);
        let (mut bd_value, mut ad_value) = (0i64, 0i64);
        for side in [Side::Buy, Side::Sell] {
            for order in snapshot.side(side) {
                if order.owner != Owner::Market {
                    continue;
                }
                let distance = if order.side == Side::Buy { bid - order.price } else { order.price - ask };
                if distance > 2 {
                    break;
                }
                let weight = order.quantity.min(20);
                if order.side == Side::Buy {
                    bd_n += 1;
                    bd_r += weight;
                    bd_value += weight * order.price;
                    if distance == 0 {
                        bn += 1;
                        br += weight;
                    }
                } else {
                    ad_n += 1;
                    ad_r += weight;
                    ad_value += weight * order.price;
                    if distance == 0 {
                        an += 1;
                        ar += weight;
                    }
                }
            }
        }
        let ratio = |a: i64, b: i64| (a - b) as f64 / (a + b).max(1) as f64;
        let count_imbalance = ratio(bn, an);
        let robust_imbalance = ratio(br, ar);
        let depth_count = ratio(bd_n, ad_n);
        let depth_imbalance = ratio(bd_r, ad_r);
        let depth_mid =
            (bd_value as f64 / bd_r.max(1) as f64 + ad_value as f64 / ad_r.max(1) as f64) * 0.5 - mid;

        let mut place_feat = [0.0f64; 2];
        if self.place > 0 {
            let (ref_bid, ref_ask) = match self.previous_touch {
                Some((ob, oa, _, _)) => (ob, oa),
                None => (bid, ask),
            };
            let mut add = [0.0f64; 4];
            self.seen_next.clear();
            for side in [Side::Buy, Side::Sell] {
                for order in snapshot.side(side) {
                    if order.owner != Owner::Market {
                        continue;
                    }
                    self.seen_next.insert(order.order_id);
                    if self.seen.contains(&order.order_id) {
                        continue;
                    }
                    if order.side == Side::Buy {
                        add[1] += 1.0;
                        if order.price >= ref_bid {
                            add[0] += 1.0;
                        }
                    } else {
                        add[3] += 1.0;
                        if order.price <= ref_ask {
                            add[2] += 1.0;
                        }
                    }
                }
            }
            std::mem::swap(&mut self.seen, &mut self.seen_next);
            for (k, tau) in [self.place_us1, self.place_us2].into_iter().enumerate() {
                let d = ((-elapsed) as f64 / tau as f64).exp();
                for q in 0..4 {
                    self.place_acc[k][q] = self.place_acc[k][q] * d + add[q];
                }
                let acc = self.place_acc[k];
                let sb = if acc[1] > 1e-9 { acc[0] / acc[1] } else { 0.5 };
                let sa = if acc[3] > 1e-9 { acc[2] / acc[3] } else { 0.5 };
                place_feat[k] = sb - sa;
            }
        }
        let mut depth5_feat = 0.0f64;
        if self.depth5 > 0 {
            let mut tot = [0i64; 2];
            for (k, side) in [Side::Buy, Side::Sell].into_iter().enumerate() {
                let mut levels = 0;
                let mut last_price = i64::MIN;
                for order in snapshot.side(side) {
                    if order.price != last_price {
                        levels += 1;
                        last_price = order.price;
                        if levels > 5 {
                            break;
                        }
                    }
                    if order.owner == Owner::Market {
                        tot[k] += order.quantity;
                    }
                }
            }
            depth5_feat = ratio(tot[0], tot[1]);
        }

        if self.vol_exp != 0.0 {
            // VOL_EXP: EXPOSURE scaled by (base rate / fast rate)^VOL_EXP of |mid change| ticks per second, the
            // base the VOL_BASE_US rate, or VOL_REF ticks a second when that is set
            if let Some((t, m)) = self.vol_last {
                let dt = (now - t).max(0) as f64;
                let mv = (mid - m).abs();
                for k in 0..2 {
                    let d = (-dt / self.vol_us[k] as f64).exp();
                    self.vol_acc[k][0] = self.vol_acc[k][0] * d + mv;
                    self.vol_acc[k][1] = self.vol_acc[k][1] * d + dt;
                }
            }
            self.vol_last = Some((now, mid));
            let rate = |a: [f64; 2]| if a[1] > 0.0 { a[0] / a[1] } else { 0.0 };
            let fast = rate(self.vol_acc[0]);
            let base = if self.vol_ref > 0.0 { self.vol_ref * 1e-6 } else { rate(self.vol_acc[1]) };
            self.exposure = if fast > 0.0 && base > 0.0 {
                ((self.exposure_base as f64 * (base / fast).powf(self.vol_exp)).round() as i64).clamp(self.vol_min, self.vol_max)
            } else {
                self.exposure_base
            };
        }
        if self.trend > 0 {
            match self.trend_time {
                Some(t) => {
                    let dt = (now - t).max(0) as f64;
                    for k in 0..2 {
                        self.trend_e[k] += (1.0 - (-dt / self.trend_us[k] as f64).exp()) * (mid - self.trend_e[k]);
                    }
                }
                None => self.trend_e = [mid; 2],
            }
            self.trend_time = Some(now);
        }
        let spread_f = spread as f64;
        let mut skew = self.skew_k * self.inventory as f64 / self.exposure as f64 * spread_f.max(1.0);
        if self.skew2_k != 0.0 {
            let excess = (self.inventory.abs() - self.skew2_x).max(0) as f64 / (self.exposure - self.skew2_x).max(1) as f64;
            skew += self.skew2_k * self.inventory.signum() as f64 * excess * spread_f.max(1.0);
        }
        match self.model_time {
            Some(t) if now - t <= 10_000_000 => {
                let dt = (now - t).max(0) as f64;
                self.fast_mid += (1.0 - (-dt / self.fast_us as f64).exp()) * (mid - self.fast_mid);
                self.slow_mid += (1.0 - (-dt / self.slow_us as f64).exp()) * (mid - self.slow_mid);
            }
            _ => {
                self.fast_mid = mid;
                self.slow_mid = mid;
                self.m1.observations.clear();
                self.m2.observations.clear();
                for m in self.ex.iter_mut() {
                    m.observations.clear();
                }
            }
        }
        self.model_time = Some(now);
        let dt = match self.ofi_time {
            None => 0,
            Some(t) => (now - t).max(0),
        };
        self.ofi_time = Some(now);
        self.ofi *= ((-dt) as f64 / self.ofi_us as f64).exp();
        if let Some((old_bid, old_ask, old_bq, old_aq)) = self.previous_touch {
            let mut change = (if bid >= old_bid { bq } else { 0 }) - (if bid <= old_bid { old_bq } else { 0 });
            change -= if ask <= old_ask { aq } else { 0 };
            change += if ask >= old_ask { old_aq } else { 0 };
            self.ofi += change as f64 / 1i64.max(bq + aq).max(old_bq + old_aq) as f64;
        }
        self.previous_touch = Some((bid, ask, bq, aq));
        let ofi = clamp(self.ofi, -3.0, 3.0);
        let base: [f64; N] = [
            flow,
            clamp(self.fast_mid - self.slow_mid, -5.0, 5.0),
            imbalance,
            ofi,
            spread_f * imbalance,
            flow * flow.abs(),
            imbalance * imbalance.abs(),
            ofi * ofi.abs(),
            count_imbalance,
            robust_imbalance,
            depth_count,
            depth_imbalance,
            depth_mid,
            count_imbalance * count_imbalance.abs(),
            robust_imbalance * robust_imbalance.abs(),
        ];
        let mut features = [0.0f64; NM];
        features[..N].copy_from_slice(&base);
        let mut k = N;
        if self.place > 0 {
            features[k] = place_feat[0];
            features[k + 1] = place_feat[1];
            k += 2;
        }
        if self.depth5 > 0 {
            features[k] = depth5_feat;
            k += 1;
        }
        if self.flow2 > 0 {
            features[k] = self.flow_fast.0 / (1.0 + self.flow_fast.1);
            features[k + 1] = self.flow_slow.0 / (1.0 + self.flow_slow.1);
            k += 2;
        }
        if self.last_agg > 0 {
            features[k] = self.last_agg_value;
            k += 1;
        }
        if self.quotefeat > 0 {
            let (c, v) = (self.new_counts, self.new_values);
            features[k] = (c[0] - c[1]) / (1.0 + c[0] + c[1]);
            features[k + 1] =
                clamp(((v[0] - mid * c[0]) / (1.0 + c[0]) + (v[1] - mid * c[1]) / (1.0 + c[1])) * 0.5, -5.0, 5.0);
            features[k + 2] =
                clamp(((v[2] - mid * c[2]) / (1.0 + c[2]) + (v[3] - mid * c[3]) / (1.0 + c[3])) * 0.5, -5.0, 5.0);
            features[k + 3] = self.cancel_net / (1.0 + self.cancel_mass);
            features[k + 4] = clamp((v[0] + v[1] - mid * (c[0] + c[1])) / (1.0 + c[0] + c[1]), -5.0, 5.0);
            features[k + 5] = (c[2] - c[3]) / (1.0 + c[2] + c[3]);
            k += 6;
        }
        if self.flowgrp > 0 {
            let (g, v, p) = (self.grp_net, self.grp_vol, self.grp_price);
            features[k] = g[0] / (1.0 + v[0]);
            features[k + 1] = g[1] / (1.0 + v[1]);
            features[k + 2] = g[2] / (1.0 + v[2]);
            features[k + 3] = v[0] / (1.0 + v[0] + v[1]);
            for i in 0..3 {
                features[k + 4 + i] = clamp((p[i] - mid * v[i]) / (1.0 + v[i]), -5.0, 5.0);
            }
            features[k + 7] = self.rest_net / (1.0 + self.rest_cnt);
        }
        if self.bucket > 0 {
            let edges = [-0.6, -0.25, 0.0, 0.25, 0.6];
            let b = edges.iter().filter(|&&e| imbalance > e).count();
            let s1 = spread == 1;
            // BUCKET is a mask: 1 the imbalance buckets by spread, 2 our inventory's sign, 4 the time since the mid
            // moved, 8 the one-tick imbalance; a group left out stays 0 (its weight 0 under the ridge)
            let mask = self.bucket;
            for i in 0..6 {
                if mask & 1 != 0 {
                    features[k + i] = if s1 && b == i { 1.0 } else { 0.0 };
                    features[k + 6 + i] = if !s1 && b == i { 1.0 } else { 0.0 };
                }
            }
            if mask & 2 != 0 {
                let inv_sign = if self.inventory > 0 { 1.0 } else if self.inventory < 0 { -1.0 } else { 0.0 };
                features[k + 12] = inv_sign;
                features[k + 13] = inv_sign * imbalance;
            }
            if mask & 4 != 0 {
                let since =
                    if self.last_mid.is_some() && self.last_mid != Some(mid) { 0 } else { (now - self.last_mid_change_us).max(0) };
                let tsl = (1.0 + since as f64 / 1000.0).ln() / 8.0;
                features[k + 14] = tsl;
                features[k + 15] = tsl * imbalance;
            }
            if mask & 8 != 0 {
                features[k + 16] = if s1 { imbalance } else { 0.0 };
            }
        }
        if self.trend > 0 {
            let k = self.n_base - 2;
            features[k] = clamp(mid - self.trend_e[0], -20.0, 20.0);
            features[k + 1] = clamp(mid - self.trend_e[1], -20.0, 20.0);
        }
        let n = self.n_base;
        if self.std_on > 0 {
            let d = ((-elapsed) as f64 / self.std_us as f64).exp();
            self.std_mass = self.std_mass * d + 1.0;
            for i in 0..n {
                self.std_m2[i] = self.std_m2[i] * d + features[i] * features[i];
                features[i] /= (self.std_m2[i] / self.std_mass).sqrt() + 1e-9;
            }
        }
        if self.last_mid != Some(mid) {
            if self.last_mid.is_some() {
                self.mid_changes += 1;
            }
            self.last_mid = Some(mid);
            self.last_mid_change_us = now;
        }
        if self.mh > 0 {
            self.learn(4, now, mid);
            self.learn(5, now, mid);
            for (j, k) in [(2usize, 0usize), (3, 1)] {
                let m = &self.ex[j];
                features[n + k] = if m.labels >= self.min_labels {
                    clamp(py_sum(m.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0)
                } else {
                    0.0
                };
            }
        }
        let n = self.n;
        self.learn(0, now, mid);
        let m2_on = self.blend_w > 0.0 || (self.lean_k != 0.0 && self.lean_src == 0) || self.ft_src == 1;
        if m2_on {
            self.learn(1, now, mid);
        }
        if self.side2 > 0 {
            self.learn(2, now, bid as f64);
            self.learn(3, now, ask as f64);
        }
        if now - self.last_observation_us >= self.observation_interval_us {
            if self.label_mode == 0 && self.m1.observations.len() >= self.obs_cap {
                self.m1.observations.pop_front();
            }
            self.m1.observations.push_back((now, mid, features, self.mid_changes));
            if m2_on {
                if self.m2.observations.len() >= self.obs_cap {
                    self.m2.observations.pop_front();
                }
                self.m2.observations.push_back((now, mid, features, self.mid_changes));
            }
            if self.side2 > 0 {
                for (j, v) in [(0usize, bid as f64), (1, ask as f64)] {
                    if self.ex[j].observations.len() >= self.obs_cap {
                        self.ex[j].observations.pop_front();
                    }
                    self.ex[j].observations.push_back((now, v, features, self.mid_changes));
                }
            }
            if self.mh > 0 {
                for j in [2usize, 3] {
                    if self.ex[j].observations.len() >= self.obs_cap {
                        self.ex[j].observations.pop_front();
                    }
                    self.ex[j].observations.push_back((now, mid, features, self.mid_changes));
                }
            }
            self.last_observation_us = now;
        }
        if self.dump_us > 0 && self.dump_snap.is_none() && now >= self.dump_us {
            self.dump_snap = Some(self.stats_text());
        }
        let mut prediction = 0.25 * spread_f * imbalance;
        if self.m1.labels >= self.min_labels {
            let raw = py_sum(self.m1.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x));
            prediction = clamp(if self.pred_scale != 1.0 { raw * self.pred_scale } else { raw }, -2.0, 2.0);
            if self.blend_w > 0.0 && self.m2.labels >= self.min_labels {
                let p2 =
                    clamp(py_sum(self.m2.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0);
                prediction = (1.0 - self.blend_w) * prediction + self.blend_w * p2;
            }
        }
        // the second model's own forecast (LEAN_SRC 0, FT_SRC 1)
        let p2_only = if m2_on && self.m2.labels >= self.min_labels {
            clamp(py_sum(self.m2.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0)
        } else {
            0.0
        };
        // LEAN_K: the skew aims at an inventory target that follows the slow forecast instead of at 0
        let skew = if self.lean_k != 0.0 {
            let src = match self.lean_src {
                0 => p2_only,
                2 => match self.big_last {
                    Some((t, sign)) => sign * (-((now - t).max(0) as f64) / self.big_us as f64).exp(),
                    None => 0.0,
                },
                _ => prediction,
            };
            let e = self.exposure as f64;
            let target = clamp(self.lean_k * src, -e, e);
            self.skew_k * (self.inventory as f64 - target) / e * spread_f.max(1.0)
        } else {
            skew
        };
        let mut fair = mid + self.pred_mix * prediction + 0.0 * 0.25 * spread_f * imbalance - skew;
        let raw = fair;
        if self.fill_learn && self.fill_q > 0 {
            for (key, side, touch) in [(0usize, Side::Buy, bid), (1usize, Side::Sell, ask)] {
                let sign = if key == 0 { 1 } else { -1 };
                let mut ahead = 0i64;
                let mut found = None;
                for order in snapshot.side(side) {
                    if order.price != touch {
                        if (key == 0 && order.price < touch) || (key == 1 && order.price > touch) {
                            break;
                        }
                        continue;
                    }
                    if order.owner == Owner::Market {
                        ahead += order.quantity;
                    } else if self.orders.iter().any(|r| r.id == order.order_id && r.sign == sign) {
                        found = Some(ahead);
                        break;
                    }
                }
                self.front_ahead[key] = found;
            }
        }
        if self.fill_learn {
            self.fill_mature(now, mid);
            self.last_d = Some(raw - mid);
        }
        if self.stats.is_some() {
            self.stat_inv.0 += self.inventory.abs() as f64;
            self.stat_inv.1 += 1.0;
        }
        if self.qp || self.stats.is_some() {
            self.qp_d = raw - mid;
            self.qp_touch = [bid, ask];
            self.ahead.clear();
            for (side, touch) in [(Side::Buy, bid), (Side::Sell, ask)] {
                let mut ahead = 0i64;
                for order in snapshot.side(side) {
                    if order.price != touch {
                        if (side == Side::Buy && order.price < touch) || (side == Side::Sell && order.price > touch) {
                            break;
                        }
                        continue;
                    }
                    if order.owner == Owner::Market {
                        ahead += order.quantity;
                    } else {
                        self.ahead.insert(order.order_id, ahead);
                    }
                }
            }
        }
        if (fair - mid).abs() <= self.dead_zone {
            fair = mid;
        }
        let mut buy = Some(bid.min((fair - 0.5).floor() as i64));
        let mut sell = Some(ask.max((fair + 0.5).ceil() as i64));
        if self.side2 == 2 && self.ex[0].labels >= self.min_labels {
            // the probability that the touch we quote is cleared within the horizon: past CLEAR_TH, a tick back
            for j in 0..2usize {
                let m = &self.ex[j];
                let p = py_sum(m.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x));
                if p > self.clear_th {
                    if j == 0 {
                        buy = buy.map(|b| b.min(bid - 1));
                    } else {
                        sell = sell.map(|a| a.max(ask + 1));
                    }
                }
            }
        }
        if self.side2 == 1 && self.ex[0].labels >= self.min_labels {
            let w = self.side_w;
            for j in 0..2usize {
                let m = &self.ex[j];
                let p = clamp(py_sum(m.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0);
                let mut f = mid + self.pred_mix * ((1.0 - w) * prediction + w * p) - skew;
                if (f - mid).abs() <= self.dead_zone {
                    f = mid;
                }
                if j == 0 {
                    buy = Some(bid.min((f - 0.5).floor() as i64));
                } else {
                    sell = Some(ask.max((f + 0.5).ceil() as i64));
                }
            }
        }
        if self.fill_learn && spread == 1 {
            let d = raw - mid;
            if let Some(m) = self.fill_mean(now, d, self.queue_class(0)) {
                let f = if m >= self.fill_min { mid } else { raw };
                buy = Some(bid.min((f - 0.5).floor() as i64));
            }
            if let Some(m) = self.fill_mean(now, -d, self.queue_class(1)) {
                let f = if m >= self.fill_min { mid } else { raw };
                sell = Some(ask.max((f + 0.5).ceil() as i64));
            }
        }
        if spread >= 2 {
            if prediction - skew > self.inside_th {
                buy = Some((ask - 1).min(bid + 1));
            } else if prediction - skew < -self.inside_th {
                sell = Some((bid + 1).max(ask - 1));
            }
        }
        if self.reduce_in > 0 && spread >= 2 {
            let at = if self.reduce_at > 0 { self.reduce_at } else { self.exposure };
            if self.inventory >= at {
                sell = Some(sell.map_or(ask - 1, |s| s.min(ask - 1)).max(bid + 1));
            } else if self.inventory <= -at {
                buy = Some(buy.map_or(bid + 1, |b| b.max(bid + 1)).min(ask - 1));
            }
        }
        let (mut cap_buy, mut cap_sell) = (self.exposure, self.exposure);
        if self.conf_exp > 0 {
            if prediction < self.conf_th {
                cap_buy = self.conf_exp;
            }
            if prediction > -self.conf_th {
                cap_sell = self.conf_exp;
            }
            self.side_exp = [cap_buy, cap_sell];
        }
        if flow < -self.flow_cut || self.inventory >= cap_buy {
            buy = None;
        }
        if flow > self.flow_cut || self.inventory <= -cap_sell {
            sell = None;
        }
        self.dbg[5] += 1.0;
        if let Some(t) = self.dbg_inv_t {
            let dt = (now - t).max(0) as f64;
            self.dbg_inv[0] += dt * self.inventory.abs() as f64;
            self.dbg_inv[1] += dt;
        }
        self.dbg_inv_t = Some(now);
        while now as f64 >= self.dbg_steps[4] {
            let pnl = self.dbg_cash + self.inventory as f64 * mid;
            let step = pnl - self.dbg_steps[3];
            self.dbg_steps[0] += 1.0;
            self.dbg_steps[1] += step;
            self.dbg_steps[2] += step * step;
            self.dbg_steps[3] = pnl;
            self.dbg_steps[4] += 25_000_000.0;
        }
        if self.inventory.abs() >= self.exposure {
            self.dbg[4] += 1.0;
        }
        if self.unwind_lots > 0 && self.unwind_id.is_none() && now >= self.unwind_block {
            let at = if self.unwind_at > 0 { self.unwind_at } else { self.exposure };
            if self.inventory.abs() >= at && -(self.inventory.signum() as f64) * prediction > self.unwind_th * spread_f {
                let sign = -self.inventory.signum();
                let mut quantity = self.unwind_lots.min(self.inventory.abs());
                if self.unwind_safe == 3 {
                    // the newest of our resting orders on that side cancelled until the rest and the IOC fit EXPOSURE
                    let cf = self.cancel_free;
                    let eff = move |r: &Record| if r.cancelling { (r.quantity as f64 * (1.0 - cf)).ceil() as i64 } else { r.quantity };
                    let mut effective: i64 = self.orders.iter().filter(|r| r.sign == sign).map(eff).sum();
                    let room = self.exposure + self.inventory.abs();
                    for index in (0..self.orders.len()).rev() {
                        if effective + quantity <= room {
                            break;
                        }
                        let r = &self.orders[index];
                        if r.sign != sign || r.cancelling || !r.accepted || Some(r.id) == self.hedge_id {
                            continue;
                        }
                        let before = eff(r);
                        self.cancel(index, ctx);
                        effective += eff(&self.orders[index]) - before;
                    }
                    quantity = quantity.min(room - effective);
                } else if self.unwind_safe == 2 {
                    // our resting orders on that side cancelled first, the IOC then for what the cancels leave room for
                    for index in 0..self.orders.len() {
                        if self.orders[index].sign == sign && Some(self.orders[index].id) != self.hedge_id {
                            self.cancel(index, ctx);
                        }
                    }
                    let effective: i64 = self
                        .orders
                        .iter()
                        .filter(|r| r.sign == sign)
                        .map(|r| if r.cancelling { (r.quantity as f64 * (1.0 - self.cancel_free)).ceil() as i64 } else { r.quantity })
                        .sum();
                    quantity = quantity.min(self.exposure + self.inventory.abs() - effective);
                } else if self.unwind_safe > 0 {
                    // every lot of ours that can still fill on that side, the IOC included, stays within EXPOSURE
                    let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
                    quantity = quantity.min(self.exposure + self.inventory.abs() - reserved);
                }
                let price = if sign > 0 { ask + self.unwind_thru } else { 1i64.max(bid - self.unwind_thru) };
                if quantity > 0 {
                    let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, true);
                    self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: 0, target: 0, kept: false });
                    self.unwind_id = Some(id);
                }
                self.unwind_block = now + self.unwind_us;
            }
        }
        if self.deplete_lots > 0 || self.take_lots > 0 {
            for (key, price, lots) in [(0, bid, bq), (1, ask, aq)] {
                match &mut self.peak[key] {
                    Some((p, most)) if *p == price => *most = (*most).max(lots),
                    slot => *slot = Some((price, lots)),
                }
            }
            let peak = |key: usize| self.peak[key].map_or(0, |(_, most)| most) as f64;
            let mut bid_dying = bq < self.deplete_lots;
            let mut ask_dying = aq < self.deplete_lots;
            if self.depl_frac > 0.0 {
                bid_dying = bid_dying && (bq as f64) < self.depl_frac * peak(0);
                ask_dying = ask_dying && (aq as f64) < self.depl_frac * peak(1);
            }
            if self.take_lots > 0 && spread == 1 {
                let (mut ask_take, mut bid_take) = (ask_dying, bid_dying);
                if self.take_deplete > 0 && self.depl_frac > 0.0 {
                    ask_take = aq < self.take_deplete && (aq as f64) < self.depl_frac * peak(1);
                    bid_take = bq < self.take_deplete && (bq as f64) < self.depl_frac * peak(0);
                }
                if ask_take && aq <= self.take_max && buy.is_some() && bq >= self.take_own {
                    self.take(now, 1, ask, ctx);
                }
                if bid_take && bq <= self.take_max && sell.is_some() && aq >= self.take_own {
                    self.take(now, -1, bid, ctx);
                }
            }
            if bid_dying && buy == Some(bid) {
                buy = Some(bid - 1);
            }
            if ask_dying && sell == Some(ask) {
                sell = Some(ask + 1);
            }
        }
        if self.m1.labels >= self.min_labels {
            if let Some(w) = self.pred_log.as_mut() {
                use std::io::Write;
                let _ = writeln!(w, "{},{},{},{},{},{}", now, mid, prediction, skew, spread, self.inventory);
            }
        }
        if self.ft_sz > 0 && self.m1.labels >= self.min_labels && now - self.ft_last >= self.ft_gap_ms * 1000 {
            let source = if self.ft_src == 1 { p2_only } else { prediction };
            let signal = if self.ft_net > 0 { source - skew } else { source };
            let need = self.ft_edge + 0.5 * spread_f;
            let sign = if signal > need {
                1
            } else if signal < -need {
                -1
            } else {
                0
            };
            if sign != 0 {
                let pos = sign * self.inventory;
                let room = match self.ft_mode {
                    1 => {
                        if pos < 0 && -pos >= self.ft_inv {
                            -pos
                        } else {
                            0
                        }
                    }
                    2 => {
                        if pos >= 0 {
                            self.exposure - pos
                        } else {
                            0
                        }
                    }
                    _ => self.exposure - pos,
                };
                let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
                let quantity = self.ft_sz.min(room).min(self.position_limit - pos - reserved);
                if quantity > 0 {
                    let price = if sign > 0 { ask + self.ft_thru } else { 1i64.max(bid - self.ft_thru) };
                    let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, true);
                    self.orders.push(Record {
                        id,
                        sign,
                        price,
                        quantity,
                        accepted: false,
                        cancelling: false,
                        exempt_until: now + 1_000_000,
                        target: 0,
                        kept: false,
                    });
                    self.ft_last = now;
                }
            }
        }
        self.cached = Some((bid, ask, now));
        self.hedge(now, ctx);
        self.desired_buy = buy;
        self.desired_sell = sell;
        self.desired_time = Some(now);
        self.quote(now, 1, buy, ctx);
        self.quote(now, -1, sell, ctx);
    }

    fn on_private(&mut self, event: &PrivateEvent, ctx: &mut Ctx) {
        let Some(index) = self.orders.iter().position(|r| r.id == event.order_id) else { return };
        match event.status {
            Status::Accepted => self.orders[index].accepted = true,
            Status::Filled | Status::PartiallyFilled => {
                let record = &self.orders[index];
                if self.fill_learn && self.hedge_id != Some(event.order_id) {
                    if let (Some((bid, ask, _)), Some(d)) = (self.cached, self.last_d) {
                        let touch = if record.sign > 0 { bid } else { ask };
                        if ask - bid == 1 && record.price == touch {
                            self.pending.push_back((
                                event.timestamp_us,
                                record.sign,
                                record.price,
                                event.filled_quantity,
                                record.sign as f64 * d,
                                self.queue_class(side_index(record.sign)),
                            ));
                        }
                    }
                }
                if self.stats.is_some() && self.hedge_id != Some(event.order_id) {
                    let b = match self.ahead.get(&event.order_id) {
                        Some(&0) => 0,
                        Some(&a) if a <= 100 => 1,
                        Some(&a) if a <= 300 => 2,
                        Some(_) => 3,
                        None => 4,
                    };
                    self.stat_lots[b] += event.filled_quantity;
                }
                let record = &mut self.orders[index];
                if let (Some((bid, ask, _)), Some(price)) = (self.cached, event.fill_price) {
                    let edge = record.sign as f64 * ((bid + ask) as f64 * 0.5 - price as f64) * event.filled_quantity as f64;
                    let ioc = self.hedge_id == Some(event.order_id) || self.unwind_id == Some(event.order_id);
                    let k = if ioc { 2 } else { 0 };
                    self.dbg[k] += event.filled_quantity as f64;
                    self.dbg[k + 1] += edge;
                    self.dbg_cash -= (record.sign * price * event.filled_quantity) as f64;
                }
                self.inventory += record.sign * event.filled_quantity;
                record.quantity = event.remaining_quantity;
                if event.status == Status::Filled {
                    self.orders.remove(index);
                }
            }
            Status::Canceled => {
                self.orders.remove(index);
            }
            Status::Rejected => {
                if !self.orders[index].accepted {
                    self.orders.remove(index);
                } else {
                    self.orders[index].cancelling = false;
                    self.orders[index].target = 0;
                }
            }
            Status::Modified => {
                self.orders[index].quantity = event.remaining_quantity;
                self.orders[index].target = 0;
            }
        }
        let was_unwind = self.unwind_id == Some(event.order_id);
        if was_unwind && matches!(event.status, Status::Filled | Status::Canceled | Status::Rejected) {
            self.unwind_id = None;
        }
        let was_hedge = self.hedge_id == Some(event.order_id) || was_unwind;
        if self.hedge_id == Some(event.order_id) && matches!(event.status, Status::Filled | Status::Canceled | Status::Rejected) {
            self.hedge_id = None;
        }
        if let Some(t) = self.desired_time {
            let d = event.timestamp_us - t;
            if !was_hedge && 0 <= d && d <= self.replenish_us && event.status == Status::Canceled {
                let (buy, sell) = (self.desired_buy, self.desired_sell);
                self.quote(event.timestamp_us, 1, buy, ctx);
                self.quote(event.timestamp_us, -1, sell, ctx);
            }
        }
        if was_hedge || matches!(event.status, Status::Filled | Status::PartiallyFilled) {
            self.hedge(event.timestamp_us, ctx);
        }
    }
}

