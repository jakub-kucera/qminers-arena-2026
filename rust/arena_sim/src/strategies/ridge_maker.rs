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
//! skew, spread and inventory, for measuring the forecast; with `RIDGE_PRED_EXTRA` set too, the latent filter's gap
//! and QS_RATE's speed as two more columns (experiments/day/quote_audit.py).
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
//!   R2-V2 (r2_V2_vol_exposure_dz18.py; 167288.05 / 21,637 and 699370.05 / 36,719, the same bytes): R2-V1's sets with
//!       --set DEAD_ZONE=0.18 --set TREND=0
//! Small orders (R2-S, 7 Nov; round 1's winner made 426k fills), off by default (every result above unchanged):
//! `BURST` (1), the most new orders a quote call sends (with SLICE_LOTS, the room posted as slices at once rather
//! than one a book event); `L2_LOTS` (0: off) / `L2_ORDERS` (0) / `L2_FREE` (0): up to L2_ORDERS orders of L2_LOTS
//! one tick behind the desired price, an old touch order a tick back kept there shrunk to L2_LOTS (the rest
//! cancelled), not counted in MAX_ORDERS, a new one at most one a quote call and one per SLICE_US; their lots count
//! toward EXPOSURE unless L2_FREE is 1 (then the position can pass 100: the breach penalty).
//! Round 2's takers (R2-T2 / L1 / L3 / L8 / L9, 8 Nov), off by default (every result above unchanged):
//! `FT_MAXSPREAD` (0: off), the forecast take only while the spread is at most that many ticks (T1's
//! TAKE_MAXSPREAD); `FT_ROOM_LIVE` (0; 1: the take's room is EXPOSURE minus the position its way minus every live
//! same-side order's lots, T2's TAKE_ROOM_LIVE); `LIQ` (0; 1 adds four features after the ones above, L1's: the
//! touch's young-order imbalance (market orders at the touch first seen at most 100 ms ago, bids minus asks over 1
//! plus both), it, the flow and the count imbalance each times the dispersion, min(3, the market orders more than 4
//! ticks from their touch / 10), recomputed unless within 5 ms of the last at the same mid); `IMPACT_US` (0: off;
//! else three more after those, L9's: the market takers' signed and gross lots decayed over IMPACT_US at every book,
//! clip(signed / 500, +-3), signed / (1 + gross) * min(9, gross / 500)^0.5, and clip(signed / (1 + the far touch's
//! lots), +-3)); `HUBER` (0.0: off; else the first model's labels weighted min(1, HUBER / |label - the forecast
//! stored at the observation|), L9's Huber-robust fit); `QS_RATE` (0.0: off) with `QS_US` (5000000): the quotes
//! are QUOTE_SIZE only while the |mid change| rate decayed over QS_US, in ticks a second, is below QS_RATE, else 0
//! (L8). Each candidate on round2_public.csv, pnl.csv and result.json the same bytes as its Python run (8 Nov):
//!   T2  (r2_T2_take_only_safe.py, 194391.00): --set POSITION_LIMIT=1000 --set EXPOSURE=100 --set HEDGE=1
//!       --set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000 --set DEAD_ZONE=0.18 --set QUOTEFEAT=1
//!       --set FLOWGRP=2 --set FLOWGRP_CAP=20 --set FLOWGRP_US=1000000 --set FT_EDGE=0.15 --set FT_SZ=200
//!       --set FT_GAP_MS=50 --set QUOTE_SIZE=1 --set KEEP_LOTS=20 --set KEEP_TH=0.3 --set FT_MAXSPREAD=1
//!       --set FT_ROOM_LIVE=1 (CANCEL_FREE stays 0.0)
//!   L1  (r2_L1_taker_liquidity.py, 269920.00): T2's and --set LIQ=1
//!   L3  (r2_L3_taker_pure.py, 294098.00): L1's and --set QUOTE_SIZE=0
//!   L8  (r2_L8_quote_switch.py, 296181.00): L1's and --set QS_RATE=2.5
//!   L9  (r2_L9_taker_huber.py, 317057.00): L3's and --set POSITION_LIMIT=100 --set IMPACT_US=500000
//!       --set HUBER=6.0 --set RIDGE_MIN=30 --set RIDGE_FRAC=0.003 (its `_quote`'s `effective=reserved` is this
//!       file's quote room at CANCEL_FREE 0 while no KEEP shrink is in flight: with quotes of at most KEEP_LOTS too,
//!       so L9 with L8's switch is L9's and --set QUOTE_SIZE=1 --set QS_RATE=2.5)
//! `RIDGE_FEAT_LOG` (an environment variable, a path; off by default, runs without it unchanged) writes each matured
//! first-model label as little-endian f64s: the observation's time (s), its mid, the label, the stored forecast,
//! inventory, the n features, then the 14 extras of `python/experiments/day/pretrain_dump_bot.py` (FeatExtras): the
//! rows `experiments.day.pretrain_forecast rdump` trains on, the same bits as the Python dump (R3-F1's settings).
//! Burst sizing over the 100-lot limit (R3-J1, 8 Nov; Rust only, off by default: L9's 317057.00 and its pnl.csv and
//! result.json unchanged): the penalty is flat (10,000 a second while |position| > 100), so a burst is short and
//! big. Its trigger: the forecast take's signal at least `BURST_TH` (0.0: off) ticks, while the spread is at least
//! `BURST_SPREAD` (0) and the |mid change| rate over `BURST_SPEED_US` (5000000) is at least `BURST_SPEED` (0.0: off)
//! ticks a second; or a jump, the mid at least `BURST_JUMP` (0.0: off) ticks from the oldest mid within
//! `BURST_JUMP_MS` (0: the last valid book's); or `BURST_QUIET_MS` (0: off), the first market trade after that long
//! without one while the spread before it was at least BURST_SPREAD, its aggressor's side; a jump burst only if the
//! signal its way is at least `BURST_AGREE` (-99: any), and it sends at once an IOC `BURST_THRU` (0) ticks through the
//! far touch for its room, whatever the forecast. At most one burst a `BURST_GAP_MS` (5000); for `BURST_MS` (500) the
//! forecast take on the burst's side has BURST_EXP (100) as its exposure and limit, `BURST_SZ` (0: BURST_EXP) lots a
//! take, BURST_THRU through, the spread cap `BURST_MAXSPREAD` (0: FT_MAXSPREAD), and fires on the burst's first book
//! whatever FT_GAP_MS; the hedge holds off that side up to BURST_EXP until the burst ends, then brings the position
//! back within EXPOSURE; `BURST_HOLD` (-99: off) ends it early once the signal its way falls below it. RIDGE_DEBUG
//! adds the bursts and the lots their takes sent. Every trigger lost to L9 on round 2's and round 3's public tapes
//! (IDEAS.md, "Burst sizing on R2-L9").
//! Round 3's latent-price filter (R3-F1, `r3_F1_latent_filter.py`, 8 Nov), off by default: `FILTER` (0; 1 adds three
//! features at the end of the base features, after TREND's: a hidden-Markov filter over the latent reference bid
//! lb on FILTER_W (8) ticks either side of the bid. Each new market order within FILTER_DEPTH (6) of the previous
//! valid book's touch multiplies it by its likelihood: a bid at lb - k, an ask at lb + 1 + k, k 0/1/2 with
//! FILTER_PI0/1/2 (0.55/0.39/0.06), clamped one tick off the other touch, plus FILTER_EPS (0.01). lb random-walks at
//! FILTER_RATE (2.0) steps a second each way. A market taker's filled lots move lb FILTER_IMPACT (3.0) x tape_gen's
//! impact table, or FILTER_SQRT_C x sqrt(lots) when that is > 0. The features are gap = E[lb] + 0.5 - mid
//! (clipped +-5), gap |gap| / 3 and min(3, the posterior sd). It needs QUOTEFEAT 1 for its new-order set.
//! `FILTER_JUMP` (0.0: off) adds jumps to lb's walk: at that rate a second, a lognormal size (median
//! FILTER_JUMP_MED 6.66, log-sd FILTER_JUMP_SD 0.79, tape_gen v2's r3 preset) either way, mixed in around the
//! posterior's mode and renormalised. No Python file has it yet: it loses on round3_public, -10k to -30k in every cell
//! of rate 0.03-0.3 x median 3-6.66 x W 8-16 on B1F, though it lifts the filter's correlation on tape_gen's draws.
//! `FILTER_VQS` (0.0: off; needs QS_RATE): while L8's |mid change| rate is at least FILTER_VQS ticks a second, the
//! inserts' k weights are FILTER_VPI0/1/2 (0.45/0.40/0.15, normalised) instead of FILTER_PI*. Rust only. On B1F it
//! gains 3-6k out of sample on round3_public but loses 1-6k in the first 75%, and loses 35-41k on hi_vol_fast1.25.)
//! `FILTER_IMP2` / `FILTER_IMP3` (0.0: off; R3-F4, `r3_F4_filter_bank.py`, 8 Nov): more copies of the filter at those
//! impact scales, fed the same events; each keeps its inserts' predictive log-likelihood (log of the likelihood's sum
//! before normalising), decayed by 1 - 1/`FILTER_LL_N` (100000) per insert, and the three features come from the copy
//! with the highest (ties: FILTER_IMPACT's own): the impact scale chosen online by likelihood. `FILTER_LL_MARGIN` (0.0):
//! a copy is chosen only while it beats FILTER_IMPACT's by that many nats. `FILTER_XGAP` 1 / 2 (0: off) instead adds
//! the first copy's gap (and gap |gap| / 3) as features after F3's three, with no choice. `FILTER_CLIP` (5.0) is the
//! gap's clip; `FILTER_VRATE` / `FILTER_VIMPACT` (0.0: off) the walk's rate and the impact scale while FILTER_VQS's
//! switch is on. None beat F3 on round3_public. `FILTER_LADDER` (0: off): a new market order 2-7 ticks behind its
//! cached touch that comes 2 ms (+-1 us) after a same-side one that was 2-7 ticks behind is not observed (round 3's
//! scheduled ladders' children, experiments/day/gen_ladders.py); on R3-F5 +2.5k on round3_public but -3.4k in its
//! first 75%, so no file.
//!   F1  (r3_F1_latent_filter.py, round3_public 480469.00, round2_public 303720.00): L9's and --set FILTER=1
//! The forecast take's early exit (R3-G1, 8 Nov), off by default: `FT_EXIT` (99.0: off). When the forecast take does
//! not fire (the signal within its need) and the signal against the position is more than FT_EXIT plus half the
//! spread, an IOC FT_THRU ticks through the touch on the reducing side for at most `FT_EXIT_SZ` (0: all) of the
//! position net of the live orders on that side, never past flat; it shares the take's FT_GAP_MS and spread cap
//! (python/experiments/day/loss_anatomy.py: on round3_public R3-F3 held 100 lots for about 550 s while its forecast
//! was 0.3-0.65 against, the position's mark-to-market -168 ticks over the next 5 s there). `FT_EXIT_WIDE` (0: off):
//! at a spread of at least that many ticks, the same reduce-only IOC at the touch, unless the signal is with the
//! position by at least `FT_EXIT_KEEP` (99.0: never kept), at most once a FT_GAP_MS (loss_anatomy: the position's
//! next 5-s mark-to-market -260 ticks at a 3+ spread).
//! The forecast take's state-dependent bar and flip size (R3-F5, 8 Nov; Rust only, off by default: F3's 505212.00
//! unchanged): each side's bar is the lowest of FT_EDGE, `FT_JUMP_EDGE` (0.15) for `FT_JUMP_HOLD_MS` (5000) after the mid
//! moved `FT_JUMP` (0.0: off) ticks or more from the oldest mid within `FT_JUMP_MS` (200), and `FT_LGAP_EDGE` (0.15)
//! while the latent filter's gap that way is at least `FT_LGAP` (99.0: off; needs FILTER); `FT_FLIP_M` (99.0: off): a
//! take from a position against it goes past flat only when the signal clears its bar by FT_FLIP_M, else it stops at
//! flat (loss_anatomy: the worst 1% of takes are 200-lot flips from a full opposite position). `FT_EDGE_CALM` (-1.0:
//! off): the base bar while L8's |mid change| rate is below `FT_CALM_RATE` (0.0: QS_RATE; needs QS_RATE).
//! `FT_JUMP_DIR` (0: both sides): 1 lowers only the bar the last jump's way, -1 only the bar against it.
//!   F5  (r3_F5_jump_bar.py, round3_public 515670.00, round2_public 330980.00): F3's and --set FT_EDGE=0.25
//!       --set FT_JUMP=3 --set FT_JUMP_HOLD_MS=5000 --set FT_JUMP_EDGE=0.15
//! The take bar's two more states (R3-P1, 8 Nov; Rust only, off by default: F3 and F5 unchanged), searched with the
//! rest by `experiments.day.policy_search`: `FT_EDGE_FLIP` (-1.0: off), the base bar (FT_EDGE's place) of a take
//! against the position, a reduce or a flip; `FT_SD` (99.0: off; needs FILTER) with `FT_SD_EDGE` (0.15), the bar at
//! most FT_SD_EDGE while the latent filter's posterior sd is at least FT_SD (loss_anatomy: takes at sd 0.5-1 earn
//! +1.34-1.39 a lot at 5 s, under 0.3 +0.41). The jump and gap rules lower either further.
//! The online ensemble selector (R4-E1, 8 Nov; Rust only, off by default: F5 515670.00 unchanged): `ENS` (0: off) runs
//! up to five more ridges beside the first model, on its features and its HUBER: `ENS_H1` / `ENS_H2` / `ENS_H3` (0:
//! off) at those horizons (us), `ENS_NOFILT` (0: off) at that horizon with the filter's three features zeroed,
//! `ENS_FIMP` (0: off) at that horizon with the filter's three from FILTER_IMP2's copy (set FILTER_LL_MARGIN=1e18 so the
//! first model keeps FILTER_IMPACT's). Each forecaster, the first model included, holds a paper position under the
//! take rule (+-EXPOSURE once its forecast net of its own paper skew clears the take's bars, at a spread within
//! FT_MAXSPREAD), marked to the mid and charged half the spread a paper trade, its PnL decayed over `ENS_W_S` (600)
//! seconds. The take's forecast is then the leader's, switching only past `ENS_MARGIN` (0.0) tick-lots (ENS 1), the
//! Hedge average with weights exp(`ENS_ETA` (0.001) x paper PnL) (2), or the first model's with the take's side set by
//! a majority of the forecasters clearing the bar (3). The quoting keeps the first model's. `ENS_DEBUG` (an
//! environment variable, a path) appends a line a run: the switches, the leaders' time shares and the paper trades.
//! R4-X1 (8 Nov; Rust only, off by default: F5 1029443.00 on round4_public and 515670.00 on round3_public unchanged):
//! `FT_WIDE_SPREAD` (0: off) lets the take fire at spreads up to that many ticks, past FT_MAXSPREAD, with the bar
//! `FT_WIDE_EDGE` (1.0) at spreads of 2 ticks or more (in place of every other bar); `FT_CLAMP` (2.0) is the take's own
//! clamp on the first model's forecast (the stored forecast, the Huber fit and the quoting keep +-2). `FT_WS_EDGE`
//! (-1.0: off): for `FT_WS_MS` (2000) after the mid moved `FT_WS_JUMP` (3.0; 0: always) ticks from the oldest mid within
//! `FT_WS_JUMP_MS` (200), a take against the held position needs at least FT_WS_EDGE (adding or opening from flat keeps
//! its bar); `FT_WS_FLIP_MS` (0: off) applies it only while the forecast changed sign within that many ms; `FT_WS_FLAT`
//! (0) 1 sends a reversal under the raised bar but over its own to flat only; `FT_WS_DIR` (0: either) 1 raises it only
//! for a position with the jump, -1 only against. `WS_STATS` (an environment variable, a path) appends a line a run:
//! takes, take lots, reversal takes, raised-bar vetoes, wide takes, position flips and flips within 1 s of the
//! position's start. All lose or rest on one episode (IDEAS.md, "R4-X1").
//! R4-A1 (8 Nov; Rust only, off by default: F5 1029443.00 on round4_public unchanged, FA_LOG on or off): one forced
//! action at the first decision at or after `FA_T` (us), then the policy unchanged, for
//! `experiments.day.action_oracle`: `FA_ACT` 1 WAIT (the take skipped, its cooldown started), 2 TAKE_NOW (the
//! forecast's way under the bar), 3 REDUCE (an IOC to flat in place of the decision), 4 COMPLETE (the first take
//! cancelled partly filled at or after FA_T: its rest at the next book). `FA_LOG` (an environment variable, a path)
//! writes the takes, the near-bar decisions and the partly filled takes. The WAIT rule `FT_CONFIRM` (0: off) defers a
//! fresh take once and sends it within `FT_CONFIRM_MS` (200) only if the signal still clears the bar; `FT_CONFIRM_FLIP`
//! (0) 1 only reversals, `FT_CONFIRM_QS_LO` / `_HI` a speed range, `FT_CONFIRM_MARGIN` (99.0) takes clearing the bar by
//! less. FT_CONFIRM loses 134k on round4_public (IDEAS.md, "R4-A1").
//!
//! The audit's quote knobs (8 Nov), off by default: `QS_PULL` (0) 1 withdraws both quotes, so the resting ones are
//! cancelled, while QS_RATE's switch is off; `QUOTE_GAP` (99.0: off) withdraws the quote on the side the latent filter's
//! gap is against by more than that many ticks. Both lose on R3-F3 (round3_public: QS_PULL 1 495,475, QUOTE_GAP
//! 0-1.0 497,848-501,145, against 505,212; IDEAS.md, "Round 3 audit").

