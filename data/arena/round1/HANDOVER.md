# Round 1 handover (7 Nov, 13:00-18:00; submissions close 18:00, freeze 17:30, last upload by 17:35)

The template (`docs/HANDOVER_TEMPLATE.md`): copy it to `data/arena/round<N>/HANDOVER.md` at the start of round N,
fill it in during the round and finish it by deadline − 0:10; the template itself stays as it is. Committed and pushed so the other laptop has it (ON_THE_DAY.md, "Handover note"); the private
run's results and `leaderboard.json` go in this folder too.

## Uploaded
<!-- each upload: file, time, why; local PnL under all / worse / --resting; the metrics expected (arena.backtest --metrics) -->
- 13:16, `python/bots/qminers/candidates/r1_F3_full_room.py` (A0: F3 with SESSION_S 1e9), round_start's best on round1.csv. Expected on the public data: pnl 425,553.00, fills 30,452, traded volume 2,645,992, end position +100, cash -577,347.00, mark price 10,029.00, breach 0, pnl_se 11,263.42, |inv| q50/68/95/99.7 98/100/100/100; exchange-simulator 26 s here.
- Next: `python/bots/qminers/candidates/r1_F5_shrink_react.py` (R1-F5). Expected on the public data: pnl 455,822.00, fills 37,847, traded volume 2,481,742, end position +100, cash -547,078.00, mark price 10,029.00, breach 0, pnl_se 11,038.79, |inv| q50/68/95/99.7 95/100/100/100.

- About 16:25, R1-C1 (`python/bots/qminers/candidates/r1_C1_codex_ridge.py`, the codex session's online ridge maker): expected 554,347.00 (37,087 fills, breach 0).
- About 17:07, R1-C5 (`r1_C5_long_horizon.py`, C1b with a 400-ms horizon, infinite memory, dead zone 0.18): expected 595,441.83 (21,120 fills, breach 1,720.17).
- About 17:44, **the final**: R1-C11 (`r1_C11_codex_v5_29feat.py`, the codex session's v5, 29 features): expected 619,281.99 (21,460 fills, breach 1,610.01, end inventory +100, ~3 min a run). R1-C10 (616,534.83) was the recommendation; the two differ by noise (6 of 12 segments). R1-C12 (v6, 622,920.99) came at 17:47 and was not uploaded (+3.6k in 5 of 12 segments).
- After 18:00: check which upload the portal marks as final; save the leaderboard to this folder's leaderboard.json when it is published, then `experiments.day.leaderboard_curves` and `experiments.day.standings`.

## Portal against local
<!-- the portal's figures against our backtest of the same file on the same days; the ratio (T); which fill mode and mark fit -->
Before the round (the playground, 7 Nov): the portal's results folder is byte-identical to a local `exchange-simulator` run of the same file on the same data (A0: -7,598, 394 fills; the trend follower +1,878), so `T` = 0 on the public data; only the private data differs (ON_THE_DAY.md, "From the playground"). Check it again on round 1's first upload.
- Round 1's first upload (R1-F3, 13:16): the portal identical to the local run (+425,553.00, 30,452 fills, 2,645,992 lots, end +100, pnl_se 11,263.42); "Simulation time" 1 min 2.8 s for 4.4M rows, so E is about 1-2 minutes with the queue. T = 0 again.
- Its review (`uv run python -m experiments.day.run_review data/arena/round1/r1_F3_full_room_res`, the results folder ignored): maker fills +0.42 ticks inside the mid at the fill, then the mid 0.26 ticks AGAINST them at 1 / 5 / 30 s (sample_v2: +0.06 our way): adverse selection eats ~60% of the edge here; PnL steady by quarter (96k / 202k / 315k / 426k), max drawdown 899; 54,646 orders, 28,162 cancels (193 too late).

## Private run against public
<!-- the private (hidden) run's PnL against the public one, per product -->
- **R1-C12 (v6) on round 1's private tape** (the portal's full log, run 17:10 UTC = 18:10 CET, saved in `data/arena/round1/r1_C12_v6_private_res/`, ignored by git): pnl **602,526.53** against 622,920.99 on the public tape (**0.967**), fills 20,662 (public 21,462), traded volume 2,063,619 (2,247,040), breach 1,173.47 (1,810), end inventory +21 at a mark of 9,939 (the public tape ends at 10,029), pnl_se 11,088, |inv| q50 99. Same rules (limit 100, wall 1,000, 10,000/s, 5 ms) and the same length (12,000 s). The drop of 20k is about 1.8 pnl_se: a different draw, not a collapse; the learned model carried over.

## Fill model and mark
<!-- the engine settings that matched the portal: --resting/--queue, --match-trades, --mark, --limit-penalty, --fee -->
Their simulator is the engine (`uv run exchange-simulator`; `arena.qgrid` and `arena.qsim_rust` run it, the Rust port byte-identical): no fill model to choose. Latency 5 ms, limit 100 (10,000/s above), markout against the market's resting orders.

## Units map
<!-- exchange unit → engine unit (1 / PRICE_SCALE) → each product's tick; their timestamps → 0..999,900; where each limit comes from -->
One instrument; prices in ticks, sizes in lots, Time in seconds. The template's clock maps (Time - first Time) / SESSION_US onto 0..999,900: set SESSION_US (template) and SESSION_S (families) from the round's file (round_start prints its length).

## Rule answers
<!-- which ON_THE_DAY.md items the rules or probes answered (written under each item, with the source), and the ones still open -->
Answered before the round: ON_THE_DAY.md, "Known so far", the 7 Nov blocks (site, starter repository, slides, playground). Open: the round's submission deadline (the dashboard's), whether the private hour looks like the public one.

