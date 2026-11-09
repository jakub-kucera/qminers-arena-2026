# Round 4's tape: statistics and what F5's forecast misses (8 Nov, 07:15-08:20)

Tapes: `round4_public.csv` (r4) against `round3_public.csv` (r3); the partial R^2 also on `round2_public.csv` (r2) and
the synthetic `gen/r3b/seed201.csv` (s201). Commands from the repo root; P is a scratch directory.

```sh
uv run python -m experiments.tape.tape_stats $T --cache P/ts.npz --json P/ts.json                   # part 1, ~1 min
uv run python -m experiments.generator.gen_identify $T --cache P/id.npz --json P/id.json                 # the generator's parameters
uv run python -m experiments.generator.gen_ladders $T --cache P/lad.npz --json P/lad.json
RIDGE_PRED_LOG=P/pred.csv RIDGE_PRED_EXTRA=1 uv run python -m arena.qsim_rust ridge_maker $T ${=F5} --threads 1
uv run python -m experiments.taker.forecast_gaps $T --pred P/pred.csv --cache P/ts.npz --json P/fg.json   # part 3
uv run python -m experiments.taker.f5_anatomy data/arena/round4/py_f5_full --pred P/pred.csv          # part 2 (full-logs run)
```

## 1. The tape's structure (r4 / r3)

| | r4 | r3 |
|---|---|---|
| 1-s mid sd; net / range | 6.30; -445.5 / 838.5 | 4.51; -127.0 / 364.5 |
| drift t (net against the 1-s sd x sqrt(T)) | -0.91 | -0.36 |
| net per 1,000 s | -234, -251, +71, -301, +6 | +4, +16, -235, +115, +49 |
| seconds at 5+ ticks/s of mid path; mean ticks/s | 29.6%; 4.52 | 26.5%; 3.83 |
| regimes (2-state mixture, 10-s blocks): calm share, mean run, 1-s sd | 63%, 72 s, 1.27 | 64%, 81 s, 1.21 |
| volatile share, mean / max run, 1-s sd | 37%, 42 / 140 s, 10.25 | 36%, 46 / 260 s, 7.30 |
| G inserts /s; cancels /s; F (IOC) /s | 195.0; 168.7; 9.74 | 196.4; 170.5; 9.38 |
| G at or inside the touch; G size median / p90 | 45.6%; 18 / 163 | 45.1%; 18 / 153 |
| F requested median / p99; Hill alpha; traded nothing | 63 / 1,577; 1.68; 3.8% | 60 / 1,528; 1.71; 5.9% |
| F side = previous side; 1-s signed lots ACF lag 1 / 2 / 5 | 0.539; 0.156 / 0.075 / 0.036 | 0.501; 0.069 / 0.003 / -0.038 |
| mid move the next 1 s per 100 net F lots in a second | +0.111 (corr 0.18) | +0.057 (corr 0.11) |
| spread 1 / 2 / 3 / 4+ ticks | 81.0 / 14.5 / 3.1 / 1.4% | 81.5 / 14.0 / 3.3 / 1.2% |
| depth at levels 1-5 (median, lots) | 727 / 840 / 719 / 633 / 602 | 730 / 846 / 700 / 607 / 558 |
| touch, smaller side: median / p10 | 202 / 15 | 210 / 16 |
| 2-ms ladders: orders, chains, /s; size median; lifetime median | 65,302, 21,496, 10.9; 49; 0.54 s | 68,527, 23,586, 11.4; 36; 0.72 s |

**Jumps** (a 3+ / 5+ / 10+ / 20+ tick mid move within 0.2 s on the 0.1-s grid, detections within 1 s merged):

| | r4 | r3 |
|---|---|---|
| count 3+ / 5+ / 10+ / 20+ | 749 / 390 / 105 / 20 | 763 / 272 / 63 / 20 |
| 5+ jumps: size median / p90 / p99 | 13.0 / 32.0 / 107.5 | 9.5 / 20.0 / 78.2 |
| 5+ jumps: move its way from the first detection at 0.4 / 1 / 5 / 30 s | +3.8 / +6.6 / +15.1 / +4.5 | +2.5 / +3.6 / +4.3 / +2.6 |
| ... share of jumps with a positive move at 1 / 5 s | 81% / 72% | 69% / 60% |
| 5+ jumps: move its way after its end at 1 / 5 / 30 s | +2.5 / +7.5 / -3.0 | +0.9 / +0.2 / -1.2 |
| 5+ jumps: max run its way within 30 s of its end (mean / median), when (median) | 36.6 / 25.8, 8.7 s | 19.9 / 15.0, 9.1 s |
| 5+ jumps: the next one the same sign (within 30 s) | 0.576 (0.581) | 0.465 (0.470) |
| 3+ jumps: the next one the same sign | 0.472 | 0.440 |