use std::collections::{HashMap, HashSet, VecDeque};

use crate::params::Params;
use crate::strategies::profit_gate::ProfitGate;
use crate::strategies::calib::Calib;
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
    /// (time, mid, features, mid changes so far, the forecast at the observation: HUBER's)
    observations: VecDeque<(i64, f64, [f64; NM], i64, f64)>,
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
    /// R4-M1's mixture of experts (MOE, 0: off; the section at the end of the file)
    moe: Option<Box<Moe>>,
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
    /// small slices one tick behind the desired price (R2-S, 7 Nov): L2_LOTS, L2_ORDERS, L2_FREE; BURST
    l2_lots: i64,
    l2_orders: usize,
    l2_free: bool,
    l2_last: [i64; 2],
    burst: usize,
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
    /// round 2's takers (8 Nov, all off by default): FT_MAXSPREAD, FT_ROOM_LIVE, LIQ, IMPACT_US, HUBER, QS_RATE, QS_US
    ft_maxspread: i64,
    ft_room_live: bool,
    /// R3-G1's early exit (FT_EXIT 99.0: off; FT_EXIT_SZ 0: the whole position)
    ft_exit: f64,
    ft_exit_sz: i64,
    ft_exit_wide: i64,
    ft_exit_keep: f64,
    /// R3-F5's state-dependent take bar and flip size (8 Nov, all off by default): FT_LGAP / FT_LGAP_EDGE, FT_JUMP /
    /// FT_JUMP_MS / FT_JUMP_HOLD_MS / FT_JUMP_EDGE, FT_FLIP_M
    ft_lgap: f64,
    ft_lgap_edge: f64,
    ft_jump: f64,
    ft_jump_ms: i64,
    ft_jump_hold_ms: i64,
    ft_jump_edge: f64,
    ft_jump_mids: VecDeque<(i64, f64)>,
    ft_jump_until: i64,
    ft_jump_sign: i64,
    ft_jump_dir: i64,
    ft_flip_m: f64,
    ft_edge_calm: f64,
    ft_calm_rate: f64,
    /// R3-P1's take-bar states (8 Nov, off by default): FT_EDGE_FLIP, FT_SD / FT_SD_EDGE
    ft_edge_flip: f64,
    ft_sd: f64,
    ft_sd_edge: f64,
    /// R4-X1 (8 Nov, off by default): wide-spread takes (FT_WIDE_SPREAD, FT_WIDE_EDGE, the take's clamp FT_CLAMP) and
    /// the post-jump whipsaw bar on reversals (FT_WS_EDGE, FT_WS_MS, FT_WS_JUMP, FT_WS_JUMP_MS, FT_WS_FLIP_MS)
    ft_wide_spread: i64,
    ft_wide_edge: f64,
    ft_clamp: f64,
    ft_ws_edge: f64,
    ft_ws_ms: i64,
    ft_ws_jump: f64,
    ft_ws_jump_ms: i64,
    ft_ws_flip_ms: i64,
    ft_ws_flat: bool,
    ft_ws_dir: i64,
    ws_sign: i64,
    ws_mids: VecDeque<(i64, f64)>,
    ws_until: i64,
    ws_pred_sign: i64,
    ws_flip_t: i64,
    /// WS_STATS (env var, a path, appended on drop): takes, take lots, reversal takes, raised-bar vetoes, wide takes,
    /// position flips and those within 1 s of the position's start
    ws_stats: Option<String>,
    ws_count: [i64; 7],
    /// R4-A1 (8 Nov, off by default): one forced action at the first decision at or after FA_T (us), then the policy
    /// unchanged. FA_ACT 1 WAIT (the first take skipped, its cooldown started), 2 TAKE_NOW (the forecast's way though
    /// under the bar), 3 REDUCE (an IOC to flat, never past, in place of that decision's take), 4 COMPLETE (the first
    /// take IOC cancelled partly filled at or after FA_T: its rest at the next book, at the touch). FA_LOG (env var, a
    /// path): takes, near-bar decisions (100 ms apart) and partly filled takes, to sample them
    fa_t: i64,
    fa_act: i64,
    fa_done: bool,
    fa_rest: Option<(i64, i64)>,
    fa_takes: HashMap<u64, (i64, i64, i64)>,
    fa_log: Option<std::io::BufWriter<std::fs::File>>,
    fa_log_last: i64,
    fa_pred_sign: i64,
    fa_flip_t: i64,
    /// R4-A1's rule (off by default): FT_CONFIRM 1 defers a take once (skipped, its cooldown started) and sends it at a
    /// later decision within FT_CONFIRM_MS only if the signal still clears the bar that way; FT_CONFIRM_FLIP 1 only
    /// takes that reverse a held position; FT_CONFIRM_QS_LO / _HI the speed (QS_RATE's rate) range it applies in;
    /// FT_CONFIRM_MARGIN only takes whose signal clears the bar by less than it
    ft_confirm: i64,
    ft_confirm_ms: i64,
    ft_confirm_flip: i64,
    ft_confirm_qs_lo: f64,
    ft_confirm_qs_hi: f64,
    ft_confirm_margin: f64,
    cf_sign: i64,
    cf_t: i64,
    ws_inv_sign: i64,
    ws_inv_start: i64,
    ws_zero_t: i64,
    ws_flat: bool,
    liq: i64,
    /// LIQ: the last recompute's time and mid, each market order's first-seen time, the young imbalance, the dispersion
    liq_time: Option<i64>,
    liq_mid: f64,
    liq_seen: HashMap<u64, i64>,
    liq_young: f64,
    liq_disp: f64,
    impact_us: i64,
    impact_net: f64,
    impact_vol: f64,
    impact_frame: [f64; 2],
    huber: f64,
    qs_th: f64,
    qs_us: i64,
    qs_last: Option<(i64, f64)>,
    qs_rate: f64,
    /// the audit's quote knobs (8 Nov, off by default): QS_PULL 1 cancels the resting quotes while QS_RATE's switch is
    /// off; QUOTE_GAP (99.0: off) withdraws the side the filter's gap is against by more than this many ticks
    qs_pull: bool,
    quote_gap: f64,
    lf_gap_now: f64,
    /// round 3's burst sizing (R3-J1, 8 Nov, off by default): BURST_TH ... BURST_HOLD
    burst_th: f64,
    burst_exp: i64,
    burst_sz: i64,
    burst_ms: i64,
    burst_gap_ms: i64,
    burst_spread: i64,
    burst_speed: f64,
    burst_speed_us: i64,
    burst_thru: i64,
    burst_maxspread: i64,
    burst_hold: f64,
    burst_jump: f64,
    burst_quiet_ms: i64,
    burst_agree: f64,
    burst_prev_mid: Option<f64>,
    burst_prev_spread: i64,
    burst_trade_last: i64,
    burst_jump_ms: i64,
    burst_mids: VecDeque<(i64, f64)>,
    /// the burst's side, its end and its start; the speed gate's decayed |mid change| rate
    burst_sign: i64,
    burst_until: i64,
    burst_last: i64,
    burst_rate_last: Option<(i64, f64)>,
    burst_rate: f64,
    /// RIDGE_DEBUG: bursts started, lots taken in bursts
    burst_n: i64,
    burst_lots: i64,
    /// R3-F1's latent-price filter (FILTER, 0: off): a probability vector over lb = lf_base + i, i < lf_n
    filter: i64,
    lf_w: i64,
    lf_n: usize,
    lf_rate: f64,
    lf_eps: f64,
    lf_pi: [f64; 3],
    lf_cum: [f64; 3],
    lf_impact: f64,
    lf_sqrt_c: f64,
    lf_depth: i64,
    lf_p: Vec<f64>,
    lf_base: i64,
    lf_t: Option<f64>,
    /// RIDGE_FEAT_LOG (env var, a path; experiments/day/pretrain_forecast.py): each matured first-model label as
    /// little-endian f64s: t (s), the observation's mid, the label, the stored forecast, inventory, the n features,
    /// then the 14 extras of pretrain_dump_bot.py's AExtras (fx) at the observation
    feat_log: Option<std::io::BufWriter<std::fs::File>>,
    feat_pending: VecDeque<(i64, f64, [f64; 14])>,
    fx: FeatExtras,
    /// FILTER_JUMP (0: off): lb also jumps at that rate a second, a lognormal size either way, spread around the MAP
    lf_jump: f64,
    lf_jump_k: Vec<f64>,
    /// FILTER_VQS (0: off): while QS_RATE's |mid change| rate is at least this, the inserts' k weights are FILTER_VPI*
    lf_vqs: f64,
    lf_vpi: [f64; 3],
    lf_vcum: [f64; 3],
    /// FILTER_IMP2 / FILTER_IMP3 (0: off): more copies of the filter at those impact scales, fed the same events; each
    /// keeps its inserts' predictive log-likelihood decayed by FILTER_LL_KEEP (1 - 1/FILTER_LL_N) per insert, and the
    /// features come from the copy with the highest (ties: the first, FILTER_IMPACT's)
    lf_bank: Vec<LfMember>,
    lf_ll: f64,
    lf_ll_keep: f64,
    /// FILTER_XGAP (0: off; needs FILTER_IMP2): no choice; F3's three features plus the first bank copy's gap (1), and
    /// its gap |gap| / 3 (2), at the end of the base features
    lf_xgap: i64,
    /// FILTER_LL_MARGIN (0.0): a bank copy is chosen only while its log-likelihood beats FILTER_IMPACT's by this many nats
    lf_ll_margin: f64,
    /// GASYM_US (R4-S1, 0: off): one more feature at the very end of the base features, the new market limit orders'
    /// mean distance behind their own (cached) touch, asks minus bids, each side's count and distance decayed over
    /// GASYM_US (round 4's tape: partial R^2 1.4% of the 0.4-s move beyond F5's forecast; ~0 on rounds 2 and 3)
    gasym_us: i64,
    gasym: [f64; 4],
    gasym_last: Option<i64>,
    /// GAPMEAN_US (R4-S1, 0: off; needs FILTER): one more feature after GASYM_US's, the filter's gap averaged over
    /// GAPMEAN_US (an exponential average at every valid book)
    gapmean_us: i64,
    gapmean: f64,
    gapmean_last: Option<i64>,
    /// the features GASYM_US and GAPMEAN_US add at the end (0-2)
    xf_n: usize,
    /// FILTER_CLIP (5.0): the gap feature's clip, +-ticks
    lf_clip: f64,
    /// FILTER_VRATE / FILTER_VIMPACT (0.0: FILTER_RATE's / FILTER_IMPACT's): the walk's rate and the impact scale while
    /// FILTER_VQS's switch is on (QS_RATE's |mid change| rate at least FILTER_VQS)
    lf_vrate: f64,
    lf_vimpact: f64,
    /// FILTER_LADDER (0: off; R3-F7): a new market order 2-7 ticks behind its own (cached) touch that comes 2 ms
    /// (+-1 us) after a same-side one that was 2-7 ticks behind its touch is not observed (round 3's scheduled ladders,
    /// experiments/day/gen_ladders.py); lf_recent holds each side's recent new orders (time, in the band)
    lf_ladder: i64,
    lf_recent: [VecDeque<(i64, bool)>; 2],
    lf_skip: HashSet<u64>,
    /// R4-PG's profit gate (profit_gate.rs; PG 0: off)
    pg: ProfitGate,
    /// R4-C1 (calib.rs, off by default): the take's forecast rescaled by the market's speed
    cal: Calib,
    /// R4-E1's online ensemble selector (ENS, 0: off): more ridges beside the first model, each with a paper
    /// position under the take rule, chosen by decayed paper PnL
    ens: i64,
    ens_models: Vec<Model>,
    /// per extra: 0 the same features, 1 the filter's three zeroed, 2 the filter's three from FILTER_IMP2's copy
    ens_kind: Vec<u8>,
    ens_pos: [i64; 8],
    ens_score: [f64; 8],
    ens_last: Option<(i64, f64)>,
    ens_w_us: f64,
    ens_margin: f64,
    ens_eta: f64,
    ens_leader: usize,
    ens_switches: i64,
    ens_lead_t: [f64; 8],
    ens_paper_trades: [i64; 8],
}

/// one more copy of R3-F1's filter (FILTER_IMP2 / FILTER_IMP3): its state, swapped into the RidgeMaker's lf_* fields
/// while it is updated, so the same code runs on it
struct LfMember {
    p: Vec<f64>,
    base: i64,
    t: Option<f64>,
    impact: f64,
    ll: f64,
}

extern "C" {
    /// the C library's erf, the one CPython's math.erf calls
    fn erf(x: f64) -> f64;
}

/// FILTER_JUMP's kernel by |offset| from the mode (each sign half), as `r3_F*`'s `_lf_jump_kernel`.
fn lf_jump_kernel(n: usize, med: f64, sd: f64) -> Vec<f64> {
    let cdf = |x: f64| 0.5 * (1.0 + unsafe { erf((x.ln() - med.ln()) / (sd * 2f64.sqrt())) });
    let mut w = Vec::new();
    for k in 1..n {
        let hi = cdf(k as f64 + 0.5);
        let lo = if k > 1 { cdf(k as f64 - 0.5) } else { 0.0 };
        w.push(hi - lo);
    }
    let mut tot = 0.0;
    for x in &w {
        tot += x;
    }
    if tot == 0.0 {
        tot = 1.0;
    }
    let mut k = vec![0.0];
    for x in w {
        k.push(x / tot / 2.0);
    }
    k
}

/// pretrain_dump_bot.py's AExtras (R3-P1's PreExtras): the frozen forecast's extra inputs' running state
#[derive(Default)]
struct FeatExtras {
    t: Option<i64>,
    mid: Option<f64>,
    v1: f64,
    v10: f64,
    t_wide: i64,
    t_move: i64,
    last_move: f64,
    fsq: f64,
    fbig: f64,
}

impl FeatExtras {
    fn update(&mut self, now: i64, bid: i64, ask: i64, trades: &[Trade]) {
        let mid = (bid + ask) as f64 * 0.5;
        let dt = match self.t {
            None => 0,
            Some(t) => (now - t).max(0),
        };
        self.t = Some(now);
        if dt != 0 {
            let d1 = ((-dt) as f64 / 1e6).exp();
            self.v1 *= d1;
            self.v10 *= ((-dt) as f64 / 1e7).exp();
            self.fsq *= d1;
            self.fbig *= d1;
        }
        if let Some(m) = self.mid {
            if mid != m {
                let mv = mid - m;
                self.v1 += mv.abs();
                self.v10 += mv.abs();
                self.t_move = now;
                self.last_move = mv;
            }
        }
        self.mid = Some(mid);
        if ask - bid >= 2 {
            self.t_wide = now;
        }
        let mut lots: Vec<(u64, i64, i64)> = Vec::new();
        for trade in trades {
            if trade.taker_owner != Owner::Market {
                continue;
            }
            let direction = if trade.book_side == Side::Sell { 1 } else { -1 };
            match lots.iter_mut().find(|(id, _, _)| *id == trade.taker_order_id) {
                Some(entry) => entry.2 += trade.quantity,
                None => lots.push((trade.taker_order_id, direction, trade.quantity)),
            }
        }
        for (_, direction, q) in lots {
            self.fsq += direction as f64 * (q as f64).powf(0.5);
            if q as f64 > self.fbig.abs() {
                self.fbig = (direction * q) as f64;
            }
        }
    }