## Re-tests
<!-- which of last round's choices were tested again this round, which were kept untested ("Choose the approach again each round") -->

## Leaderboard
- **Round 1's private leaderboard** (18:50, `data/arena/round1/leaderboard.json`, ranks and PnL only, no curves): **8th of 61** with 602,526.53 (R1-C12, v6). 60 teams positive: mean 434,481, sd 137,534, median 447,797, so our z = +1.22 (weight 0.8 in the final score). Above us: Team 2 792,696 (z +2.60), Team 5 701,374, Team 4 667,357, Team 10 657,359, Team 3 655,444, Team 6 615,391, Team 15 603,501. The leader made +32% over us on the same tape, so something structurally better exists (round 1's ceilings: a front-of-queue maker 790k; IDEAS.md, "Round 1 ceilings on R1-F8").
<!-- leaderboard.json saved here; experiments.day.leaderboard_curves --read verdict; our standing -->

## Next round
<!-- round N+1's first candidate, and its first three actions -->
- 15:10 (the stronger-model session, KICKOFF's open-ended prompt): R1-F8 (`python/bots/qminers/candidates/r1_F8_take_join.py`) is F7 plus three additions chosen on round1's first 75%: a limit order taking the last lots of the other side's dying touch (its remainder resting first at the level the followers form), ALLOC_K -0.5, and F7's sweep join only while the flow side's touch holds 400+ lots. +519,027 on round1 (+22,463 on F7, 12 of 12 segments, last 25% +4,117), +234,661 on sample_v2 (+5,768). What it rests on: after a touch clears, the other side follows into the gap in 71% of clears within 20 ms, 79% when its own touch holds 2,000+ lots and 35% under 100 (`experiments.day.spread_episodes` and the IDEAS row "Round 1 on R1-F7: taking the last lots of a dying touch ..."). The aggressors are iid Poisson with iid sizes (no sweep can be seen coming); fills by state (`experiments.day.fill_state`) show the money is in the queue place (one tick behind +0.46 a lot, the oldest orders +0.42, inside the spread -0.23), not in a predictable state.
- 16:15: R1-F8b (`r1_F8b_combo.py`, R1-F8 + SIZE_NARROW 100, SIZE_DEEP 60 and the sweep take at 1,000 lots with our orders at the hit touch pulled) +523,330 (+4,303), 9 of 12 segments, last 25% +1,936, sample_v2 +338: the upload if its verifier passes, R1-F8 otherwise. Tried and dropped after R1-F8 (the IDEAS row "Round 1 after R1-F8"): the thin-touch take, a position gate, the ghost harvest, breaches of the 100-lot limit (10 a millisecond beats anything a 5-ms action can earn).
- 16:35: the stronger round-1 bot is NOT the ladder: `strategy_codex_best.py` (the repo root; an online ridge model of 100-ms mid returns driving a full-room single-level maker: the touch, one tick back when the predicted move is against the side, inside a 2-tick spread at 0.3 ticks of edge) +554,347 on round1 (11 of 12 segments over R1-F8b, last 25% 136,522) and 272,830 on sample_v2 (R1-F8b 234,999): fitted on the fly, nothing tuned to the public tape. Its knobs are at a plateau (R1-X1 grids in CANDIDATES.md); it needs its full room (a smaller cap loses 45-185k) and sits at |position| 100 half the time, the full-room maker's trend risk. Another team reports 650k on round 1: 17% above it; no mechanism found today moves a bot by more than about 1% once verified.
- Round 2's first candidate is therefore the codex maker, and the work is the hybrid, not more ladder knobs: (1) run it and R1-F8b on the new tape beside each other; (2) the two hybrids started at 16:35 with a 17:05 stop (`r1_HA_codex_deep.py`: its predictor placing a second level one tick behind, the ladder's +27k mechanism; `r1_HB_codex_take.py`: the dying-touch take inside it), whatever their state in CANDIDATES.md; (3) its runtime margin on the sandbox (a 15x15 ridge solve a second, 2-4 min here under load).
- Round 2's first three actions (written at 15:10, the ladder's view): (1) `spread_episodes` on the new tape (the follow share by the follower's depth: if it is not above ~70% with a deep follower, switch TAKE_LOTS and JOIN_OWN off); (2) `--grid TAKE_LOTS=0,40,60 --grid JOIN_OWN=0,400 --grid ALLOC_K=0,-0.5` on R1-F8 with `--holdout 0.25`, chosen by `in`; (3) the ladder's own knobs (SIZE_TOUCH, SIZE_NARROW, SIZE_DEEP, DEPL_FRAC) re-gridded only if the spread's share at 1 tick or the touch depth differ from round 1's (93%, ~1,065 lots).

## Round 1 results, marked (17:40)
All on round1.csv (12,000 s, one instrument), their simulator or the byte-identical Rust port. "Last 25%" is the last 3,000 s (qgrid's split unless marked "seg", the last three 1,000-s segments). Penalty 0 unless shown. sample_v2 decides nothing (a different tape). Files under `python/bots/qminers/candidates/` and `families/`.

### (a) The learned-model line (an online ridge forecast of the mid driving a full-room maker)
| Candidate | Mechanism | Full | Last 25% | Penalty | Verdict | Why |
|---|---|---|---|---|---|---|
| R1-C9 `r1_C9_codex_v4_flow_groups.py` | C5 + 8 flow-group features (takers still resting after they traded, the rest, our own fills), weights learned online | 605,753 | +5.3k over C5 (seg) | 1,280 | **KEPT, the final if uploaded** | +10.3k over C5, 8 of 12 segments, bootstrap p5 +1.9k; features chosen on the whole tape, but no new hand constant |
| R1-C6 `r1_C6_place_slow.py` | C5 + the order-placement share at 0.4 s / 1 s, horizon 500 ms, dead zone 0.20, inside 0.35 | 601,155 | 147,463 | 1,766 | small gain | +5.7k, out +1.0k, 8 of 12 (t 1.83); a fifth round of selection |
| R1-C7 `r1_C7_event_blend.py` (branch, not merged) | C5 blended 0.8 with an event-time model (the mid at its next change) | 600,430 | 147,191 | 1,620 | small gain | +5.0k, out +0.7k, best of ~250 cells |
| learned dead zone (Rust `FILL_LEARN`) | step back only when the learned markout of a fill at this forecast is below FILL_MIN | 597,806 | 147,945 | 1,770 | tie | +2.4k; robust on a new tape (no dead-zone grid needed) |
| **R1-C5** `r1_C5_long_horizon.py` | v2 with a 400-ms horizon, infinite memory, dead zone 0.18 | 595,442 | 146,491 | 1,720 | **UPLOADED (17:10)** | +24.2k over C1b, 10 of 12, bootstrap p5 +13.7k; centre of a flat plateau |
| R1-C4 `r1_C4_pipelined_blend.py` | v2 + a second 500-ms ridge blended at 0.4 | 586,109 | +6.6k over C1b (seg) | 879 | superseded by C5 | +14.9k over C1b |
| R1-C1b `r1_C1b_codex_pipelined.py` (codex v2) | C1 + replacements sent while cancels are in flight + an IOC hedge back to 100 | 571,237 | 140,228 | 1,870 | uploaded 16:55, superseded | +16.9k over C1, 12 of 12; the hedge is worth +137k (without it: 433,889, penalty 139k) |
| R1-C3 `r1_C3_ridge_blend.py` | C1 + the 500-ms blend | 567,182 | 141,008 | 0 | superseded | +12.8k over C1 |
| R1-C1 `r1_C1_codex_ridge.py` (codex v1) | 15-feature ridge of the 100-ms mid move, refit each second; quote one tick back when the forecast is adverse | 554,347 | 136,636 | 0 | uploaded 16:25, superseded | +35k over F8, 11 of 12 |
| C1 with no learning (`MIN_LABELS` 1e9) | the fallback forecast 0.25 x spread x imbalance | 293,328 | 74,164 | 0 | control | **the learned forecast is worth +261k** |
| C1 + F8's depletion guard / sweep hold (`r1_C2_ridge_dying.py`) | step back on a dying touch; hold after 400+ lots | 528-553k | below | 0 | DROPPED | the ridge's imbalance features already price a dying touch |
| C1/C5 hand knobs | skew 0.1-0.5, flow cut, dead zone 0.05/0.2, exposure 90-105, partial cancel-free, hedge ticks, refit/sampling speed | 321-556k | | | DROPPED / flat | skew pulls it off the limit (321k at 0.5); dead zone is a sharp peak; exposure 105 costs 58M |
| extra features at 100 ms (placement, 5-level depth, flow 0.1/2 s, last aggressor size, scaling, ridge strength) | | 548-555k | | 0 | DROPPED at 100 ms | the 15 features carry it; placement pays only at slow time constants (C6) |
| F8's take on v2 | | 438,878 | | 134k | DROPPED | sizes against the 1,000-lot wall, carries the position past 100 |

### (b) The hand-built maker line (the ladder at the touch, queue-place rules)
| Candidate | Mechanism | Full | Last 25% | Verdict | Why |
|---|---|---|---|---|---|
| R1-F8b `r1_F8b_combo.py` | F8 + SIZE_NARROW 100, SIZE_DEEP 60, the sweep take | 523,330 | 133,883 | best hand-built; fallback | +4.3k over F8, 9 of 12 |
| R1-F8 `r1_F8_take_join.py` | F7 + a limit order taking a dying touch's last lots while ours is deep, ALLOC_K, the gated sweep join | 519,027 | 131,947 | superseded | +22.5k over F7, 12 of 12; the 729-cell Rust grid around it: nothing above (+69) |
| R1-F7 `r1_F7_signal.py` | F6b + a dying touch's room one tick back + joining inside after a sweep | 496,564 | 127,975 | superseded | |
| R1-F6b / R1-F6 | two levels (65/80, 115 at one tick), imbalance allocation | 489,844 / 483,074 | 127,092 / 126,359 | superseded | |
| R1-F5 `r1_F5_shrink_react.py` | F3 + the shrinking-level guard + re-quote on our cancel | 455,822 | 115,306 | superseded | |
| R1-F3 `r1_F3_full_room.py` | all 200 lots of room at the touch | 425,553 | 110,540 | uploaded 13:16 (portal identical) | the first upload |
| H1-H9 (the other model) | any-clear join, imbalance join, thin-touch take, position gate, ghost harvest, sweep take | about F7-F8 | | DROPPED but H9 (into F8b) | each within noise or below |
| G1 `r1_G1_queue_depth.py` | a third level, deep-first room, any-clear join, no posting behind long queues | 398-514k | | DROPPED | deep orders fill only in big sweeps; long queues still pay |
| G2 `r1_G2_latent.py` | F8 + the placement signal: shrink / block / IOC / veto | 492-520k | | DROPPED (veto +0.9k, noise) | the signal's half-tick move is what a maker fill earns |
| G3 `r1_G3_steer.py` | an inventory target from a 1-30 s forecast | 508-519k | | DROPPED | F8's inventory loses within 1 s, flat beyond 5 s |
| G4 `r1_G4_deep_queue.py` | orders 2-4 levels back, uncounted or counted; over-committing with a reducer | 246-491k | | DROPPED | deep fills are adverse; the reducer's penalty beats the fills |
| rules_maker (CANCEL_FREE 3) | an order cancelled for being 2+ ticks behind frees its room at once | +2.6k on F7 | +0.7k | small gain | the same mechanism, applied to every cancel with a hedge, is C1b's +17k |

### (c) The bad ones
| Idea | Best result | Verdict | Why |
|---|---|---|---|
| Momentum runner / taker / maker, fade, protected maker (families 1-5) | M2 runner -928,807; the rest negative or small | DROPPED | the move after a trade (~0.3 ticks at 1 s, 0.9 after 800+ lots) doesn't pay the spread crossed twice |
| Burst taker over the limit (`families/burst_taker.py`) | -28,535 within the limit; -0.53M to -46M over | DROPPED | the penalty is ~10 a millisecond |
| Maker with LIMIT 110-200, no reducer | -18M to -34M (pnl before penalty 553-667k) | DROPPED | sits over 100 for 1,900-3,500 s |
| The same with an IOC unwind to 60-100 | 239,319 at best (penalty 290k) | DROPPED | each breach >= 50 plus the crossed spread, thousands of them |
| Over-committing with a gated reducer (OVER) | 491,589 (penalty 30k) | DROPPED | same arithmetic |
| Engine tricks: free every cancel (no hedge), the penalty's integral, flattening at the end, modify vs cancel, landing before tape events | 395,885 (penalty 103k) and ties | DROPPED (gray area measured only) | the dying touch's cancels lose the race; the end mark is worth 0 |
| Generator robust grid (tape_gen, 30 seeds) | chosen cell 486,943 on the real tape (-9.6k vs F7) | DROPPED | generated tapes have a third of the 2-tick time, so they misrank the signal knobs |
| Deep ladders, a third level, front-of-queue ideas | see G1, G4 | DROPPED | |
| Inventory steering, a 1-30 s bet | see G3 | DROPPED | |

### What round 1 taught
- **The learned forecast is the edge:** without learning the same bot makes 293k; with it 554k. Long memory is as good as short: the coefficients are fixed over the hour, so the online fit estimates them from the tape itself, which is what makes it robust to a new tape.
- **Horizon:** a 400-500 ms forecast beats 100 ms (+24k), on a broad plateau (350-500 ms, dead zone 0.16-0.22, inside 0.3-0.4).
- **A cancel lands before an order sent after it:** counting cancelling orders as free room and hedging the rare breach is worth +17k (C1b); without the hedge it is a 139k penalty.
- **Penalty arithmetic:** 10,000 a second is ~10 a millisecond and the 5-ms latency makes any breach cost >= 50; plans that sit over 100 lose millions, plans that touch it for milliseconds and hedge pay ~1.7k an hour.
- **The queue place is the maker's edge:** 57% of F8's lots fill at the front (+0.34 ticks a lot after 1 s); fills against 800+-lot sweeps lose (-0.20); deep orders fill only in sweeps.
- **Hand constants overfit, learned weights adapt:** the dead zone is a sharp peak (0.05 / 0.2 cost 20-58k); every round of selection on the first 75% shrank the out-of-sample gain (C6, C7: +0.7-1.0k out).
- **Takers lose on this tape:** even with perfect 1-s foresight a taker tops out at ~441k; makers with front-of-queue priority on every touch would make 0.8-1.4M (the ceiling).
- **The portal is byte-identical to a local run** (F3's 30,452 fills); bot speed doesn't matter (latency is simulated), only the 900-s timeout (C9 takes 139 s).
- **sample_v2 is a different tape** (58% 2-tick spreads vs 7% on round1): judge only on the round's own CSV.