The "after detection" numbers include the rest of the jump itself; "after its end" conditions on the run having ended.

**Autocorrelation of non-overlapping mid changes (lag one), variance ratio against 1 s:**

| h | 0.1 s | 0.4 s | 1 s | 5 s | 30 s | 60 s |
|---|---|---|---|---|---|---|
| r4 ACF | +0.121 | +0.192 | +0.257 | +0.135 | -0.206 | -0.056 |
| r3 ACF | +0.079 | -0.021 | +0.111 | -0.007 | -0.093 | -0.043 |
| r4 VR | 0.61 | 0.78 | 1 | 1.68 | 1.68 | 1.27 |
| r3 VR | 0.81 | 0.96 | 1 | 1.13 | 0.98 | 0.95 |
| r4 volatile blocks / calm blocks (1, 5, 30 s) | | | +0.26 / +0.15 | +0.17 / -0.03 | -0.32 / -0.06 | |
| r4 away from 5+ jumps (58% of time) | | | +0.16 | +0.10 | +0.06 | |

**Drift or momentum: clustered momentum, not a drift.** The net move is t = -0.91 (no significant push); the momentum
lives in the volatile blocks (1-s ACF +0.26, 5-s +0.17) and reverses at 30 s there (-0.32): the variance ratio climbs
to 1.68 by 5 s and falls to 1.27 by 60 s. 58% of r4's time is 10+ s from a 5+ tick jump and still carries +0.16 / +0.10
at 1 / 5 s, so it is not only jumps continuing. The market orders follow it: side persistence 0.539 (r3 0.501).

**The generator's identified parameters** (`gen_identify`, `filter_process_probe`):

| | r4 | r3 |
|---|---|---|
| impact c (sqrt traded), calm / volatile | 0.0457 (0.0307 / 0.0545) | 0.0485 (0.0331 / 0.0585) |
| observable impact c, transient tau (filter_process_probe) | 0.0243, 0.127 s | 0.0230, 0.100 s |
| own impact left at 60 s (120-500 lots) | 0.637 | 0.248 |
| exogenous variance /s (calm / volatile) | 40.6 (0.95 / 38.5) | 13.6 (0.88 / 20.7) |
| 1-s residual kurtosis; variance share in 2+ tick steps | 262; 0.980 | 423; 0.958 |
| jumps /1,000 s; size median / q90 | 70.3; 7.6 / 23.4 | 64.8; 5.2 / 11.6 |
| F side against the next exogenous move (corr) | **0.071** | 0.007 |
| P(jump within 5 s given spread 3+) | 0.873 | 0.766 |
| volatile share (2-state, 60-s RV) | 0.702 | 0.683 |

Round 4's generator is round 3's order process (same rates, sizes, spread, depth, ladders, impact c) with three times
the exogenous variance, jumps half again as large, more permanent impact, and **market orders that lean toward the next
exogenous move** (corr 0.071 against 0.007).

## 2. Where F5 earns and loses (`f5_anatomy`, against the market mid; r4 / r3)