    fn features(&self, now: i64, snapshot: &Snapshot, bid: i64, ask: i64, lf_p: &[f64], lf_base: i64) -> [f64; 14] {
        let mid = (bid + ask) as f64 * 0.5;
        let mut q = [[0i64; 2]; 2];
        for (k, (side, touch, sgn)) in [(Side::Buy, bid, -1i64), (Side::Sell, ask, 1)].into_iter().enumerate() {
            for order in snapshot.side(side) {
                if order.owner != Owner::Market {
                    continue;
                }
                let d = (order.price - touch) * sgn;
                if d == 0 {
                    q[k][0] += order.quantity;
                } else if d == 1 {
                    q[k][1] += order.quantity;
                } else if d > 1 {
                    break;
                }
            }
        }
        let (bq, b2, aq, a2) = (q[0][0] as f64, q[0][1] as f64, q[1][0] as f64, q[1][1] as f64);
        let (mut up, mut dn, mut raw) = (0.0f64, 0.0f64, 0.0f64);
        if !lf_p.is_empty() {
            let mut m = 0.0f64;
            for (i, &v) in lf_p.iter().enumerate() {
                let g = (lf_base + i as i64) as f64 + 0.5 - mid;
                m += v * g;
                if g >= 0.5 {
                    up += v;
                } else if g <= -0.5 {
                    dn += v;
                }
            }
            raw = clamp(m, -10.0, 10.0);
        }
        let fb = self.fbig;
        let sgn = if fb > 0.0 { 1.0 } else if fb < 0.0 { -1.0 } else { 0.0 };
        [
            (ask - bid).min(5) as f64,
            bq.ln_1p() - aq.ln_1p(),
            (bq.ln_1p() + aq.ln_1p()) / 5.0,
            self.v1.min(20.0) / 5.0,
            self.v10.min(200.0) / 50.0,
            ((now - self.t_wide) as f64 / 1e6).min(10.0),
            ((now - self.t_move) as f64 / 1e6).min(5.0),
            clamp(self.last_move, -5.0, 5.0),
            clamp(self.fsq, -50.0, 50.0) / 10.0,
            sgn * fb.abs().ln_1p() / 5.0,
            up,
            dn,
            raw,
            b2.ln_1p() - a2.ln_1p(),
        ]
    }
}

impl RidgeMaker {
    /// RIDGE_DUMP: the models' sufficient statistics (at DUMP_US, else at the end) to that file, for a warm start
    fn dump_on_drop(&mut self) {
        if self.ens > 0 {
            if let Ok(path) = std::env::var("ENS_DEBUG") {
                use std::io::Write;
                let n = 1 + self.ens_models.len();
                let tot: f64 = self.ens_lead_t[..n].iter().sum();
                let share: Vec<String> = self.ens_lead_t[..n].iter().map(|t| format!("{:.3}", t / tot.max(1.0))).collect();
                let line = format!(
                    "ENS mode={} n={} w_s={} margin={} eta={} secs={:.0} switches={} lead_share=[{}] paper_trades={:?}\n",
                    self.ens, n, self.ens_w_us / 1e6, self.ens_margin, self.ens_eta, tot / 1e6, self.ens_switches,
                    share.join(","), &self.ens_paper_trades[..n]
                );
                if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
                    let _ = f.write_all(line.as_bytes());
                }
            }
        }
        if std::env::var("RIDGE_DEBUG").is_ok() {
            eprintln!(
                "RIDGE_DEBUG maker_lots={} maker_edge={:.1} ioc_lots={} ioc_edge={:.1} at_limit_share={:.3} final_inv={}",
                self.dbg[0], self.dbg[1], self.dbg[2], self.dbg[3], self.dbg[4] / self.dbg[5].max(1.0), self.inventory
            );
            let st = self.dbg_steps;
            let mean = st[1] / st[0].max(1.0);
            eprintln!(
                "RIDGE_DEBUG mean_abs_inv={:.1} step25_n={} step25_mean={:.1} step25_sd={:.1} bursts={} burst_lots={}",
                self.dbg_inv[0] / self.dbg_inv[1].max(1.0), st[0], mean, (st[2] / st[0].max(1.0) - mean * mean).max(0.0).sqrt(),
                self.burst_n, self.burst_lots
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
        if let Some(path) = &self.ws_stats {
            use std::io::Write;
            let c = self.ws_count;
            let line = format!(
                "FT_WIDE_SPREAD={} FT_WIDE_EDGE={} FT_CLAMP={} FT_WS_EDGE={} FT_WS_MS={} FT_WS_JUMP={} FT_WS_JUMP_MS={} FT_WS_FLIP_MS={} FT_WS_FLAT={} FT_WS_DIR={}\ttakes={}\ttake_lots={}\treversals={}\tvetoes={}\twide_takes={}\tflips={}\tfast_flips={}\n",
                self.ft_wide_spread, self.ft_wide_edge, self.ft_clamp, self.ft_ws_edge, self.ft_ws_ms, self.ft_ws_jump,
                self.ft_ws_jump_ms, self.ft_ws_flip_ms, self.ft_ws_flat as i64, self.ft_ws_dir, c[0], c[1], c[2], c[3], c[4], c[5], c[6]
            );
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
                let _ = f.write_all(line.as_bytes());
            }
        }
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

pub const KEYS: [&str; 196] = [
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
    "L2_LOTS", "L2_ORDERS", "L2_FREE", "BURST",
    "FT_MAXSPREAD", "FT_ROOM_LIVE", "LIQ", "IMPACT_US", "HUBER", "QS_RATE", "QS_US",
    "BURST_TH", "BURST_EXP", "BURST_SZ", "BURST_MS", "BURST_GAP_MS", "BURST_SPREAD", "BURST_SPEED", "BURST_SPEED_US",
    "BURST_THRU", "BURST_MAXSPREAD", "BURST_HOLD", "BURST_JUMP", "BURST_QUIET_MS", "BURST_AGREE",
    "BURST_JUMP_MS",
    "FILTER", "FILTER_W", "FILTER_RATE", "FILTER_EPS", "FILTER_PI0", "FILTER_PI1", "FILTER_PI2", "FILTER_IMPACT",
    "FILTER_SQRT_C", "FILTER_DEPTH", "FILTER_JUMP", "FILTER_JUMP_MED", "FILTER_JUMP_SD",
    "FILTER_VQS", "FILTER_VPI0", "FILTER_VPI1", "FILTER_VPI2", "FILTER_IMP2", "FILTER_IMP3", "FILTER_LL_N", "FILTER_XGAP", "FILTER_LL_MARGIN", "FILTER_CLIP", "FILTER_VRATE", "FILTER_VIMPACT", "FILTER_LADDER",
    "FT_EXIT", "FT_EXIT_SZ", "FT_EXIT_WIDE", "FT_EXIT_KEEP", "QS_PULL", "QUOTE_GAP",
    "FT_LGAP", "FT_LGAP_EDGE", "FT_JUMP", "FT_JUMP_MS", "FT_JUMP_HOLD_MS", "FT_JUMP_EDGE", "FT_FLIP_M",
    "FT_EDGE_CALM", "FT_CALM_RATE", "FT_JUMP_DIR",
    "FT_EDGE_FLIP", "FT_SD", "FT_SD_EDGE",
    "ENS", "ENS_H1", "ENS_H2", "ENS_H3", "ENS_NOFILT", "ENS_FIMP", "ENS_W_S", "ENS_MARGIN", "ENS_ETA",
    "GASYM_US", "GAPMEAN_US",
];

/// R4-X1's knobs (wide-spread takes, the post-jump whipsaw bar), all off by default
pub const X1_KEYS: [&str; 10] = [
    "FT_WIDE_SPREAD", "FT_WIDE_EDGE", "FT_CLAMP", "FT_WS_EDGE", "FT_WS_MS", "FT_WS_JUMP", "FT_WS_JUMP_MS", "FT_WS_FLIP_MS",
    "FT_WS_FLAT", "FT_WS_DIR",
];

/// R4-A1's forced action (off by default)
pub const FA_KEYS: [&str; 8] =
    ["FA_T", "FA_ACT", "FT_CONFIRM", "FT_CONFIRM_MS", "FT_CONFIRM_FLIP", "FT_CONFIRM_QS_LO", "FT_CONFIRM_QS_HI", "FT_CONFIRM_MARGIN"];

fn side_index(sign: i64) -> usize {
    if sign > 0 {
        0
    } else {
        1
    }
}

impl RidgeMaker {
    pub fn new(params: &Params) -> Result<RidgeMaker, String> {
        params.check_keys(&[&KEYS[..], &MOE_KEYS[..], &crate::strategies::profit_gate::KEYS[..], &crate::strategies::calib::KEYS[..], &X1_KEYS[..], &FA_KEYS[..]].concat())?;
        let n_base = N + if params.int("PLACE", 0)? > 0 { 2 } else { 0 }
                + if params.int("DEPTH5", 0)? > 0 { 1 } else { 0 }
                + if params.int("FLOW2", 0)? > 0 { 2 } else { 0 }
                + if params.int("LAST_AGG", 0)? > 0 { 1 } else { 0 }
                + if params.int("QUOTEFEAT", 0)? > 0 { 6 } else { 0 }
                + if params.int("FLOWGRP", 0)? > 0 { 8 } else { 0 }
                + if params.int("BUCKET", 0)? > 0 { 17 } else { 0 }
                + if params.int("LIQ", 0)? > 0 { 4 } else { 0 }
                + if params.int("IMPACT_US", 0)? > 0 { 3 } else { 0 }
                + if params.int("TREND", 0)? > 0 { 2 } else { 0 }
                + if params.int("FILTER", 0)? > 0 { 3 + params.int("FILTER_XGAP", 0)? as usize } else { 0 }
                + if params.int("GASYM_US", 0)? > 0 { 1 } else { 0 }
                + if params.int("GAPMEAN_US", 0)? > 0 { 1 } else { 0 };
        if params.int("GASYM_US", 0)? > 0 && params.int("QUOTEFEAT", 0)? == 0 {
            return Err("GASYM_US reads the new market orders QUOTEFEAT tracks: set QUOTEFEAT=1".to_string());
        }
        if params.int("GAPMEAN_US", 0)? > 0 && params.int("FILTER", 0)? == 0 {
            return Err("GAPMEAN_US averages the filter's gap: set FILTER=1".to_string());
        }
        if params.int("FILTER_XGAP", 0)? > 0 && params.float("FILTER_IMP2", 0.0)? <= 0.0 {
            return Err("FILTER_XGAP reads the bank's first copy: set FILTER_IMP2".to_string());
        }
        if params.int("CAL", 0)? > 0 && params.float("QS_RATE", 0.0)? <= 0.0 {
            return Err("CAL reads QS_RATE's speed: set QS_RATE".to_string());
        }
        if params.int("FILTER", 0)? > 0 && params.int("QUOTEFEAT", 0)? == 0 {
            return Err("FILTER reads the new market orders QUOTEFEAT tracks: set QUOTEFEAT=1".to_string());
        }
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
        if rm.ens > 0 {
            for (key, kind) in [("ENS_H1", 0u8), ("ENS_H2", 0), ("ENS_H3", 0), ("ENS_NOFILT", 1), ("ENS_FIMP", 2)] {
                let h = params.int(key, 0)?;
                if h > 0 {
                    if kind > 0 && rm.filter == 0 {
                        return Err(format!("{key} changes the filter's features: set FILTER=1"));
                    }
                    if kind == 2 && (rm.lf_bank.is_empty() || rm.lf_xgap > 0) {
                        return Err("ENS_FIMP reads FILTER_IMP2's copy: set FILTER_IMP2 (and FILTER_LL_MARGIN=1e18)".to_string());
                    }
                    rm.ens_models.push(Model::new(h, n));
                    rm.ens_kind.push(kind);
                }
            }
        }
        if rm.side2 == 2 {
            rm.ex[0].label = 1;
            rm.ex[1].label = 2;
        }
        rm.load_warm();
        Ok(rm)
    }

    fn build(params: &Params, n_base: usize, n: usize) -> Result<RidgeMaker, String> {
        // R3-F1's FILTER_PI, normalised as the Python's sum() and division
        let lf_w = params.int("FILTER_W", 8)?;
        let raw = [params.float("FILTER_PI0", 0.55)?, params.float("FILTER_PI1", 0.39)?, params.float("FILTER_PI2", 0.06)?];
        let total = 0.0 + raw[0] + raw[1] + raw[2];
        let lf_pi = [raw[0] / total, raw[1] / total, raw[2] / total];
        let vraw = [params.float("FILTER_VPI0", 0.45)?, params.float("FILTER_VPI1", 0.40)?, params.float("FILTER_VPI2", 0.15)?];
        let vtotal = 0.0 + vraw[0] + vraw[1] + vraw[2];
        let lf_vpi = [vraw[0] / vtotal, vraw[1] / vtotal, vraw[2] / vtotal];
        if params.float("FILTER_VQS", 0.0)? > 0.0 && params.float("QS_RATE", 0.0)? <= 0.0 {
            return Err("FILTER_VQS reads QS_RATE's speed: set QS_RATE".to_string());
        }
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
            moe: Moe::from_params(params)?,
            feat_log: std::env::var("RIDGE_FEAT_LOG")
                .ok()
                .map(|p| std::io::BufWriter::new(std::fs::File::create(p).expect("RIDGE_FEAT_LOG"))),
            feat_pending: VecDeque::new(),
            fx: FeatExtras { t_wide: -1_000_000_000_000, t_move: -1_000_000_000_000, ..Default::default() },
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
            l2_lots: params.int("L2_LOTS", 0)?,
            l2_orders: params.int("L2_ORDERS", 0)? as usize,
            l2_free: params.int("L2_FREE", 0)? != 0,
            l2_last: [-5000, -5000],
            burst: params.int("BURST", 1)?.max(1) as usize,
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
            ft_maxspread: params.int("FT_MAXSPREAD", 0)?,
            ft_room_live: params.int("FT_ROOM_LIVE", 0)? != 0,
            ft_exit: params.float("FT_EXIT", 99.0)?,
            ft_exit_sz: params.int("FT_EXIT_SZ", 0)?,
            ft_exit_wide: params.int("FT_EXIT_WIDE", 0)?,
            ft_exit_keep: params.float("FT_EXIT_KEEP", 99.0)?,
            ft_lgap: params.float("FT_LGAP", 99.0)?,
            ft_lgap_edge: params.float("FT_LGAP_EDGE", 0.15)?,
            ft_jump: params.float("FT_JUMP", 0.0)?,
            ft_jump_ms: params.int("FT_JUMP_MS", 200)?,
            ft_jump_hold_ms: params.int("FT_JUMP_HOLD_MS", 5000)?,
            ft_jump_edge: params.float("FT_JUMP_EDGE", 0.15)?,
            ft_jump_mids: VecDeque::new(),
            ft_jump_until: i64::MIN,
            ft_jump_sign: 0,
            ft_jump_dir: params.int("FT_JUMP_DIR", 0)?,
            ft_flip_m: params.float("FT_FLIP_M", 99.0)?,
            ft_edge_calm: params.float("FT_EDGE_CALM", -1.0)?,
            ft_calm_rate: params.float("FT_CALM_RATE", 0.0)?,
            ft_edge_flip: params.float("FT_EDGE_FLIP", -1.0)?,
            ft_sd: params.float("FT_SD", 99.0)?,
            ft_sd_edge: params.float("FT_SD_EDGE", 0.15)?,
            ft_wide_spread: params.int("FT_WIDE_SPREAD", 0)?,
            ft_wide_edge: params.float("FT_WIDE_EDGE", 1.0)?,
            ft_clamp: params.float("FT_CLAMP", 2.0)?,
            ft_ws_edge: params.float("FT_WS_EDGE", -1.0)?,
            ft_ws_ms: params.int("FT_WS_MS", 2000)?,
            ft_ws_jump: params.float("FT_WS_JUMP", 3.0)?,
            ft_ws_jump_ms: params.int("FT_WS_JUMP_MS", 200)?,
            ft_ws_flip_ms: params.int("FT_WS_FLIP_MS", 0)?,
            ft_ws_flat: params.int("FT_WS_FLAT", 0)? != 0,
            ft_ws_dir: params.int("FT_WS_DIR", 0)?,
            ws_sign: 0,
            ws_mids: VecDeque::new(),
            ws_until: i64::MIN,
            ws_pred_sign: 0,
            ws_flip_t: -(1i64 << 60),
            ws_stats: std::env::var("WS_STATS").ok(),
            ws_count: [0; 7],
            ws_inv_sign: 0,
            ws_inv_start: 0,
            ws_zero_t: -(1i64 << 60),
            ws_flat: true,
            fa_t: params.int("FA_T", 0)?,
            fa_act: params.int("FA_ACT", 0)?,
            fa_done: false,
            fa_rest: None,
            fa_takes: HashMap::new(),
            fa_log: std::env::var("FA_LOG").ok().map(|p| std::io::BufWriter::new(std::fs::File::create(p).expect("FA_LOG"))),
            fa_log_last: i64::MIN / 2,
            fa_pred_sign: 0,
            fa_flip_t: -(1i64 << 60),
            ft_confirm: params.int("FT_CONFIRM", 0)?,
            ft_confirm_ms: params.int("FT_CONFIRM_MS", 200)?,
            ft_confirm_flip: params.int("FT_CONFIRM_FLIP", 0)?,
            ft_confirm_qs_lo: params.float("FT_CONFIRM_QS_LO", 0.0)?,
            ft_confirm_qs_hi: params.float("FT_CONFIRM_QS_HI", 1e9)?,
            ft_confirm_margin: params.float("FT_CONFIRM_MARGIN", 99.0)?,
            cf_sign: 0,
            cf_t: i64::MIN / 2,
            liq: params.int("LIQ", 0)?,
            liq_time: None,
            liq_mid: 0.0,
            liq_seen: HashMap::new(),
            liq_young: 0.0,
            liq_disp: 0.0,
            impact_us: params.int("IMPACT_US", 0)?,
            impact_net: 0.0,
            impact_vol: 0.0,
            impact_frame: [0.0; 2],
            huber: params.float("HUBER", 0.0)?,
            qs_th: params.float("QS_RATE", 0.0)?,
            qs_us: params.int("QS_US", 5_000_000)?,
            qs_last: None,
            qs_rate: 0.0,
            qs_pull: params.int("QS_PULL", 0)? > 0,
            quote_gap: params.float("QUOTE_GAP", 99.0)?,
            lf_gap_now: 0.0,
            burst_th: params.float("BURST_TH", 0.0)?,
            burst_exp: params.int("BURST_EXP", 100)?,
            burst_sz: params.int("BURST_SZ", 0)?,
            burst_ms: params.int("BURST_MS", 500)?,
            burst_gap_ms: params.int("BURST_GAP_MS", 5000)?,
            burst_spread: params.int("BURST_SPREAD", 0)?,
            burst_speed: params.float("BURST_SPEED", 0.0)?,
            burst_speed_us: params.int("BURST_SPEED_US", 5_000_000)?,
            burst_thru: params.int("BURST_THRU", 0)?,
            burst_maxspread: params.int("BURST_MAXSPREAD", 0)?,
            burst_hold: params.float("BURST_HOLD", -99.0)?,
            burst_jump: params.float("BURST_JUMP", 0.0)?,
            burst_quiet_ms: params.int("BURST_QUIET_MS", 0)?,
            burst_agree: params.float("BURST_AGREE", -99.0)?,
            burst_prev_mid: None,
            burst_prev_spread: 0,
            burst_trade_last: i64::MIN / 2,
            burst_jump_ms: params.int("BURST_JUMP_MS", 0)?,
            burst_mids: VecDeque::new(),
            burst_sign: 0,
            burst_until: i64::MIN / 2,
            burst_last: i64::MIN / 2,
            burst_rate_last: None,
            burst_rate: 0.0,
            burst_n: 0,
            burst_lots: 0,
            filter: params.int("FILTER", 0)?,
            lf_w,
            lf_n: (2 * lf_w + 1) as usize,
            lf_rate: params.float("FILTER_RATE", 2.0)?,
            lf_eps: params.float("FILTER_EPS", 0.01)?,
            lf_pi,
            lf_cum: [lf_pi[0], lf_pi[0] + lf_pi[1], 1.0],
            lf_impact: params.float("FILTER_IMPACT", 3.0)?,
            lf_sqrt_c: params.float("FILTER_SQRT_C", 0.0)?,
            lf_depth: params.int("FILTER_DEPTH", 6)?,
            lf_p: Vec::new(),
            lf_base: 0,
            lf_t: None,
            lf_jump: params.float("FILTER_JUMP", 0.0)?,
            lf_jump_k: lf_jump_kernel((2 * lf_w + 1) as usize, params.float("FILTER_JUMP_MED", 6.66)?,
                                      params.float("FILTER_JUMP_SD", 0.79)?),
            lf_vqs: params.float("FILTER_VQS", 0.0)?,
            lf_vpi,
            lf_vcum: [lf_vpi[0], lf_vpi[0] + lf_vpi[1], 1.0],
            lf_bank: [params.float("FILTER_IMP2", 0.0)?, params.float("FILTER_IMP3", 0.0)?]
                .into_iter()
                .filter(|&x| x > 0.0)
                .map(|impact| LfMember { p: Vec::new(), base: 0, t: None, impact, ll: 0.0 })
                .collect(),
            lf_ll: 0.0,
            lf_ll_keep: 1.0 - 1.0 / params.float("FILTER_LL_N", 100000.0)?,
            lf_xgap: params.int("FILTER_XGAP", 0)?,
            lf_ll_margin: params.float("FILTER_LL_MARGIN", 0.0)?,
            gasym_us: params.int("GASYM_US", 0)?,
            gasym: [0.0; 4],
            gasym_last: None,
            gapmean_us: params.int("GAPMEAN_US", 0)?,
            gapmean: 0.0,
            gapmean_last: None,
            xf_n: (params.int("GASYM_US", 0)? > 0) as usize + (params.int("GAPMEAN_US", 0)? > 0) as usize,
            lf_clip: params.float("FILTER_CLIP", 5.0)?,
            lf_vrate: params.float("FILTER_VRATE", 0.0)?,
            lf_vimpact: params.float("FILTER_VIMPACT", 0.0)?,
            lf_ladder: params.int("FILTER_LADDER", 0)?,
            lf_recent: [VecDeque::new(), VecDeque::new()],
            lf_skip: HashSet::new(),
            pg: ProfitGate::new(params)?,
            cal: Calib::new(params, params.int("HORIZON_US", 100_000)?)?,
            ens: params.int("ENS", 0)?,
            ens_models: Vec::new(),
            ens_kind: Vec::new(),
            ens_pos: [0; 8],
            ens_score: [0.0; 8],
            ens_last: None,
            ens_w_us: params.float("ENS_W_S", 600.0)? * 1e6,
            ens_margin: params.float("ENS_MARGIN", 0.0)?,
            ens_eta: params.float("ENS_ETA", 0.001)?,
            ens_leader: 0,
            ens_switches: 0,
            ens_lead_t: [0.0; 8],
            ens_paper_trades: [0; 8],
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
        // HUBER: the first model's labels down-weighted by their residual against the forecast stored with them
        let huber = if which == 0 || which >= 100 { self.huber } else { 0.0 };
        let m = match which {
            0 => &mut self.m1,
            1 => &mut self.m2,
            k if k >= 100 => &mut self.ens_models[k - 100],
            k => &mut self.ex[k - 2],
        };
        let n = m.n;
        while let Some(&(observed_us, old_mid, features, count, stored)) = m.observations.front() {
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
            if which == 0 {
                if let Some(w) = self.feat_log.as_mut() {
                    while self.feat_pending.front().is_some_and(|e| e.0 < observed_us) {
                        self.feat_pending.pop_front();
                    }
                    if let Some(&(t, inv, extra)) = self.feat_pending.front() {
                        if t == observed_us {
                            self.feat_pending.pop_front();
                            use std::io::Write;
                            let mut buf: Vec<u8> = Vec::with_capacity(8 * (5 + n + 14));
                            for v in [observed_us as f64 * 1e-6, old_mid, response, stored, inv]
                                .into_iter()
                                .chain(features[..n].iter().copied())
                                .chain(extra)
                            {
                                buf.extend_from_slice(&v.to_le_bytes());
                            }
                            let _ = w.write_all(&buf);
                        }
                    }
                }
            }
            if label_mode == 2 {
                response = if response > 0.0 { 1.0 } else if response < 0.0 { -1.0 } else { 0.0 };
            }
            if m.label == 1 {
                response = if response < 0.0 { 1.0 } else { 0.0 };
            } else if m.label == 2 {
                response = if response > 0.0 { 1.0 } else { 0.0 };
            }
            if huber > 0.0 {
                // L9: weight = min(1, HUBER / max(1e-12, |response - stored|)), in the Python's operation order
                let residual = (response - stored).abs();
                let r = if residual > 1e-12 { residual } else { 1e-12 };
                let q = huber / r;
                let weight = if q < 1.0 { q } else { 1.0 };
                m.mass = m.mass * decay + weight;
                for i in 0..n {
                    m.xy[i] = m.xy[i] * decay + weight * features[i] * response;
                    for j in 0..n {
                        m.xx[i][j] = m.xx[i][j] * decay + weight * features[i] * features[j];
                    }
                }
            } else {
                m.mass = m.mass * decay + 1.0;
                for i in 0..n {
                    m.xy[i] = m.xy[i] * decay + features[i] * response;
                    for j in 0..n {
                        m.xx[i][j] = m.xx[i][j] * decay + features[i] * features[j];
                    }
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

    /// R3-F1 (`r3_F1_latent_filter.py`'s `_lf_advance`): lb random-walks at FILTER_RATE steps a second each way.
    fn lf_advance(&mut self, t: f64) {
        let Some(last) = self.lf_t else {
            self.lf_t = Some(t);
            return;
        };
        let dt = t - last;
        if dt <= 0.0 {
            return;
        }
        self.lf_t = Some(t);
        let vol = self.lf_vqs > 0.0 && self.qs_rate >= self.lf_vqs;
        let mut a = if vol && self.lf_vrate > 0.0 { self.lf_vrate } else { self.lf_rate } * dt;
        if a < 1e-9 {
            return;
        }
        if a > 0.3 {
            a = 0.3;
        }
        let n = self.lf_n;
        let p = &self.lf_p;
        let keep = 1.0 - 2.0 * a;
        let mut q = vec![0.0f64; n];
        let mut prev = 0.0;
        for i in 0..n {
            let cur = p[i];
            let next = if i + 1 < n { p[i + 1] } else { 0.0 };
            q[i] = keep * cur + a * (prev + next);
            prev = cur;
        }
        q[0] += a * p[0];
        q[n - 1] += a * p[n - 1];
        if self.lf_jump > 0.0 {
            let x = self.lf_jump * dt;
            let pj = if x < 0.5 { x } else { 0.5 };
            let mut m = 0usize;
            for i in 1..n {
                if q[i] > q[m] {
                    m = i;
                }
            }
            let mut total = 0.0;
            for i in 0..n {
                let v = (1.0 - pj) * q[i] + pj * self.lf_jump_k[if i > m { i - m } else { m - i }];
                q[i] = v;
                total += v;
            }
            let inv = 1.0 / total;
            for v in q.iter_mut() {
                *v *= inv;
            }
        }
        self.lf_p = q;
    }

    /// `_lf_recenter`: keep the grid on the bid, whole ticks, mass beyond an edge piled on it.
    fn lf_recenter(&mut self, bid: i64) {
        let n = self.lf_n;
        let shift = bid - self.lf_w - self.lf_base;
        if shift == 0 {
            return;
        }
        if shift.abs() >= n as i64 {
            self.lf_base = bid - self.lf_w;
            self.lf_p = vec![0.0; n];
            self.lf_p[self.lf_w as usize] = 1.0;
            return;
        }
        let mut q = vec![0.0f64; n];
        for i in 0..n {
            let j = (i as i64 - shift).clamp(0, n as i64 - 1) as usize;
            q[j] += self.lf_p[i];
        }
        self.lf_p = q;
        self.lf_base += shift;
    }

    /// `_lf_trade`: a market taker's filled lots move lb FILTER_IMPACT x tape_gen's table (or FILTER_SQRT_C sqrt(lots)).
    fn lf_trade(&mut self, direction: i64, lots: i64) {
        const TABLE: [(i64, f64); 8] =
            [(10, 0.097), (30, 0.111), (60, 0.161), (120, 0.254), (250, 0.349), (500, 0.468), (1000, 0.704), (1_000_000_000, 0.903)];
        let m = if self.lf_sqrt_c > 0.0 {
            self.lf_sqrt_c * (lots as f64).powf(0.5)
        } else {
            let vol = self.lf_vqs > 0.0 && self.qs_rate >= self.lf_vqs;
            let mut m = if vol && self.lf_vimpact > 0.0 { self.lf_vimpact } else { self.lf_impact };
            for (top, value) in TABLE {
                if lots <= top {
                    m *= value;
                    break;
                }
            }
            m
        };
        if m <= 0.0 {
            return;
        }
        let whole = m as i64;
        let frac = m - whole as f64;
        let n = self.lf_n;
        let top = n as i64 - 1;
        let mut q = vec![0.0f64; n];
        for i in 0..n {
            let v = self.lf_p[i];
            if v == 0.0 {
                continue;
            }
            let j = i as i64 + direction * whole;
            let k = j + direction;
            q[j.clamp(0, top) as usize] += v * (1.0 - frac);
            q[k.clamp(0, top) as usize] += v * frac;
        }
        self.lf_p = q;
    }

    /// `_lf_insert`: a new market order at `price` (the touch before it `bid`/`ask`) times its likelihood.
    fn lf_insert(&mut self, buy: bool, price: i64, bid: i64, ask: i64) {
        let n = self.lf_n;
        let base = self.lf_base;
        let eps = self.lf_eps;
        let (pi, cum) = if self.lf_vqs > 0.0 && self.qs_rate >= self.lf_vqs {
            (self.lf_vpi, self.lf_vcum)
        } else {
            (self.lf_pi, self.lf_cum)
        };
        let p = &mut self.lf_p;
        let mut total = 0.0;
        if buy {
            let clamp_at = ask - 1;
            if price >= clamp_at {
                for i in 0..n {
                    let d = base + i as i64 - clamp_at;
                    let like = if d >= 0 { eps + if d < 3 { cum[d as usize] } else { 1.0 } } else { eps };
                    let v = p[i] * like;
                    p[i] = v;
                    total += v;
                }
            } else {
                for i in 0..n {
                    let k = base + i as i64 - price;
                    let v = p[i] * if (0..3).contains(&k) { eps + pi[k as usize] } else { eps };
                    p[i] = v;
                    total += v;
                }
            }
        } else {
            let clamp_at = bid + 1;
            if price <= clamp_at {
                for i in 0..n {
                    let d = clamp_at - 1 - base - i as i64;
                    let like = if d >= 0 { eps + if d < 3 { cum[d as usize] } else { 1.0 } } else { eps };
                    let v = p[i] * like;
                    p[i] = v;
                    total += v;
                }
            } else {
                for i in 0..n {
                    let k = price - 1 - base - i as i64;
                    let v = p[i] * if (0..3).contains(&k) { eps + pi[k as usize] } else { eps };
                    p[i] = v;
                    total += v;
                }
            }
        }
        if total <= 0.0 || !total.is_finite() {
            self.lf_p = vec![1.0 / n as f64; n];
            return;
        }
        let inv = 1.0 / total;
        for v in p.iter_mut() {
            *v *= inv;
        }
        if !self.lf_bank.is_empty() {
            self.lf_ll = self.lf_ll * self.lf_ll_keep + total.ln();
        }
    }

    /// `_lf_observe`: the book's market taker fills, then its new market orders within FILTER_DEPTH of the previous
    /// valid book's touch (the cached one), in the feed's order; before quote_centres moves `known_ids` on.
    /// GASYM_US: decay each side's count and summed distance behind its own cached touch, then add the snapshot's new
    /// market orders (ids not yet in `known_ids`)
    fn gasym_observe(&mut self, snapshot: &Snapshot, now: i64) {
        let Some((bid, ask, _)) = self.cached else { return };
        if bid >= ask {
            return;
        }
        if let Some(t) = self.gasym_last {
            let d = ((-((now - t).max(0))) as f64 / self.gasym_us as f64).exp();
            for v in self.gasym.iter_mut() {
                *v *= d;
            }
        }
        self.gasym_last = Some(now);
        let mut seen: HashSet<u64> = HashSet::new();
        for side in [Side::Buy, Side::Sell] {
            for order in snapshot.side(side) {
                if order.owner != Owner::Market || !seen.insert(order.order_id) || self.known_ids.contains(&order.order_id) {
                    continue;
                }
                if order.side == Side::Buy {
                    self.gasym[0] += 1.0;
                    self.gasym[1] += (bid - order.price) as f64;
                } else {
                    self.gasym[2] += 1.0;
                    self.gasym[3] += (order.price - ask) as f64;
                }
            }
        }
    }

    fn lf_observe(&mut self, snapshot: &Snapshot, trades: &[Trade], now: i64) {
        if self.lf_ladder > 0 {
            self.lf_ladders(snapshot, now);
        }
        self.lf_observe_one(snapshot, trades, now);
        for i in 0..self.lf_bank.len() {
            self.lf_swap(i);
            self.lf_observe_one(snapshot, trades, now);
            self.lf_swap(i);
        }
    }

    /// FILTER_LADDER: mark the snapshot's new market orders that are a ladder's children (lf_skip), and remember each
    /// new order's time and whether it sits 2-7 ticks behind the cached touch
    fn lf_ladders(&mut self, snapshot: &Snapshot, now: i64) {
        self.lf_skip.clear();
        let Some((bid, ask, _)) = self.cached else { return };
        if bid >= ask {
            return;
        }
        for r in self.lf_recent.iter_mut() {
            while r.front().is_some_and(|x| x.0 < now - 3000) {
                r.pop_front();
            }
        }
        let mut seen: HashSet<u64> = HashSet::new();
        for side in [Side::Buy, Side::Sell] {
            for order in snapshot.side(side) {
                if order.owner != Owner::Market || !seen.insert(order.order_id) || self.known_ids.contains(&order.order_id) {
                    continue;
                }
                let buy = order.side == Side::Buy;
                let off = if buy { bid - order.price } else { order.price - ask };
                let band = (2..=7).contains(&off);
                let r = &mut self.lf_recent[if buy { 0 } else { 1 }];
                if band && r.iter().any(|&(t, b)| b && (now - t - 2000).abs() <= 1) {
                    self.lf_skip.insert(order.order_id);
                }
                r.push_back((now, band));
            }
        }
    }

    /// FILTER_IMP2 / 3: swap bank member i's state with the lf_* fields (twice restores both)
    fn lf_swap(&mut self, i: usize) {
        let m = &mut self.lf_bank[i];
        std::mem::swap(&mut self.lf_p, &mut m.p);
        std::mem::swap(&mut self.lf_base, &mut m.base);
        std::mem::swap(&mut self.lf_t, &mut m.t);
        std::mem::swap(&mut self.lf_impact, &mut m.impact);
        std::mem::swap(&mut self.lf_ll, &mut m.ll);
    }

    fn lf_observe_one(&mut self, snapshot: &Snapshot, trades: &[Trade], now: i64) {
        let Some((bid, ask, _)) = self.cached else { return };
        if bid >= ask {
            return;
        }
        if self.lf_p.is_empty() {
            self.lf_base = bid - self.lf_w;
            self.lf_p = vec![0.0; self.lf_n];
            self.lf_p[self.lf_w as usize] = 1.0;
        }
        let t = now as f64 * 1e-6;
        let (mut changed, mut centred) = (false, false);
        let mut lots: Vec<(u64, i64, i64)> = Vec::new();
        for trade in trades {
            if trade.taker_owner != Owner::Market {
                continue;
            }
            let direction = if trade.book_side == Side::Sell { 1 } else { -1 };
            match lots.iter_mut().find(|(id, _, _)| *id == trade.taker_order_id) {
                Some(entry) => entry.2 += trade.quantity,
                None => lots.push((trade.taker_order_id, direction, trade.quantity)),
            }
        }
        if !lots.is_empty() {
            self.lf_advance(t);
            changed = true;
            for (_, direction, quantity) in lots {
                self.lf_trade(direction, quantity);
            }
        }
        let mut seen: HashSet<u64> = HashSet::new();
        for side in [Side::Buy, Side::Sell] {
            for order in snapshot.side(side) {
                if order.owner != Owner::Market || !seen.insert(order.order_id) || self.known_ids.contains(&order.order_id) {
                    continue;
                }
                let buy = order.side == Side::Buy;
                if (order.price - if buy { bid } else { ask }).abs() > self.lf_depth {
                    continue;
                }
                if self.lf_ladder > 0 && self.lf_skip.contains(&order.order_id) {
                    continue;
                }
                if !centred {
                    if !changed {
                        self.lf_advance(t);
                    }
                    self.lf_recenter(bid);
                    changed = true;
                    centred = true;
                }
                self.lf_insert(buy, order.price, bid, ask);
            }
        }
    }

    /// `_lf_features`: gap = E[lb] + 0.5 - mid (clipped +-5), gap |gap| / 3 and min(3, the posterior sd).
    fn lf_features(&self, mid: f64) -> [f64; 3] {
        let (mut p, mut base, mut best) = (&self.lf_p, self.lf_base, self.lf_ll + self.lf_ll_margin);
        for m in &self.lf_bank {
            if self.lf_xgap == 0 && m.ll > best {
                (p, base, best) = (&m.p, m.base, m.ll);
            }
        }
        if p.is_empty() {
            return [0.0; 3];
        }
        let (mut m, mut s2) = (0.0f64, 0.0f64);
        for (i, &v) in p.iter().enumerate() {
            let fi = i as f64;
            m += v * fi;
            s2 += v * fi * fi;
        }
        let mean = base as f64 + m;
        let var = s2 - m * m;
        let sd = (if var > 0.0 { var } else { 0.0 }).powf(0.5);
        let gap = clamp(mean + 0.5 - mid, -self.lf_clip, self.lf_clip);
        [gap, gap * gap.abs() / 3.0, if sd < 3.0 { sd } else { 3.0 }]
    }

    /// ENS (R4-E1): extra `j`'s features: the first model's, with the filter's three zeroed (kind 1) or taken from
    /// FILTER_IMP2's copy (kind 2)
    fn ens_features(&self, j: usize, features: &[f64; NM], mid: f64) -> [f64; NM] {
        let mut f = *features;
        let kind = self.ens_kind[j];
        if kind == 0 {
            return f;
        }
        let k = self.n_base - self.xf_n - (3 + self.lf_xgap as usize);
        if kind == 1 {
            f[k] = 0.0;
            f[k + 1] = 0.0;
            f[k + 2] = 0.0;
            return f;
        }
        let m = &self.lf_bank[0];
        if m.p.is_empty() {
            f[k] = 0.0;
            f[k + 1] = 0.0;
            f[k + 2] = 0.0;
            return f;
        }
        let (mut e, mut s2) = (0.0f64, 0.0f64);
        for (i, &v) in m.p.iter().enumerate() {
            let fi = i as f64;
            e += v * fi;
            s2 += v * fi * fi;
        }
        let var = s2 - e * e;
        let sd = (if var > 0.0 { var } else { 0.0 }).powf(0.5);
        let gap = clamp(m.base as f64 + e + 0.5 - mid, -self.lf_clip, self.lf_clip);
        f[k] = gap;
        f[k + 1] = gap * gap.abs() / 3.0;
        f[k + 2] = if sd < 3.0 { sd } else { 3.0 };
        f
    }

    /// R4-A1: FA_LOG's line for a decision (kind 0 near the bar, 1 a take, 2 a take signal with no room)
    #[allow(clippy::too_many_arguments)]
    fn fa_write(&mut self, kind: i64, now: i64, mid: f64, spread: i64, signal: f64, need_up: f64, need_dn: f64, sign: i64, quantity: i64) {
        let res_b: i64 = self.orders.iter().filter(|r| r.sign > 0).map(|r| r.quantity).sum();
        let res_s: i64 = self.orders.iter().filter(|r| r.sign < 0).map(|r| r.quantity).sum();
        let jump = if self.ft_jump > 0.0 && now < self.ft_jump_until { self.ft_jump_sign } else { 0 };
        let lf = if self.filter > 0 { self.lf_features(mid) } else { [0.0; 3] };
        let (inv, qs, flip_age) = (self.inventory, self.qs_rate, now - self.fa_flip_t);
        if let Some(w) = self.fa_log.as_mut() {
            use std::io::Write;
            let _ = writeln!(
                w,
                "{kind},{now},{mid},{spread},{signal:.5},{need_up:.4},{need_dn:.4},{sign},{quantity},{inv},{res_b},{res_s},{qs:.4},{jump},{flip_age},{:.4},{:.4}",
                lf[0], lf[2]
            );
        }
    }

    /// R4-A1: an IOC of `quantity` at the touch `sign`'s way, as the take sends it
    fn fa_send(&mut self, now: i64, sign: i64, quantity: i64, bid: i64, ask: i64, ctx: &mut Ctx) -> u64 {
        let price = if sign > 0 { ask + self.ft_thru } else { 1i64.max(bid - self.ft_thru) };
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, true);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: now + 1_000_000, target: 0, kept: false });
        self.ft_last = now;
        id
    }

    /// ENS (R4-E1): the forecast take's two bars (up, down) as the take computes them, for a position `inventory`
    fn ens_bars(&self, mid: f64, now: i64, inventory: i64) -> (f64, f64) {
        let calm_rate = if self.ft_calm_rate > 0.0 { self.ft_calm_rate } else { self.qs_th };
        let base_edge = if self.ft_edge_calm >= 0.0 && self.qs_rate < calm_rate { self.ft_edge_calm } else { self.ft_edge };
        let (mut edge_up, mut edge_dn) = (base_edge, base_edge);
        if self.ft_edge_flip >= 0.0 {
            if inventory < 0 {
                edge_up = self.ft_edge_flip;
            }
            if inventory > 0 {
                edge_dn = self.ft_edge_flip;
            }
        }
        if self.ft_sd < 99.0 && self.filter > 0 && self.lf_features(mid)[2] >= self.ft_sd {
            edge_up = edge_up.min(self.ft_sd_edge);
            edge_dn = edge_dn.min(self.ft_sd_edge);
        }
        if self.ft_jump > 0.0 && now < self.ft_jump_until {
            if self.ft_jump_dir == 0 || self.ft_jump_dir * self.ft_jump_sign > 0 {
                edge_up = edge_up.min(self.ft_jump_edge);
            }
            if self.ft_jump_dir == 0 || self.ft_jump_dir * self.ft_jump_sign < 0 {
                edge_dn = edge_dn.min(self.ft_jump_edge);
            }
        }
        if self.ft_lgap < 99.0 && self.filter > 0 {
            let gap = self.lf_features(mid)[0];
            if gap >= self.ft_lgap {
                edge_up = edge_up.min(self.ft_lgap_edge);
            }
            if -gap >= self.ft_lgap {
                edge_dn = edge_dn.min(self.ft_lgap_edge);
            }
        }
        (edge_up, edge_dn)
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

    /// LIQ (R2-L1's `_distribution_features`, the parts its four features use): the market orders at each touch
    /// first seen at most 100 ms ago (young) and those more than 4 ticks from their touch (far); kept from the last
    /// call while it was under 5 ms ago at the same mid, first-seen times included.
    fn liquidity(&mut self, snapshot: &Snapshot, now: i64, bid: i64, ask: i64, mid: f64) {
        if let Some(t) = self.liq_time {
            if now - t < 5000 && mid == self.liq_mid {
                return;
            }
        }
        let mut seen: HashMap<u64, i64> = HashMap::with_capacity(self.liq_seen.len() + 16);
        let mut young = [0.0f64; 2];
        let mut far = [0.0f64; 2];
        for (k, side, touch) in [(0usize, Side::Buy, bid), (1usize, Side::Sell, ask)] {
            for order in snapshot.side(side) {
                if order.owner != Owner::Market {
                    continue;
                }
                let distance = (order.price - touch).abs();
                let first = *self.liq_seen.get(&order.order_id).unwrap_or(&now);
                seen.insert(order.order_id, first);
                if distance > 4 {
                    far[k] += 1.0;
                    continue;
                }
                if distance == 0 && now - first <= 100_000 {
                    young[k] += 1.0;
                }
            }
        }
        self.liq_seen = seen;
        self.liq_young = (young[0] - young[1]) / (1.0 + young[0] + young[1]);
        let count = far[0] + far[1];
        let e = (if count < 100.0 { count } else { 100.0 }) / 10.0;
        self.liq_disp = if e < 3.0 { e } else { 3.0 };
        self.liq_time = Some(now);
        self.liq_mid = mid;
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
        let mut behind = 0usize;
        let l2_price = if self.l2_lots > 0 { price.map(|p| p - sign) } else { None };
        for index in 0..self.orders.len() {
            if self.orders[index].sign != sign {
                continue;
            }
            if l2_price.is_some() && Some(self.orders[index].price) == l2_price && now >= self.orders[index].exempt_until {
                // R2-S: up to L2_ORDERS orders one tick behind the desired price rest there, each shrunk to
                // L2_LOTS (an old touch order a tick back included), not counted in MAX_ORDERS; the rest cancelled
                let r = &self.orders[index];
                if !r.cancelling && r.accepted && self.hedge_id != Some(r.id) && behind < self.l2_orders {
                    let (id, quantity, target) = (r.id, r.quantity, r.target);
                    if quantity > self.l2_lots && (target == 0 || target > self.l2_lots) {
                        ctx.modify_order(id, self.l2_lots);
                        self.orders[index].target = self.l2_lots;
                    }
                    self.orders[index].kept = false;
                    behind += 1;
                } else if !r.accepted && !r.cancelling && r.quantity <= self.l2_lots && behind < self.l2_orders {
                    // a slice of ours still in flight
                    behind += 1;
                } else {
                    self.cancel(index, ctx);
                }
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
        for _ in 0..self.burst {
            if !self.place(now, sign, price, current, l2_price, ctx) {
                break;
            }
            current += 1;
        }
        if let Some(p2) = l2_price {
            if behind < self.l2_orders && p2 > 0 && now - self.l2_last[side_index(sign)] >= self.slice_us {
                self.place_behind(now, sign, p2, ctx);
            }
        }
    }

    /// R2-S: one L2_LOTS slice one tick behind the desired price, within the limit (and EXPOSURE unless L2_FREE)
    fn place_behind(&mut self, now: i64, sign: i64, price: i64, ctx: &mut Ctx) {
        let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
        let mut quantity = self.l2_lots.min(self.position_limit - sign * self.inventory - reserved);
        if !self.l2_free {
            let effective: i64 = self
                .orders
                .iter()
                .filter(|r| r.sign == sign)
                .map(|r| if r.cancelling { (r.quantity as f64 * (1.0 - self.cancel_free)).ceil() as i64 } else { r.quantity })
                .sum();
            quantity = quantity.min(self.exposure - sign * self.inventory - effective);
        }
        if quantity <= 0 {
            return;
        }
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, false);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: 0, target: 0, kept: false });
        self.l2_last[side_index(sign)] = now;
    }

    /// the quoting's new order at `price` (one call, one order): whether one was sent
    fn place(&mut self, now: i64, sign: i64, price: Option<i64>, current: usize, l2_price: Option<i64>, ctx: &mut Ctx) -> bool {
        if current >= self.max_orders {
            return false;
        }
        if self.keep_noback && self.orders.iter().any(|r| r.sign == sign && r.kept && !r.cancelling) {
            return false;
        }
        let Some(price) = price else { return false };
        if price <= 0 || now - self.last_action[side_index(sign)] < self.requote_us {
            return false;
        }
        if self.slice_lots > 0
            && now - self.last_action[side_index(sign)] < self.slice_us
            && self.orders.iter().any(|r| r.sign == sign && r.price == price && !r.cancelling)
        {
            return false;
        }
        let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
        let free_behind = self.l2_free && l2_price.is_some();
        let effective: i64 = self
            .orders
            .iter()
            .filter(|r| r.sign == sign && !(free_behind && Some(r.price) == l2_price))
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
        // QS_RATE (L8): one quote size only while the decayed |mid change| rate is below QS_RATE, else none
        let size = if self.qs_th > 0.0 && !(self.qs_rate < self.qs_th) { 0 } else { self.quote_size };
        let mut quantity = size
            .min(if self.conf_exp > 0 { self.side_exp[side_index(sign)] } else { self.exposure } - sign * self.inventory - effective)
            .min(self.position_limit - sign * self.inventory - reserved);
        if self.slice_lots > 0 {
            quantity = quantity.min(self.slice_lots);
        }
        if quantity <= 0 {
            return false;
        }
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, false);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: 0, target: 0, kept: false });
        self.last_action[side_index(sign)] = now;
        true
    }