| | r4 | r3 |
|---|---|---|
| PnL (simulator / mid) | 1,029,443 / 1,029,543 | 515,670 / 515,720 |
| takes: fills, lots, edge (a lot) | 12,161, 546,161, -273,934 (-0.502) | 10,649, 500,277, -252,876 (-0.505) |
| passive fills: lots, edge | 36,943, +20,954 | 48,703, +27,332 |
| the position's moves | +1,282,524 | +741,264 |
| time at \|pos\| 100 / flat | 58.4% / 0.1% | 52.9% / 0.1% |
| calm / volatile half of 60-s blocks (1-s sd) | 153,412 (2.27) / 876,130 (8.43) | 91,348 (1.55) / 424,372 (6.15) |
| speed terciles slow / mid / fast | 50,311 / 141,252 / 837,957 | 46,260 / 62,964 / 406,522 |
| jump onsets (3+ ticks in 0.2 s, merged within 1 s) | 600 | 636 |
| PnL [-3,0) / [0,1) / [1,10) / [10,30) s / away | 14,592 / 367,554 / 564,415 / 35,636 / 47,346 | 14,100 / 241,818 / 189,130 / 22,252 / 48,420 |
| share of PnL in [-3,10) s (r4: 47% of the time) | 91.9% | 86.3% |
| onsets with / against our position 0.2 s before | 402 / 198 | 388 / 247 |
| after an onset against us, PnL [0,1) / [1,10) s | +36,788 / +175,822 | +46,254 / +73,495 |
| takes at a 1-tick spread: lots, 1-s / 5-s markout | 544,757, 515,192 / 1,010,878 | 496,239, 432,458 / 483,476 |
| holding episodes; median; time-weighted median | 2,806; 1.45 s; 3.4 s | 2,609; 1.58 s; 3.7 s |
| episodes < 1 s / 1-2 / 2-5 / 5-10 / 10-30 s | -56,431 / 77,388 / 445,060 / 410,937 / 152,589 | -45,444 / 117,243 / 322,207 / 101,232 / 20,482 |
| whipsaws (ended by a flip within 1 s): n, PnL | 979, -55,981 | 801, -43,699 |
| per 1,000 s (first block first) | 132,794 / 255,374 / 125,949 / 222,948 / 96,667 / 195,711 | 70,890 / 70,374 / 114,599 / 95,197 / 66,734 / 97,876 |

Regimes here are a median split of 60-s realised variance (each half 50% of the time by construction); speed is the
prediction log's QS_RATE column on a 1-s grid. Takes at a 2+ tick spread are 0.3% of take lots (FT_MAXSPREAD 1).

- The extra 514k over r3 is all the position's moves (+1.28M against +0.74M); the takes pay half a tick a lot on both.
- r4's money is the 1-10 s after a jump onset: 564k (r3 189k). The takes' 5-s markout is twice the 1-s (1.01M against
  515k; r3 483k against 432k): F5's positions are held about as long as the momentum pays (time-weighted median 3.4 s).
- The losses are whipsaws: 979 episodes reversed within 1 s cost 56k. A jump against a full position nets positive.
- **The slow start is not a problem on r4:** the first 1,000 s made 132.8k against 96.7k-255.4k for the later blocks,
  as the warm start's -1.7k to +0.3k said.

## 3. What F5's forecast misses (`forecast_gaps`)

Baseline: F5's own 0.4-s forecast (the Rust prediction log) on the 0.1-s grid. An OLS of the move on the forecast,
fitted on the first 75%, scored on the last 25%: r4 test corr 0.369 / 0.393 / 0.330 at 0.4 / 1 / 5 s (coefficient
1.50 / 2.87 / 6.48), r3 0.394 / 0.324 / 0.138 (1.20 / 1.74 / 1.45). On r4 the forecast predicts the 5-s move almost as
well as the 0.4-s one.

**Partial R^2 (%) beyond the forecast, last 25%, at 0.4 / 1 s** (all candidates causal; "take" = the share of
one-tick-spread grid points where the forecast plus the candidate's increment crosses F5's bar 0.75 differently, the
forecast alone crossing it 21.3% of the time on r4; for candidates correlated with the forecast it overstates):