    /// v2's `_hedge`: an IOC for |inventory| - EXPOSURE, HEDGE_TICKS through the cached touch, one at a time.
    fn hedge(&mut self, now: i64, ctx: &mut Ctx) {
        // VOL_NOHEDGE: the hedge keeps EXPOSURE's level when the scaled exposure is below it
        let exposure = if self.vol_nohedge && self.vol_exp != 0.0 { self.exposure.max(self.exposure_base) } else { self.exposure };
        // BURST: the burst's side keeps up to BURST_EXP until the burst ends
        let exposure = if now < self.burst_until && self.inventory * self.burst_sign > 0 { exposure.max(self.burst_exp) } else { exposure };
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
        if self.impact_us > 0 {
            // L9's `_impact_features`, at every book (an invalid one too): the market takers' lots over IMPACT_US
            let (mut net, mut volume) = (0i64, 0i64);
            for trade in trades {
                if trade.taker_owner == Owner::Market {
                    net += if trade.book_side == Side::Sell { trade.quantity } else { -trade.quantity };
                    volume += trade.quantity;
                }
            }
            let d = ((-elapsed) as f64 / self.impact_us as f64).exp();
            self.impact_net = self.impact_net * d + net as f64;
            self.impact_vol = self.impact_vol * d + volume as f64;
            let (signed, gross) = (self.impact_net, self.impact_vol);
            let g = gross / 500.0;
            let g = if g < 9.0 { g } else { 9.0 };
            self.impact_frame = [clamp(signed / 500.0, -3.0, 3.0), signed / (1.0 + gross) * g.powf(0.5)];
        }
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
        if self.gasym_us > 0 {
            self.gasym_observe(snapshot, now);
        }
        if self.filter > 0 {
            self.lf_observe(snapshot, trades, now);
        }
        if self.quotefeat > 0 {
            self.quote_centres(snapshot, trades, now, bid, ask);
        }
        let mid = (bid + ask) as f64 * 0.5;
        if self.qs_th > 0.0 {
            // L8: the |mid change| ticks a second, decayed over QS_US, at every valid book
            if let Some((t, m)) = self.qs_last {
                let k = ((-((now - t).max(0))) as f64 / self.qs_us as f64).exp();
                self.qs_rate = self.qs_rate * k + (mid - m).abs() / (self.qs_us as f64 / 1e6);
            }
            self.qs_last = Some((now, mid));
        }
        if self.burst_speed > 0.0 {
            // BURST_SPEED: the |mid change| ticks a second, decayed over BURST_SPEED_US, at every valid book (L8's rate)
            if let Some((t, m)) = self.burst_rate_last {
                let k = ((-((now - t).max(0))) as f64 / self.burst_speed_us as f64).exp();
                self.burst_rate = self.burst_rate * k + (mid - m).abs() / (self.burst_speed_us as f64 / 1e6);
            }
            self.burst_rate_last = Some((now, mid));
        }
        if self.ft_jump > 0.0 {
            // FT_JUMP (R3-F5): the mid at least FT_JUMP ticks from the oldest mid within FT_JUMP_MS opens FT_JUMP_HOLD_MS
            // of the take bar FT_JUMP_EDGE
            self.ft_jump_mids.push_back((now, mid));
            while let Some(&(t, _)) = self.ft_jump_mids.front() {
                if t < now - self.ft_jump_ms * 1000 {
                    self.ft_jump_mids.pop_front();
                } else {
                    break;
                }
            }
            if let Some(&(_, m)) = self.ft_jump_mids.front() {
                if (mid - m).abs() >= self.ft_jump {
                    self.ft_jump_until = now + self.ft_jump_hold_ms * 1000;
                    self.ft_jump_sign = if mid > m { 1 } else { -1 };
                }
            }
        }
        if self.ft_ws_edge >= 0.0 && self.ft_ws_jump > 0.0 {
            // R4-X1: the mid at least FT_WS_JUMP ticks from the oldest mid within FT_WS_JUMP_MS opens FT_WS_MS of the
            // reversal bar
            self.ws_mids.push_back((now, mid));
            while let Some(&(t, _)) = self.ws_mids.front() {
                if t < now - self.ft_ws_jump_ms * 1000 {
                    self.ws_mids.pop_front();
                } else {
                    break;
                }
            }
            if let Some(&(_, m)) = self.ws_mids.front() {
                if (mid - m).abs() >= self.ft_ws_jump {
                    self.ws_until = now + self.ft_ws_ms * 1000;
                    self.ws_sign = if mid > m { 1 } else { -1 };
                }
            }
        }
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
        // LIQ's four and IMPACT_US's three sit just before TREND's two, then FILTER's three end the base features
        let filter_n = if self.filter > 0 { 3 + self.lf_xgap as usize } else { 0 };
        let trend_n = filter_n + if self.trend > 0 { 2 } else { 0 };
        let tail = trend_n + if self.impact_us > 0 { 3 } else { 0 };
        if self.liq > 0 {
            self.liquidity(snapshot, now, bid, ask, mid);
            let k = self.n_base - self.xf_n - tail - 4;
            let (young, dispersion) = (self.liq_young, self.liq_disp);
            features[k] = young;
            features[k + 1] = young * dispersion;
            features[k + 2] = flow * dispersion;
            features[k + 3] = count_imbalance * dispersion;
        }
        if self.impact_us > 0 {
            let k = self.n_base - self.xf_n - trend_n - 3;
            features[k] = self.impact_frame[0];
            features[k + 1] = self.impact_frame[1];
            let far = if self.impact_net >= 0.0 { aq } else { bq };
            features[k + 2] = clamp(self.impact_net / (1 + far) as f64, -3.0, 3.0);
        }
        if self.trend > 0 {
            let k = self.n_base - self.xf_n - filter_n - 2;
            features[k] = clamp(mid - self.trend_e[0], -20.0, 20.0);
            features[k + 1] = clamp(mid - self.trend_e[1], -20.0, 20.0);
        }
        if self.filter > 0 {
            let k = self.n_base - self.xf_n - filter_n;
            let f = self.lf_features(mid);
            self.lf_gap_now = f[0];
            features[k] = f[0];
            features[k + 1] = f[1];
            features[k + 2] = f[2];
            if self.lf_xgap > 0 {
                let m = &self.lf_bank[0];
                let mut gap = 0.0;
                if !m.p.is_empty() {
                    let mut e = 0.0f64;
                    for (i, &v) in m.p.iter().enumerate() {
                        e += v * i as f64;
                    }
                    gap = clamp(m.base as f64 + e + 0.5 - mid, -5.0, 5.0);
                }
                features[k + 3] = gap;
                if self.lf_xgap > 1 {
                    features[k + 4] = gap * gap.abs() / 3.0;
                }
            }
        }
        if self.xf_n > 0 {
            let mut k = self.n_base - self.xf_n;
            if self.gasym_us > 0 {
                let [nb, ob, na, oa] = self.gasym;
                features[k] = if nb >= 0.5 && na >= 0.5 { clamp(oa / na - ob / nb, -5.0, 5.0) } else { 0.0 };
                k += 1;
            }
            if self.gapmean_us > 0 {
                let d = match self.gapmean_last {
                    Some(t) => ((-((now - t).max(0))) as f64 / self.gapmean_us as f64).exp(),
                    None => 0.0,
                };
                self.gapmean_last = Some(now);
                self.gapmean = self.gapmean * d + (1.0 - d) * self.lf_gap_now;
                features[k] = self.gapmean;
            }
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
        if self.feat_log.is_some() {
            self.fx.update(now, bid, ask, trades);
        }
        self.learn(0, now, mid);
        let m2_on = self.blend_w > 0.0 || (self.lean_k != 0.0 && self.lean_src == 0) || self.ft_src == 1;
        if m2_on {
            self.learn(1, now, mid);
        }
        if self.side2 > 0 {
            self.learn(2, now, bid as f64);
            self.learn(3, now, ask as f64);
        }
        // R4-M1 (MOE): the experts learn, and the active regime's gets this book's observation
        let moe_base = if self.moe.is_some() { clamp(Moe::dot(&self.m1.weights, &features, n), -2.0, 2.0) } else { 0.0 };
        let moe_sd = if self.moe.as_ref().is_some_and(|m| m.gate == 5) { self.lf_features(mid)[2] } else { 0.0 };
        let moe_k = self
            .moe
            .as_ref()
            .map(|m| m.regime(spread, self.qs_th > 0.0 && !(self.qs_rate < self.qs_th), moe_base, moe_sd));
        if let (Some(moe), Some(k)) = (self.moe.as_mut(), moe_k) {
            moe.learn(now, mid, n);
            if now - self.last_observation_us >= self.observation_interval_us {
                moe.observe(k, now, mid, &features, n, moe_base);
            }
        }
        for j in 0..self.ens_models.len() {
            self.learn(100 + j, now, mid);
        }
        if now - self.last_observation_us >= self.observation_interval_us {
            for j in 0..self.ens_models.len() {
                let fj = self.ens_features(j, &features, mid);
                let huber = self.huber;
                let cap = self.obs_cap;
                let changes = self.mid_changes;
                let m = &mut self.ens_models[j];
                if m.observations.len() >= cap {
                    m.observations.pop_front();
                }
                let stored = if huber > 0.0 {
                    clamp(py_sum(m.weights[..n].iter().zip(fj[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0)
                } else {
                    0.0
                };
                m.observations.push_back((now, mid, fj, changes, stored));
            }
            if self.label_mode == 0 && self.m1.observations.len() >= self.obs_cap {
                self.m1.observations.pop_front();
            }
            // HUBER: the forecast with the weights as they stand, stored with the observation (L9's stored_forecast)
            let stored = if self.huber > 0.0 {
                clamp(py_sum(self.m1.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0)
            } else {
                0.0
            };
            self.m1.observations.push_back((now, mid, features, self.mid_changes, stored));
            if self.feat_log.is_some() {
                let extra = self.fx.features(now, snapshot, bid, ask, &self.lf_p, self.lf_base);
                self.feat_pending.push_back((now, self.inventory as f64, extra));
            }
            if m2_on {
                if self.m2.observations.len() >= self.obs_cap {
                    self.m2.observations.pop_front();
                }
                self.m2.observations.push_back((now, mid, features, self.mid_changes, 0.0));
            }
            if self.side2 > 0 {
                for (j, v) in [(0usize, bid as f64), (1, ask as f64)] {
                    if self.ex[j].observations.len() >= self.obs_cap {
                        self.ex[j].observations.pop_front();
                    }
                    self.ex[j].observations.push_back((now, v, features, self.mid_changes, 0.0));
                }
            }
            if self.mh > 0 {
                for j in [2usize, 3] {
                    if self.ex[j].observations.len() >= self.obs_cap {
                        self.ex[j].observations.pop_front();
                    }
                    self.ex[j].observations.push_back((now, mid, features, self.mid_changes, 0.0));
                }
            }
            self.last_observation_us = now;
        }
        if self.dump_us > 0 && self.dump_snap.is_none() && now >= self.dump_us {
            self.dump_snap = Some(self.stats_text());
        }
        let mut prediction = 0.25 * spread_f * imbalance;
        // FT_CLAMP (R4-X1): the take's own clamp of the first model's forecast (the stored forecast stays at +-2)
        let mut take_wide: Option<f64> = None;
        if self.m1.labels >= self.min_labels {
            let raw = py_sum(self.m1.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x));
            prediction = clamp(if self.pred_scale != 1.0 { raw * self.pred_scale } else { raw }, -2.0, 2.0);
            if self.ft_clamp != 2.0 && self.blend_w <= 0.0 && self.moe.is_none() {
                take_wide = Some(clamp(if self.pred_scale != 1.0 { raw * self.pred_scale } else { raw }, -self.ft_clamp, self.ft_clamp));
            }
            if self.blend_w > 0.0 && self.m2.labels >= self.min_labels {
                let p2 =
                    clamp(py_sum(self.m2.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0);
                prediction = (1.0 - self.blend_w) * prediction + self.blend_w * p2;
            }
        }
        if let (Some(moe), Some(k)) = (self.moe.as_mut(), moe_k) {
            prediction = moe.predict(k, &features, n, prediction);
        }
        // the second model's own forecast (LEAN_SRC 0, FT_SRC 1)
        let p2_only = if m2_on && self.m2.labels >= self.min_labels {
            clamp(py_sum(self.m2.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0)
        } else {
            0.0
        };
        // ENS (R4-E1): each forecaster's paper position under the take rule, marked to the mid net of half the spread
        // a paper trade, its PnL decayed over ENS_W_S; the take follows the leader (1), the Hedge weights (2) or a vote (3)
        let ens_n = 1 + self.ens_models.len();
        let mut ens_preds = [0.0f64; 8];
        let mut ens_src: Option<f64> = None;
        if self.ens > 0 {
            ens_preds[0] = prediction;
            for j in 0..self.ens_models.len() {
                let m = &self.ens_models[j];
                ens_preds[1 + j] = if self.m1.labels >= self.min_labels && m.labels >= self.min_labels {
                    let fj = self.ens_features(j, &features, mid);
                    clamp(py_sum(m.weights[..n].iter().zip(fj[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0)
                } else {
                    prediction
                };
            }
            if let Some((t, m0)) = self.ens_last {
                let dt = (now - t).max(0) as f64;
                let d = (-dt / self.ens_w_us).exp();
                let dmid = mid - m0;
                for k in 0..ens_n {
                    self.ens_score[k] = self.ens_score[k] * d + self.ens_pos[k] as f64 * dmid;
                }
                self.ens_lead_t[self.ens_leader] += dt;
            }
            self.ens_last = Some((now, mid));
            if self.m1.labels >= self.min_labels && (self.ft_maxspread <= 0 || spread <= self.ft_maxspread) {
                let e = self.exposure;
                for k in 0..ens_n {
                    let pos = self.ens_pos[k];
                    let (eu, ed) = self.ens_bars(mid, now, pos);
                    let pskew = self.skew_k * pos as f64 / e as f64 * spread_f.max(1.0);
                    let sig = ens_preds[k] - pskew;
                    let target = if sig > eu + 0.5 * spread_f {
                        e
                    } else if sig < -(ed + 0.5 * spread_f) {
                        -e
                    } else {
                        pos
                    };
                    if target != pos {
                        self.ens_score[k] -= 0.5 * spread_f * (target - pos).abs() as f64;
                        self.ens_pos[k] = target;
                        self.ens_paper_trades[k] += 1;
                    }
                }
            }
            // the leader: switches only past ENS_MARGIN
            let mut best = self.ens_leader;
            for k in 0..ens_n {
                if self.ens_score[k] > self.ens_score[best] {
                    best = k;
                }
            }
            if best != self.ens_leader && self.ens_score[best] > self.ens_score[self.ens_leader] + self.ens_margin {
                self.ens_leader = best;
                self.ens_switches += 1;
            }
            if self.ens == 1 {
                ens_src = Some(ens_preds[self.ens_leader]);
            } else if self.ens == 2 {
                let top = self.ens_score[..ens_n].iter().cloned().fold(f64::MIN, f64::max);
                let (mut wsum, mut psum) = (0.0f64, 0.0f64);
                for k in 0..ens_n {
                    let w = (self.ens_eta * (self.ens_score[k] - top)).exp();
                    wsum += w;
                    psum += w * ens_preds[k];
                }
                ens_src = Some(psum / wsum);
            }
        }
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
        if self.qs_pull && self.qs_th > 0.0 && !(self.qs_rate < self.qs_th) {
            buy = None;
            sell = None;
        }
        if self.quote_gap < 99.0 {
            if self.lf_gap_now < -self.quote_gap {
                buy = None;
            }
            if self.lf_gap_now > self.quote_gap {
                sell = None;
            }
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
                if std::env::var("RIDGE_PRED_EXTRA").is_ok() {
                    // the audit (8 Nov): the filter's gap and QS_RATE's speed as two more columns
                    let _ = writeln!(w, "{},{},{},{},{},{},{},{}", now, mid, prediction, skew, spread, self.inventory,
                                     self.lf_gap_now, self.qs_rate);
                } else {
                    let _ = writeln!(w, "{},{},{},{},{},{}", now, mid, prediction, skew, spread, self.inventory);
                }
            }
        }
        // BURST (R3-J1): a forecast of BURST_TH or more starts a burst of BURST_MS on its side, the take's room there
        // BURST_EXP lots (over the 100-lot limit: the penalty), the hedge holding off that side until it ends
        let mut burst_new = false;
        // the jump triggers: BURST_JUMP, the mid's move since the last valid book; BURST_QUIET_MS, the first market
        // trade after that long without one while the spread before it was at least BURST_SPREAD (its aggressor's side)
        let jump_mode = self.burst_jump > 0.0 || self.burst_quiet_ms > 0;
        let mut jump_sign = 0i64;
        if jump_mode {
            if self.burst_jump > 0.0 {
                // BURST_JUMP_MS (0: since the last valid book): the move from the oldest mid within that window
                let base = if self.burst_jump_ms > 0 {
                    self.burst_mids.push_back((now, mid));
                    while let Some(&(t, _)) = self.burst_mids.front() {
                        if t < now - self.burst_jump_ms * 1000 {
                            self.burst_mids.pop_front();
                        } else {
                            break;
                        }
                    }
                    self.burst_mids.front().map(|&(_, m)| m)
                } else {
                    self.burst_prev_mid
                };
                if let Some(m) = base {
                    if (mid - m).abs() >= self.burst_jump {
                        jump_sign = if mid > m { 1 } else { -1 };
                    }
                }
            }
            if let Some(trade) = trades.iter().find(|t| t.taker_owner == Owner::Market) {
                if self.burst_quiet_ms > 0 && now - self.burst_trade_last >= self.burst_quiet_ms * 1000 && self.burst_prev_spread >= self.burst_spread {
                    jump_sign = if trade.book_side == Side::Sell { 1 } else { -1 };
                }
                self.burst_trade_last = now;
            }
            self.burst_prev_mid = Some(mid);
            self.burst_prev_spread = spread;
        }
        if (self.burst_th > 0.0 || jump_mode) && self.ft_sz > 0 && self.m1.labels >= self.min_labels {
            let source = if self.ft_src == 1 { p2_only } else { prediction };
            let signal = if self.ft_net > 0 { source - skew } else { source };
            if now < self.burst_until && self.burst_sign as f64 * signal < self.burst_hold {
                // BURST_HOLD: the forecast its way fell below it, the burst ends (the hedge brings the position back)
                self.burst_until = now;
            }
            if now >= self.burst_until && now - self.burst_last >= self.burst_gap_ms * 1000 {
                let start = if jump_mode {
                    // BURST_AGREE: the forecast the jump's way at least this (-99: any)
                    if jump_sign != 0 && jump_sign as f64 * signal >= self.burst_agree && (self.burst_quiet_ms > 0 || spread >= self.burst_spread) {
                        jump_sign
                    } else {
                        0
                    }
                } else if signal.abs() >= self.burst_th
                    && spread >= self.burst_spread
                    && (self.burst_speed <= 0.0 || self.burst_rate >= self.burst_speed)
                {
                    if signal > 0.0 { 1 } else { -1 }
                } else {
                    0
                };
                if start != 0 {
                    self.burst_sign = start;
                    self.burst_until = now + self.burst_ms * 1000;
                    self.burst_last = now;
                    self.burst_n += 1;
                    burst_new = true;
                    if jump_mode {
                        // the jump's take: an IOC BURST_THRU through the far touch for the burst's room, whatever the forecast
                        let pos = start * self.inventory;
                        let reserved: i64 = self.orders.iter().filter(|r| r.sign == start).map(|r| r.quantity).sum();
                        let size = if self.burst_sz > 0 { self.burst_sz } else { self.burst_exp };
                        let quantity = size.min(self.burst_exp - pos - reserved);
                        if quantity > 0 {
                            self.burst_lots += quantity;
                            let price = if start > 0 { ask + self.burst_thru } else { 1i64.max(bid - self.burst_thru) };
                            let id = ctx.send_order(if start > 0 { Side::Buy } else { Side::Sell }, price, quantity, true);
                            self.orders.push(Record {
                                id,
                                sign: start,
                                price,
                                quantity,
                                accepted: false,
                                cancelling: false,
                                exempt_until: now + 1_000_000,
                                target: 0,
                                kept: false,
                            });
                            self.ft_last = now;
                            burst_new = false;
                        }
                    }
                }
            }
        }
        // R4-C1 (calib.rs, off by default): its matured labels learned, then an observation of the take's forecast
        let cal_x = if self.cal.mode > 0 && self.m1.labels >= self.min_labels {
            let source = if let Some(src) = ens_src {
                src
            } else if self.ft_src == 1 {
                p2_only
            } else if self.cal.raw {
                py_sum(self.m1.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x))
            } else {
                prediction
            };
            self.cal.observe(now, mid, source, self.qs_rate);
            source
        } else {
            prediction
        };
        // R4-PG (profit_gate.rs, off by default): its matured labels learned, then an observation at the take's signal
        let pg_w = ProfitGate::width(n);
        let pg_jump = self.ft_jump > 0.0 && now < self.ft_jump_until;
        let pg_inv = self.inventory as f64 / self.exposure.max(1) as f64;
        if self.pg.mode > 0 {
            self.pg.learn(now, mid, pg_w);
            let source = if self.ft_src == 1 { p2_only } else { prediction };
            let signal = if self.ft_net > 0 { source - skew } else { source };
            let d = if signal > 0.0 { 1.0 } else { -1.0 };
            let g = ProfitGate::feats(&features[..n], d, signal, 0.5 * spread_f, pg_inv, pg_jump);
            self.pg.observe(now, mid, signal, 0.5 * spread_f, g);
        }
        let bursting = now < self.burst_until;
        let ft_maxspread = if bursting && self.burst_maxspread > 0 { self.burst_maxspread } else { self.ft_maxspread };
        // R4-X1: the forecast's sign changes (FT_WS_FLIP_MS), at every book
        if self.ft_ws_edge >= 0.0 && self.ft_ws_flip_ms > 0 {
            let s = if prediction > 0.0 { 1 } else if prediction < 0.0 { -1 } else { 0 };
            if s != 0 {
                if self.ws_pred_sign != 0 && s != self.ws_pred_sign {
                    self.ws_flip_t = now;
                }
                self.ws_pred_sign = s;
            }
        }
        // R4-A1: FA_LOG's forecast sign changes, at every book
        if self.fa_log.is_some() {
            let s = if prediction > 0.0 { 1 } else if prediction < 0.0 { -1 } else { 0 };
            if s != 0 {
                if self.fa_pred_sign != 0 && s != self.fa_pred_sign {
                    self.fa_flip_t = now;
                }
                self.fa_pred_sign = s;
            }
        }
        // R4-A1 COMPLETE: the armed take's unfilled rest at once, at the touch, within the take's room
        if let Some((s, lots)) = self.fa_rest.take() {
            let pos = s * self.inventory;
            let reserved: i64 = self.orders.iter().filter(|r| r.sign == s).map(|r| r.quantity).sum();
            let quantity = lots.min(self.exposure - pos - reserved).min(self.position_limit - pos - reserved);
            if quantity > 0 {
                self.fa_send(now, s, quantity, bid, ask, ctx);
            }
        }
        // FT_WIDE_SPREAD (R4-X1): takes also at spreads up to it, at the bar FT_WIDE_EDGE from 2 ticks
        let wide =self.ft_wide_spread > 0 && spread >= 2 && spread <= self.ft_wide_spread;
        if self.ft_sz > 0
            && self.m1.labels >= self.min_labels
            && (now - self.ft_last >= self.ft_gap_ms * 1000 || burst_new)
            && (ft_maxspread <= 0 || spread <= ft_maxspread || wide)
        {
            let take_pred = take_wide.unwrap_or(prediction);
            let source = if let Some(src) = ens_src { src } else if self.ft_src == 1 { p2_only } else { take_pred };
            let source = if self.cal.mode > 0 { self.cal.apply(cal_x, self.qs_rate) } else { source };
            let signal = if self.ft_net > 0 { source - skew } else { source };
            // R3-F5 (off by default): each side's bar is the lowest of FT_EDGE, FT_JUMP_EDGE within FT_JUMP_HOLD_MS of
            // a jump, and FT_LGAP_EDGE while the filter's gap that way is at least FT_LGAP
            // FT_EDGE_CALM: the bar in its place while L8's |mid change| rate is below FT_CALM_RATE (0: QS_RATE)
            let calm_rate = if self.ft_calm_rate > 0.0 { self.ft_calm_rate } else { self.qs_th };
            let base_edge = if self.ft_edge_calm >= 0.0 && self.qs_rate < calm_rate { self.ft_edge_calm } else { self.ft_edge };
            let (mut edge_up, mut edge_dn) = (base_edge, base_edge);
            // FT_EDGE_FLIP (R3-P1): the base bar of a take against the position (a reduce or a flip)
            if self.ft_edge_flip >= 0.0 {
                if self.inventory < 0 {
                    edge_up = self.ft_edge_flip;
                }
                if self.inventory > 0 {
                    edge_dn = self.ft_edge_flip;
                }
            }
            // FT_SD (R3-P1): the bar at most FT_SD_EDGE while the latent filter's posterior sd is at least FT_SD
            if self.ft_sd < 99.0 && self.filter > 0 && self.lf_features(mid)[2] >= self.ft_sd {
                edge_up = edge_up.min(self.ft_sd_edge);
                edge_dn = edge_dn.min(self.ft_sd_edge);
            }
            if self.ft_jump > 0.0 && now < self.ft_jump_until {
                // FT_JUMP_DIR: 0 both sides, 1 only the jump's way, -1 only against it
                if self.ft_jump_dir == 0 || self.ft_jump_dir * self.ft_jump_sign > 0 {
                    edge_up = edge_up.min(self.ft_jump_edge);
                }
                if self.ft_jump_dir == 0 || self.ft_jump_dir * self.ft_jump_sign < 0 {
                    edge_dn = edge_dn.min(self.ft_jump_edge);
                }
            }
            if self.ft_lgap < 99.0 && self.filter > 0 {
                let gap = self.lf_features(mid)[0];
                if gap >= self.ft_lgap {
                    edge_up = edge_up.min(self.ft_lgap_edge);
                }
                if -gap >= self.ft_lgap {
                    edge_dn = edge_dn.min(self.ft_lgap_edge);
                }
            }
            // R4-PG's vote (PG 2): each side's bar lowered by PG_K * (the gate's prediction that way - PG_G), floor 0
            if self.pg.mode == 2 && self.pg.ready() {
                let hs = 0.5 * spread_f;
                let up = self.pg.predict(&ProfitGate::feats(&features[..n], 1.0, signal, hs, pg_inv, pg_jump), pg_w);
                let dn = self.pg.predict(&ProfitGate::feats(&features[..n], -1.0, signal, hs, pg_inv, pg_jump), pg_w);
                edge_up = (edge_up - self.pg.k * (up - self.pg.g)).max(0.0);
                edge_dn = (edge_dn - self.pg.k * (dn - self.pg.g)).max(0.0);
            }
            if wide {
                edge_up = self.ft_wide_edge;
                edge_dn = self.ft_wide_edge;
            }
            // FT_WS_EDGE (R4-X1): within FT_WS_MS of a FT_WS_JUMP-tick move (FT_WS_JUMP 0: always), and while the
            // forecast changed sign within FT_WS_FLIP_MS (0: always), a take against the held position needs at least
            // FT_WS_EDGE; adding or opening from flat keeps its bar
            let (base_up, base_dn) = (edge_up, edge_dn);
            if self.ft_ws_edge >= 0.0
                && self.inventory != 0
                && (self.ft_ws_jump <= 0.0 || now < self.ws_until)
                && (self.ft_ws_flip_ms <= 0 || now - self.ws_flip_t <= self.ft_ws_flip_ms * 1000)
                && (self.ft_ws_dir == 0 || self.ft_ws_dir * self.ws_sign * self.inventory.signum() > 0)
            {
                if self.inventory < 0 {
                    edge_up = edge_up.max(self.ft_ws_edge);
                } else {
                    edge_dn = edge_dn.max(self.ft_ws_edge);
                }
            }
            let need_up = edge_up + 0.5 * spread_f;
            let need_dn = edge_dn + 0.5 * spread_f;
            let sign = if signal > need_up {
                1
            } else if signal < -need_dn {
                -1
            } else {
                0
            };
            // FT_WS_FLAT 1: a reversal under the raised bar but over its own goes to flat only
            let base_sign = if signal > base_up + 0.5 * spread_f {
                1
            } else if signal < -(base_dn + 0.5 * spread_f) {
                -1
            } else {
                0
            };
            let ws_flat_only = sign == 0 && base_sign != 0 && self.ft_ws_flat;
            let sign = if ws_flat_only { base_sign } else { sign };
            if self.ws_stats.is_some() && sign == 0 && base_sign != 0 {
                self.ws_count[3] += 1;
            }
            // ENS 3 (R4-E1): a take only when most forecasters clear the bar its way
            let sign = if self.ens == 3 {
                let (mut up, mut dn) = (0usize, 0usize);
                for k in 0..ens_n {
                    let s = if self.ft_net > 0 { ens_preds[k] - skew } else { ens_preds[k] };
                    if s > need_up {
                        up += 1;
                    } else if s < -need_dn {
                        dn += 1;
                    }
                }
                if 2 * up > ens_n {
                    1
                } else if 2 * dn > ens_n {
                    -1
                } else {
                    0
                }
            } else {
                sign
            };
            let need = if sign < 0 { need_dn } else { need_up };
            // R4-PG: a take signal closes PG_HOLD's observations the other way; the gate (PG 1) vetoes a take whose
            // predicted net is not above PG_G
            if sign != 0 {
                self.pg.on_signal(sign, mid);
            }
            let sign = if sign != 0 && self.pg.mode == 1 && self.pg.ready() {
                let g = ProfitGate::feats(&features[..n], sign as f64, signal, 0.5 * spread_f, pg_inv, pg_jump);
                if self.pg.predict(&g, pg_w) > self.pg.g {
                    sign
                } else {
                    self.pg.vetoes += 1;
                    0
                }
            } else {
                sign
            };
            // R4-A1 (FA_ACT 2 / 3): the forced action at the first decision at or after FA_T
            let f5_sign = sign;
            let sign = if (self.fa_act == 2 || self.fa_act == 3) && !self.fa_done && now >= self.fa_t {
                self.fa_done = true;
                if self.fa_act == 2 {
                    if sign != 0 {
                        sign
                    } else if signal > 0.0 {
                        1
                    } else if signal < 0.0 {
                        -1
                    } else {
                        0
                    }
                } else {
                    if self.inventory != 0 {
                        let s = -self.inventory.signum();
                        let reserved: i64 = self.orders.iter().filter(|r| r.sign == s).map(|r| r.quantity).sum();
                        let quantity = self.inventory.abs() - reserved;
                        if quantity > 0 {
                            self.fa_send(now, s, quantity, bid, ask, ctx);
                        }
                    }
                    0
                }
            } else {
                sign
            };
            let fa_logging = self.fa_log.is_some();
            if fa_logging && sign == 0 && (signal > need_up - 0.3 || signal < 0.3 - need_dn) && now - self.fa_log_last >= 100_000 {
                self.fa_log_last = now;
                self.fa_write(0, now, mid, spread, signal, need_up, need_dn, f5_sign, 0);
            }
            if sign != 0 {
                let pos = sign * self.inventory;
                // a burst on this side: BURST_EXP is the exposure and the limit, BURST_SZ (0: BURST_EXP) the take's lots
                let big = bursting && sign == self.burst_sign;
                let exposure = if big { self.burst_exp } else { self.exposure };
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
                            exposure - pos
                        } else {
                            0
                        }
                    }
                    _ => exposure - pos,
                };
                let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
                // FT_ROOM_LIVE (T2): every live same-side order can fill first, so it comes off the room
                let room = if self.ft_room_live { room - reserved } else { room };
                let (size, limit, thru) = if big {
                    (if self.burst_sz > 0 { self.burst_sz } else { self.burst_exp }, self.burst_exp.max(self.position_limit), self.burst_thru)
                } else {
                    (self.ft_sz, self.position_limit, self.ft_thru)
                };
                let mut quantity = size.min(room).min(limit - pos - reserved);
                // FT_FLIP_M (R3-F5): from a position against the take, past flat only when the signal clears its bar
                // by FT_FLIP_M
                if self.ft_flip_m < 99.0 && pos < 0 && signal * (sign as f64) < need + self.ft_flip_m {
                    quantity = quantity.min(-pos - reserved);
                }
                if ws_flat_only {
                    quantity = quantity.min(-pos - reserved);
                }
                if fa_logging {
                    if quantity > 0 {
                        self.fa_write(1, now, mid, spread, signal, need_up, need_dn, sign, quantity);
                    } else if now - self.fa_log_last >= 100_000 {
                        self.fa_log_last = now;
                        self.fa_write(2, now, mid, spread, signal, need_up, need_dn, sign, quantity);
                    }
                }
                // R4-A1's rule FT_CONFIRM: a fresh take in the rule's states deferred once, sent at a later decision
                // within FT_CONFIRM_MS if the signal still clears the bar its way
                if quantity > 0 && self.ft_confirm > 0 {
                    let confirmed = self.cf_sign == sign && now - self.cf_t <= self.ft_confirm_ms * 1000;
                    let applies = (self.ft_confirm_flip == 0 || pos < 0)
                        && self.qs_rate >= self.ft_confirm_qs_lo
                        && self.qs_rate < self.ft_confirm_qs_hi
                        && signal * (sign as f64) - need < self.ft_confirm_margin;
                    if !confirmed && applies {
                        self.cf_sign = sign;
                        self.cf_t = now;
                        self.ft_last = now;
                        quantity = 0;
                    } else {
                        self.cf_sign = 0;
                    }
                }
                // R4-A1 WAIT (FA_ACT 1): the first take at or after FA_T skipped, its cooldown started
                if quantity > 0 && self.fa_act == 1 && !self.fa_done && now >= self.fa_t {
                    self.fa_done = true;
                    self.ft_last = now;
                    quantity = 0;
                }
                if quantity > 0 {
                    self.pg.takes += 1;
                    self.pg.lots += quantity;
                    self.cal.takes += 1;
                    self.cal.lots += quantity;
                    if self.ws_stats.is_some() {
                        self.ws_count[0] += 1;
                        self.ws_count[1] += quantity;
                        if pos < 0 {
                            self.ws_count[2] += 1;
                        }
                        if wide {
                            self.ws_count[4] += 1;
                        }
                    }
                    if big {
                        self.burst_lots += quantity;
                    }
                    let price = if sign > 0 { ask + thru } else { 1i64.max(bid - thru) };
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
                    if fa_logging || (self.fa_act == 4 && !self.fa_done) {
                        self.fa_takes.insert(id, (sign, quantity, 0));
                    }
                }
            } else if self.ft_exit < 99.0 && self.inventory != 0 {
                // FT_EXIT (R3-G1): the signal against the position past FT_EXIT + half the spread, flatten (reduce only)
                let s = if self.inventory > 0 { -1 } else { 1 };
                if signal * (s as f64) > self.ft_exit + 0.5 * spread_f {
                    let reserved: i64 = self.orders.iter().filter(|r| r.sign == s).map(|r| r.quantity).sum();
                    let mut quantity = self.inventory.abs() - reserved;
                    if self.ft_exit_sz > 0 {
                        quantity = quantity.min(self.ft_exit_sz);
                    }
                    if quantity > 0 {
                        let price = if s > 0 { ask + self.ft_thru } else { 1i64.max(bid - self.ft_thru) };
                        let id = ctx.send_order(if s > 0 { Side::Buy } else { Side::Sell }, price, quantity, true);
                        self.orders.push(Record {
                            id,
                            sign: s,
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
        }
        // FT_EXIT_WIDE (R3-G1): at a wide spread, flatten (reduce only) unless the signal is with the position
        if self.ft_exit_wide > 0
            && spread >= self.ft_exit_wide
            && self.inventory != 0
            && self.m1.labels >= self.min_labels
            && now - self.ft_last >= self.ft_gap_ms * 1000
        {
            let source = if self.ft_src == 1 { p2_only } else { prediction };
            let signal = if self.ft_net > 0 { source - skew } else { source };
            let s = if self.inventory > 0 { -1 } else { 1 };
            if -signal * (s as f64) < self.ft_exit_keep {
                let reserved: i64 = self.orders.iter().filter(|r| r.sign == s).map(|r| r.quantity).sum();
                let mut quantity = self.inventory.abs() - reserved;
                if self.ft_exit_sz > 0 {
                    quantity = quantity.min(self.ft_exit_sz);
                }
                if quantity > 0 {
                    let price = if s > 0 { ask + self.ft_thru } else { 1i64.max(bid - self.ft_thru) };
                    let id = ctx.send_order(if s > 0 { Side::Buy } else { Side::Sell }, price, quantity, true);
                    self.orders.push(Record {
                        id,
                        sign: s,
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
        // R4-A1: the takes' fills; a take cancelled partly filled is logged (FA_LOG) and arms COMPLETE (FA_ACT 4)
        if !self.fa_takes.is_empty() {
            match event.status {
                Status::Filled => {
                    self.fa_takes.remove(&event.order_id);
                }
                Status::PartiallyFilled => {
                    if let Some(e) = self.fa_takes.get_mut(&event.order_id) {
                        e.2 += event.filled_quantity;
                    }
                }
                Status::Canceled | Status::Rejected => {
                    if let Some((s, requested, filled)) = self.fa_takes.remove(&event.order_id) {
                        let ts = event.timestamp_us;
                        if filled > 0 && filled < requested {
                            if let Some(w) = self.fa_log.as_mut() {
                                use std::io::Write;
                                let _ = writeln!(w, "3,{ts},{s},{requested},{filled},{}", self.inventory);
                            }
                            if self.fa_act == 4 && !self.fa_done && ts >= self.fa_t {
                                self.fa_done = true;
                                self.fa_rest = Some((s, requested - filled));
                            }
                        }
                    }
                }
                _ => {}
            }
        }
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
                if self.ws_stats.is_some() {
                    // WS_STATS: a flip is a position's sign reversed, through flat only within the same timestamp
                    let (s, t) = (self.inventory.signum(), event.timestamp_us);
                    if s == 0 {
                        self.ws_flat = true;
                        self.ws_zero_t = t;
                    } else if s != self.ws_inv_sign || self.ws_flat {
                        if self.ws_inv_sign == -s && (!self.ws_flat || self.ws_zero_t == t) {
                            self.ws_count[5] += 1;
                            if t - self.ws_inv_start < 1_000_000 {
                                self.ws_count[6] += 1;
                            }
                        }
                        if s != self.ws_inv_sign || self.ws_zero_t != t {
                            self.ws_inv_sign = s;
                            self.ws_inv_start = t;
                        }
                        self.ws_flat = false;
                    }
                }
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

// ===== R4-M1: a mixture of experts over the forecast (8 Nov, off by default: MOE 0) =====
//
// MOE picks the regime: 1 the spread (1 tick, MOE_SPREAD+), 2 the speed (QS_RATE's |mid change| rate below / at least
// QS_RATE), 3 both (four experts), 4 the first model's forecast under / at least MOE_CONF (0.3) ticks either way, 5 the
// latent filter's posterior sd under / at least MOE_SD (1.0; needs FILTER). Each expert is a ridge on the first model's features and labels (HORIZON_US ahead,
// MODEL_MEMORY_US, FIT_US, HUBER), learning only from its own regime's observations. MOE_MODE 0 (hard): the active
// regime's expert's forecast replaces the first model's once that expert has MOE_MIN labels (0: MIN_LABELS), or with
// MOE_W under 1, the blend (1 - MOE_W) x the first model's + MOE_W x the expert's (a soft gate). MOE_MODE 1
// (hierarchical): the expert learns the first model's residual (the label less the first model's forecast at the
// observation) and the forecast is the first model's plus MOE_W times the active expert's. MOE_RIDGE_MIN / MOE_RIDGE_FRAC
// (0: RIDGE_MIN's / RIDGE_FRAC's) set the experts' ridge, max(MOE_RIDGE_MIN, MOE_RIDGE_FRAC * mass). The forecast feeds
// everything the first model's does (the take, fair). RIDGE_DEBUG prints each expert's labels and the books it served.

pub const MOE_KEYS: [&str; 9] =
    ["MOE", "MOE_MODE", "MOE_MIN", "MOE_RIDGE_MIN", "MOE_RIDGE_FRAC", "MOE_W", "MOE_SPREAD", "MOE_CONF", "MOE_SD"];

struct MoeExpert {
    /// (time, mid, features, the first model's forecast, this expert's forecast)
    obs: VecDeque<(i64, f64, [f64; NM], f64, f64)>,
    last_label_us: Option<i64>,
    last_fit_us: Option<i64>,
    labels: i64,
    mass: f64,
    xx: [[f64; NM]; NM],
    xy: [f64; NM],
    weights: [f64; NM],
    served: i64,
}

pub struct Moe {
    gate: i64,
    mode: i64,
    min_labels: i64,
    ridge_min: f64,
    ridge_frac: f64,
    w: f64,
    wide: i64,
    conf: f64,
    sd: f64,
    horizon_us: i64,
    memory_us: i64,
    fit_us: i64,
    huber: f64,
    experts: Vec<MoeExpert>,
}

impl Moe {
    fn from_params(params: &Params) -> Result<Option<Box<Moe>>, String> {
        let gate = params.int("MOE", 0)?;
        if gate <= 0 {
            return Ok(None);
        }
        if gate > 5 {
            return Err("MOE: 1 spread, 2 speed, 3 both, 4 the forecast's size, 5 the filter's sd".to_string());
        }
        if gate == 5 && params.int("FILTER", 0)? <= 0 {
            return Err("MOE 5 reads the latent filter's sd: set FILTER=1".to_string());
        }
        if gate >= 2 && params.float("QS_RATE", 0.0)? <= 0.0 {
            return Err("MOE 2 / 3 read QS_RATE's speed: set QS_RATE".to_string());
        }
        let min = params.int("MOE_MIN", 0)?;
        let rmin = params.float("MOE_RIDGE_MIN", 0.0)?;
        let rfrac = params.float("MOE_RIDGE_FRAC", 0.0)?;
        let k = if gate == 3 { 4 } else { 2 };
        let experts = (0..k)
            .map(|_| MoeExpert {
                obs: VecDeque::new(),
                last_label_us: None,
                last_fit_us: None,
                labels: 0,
                mass: 0.0,
                xx: [[0.0; NM]; NM],
                xy: [0.0; NM],
                weights: [0.0; NM],
                served: 0,
            })
            .collect();
        Ok(Some(Box::new(Moe {
            gate,
            mode: params.int("MOE_MODE", 0)?,
            min_labels: if min > 0 { min } else { params.int("MIN_LABELS", 200)? },
            ridge_min: if rmin > 0.0 { rmin } else { params.float("RIDGE_MIN", 1.0)? },
            ridge_frac: if rfrac > 0.0 { rfrac } else { params.float("RIDGE_FRAC", 0.001)? },
            w: params.float("MOE_W", 1.0)?,
            wide: params.int("MOE_SPREAD", 2)?,
            conf: params.float("MOE_CONF", 0.3)?,
            sd: params.float("MOE_SD", 1.0)?,
            horizon_us: params.int("HORIZON_US", 100_000)?,
            memory_us: params.int("MODEL_MEMORY_US", 300_000_000)?,
            fit_us: params.int("FIT_US", 1_000_000)?,
            huber: params.float("HUBER", 0.0)?,
            experts,
        })))
    }

    fn regime(&self, spread: i64, fast: bool, base: f64, sd: f64) -> usize {
        let wide = (spread >= self.wide) as usize;
        match self.gate {
            1 => wide,
            2 => fast as usize,
            3 => wide + 2 * fast as usize,
            // 4: the first model's own forecast at least MOE_CONF either way (where the take decides)
            4 => (base.abs() >= self.conf) as usize,
            // 5: the latent filter's posterior sd at least MOE_SD
            _ => (sd >= self.sd) as usize,
        }
    }

    fn dot(w: &[f64; NM], f: &[f64; NM], n: usize) -> f64 {
        py_sum(w[..n].iter().zip(f[..n].iter()).map(|(w, x)| w * x))
    }

    /// matures every expert's labels at this book's mid and refits (each at most once per FIT_US)
    fn learn(&mut self, now: i64, mid: f64, n: usize) {
        let (horizon, memory, huber, mode) = (self.horizon_us, self.memory_us, self.huber, self.mode);
        for e in self.experts.iter_mut() {
            while let Some(&(t, old_mid, features, base, own)) = e.obs.front() {
                if t + horizon > now {
                    break;
                }
                e.obs.pop_front();
                if now - t > horizon + 1_000_000 {
                    continue;
                }
                let elapsed = e.last_label_us.map_or(0, |l| now - l);
                let decay = ((-(elapsed.max(0))) as f64 / memory as f64).exp();
                e.last_label_us = Some(now);
                let response = clamp(mid - old_mid, -20.0, 20.0);
                let target = if mode == 1 { response - base } else { response };
                let weight = if huber > 0.0 { (huber / (target - own).abs().max(1e-12)).min(1.0) } else { 1.0 };
                e.mass = e.mass * decay + weight;
                for i in 0..n {
                    e.xy[i] = e.xy[i] * decay + weight * features[i] * target;
                    for j in 0..n {
                        e.xx[i][j] = e.xx[i][j] * decay + weight * features[i] * features[j];
                    }
                }
                e.labels += 1;
            }
            if e.labels < self.min_labels || e.last_fit_us.is_some_and(|t| now - t < self.fit_us) {
                continue;
            }
            e.last_fit_us = Some(now);
            let r = self.ridge_frac * e.mass;
            let ridge = if r > self.ridge_min { r } else { self.ridge_min };
            let mut matrix = [[0.0f64; NM + 1]; NM];
            for i in 0..n {
                matrix[i][..n].copy_from_slice(&e.xx[i][..n]);
                matrix[i][n] = e.xy[i];
                matrix[i][i] += ridge;
            }
            let mut ok = true;
            for col in 0..n {
                let pivot = matrix[col][col];
                if !pivot.is_finite() || pivot <= 1e-12 {
                    ok = false;
                    break;
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
            if ok {
                let mut weights = [0.0; NM];
                for i in 0..n {
                    weights[i] = matrix[i][n];
                }
                if weights.iter().all(|w| w.is_finite()) {
                    e.weights = weights;
                }
            }
        }
    }

    /// the active expert's own forecast (clamped), or None while it has fewer than MOE_MIN labels
    fn own(&self, k: usize, features: &[f64; NM], n: usize) -> Option<f64> {
        let e = &self.experts[k];
        (e.labels >= self.min_labels).then(|| clamp(Moe::dot(&e.weights, features, n), -2.0, 2.0))
    }

    /// an observation for regime k's expert, with the first model's forecast (`base`) stored for the residual
    fn observe(&mut self, k: usize, now: i64, mid: f64, features: &[f64; NM], n: usize, base: f64) {
        let own = self.own(k, features, n).unwrap_or(0.0);
        self.experts[k].obs.push_back((now, mid, *features, base, own));
    }

    /// the forecast: the first model's (`prediction`) replaced by (mode 0) or corrected by (mode 1) regime k's expert
    fn predict(&mut self, k: usize, features: &[f64; NM], n: usize, prediction: f64) -> f64 {
        let Some(own) = self.own(k, features, n) else { return prediction };
        self.experts[k].served += 1;
        if self.mode == 1 {
            clamp(prediction + self.w * own, -2.0, 2.0)
        } else if self.w != 1.0 {
            // a soft gate: MOE_W of the expert, the rest the first model's
            (1.0 - self.w) * prediction + self.w * own
        } else {
            own
        }
    }
}

impl Drop for Moe {
    fn drop(&mut self) {
        if std::env::var("RIDGE_DEBUG").is_ok() {
            let s: Vec<String> = self.experts.iter().map(|e| format!("{}/{}", e.labels, e.served)).collect();
            eprintln!("RIDGE_DEBUG moe gate={} mode={} labels/served={}", self.gate, self.mode, s.join(" "));
        }
    }
}