| candidate | r4 | r3 | r2 | s201 | r4 ticks a sd at 0.4 / 1 / 5 s | r4 take |
|---|---|---|---|---|---|---|
| G_offset_asym_1s: new G asks' mean distance behind their touch minus the bids', 1 s | **1.41 / 1.89** | 0.02 / 0.01 | -0.02 / -0.03 | 0.09 / 0.06 | 0.51 / 1.28 / 2.76 | 13.0% |
| gap_mean_1s: the filter's gap averaged over 1 s | **1.04 / 3.27** | 0.03 / -0.01 | -0.05 / -0.09 | 0.00 / 0.00 | 0.50 / 1.48 / 3.63 | 12.4% |
| gap_now: the filter's gap (already a ridge feature) | 1.06 / 1.41 | 0.31 / 0.53 | 0.09 / -0.01 | -0.10 / -0.08 | 1.05 / 1.90 / 3.88 | (30.1%) |
| gap_mean_5s | 0.54 / 1.30 | -0.03 / -0.04 | -0.06 / -0.13 | -0.01 / -0.01 | 0.23 / 0.64 / 0.25 | 4.5% |
| pred x (a 3-tick move within 5 s) | 0.76 / 1.93 | 0.11 / 0.08 | 0.43 / 0.11 | 0.00 / 0.03 | 0.59 / 1.65 / 4.06 | 3.4% |
| jump sign, decayed 2 s (unmerged detections) | 0.41 / 1.03 | 0.00 / -0.05 | -0.12 / -0.34 | -0.08 / -0.08 | 0.15 / 0.47 / 1.08 | 1.4% |
| pred x speed (z) | 0.29 / 0.89 | -0.41 / -0.36 | 0.13 / 0.05 | -0.23 / 0.06 | | |
| trend 1 / 5 / 30 s | 0.11 / 0.07, 0.24 / 0.75, -0.02 / -0.14 | <= 0.07 | <= 0.00 | ~0 | | |
| G at or inside the touch (bids minus asks, 1 s) | 0.16 / 0.35 | 0.01 / -0.06 | 0.02 / 0.01 | 0.00 | | |
| depth beyond the touch (levels 2-5 imbalance) | 0.07 / 0.30 | -0.01 / -0.07 | -0.01 | -0.02 | | |
| F lots 1 / 5 s; F count 1 s | <= 0.08 | <= 0.06 | <= 0.02 | ~0 | | |
| cancels near the touch 0.5 / 1 s; bursts 0.2 s | <= 0.07 | ~0 | ~0 | ~0 | | |
| touch imbalance; 2-ms ladders (bids minus asks, 1 s) | <= 0.02 | <= 0.02 | ~0 | ~0 | | |
| G centre minus mid (0.5 s) | 0.01 / 0.08 | -1.24 / -0.07 | 0.11 / 0.02 | -0.02 | | |
| all 25 together | 3.69 (0.4 s), 5.79 (1 s) | -1.60, 0.95 | 0.43 | 0.18 | | |

An earlier version keyed the jump features to the end of a merged run, which looks ahead (it knows the run stopped):
it showed a spurious 1.1-1.8% on every tape. The table uses every detection as it happens.

**Calibration** (slope of the 0.4-s move on the forecast; 1 = calibrated):

| state | r4 | r3 | r2 | s201 |
|---|---|---|---|---|
| all | 1.48 | 1.21 | | |
| speed tercile slow / fast | 0.83 / 1.61 | 0.83 / 1.35 | 0.87 / 1.34 | 1.04 / 1.16 |
| calm / volatile | 0.83 / 1.62 | 0.85 / 1.33 | 0.87 / 1.39 | 1.01 / 1.27 |
| within 5 s of a 3-tick move / none for 30 s | 1.62 / 0.88 | 1.34 / 0.83 | 1.43 / 0.83 | 1.14 / 1.08 |
| spread 1 / 2+ | 1.57 / 1.17 | 1.19 / 1.30 | | |

The forecast is too small when fast (x1.6 on r4) and too large when calm (x0.83) on every real tape; the synthetic tape
barely shows it. (Handed to another agent as a speed-binned recalibration; the existing FT_EDGE_CALM, a higher bar when
calm, loses on r4: 0.35 / 0.5 / 0.75 x FT_CALM_RATE 1.5 / 2.5 / 4 all -2k to -32k, while r3 gains up to +31k.)

**What the ridge does with them** (F5 with both new features, its own matured labels from `RIDGE_FEAT_LOG`, event time,
263k rows, fit on the first 75%): beyond the stored forecast, the filter's gap adds 4.3% of the label's variance (the
forecast's weight falling to 0.46), GAPMEAN 2.4%, GASYM 1.4%, though all three are ridge features. The stored forecast
is clamped at +-2 ticks (`ridge_maker.rs`, `clamp(..., -2.0, 2.0)`, the forecast too), and F5's forecast sd is 1.33 in
the fastest tercile, so part of this, and part of the fast-market slope above, is the clamp on large moves, which does
not change a take (the bar is 0.75). HUBER is not the cause: F5 on r4 with HUBER 4 / 9 / 12 / 20 / off makes -0.4k /
-6.1k / -1.8k / -1.3k / +0.1k (r3 -9.2k to +4.5k).

## 4. Bot changes, ranked

Nothing below beats F5 on round4_public by more than its noise while holding on the other tapes: **F5 unchanged stays
the final.** The ranking is by evidence for the next tape, not by gain here.

1. **A state-dependent take bar from the forecast's calibration** (evidence: slope 1.61 fast / 0.83 slow on r4, 1.35 /
   0.83 on r3, 1.34 / 0.87 on r2; within 5 s of a 3-tick move 1.62 against 0.88). Expected: small, and the crude form
   loses: FT_EDGE_CALM 0.35 / 0.5 / 0.75 x FT_CALM_RATE 1.5 / 2.5 / 4 costs r4 -1.9k to -32.3k in every cell while r3
   gains up to +31.0k. Cheapest test: a PRED_SCALE by QS_RATE tercile, judged on the calibration at |forecast| 0.4-1.1
   (the decisions the bar can change), not the overall slope. Handed to the recalibration agent.
2. **GASYM_US and GAPMEAN_US, the two r4-only signals, as ridge features** (built: `ridge_maker` knobs, off by default;
   F5 1,029,443 / 515,670 unchanged at 0). Evidence: partial R^2 1.41% / 1.04% at 0.4 s on r4, ~0 elsewhere; the Rust
   features correlate 0.92 / 0.94 with the Python ones and still add 1.4% / 2.4% beyond the ridge's own stored forecast
   on its matured labels. **Backtest** (`experiments.rounds.paired_rust` on six tapes, 1,000-s segments), against F5:

   | bot | r4 (first 75% / last 25%) | r4 segments | r3 | r2 | seed201 | seed202 | seed203 |
   |---|---|---|---|---|---|---|---|
   | GASYM 0.5 s | +1,491 (+1,871 / -380) | +248, t 0.21, 2/6 | -16,300 | -570 | +3,213 | +1,058 | -2,038 |
   | GASYM 1 s | +497 (+2,084 / -1,587) | +83, t 0.07, 2/6 | -12,295 | -719 | -5,717 | -2,924 | -5,493 |
   | GAPMEAN 1 s | -5,869 (-5,466 / -403) | -978, t -0.95, 2/6 | -1,342 | +917 | -6,476 | -1,225 | -20,479 |
   | both (0.5 s, 1 s) | +3,109 (+2,733 / +376) | +518, t 0.48, 2/6 | -373 | -2,276 | +1,174 | +3,108 | -12,583 |

   Takes sent (`--set PG_STATS=1`, which works at PG 0): r4 F5 4,869 takes / 693,482 lots, GASYM 0.5 s 4,639 / 658,574,
   both 4,639 / 657,457 (-4.7% takes); r3 F5 4,543 / 637,631, both 4,464 / 623,931. Lots traded on r4 550,612 (both)
   against 583,104, fills 41,668 against 41,854. The information is
   real but a 1-2% better 400-ms forecast does not move the PnL: F5 sits at |position| 100 58% of the time and the
   forecast matters only near the 0.75 bar. `dropped here`.
3. **Fewer whipsaws** (979 positions reversed within 1 s cost 56k on r4, 44k on r3). The unconditional form, a higher bar
   against the position (FT_EDGE_FLIP 0.35 / 0.5 / 0.75), costs r4 -3.5k / -13.7k / -28.8k (r3 -6.1k / +31.3k / +4.8k):
   the momentum that makes the whipsaws also pays the flips. Untested and the only form left: the flip bar raised only
   within ~5 s of a 5+ tick jump the position is with (5+ jumps run +15 ticks their way over 5 s on r4). A new knob;
   expected at most a part of the 56k.
4. **No change for the informed market flow** (F side against the next exogenous move, corr 0.071 on r4 against 0.007):
   F flow over 1 / 5 s adds <= 0.08% beyond the forecast, so F5's flow features already carry it.
5. **Dropped as signals** (partial R^2 <= 0.35% at 0.4 and 1 s on every tape): the 1 / 5 / 30-s trend, cancel imbalance
   and bursts, depth beyond the touch, the touch imbalance, 2-ms ladder activity, the G centre minus the mid.
