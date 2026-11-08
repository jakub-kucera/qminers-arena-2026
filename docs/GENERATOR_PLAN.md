# Reverse-engineering the tape generator: plan (8 Nov, 00:55, before round 3)

## Why now

The Arena's tapes are synthetic: every round's public, validation and private tape is a draw from the organisers'
generator, with per-round (maybe per-tape) parameters. Round 2 showed what one wrong guess about those parameters costs:
the public tape's tuning put R2-E2 at +47k locally and -41k on validation, because the validation tape ran in a more
volatile regime. What we can learn about the generator is worth more than any single strategy tweak, because it
transfers to every tape of every remaining round.

## What we already know (round 1's fit, `python/experiments/day/tape_gen.py`; round 2's diagnosis, `tape_character.py`)

- **Hidden fair price.** New limit orders are placed around a latent price that the mid only follows: at a 1-tick
  spread a bid lands at the touch 80% of the time when the mid is up 0.5 s later, 23% when it is down; the past move
  predicts nothing. This is why the 400-ms ridge forecast works: it is an empirical estimate of that latent price.
- **Limit inserts:** one Poisson stream (~180/s), side a coin flip, offsets 0 / 1 / 2 ticks from the latent price
  (55 / 39 / 6% in round 1), sizes from a heavy-tailed table; nearly every order has a scheduled cancel with a median
  lifetime of 0.31-0.34 s (99th percentile 2.1 s), independent of size and offset.
- **Aggressive orders:** Poisson (~8-9/s), side independent of the previous one, heavy-tailed sizes (median ~60,
  p99 ~1,543 lots); they move the latent price by a size-dependent impact (round 1: +0.10 ticks for small up to +0.90
  for 1,000+ lots at 5 s; round 2: +1.3 for 500-800 lots, +2.1 for 800-1,500).
- **Round 2's regime:** the same order flow as round 1, but the mid changes twice as often, the price wanders ~550
  ticks, moves persist; validation behaved like the public tape's high-volatility half ~1.25x faster. Volatility
  clusters (absolute 100-ms returns have lag-1 correlation 0.20; 10-minute return sd ranges 0.37-1.66).
- **Gaps in the round-1 model:** too few 2-tick spreads (a third of real), no volatility regimes, no heavy-tailed
  latent jumps; it ranked the makers right but F7 against F6 wrong.

## Phase 1: identify the generator's structure (on round 2's public tape, then round 3's)

Each item is a measurable hypothesis; the replay is `tape_book` (no strategy), the outputs go to one report.

1. **The latent price's dynamics.** Estimate a latent path (e.g. a smoothed midpoint of the inserts' centres, or a
   particle filter, below) and test: is it a random walk with jumps? Are the jumps triggered only by aggressive orders
   (impact) or also exogenous? Is volatility regime-switching (a hidden Markov chain over a few volatility levels) or
   GARCH-like? The answer sets the generator's core.
2. **Impact as a function of size,** and whether it is permanent or decays (the latent price after a big IOC at 1 s,
   5 s, 60 s), per regime.
3. **Insert placement relative to the latent price:** the offset distribution, whether it widens with volatility (the
   2-tick share rose from 7% to 12% between rounds), and the size distribution by offset.
4. **Cancellation:** scheduled lifetimes only, or also "stale" cancels when the latent price passes an order?
5. **Aggressive flow:** Poisson or self-exciting (Hawkes) arrivals; does the side correlate with the latent price's
   direction (informed flow) or with the last move (trend followers)?
6. **What differs between tapes:** fit the same structure to round 1's public, round 2's public, round 1's rebuilt
   private tape and round 3's public tape; tabulate which parameters move (volatility level, impact scale, insert
   rates) and which stay fixed.

## Phase 2: a calibrated generator v2

- Extend `tape_gen` with what Phase 1 finds: volatility regimes, latent jumps, volatility-dependent offsets, Hawkes
  arrivals if needed.
- **Validate on three levels:**
  1. statistics: spread mix, mid-change rate, return distribution by horizon, impact curve, fills by offset;
  2. strategy ranking: our candidates' PnL order on generated tapes must match the public tape's (round 1's model
     failed this for F7 against F6);
  3. **the validation scoreboard:** we have 14 server results on round 2's validation tape (E2 -41k, V2 +72k, M2
     +376k, M3, M4, RA, T1, T2, H1, L1, L3, L6, L8, L9 +874k). Find the generator parameters under which those 14
     bots score in the same order and roughly the same ratios. That is simulation-based inference of the validation
     tape's regime, and a direct estimate of what the private tape may look like.

## Phase 3: how it is used

1. **Robust choice:** run every candidate and grid on 30-100 generated tapes per plausible regime; choose the setting
   with the best mean (or a low quantile) across them, instead of the one public tape. This replaces the stitched
   tapes, which overrated the flow-window bots (M4 scored 0.62 of its stitched level on validation).
2. **The "perfect model" forecast:** a Bayesian / particle filter of the latent price from the observable events
   (where inserts land, cancels, aggressive orders and their sizes), using the fitted generator as its likelihood.
   Its forecast, E[latent] - mid, either replaces the ridge forecast or becomes its strongest feature. If the
   generator is right, this is close to the optimal predictor, and the take rule follows from it.
3. **Online regime identification:** estimate the tape's volatility and impact parameters in the first minutes of a
   run and switch the bot's settings (quotes on or off, the take threshold, the Huber cutoff) to those that win in
   that regime on generated tapes.
4. **Warm start:** pre-fit the ridge (or a non-linear forecast) on generated tapes of the identified regime, so the
   bot does not lose its first minutes to learning.

## Execution during round 3 (01:00-06:00), alongside the round's normal protocol

| When | Who | What |
|---|---|---|
| 01:00-01:30 | me | round 3's first look; the base bot (L9 or R3-B1) uploaded first |
| 01:00-02:15 | agent A | Phase 1, items 1-6, on round 2 public, round 1, round 1's private rebuild and round 3 public |
| 01:00-02:15 | agent B | Phase 3.2 prototype: a latent-price filter as a feature of L9's ridge, on the existing tapes |
| 02:15-03:30 | agent C | Phase 2: generator v2 from A's findings, validated against the 14 validation scores |
| 03:30-05:00 | me + agents | Phase 3.1 / 3.3 on round 3's candidates; one or two validation uploads as paired tests |
| 05:00-06:00 | me | the final choice and the handover |

## Risks

- **Overfitting the generator to the public tape:** the validation scoreboard is the guard; a generator that cannot
  reproduce the 14 results' order is not trusted for choices.
- **Per-tape parameters:** the private tape may sit in a different regime; Phase 3.3 (online identification) is the
  answer, not a fixed tuning.
- **Time:** Phase 3.2 (the filter) is the highest-value and the riskiest; if it is not clearly better than the ridge
  by 03:30 it is dropped for this round, and its findings move to round 4.
- **Legitimacy:** modelling the public data and our own validation results is ordinary research; the rules allow it.

## Phase 1 findings (8 Nov, 01:30; `python/experiments/day/gen_identify.py`, IDEAS.md "The tape generator's structure")

Five tapes, one replay each: round 1 public (r1), round 1's private rebuild (r1p), round 2 public (r2) and its mirror
(r2m: every number mirrored, a check of the code), round 3 public (r3). The latent estimate is the mean price of the
new bid inserts plus that of the new ask inserts, halved, over 0.1 s; its noise is 0.036 ticks² on r1, 0.5-0.9 on r2/r3.

**The generator, as the data shows it.** One generator with two hidden regimes; round 1 sat in the calm one throughout.

1. **A latent price moved by every aggressive order by c·sign·√(traded lots)**, deterministically and permanently.
   - Beta 0.5 fits r1 best (0.55 on r2/r3). On r1 the jump's variance equals the estimator's noise, so the impact has
     no random part.
   - c = 0.024 on r1. In the calm state c is 0.028 (r2) and 0.033 (r3); in the volatile state 0.046 and 0.058.
   - What is left of the order's own impact is flat from 0.1 s to 300 s (r1: 0.70 to 0.71 ticks for 500+ lots), with
     6-10% more arriving within the first second.
   - On r1 this is the whole latent: the residual against the impact path is 0.06 ticks² at 1 s and 0.75 at 300 s, no
     more than a 6% misfit of c explains.
   - So r1's exogenous variance is about 0: no exogenous moves, no jumps (|1-s residual| never reaches 2 ticks).
2. **The volatile regime adds exogenous jumps:**

   | | r2 | r3 |
   |---|---|---|
   | exogenous variance a second (impact's share) | 14 ticks² (1.1 from impact) | 13.6 ticks² (4.4 from impact) |
   | share of the 1-s residual's variance in 2+ tick steps (kurtosis) | 97% (427) | 96% (423) |
   | jumps of 3+ ticks in 0.2 s (per 1,000 s) | 313 (52) | 389 (65) |
   | \|size\| median / q90 / q99 | 5.6 / 13.5 / 63 | 5.2 / 11.6 / 64 |
   | up share | 0.45 | 0.51 |

   - Persistence: 98-103% of the jump is still there at 1-5 s; no reversal.
   - Clustering: the gaps' CV is 2.6-2.8 (median 2.7 / 4.0 s), and the counts per 500 s run 2-101.
   - A jump's sign is independent of the previous one's (P(same) 0.48).
   - Mechanics (r2's +100-tick jump at 5,569.8 s): the latent moves first. The next aggressive order, 22 lots, is
     priced at the new latent, 98 ticks through the ask. The stale asks cancel 4-21 ms later, and the book rebuilds at
     the new level within about 0.2 s.
   - The "big sweeps" before a crash are this effect: aggressive orders priced at a latent that has already jumped.
3. **Two regimes** (a Gaussian mixture on the log of each 60-s block's residual variance; BIC: one state on r1, two on
   r2/r3):

   | | r1 (one state) | r2 calm / volatile | r3 calm / volatile |
   |---|---|---|---|
   | share of blocks | 1 | 47% / 53% | 32% / 68% |
   | mean run (60-s blocks) | | 2.1 / 2.3 | 1.8 / 3.5 |
   | F orders a second | 8.0 | 8.0 / 9.8 | 7.9 / 10.1 |
   | G inserts a second | 180 | 180 / 177 | 187 / 201 |
   | insert width (ticks) | 2.05 | 2.08 / 2.81 | 2.41 / 3.77 |
   | 1-tick spread share | 93% | 93.5% / 75% | 93% / 76% |
   | impact c | 0.024 | 0.028 / 0.046 | 0.033 / 0.058 |

   The calm state is round 1's tape. What moves between tapes is chiefly **the volatile state's share** (0, 53%, 68%),
   plus a drift in the calm-state c and, on r3, a higher insert rate and G size (median 18 against 14).
4. **Placement:** G inserts land at an offset from the latent.
   - r1: mean 1.03, sd 0.56, in 0.5-tick bins 0 / 0.5 / 1 / 1.5 / 2 / 2.5+: 5% / 26% / 42% / 17% / 9% / 1%.
   - The offsets widen in the volatile state: r3 calm mean 1.21 / sd 1.03, volatile 1.95 / 1.71; share 2+ ticks 11% vs 35%.
   - The offsets also widen with the spread at insert time.
   - Sizes do not depend on the offset (r1 median 14 at every offset); on r3 the deepest inserts are larger (median 32).
   - The insert rate does not vary with volatility.
5. **Cancels:**
   - Every G order has a cancel row. Median lifetime 0.31-0.35 s on every tape; p99 2.1 s, or 4.5 s on r3.
   - **Stale cancels exist on every tape.** The hazard for an order the latent has passed is 1.5-2.4x that of a fresh
     one at ages 0.05-0.8 s (r1 1.5-1.9, r2/r3 1.8-2.4).
   - The burst right at a jump's onset is too fast for the 0.1-s grid (seen in the example, not measured).
6. **Aggressive flow:**
   - Side: a coin flip (buy share 0.500, P(same as previous) 0.501). Not informed about the next exogenous move
     (corr 0.007 or less on r2/r3); r1's 0.09 is the impact's late part. Not trend-following (corr with the past 1 s 0.005).
   - Sizes are the same on every tape: median 59-61, p99 about 1,540, Hill tail α 1.7.
   - Arrivals are Poisson on r1 (CV 1.00, 10-s dispersion 1.04, no autocorrelation). On r2/r3 they are clustered:
     10-s dispersion 5.5-5.9, 1-s count autocorrelation 0.39 at lag 1 on r3.
   - Within the calm state the counts are Poisson: 10-s dispersion 1.0 on r1 and r2, 1.5 on r3. Within the volatile
     state they burst (dispersion 7.7 / 6.3), so the volatile state's aggressive flow is self-exciting or tied to the
     jumps, not just a higher rate.
   - **The limit price is set from the latent, not the touch:** a median 1.0-1.3 ticks beyond the latent centre. This is
     why only 34-55% of aggressive orders trade at a 4+ tick spread (95-97% at 1-2 ticks).

**Jump precursors: the placement widens about 2 s before a jump; the direction does not show until after it.**
- Profile, for the first jump after 30 s without one (36 on each tape): the book spread is 1.0-1.3 from -60 s to -3 s,
  2.2-2.7 at -2 s and 2.4-3.1 at -0.5 s. The insert width goes 2.1-2.9, then 4.0-4.7 at -2 s.
- Hit rates, at times 10+ s after any jump (P(jump within 5 s | signal); share of jumps flagged in the 1 s before):

  | signal | r2 | r3 |
  |---|---|---|
  | spread 3+ (1.0-1.3% of the time) | 0.83 (lift 20); 51% | 0.77 (lift 11); 36% |
  | insert width over its q90 at those times (r2 2.35, r3 3.19) | 0.20 (lift 5); 93% | 0.45 (lift 7); 93% |
  | insert width over its q97 (r2 2.65, r3 5.16) | 0.60 (lift 15); 91% | 0.72 (lift 11); 42% |

- Episodes (each upward crossing, 10+ s after a jump) end in a jump within 5 s:
  - insert width over its all-time q90 (r2 4.2, r3 5.6): 90% / 71%, lead median 1.6 / 2.75 s;
  - over q97: 91% / 88%;
  - spread 3+: 50% / 59%, lead median 2.2 / 2.5 s;
  - spread 2+: 7-14% only.
- The spread before the jump predicts its size: corr(|size|, spread at -0.2 s) 0.35-0.38.
- **Direction: nothing before the onset predicts it.** |corr| ≤ 0.13 and P(agree) 0.47-0.54 for the signed aggressive
  lots (0.3 / 1 / 5 s), the insert and cancel imbalance, the latent's drift (5 s, 60 s), centre minus mid and the
  previous jump's sign.
- After the onset the direction shows fast:
  - A trade at a 3+ tick spread has its side match the latent's next move 64-66% of the time, 73-76% on moves of 5+
    ticks. The first such trade after 0.3 s without trades matches 63-69% (25 a 1,000 s).
  - 5 ms after it, the book still holds stale lots on that side beyond the latent's new level: worth 1.21M (r2) and
    344k (r3) ticks·lots in all; 38k / 17k capped at 100 lots.
  - So the value is in the big jumps and in briefly holding more than the 100-lot limit; this matches the round-2
    winner's +148k in one 25-s step.
- **The race** (`stale_race`, jumps of 5+ ticks: 175 on r2, 202 on r3):
  - The reveal is the first order priced half the jump beyond the old level (an aggressive limit or a new G order),
    a median 0.01-0.07 s before the grid onset.
  - The first trade the jump's way comes 0.065 s after it (median; q90 0.18-0.21 s), and is the reveal itself 13-15%
    of the time.
  - Lots resting on the stale side beyond the latent's new level (marked 0.5-1 s on), d ms after that trade:

    | d (ms) | 0 | 5 | 10 | 20 | 50 | 100 |
    |---|---|---|---|---|---|---|
    | r2: lots (mean) / value in all, k ticks·lots / capped at 100 lots, k | 1,361 / 1,607 / 102 | 1,319 / 1,539 / 98 | 1,203 / 1,369 / 94 | 1,137 / 1,222 / 90 | 931 / 908 / 70 | 727 / 651 / 56 |
    | r3 | 1,775 / 2,619 / 133 | 1,775 / 2,605 / 132 | 1,760 / 2,559 / 130 | 1,656 / 2,369 / 125 | 1,462 / 1,966 / 110 | 1,195 / 1,441 / 88 |

  - The stale book drains slowly, not in 20 ms: a taker 5 ms late keeps about 96% of the value.
  - The open question for a bot is the trigger. Its false positives (a trade at a wide spread is the jump's way only
    64-69% of the time) are not costed here.

**For Phase 2 (generator v2):**
- The latent is a sum of √-impacts plus, in the volatile state, a compound-Poisson jump process.
  - Size: median 5, a tail to 100.
  - Rate: about 0.1-0.2 a second within the state, clustered.
- The state is a two-state Markov chain with runs of about 2-3 minutes.
- Each jump is preceded by about 2 s of widened placement: the offsets' scale goes up about 2x.
- Aggressive orders are priced at latent ± about 1 tick; their rate is 8/s calm and 10/s volatile.
- Stale orders cancel at about 2x the hazard; the scheduled lifetime table stays.
- Calibrate per tape: the volatile share, c per state, the jump rate and size.
- Open: whether the widening is a separate pre-jump state (a fixed lead) or the volatile state's own wider placement
  (the lead is 0.4-6.7 s, q10-q90, so not fixed); the jump size's law (heavy tail, n ≈ 300 a tape); the cancel burst
  at the onset (needs event-level timing, not the 0.1-s grid).

Commands (each tape about 10 s once its replay is cached):
`uv run python -m experiments.day.gen_identify data/arena/round3/round3_public.csv --cache R3.npz --json R3.json`, then
`uv run python -m experiments.day.gen_identify --compare R1.json R2.json R3.json`.

## Phase 2 results (8 Nov, 02:25; `python/experiments/day/gen_calibrate.py`, IDEAS.md "Calibrating the generator to round 2's validation scoreboard")

**tape_gen v2.** Phase 1's structure, as latent options that are all off by default (a draw without them is the same
bytes as before):
- `impact_sqrt`: c·√lots impact.
- `f_limit_latent`: IOC limits at the latent ±1.
- Scheduled lognormal jumps in a two-state intensity chain (`jx_*`).
- Wider inserts before each jump: `jx_warn_s` / `jx_warn_k`, a lognormal lead with `jx_warn_sd`, and false alarms with
  `jx_false_rate`.
- The volatile state's own wider placement (`jx_on_k`) and diffusion (`jx_diff_sd`).
- Informed IOC orders at the jump: `jx_lead_extra` before it, `jx_after_extra` after it.
- A transient part of the impact: a negative `impact_delay`.
- `--latent-out`: the true latent every 10 ms.
The calibrated option sets are `gen_calibrate.PRESETS`, used as `--opts NAME`.

**Against round 2's validation scoreboard** (14 server scores, 12,000-s draws, the bots in Rust or `simulator.main`):

| generator | Spearman (bots) | level (draws / server) | misses |
|---|---|---|---|
| round 2's plain fit | 0.17 (8) | makers 5-7x, takers 0.45-0.84x, M 0 | everything but the takers' order |
| generic jumps + drift (sd right at every horizon) | 0.64-0.76 (8) | 2-5x | M negative, makers far too rich |
| `r2_validation` (informed IOC orders before the jump), 3 draws | **0.974 (14)** | about 0.75x (common factor 1.35) | E2 +45k against -41k; T1 / T2 a little high |
| `r2_validation_after` (informed IOC orders after the jump), 1 draw | 0.95 (8) | about 0.82x (asinh error 0.29 against 0.59 on the same seed) | L9 under L3; M 1.1x |

What made the difference:
- the sqrt impact, the latent-priced IOC orders and the clustered jumps (the makers stop being rich);
- stale cancels at the default 0.2 s, not Phase 1's 4-21 ms burst: a fast burst makes the makers rich and the takers
  poor (asinh error 0.98 against 0.59), and Phase 1's race table shows the stale book drains slowly too;
- informed IOC orders at each jump (the M-family's edge).

The last needs care. Timed by the latent (`gen_calibrate jumpflow`), the real tape's 500+ lot orders run 113 / 3 the
jump's way in the 0.1 s around the onset, but 43 / 30 from 0.5 to 0.2 s before. They follow an already-moved latent,
so a bot sees them 0.1-0.2 s before the mid moves, never before the latent does. The scoreboard wants about 3-4 such
orders a jump; the tape shows about 0.75 (r2 223 / 300, r3 341 / 458). With that much informed flow, a big order's
move at 0.5 s is 2.6 ticks on the draws against 1.9 on the tape.

**Round 3** (six bases on the public tape, all reproduced to the unit in Rust: L8 427,819, L3 425,321, L9 424,730, B1
433,922, L8F 484,057, B1F 505,212; checked on 5 fresh 6,000-s draws):

| preset | Spearman | draws / real | FILTER gain on L8 / B1 (real +13.1% / +16.4%) | misses |
|---|---|---|---|---|
| `r3_public_stats` (fitted to price statistics only) | 0.31 | 1.16-1.46 | +6.2% / +6.7% | L9, B1 overrated by 20-25% |
| `r3_public_after` (fitted to the six scores) | **0.60** | **1.12-1.21** (\|log ratio\| after a common factor 0.020) | **+16.7% / +13.1%** | L9, B1 about 7% above L8, L3 (real: equal) |

`r3_public_after`'s volatile state has smaller jumps (median 3) and diffusion (4 ticks/√s), with wider placement in
it, warnings of varying lead and widenings with no jump after them. This answers the filter agent's finding (the
draws' jumps were cleaner than the tape's) in the direction it pointed. Round 3's first validation score, R3-F1
+862,764 on 12,000 s, is 0.90x the public tape's rate a second: the same regime.

Shared draws (data/ is ignored; each folder has a README.txt with the command and params.json):
- `data/arena/gen/r3b/seed201-220.csv` (`r3_public_after`, 12,000 s), with seed201-203_latent.csv;
- `data/arena/gen/r3/seed101-130.csv` (`r3_public_stats`), with seed101-103_latent.csv.

## Using the generator in round 4

The first hour of round 4, beside round_start:
1. **Fit and profile the new public tape:** `uv run python -m experiments.day.tape_gen --fit D --params-out P.json`;
   `uv run python -m experiments.day.gen_calibrate stats D` (the price sd over 1-300 s, spreads, impact by size, a big
   order's move curve, the touch-landing test, 3+ tick jumps per 1,000 s) and `gen_calibrate jumpflow D`. Compare with round 2's
   and round 3's rows in IDEAS.md.
2. **Choose the starting preset:**
   - calm, round 1's state (no 3+ tick jumps, sd at 1 s under 1.5): no preset, the plain fit;
   - volatile: start from `r3_public_after`. Its volatile share is set by `jx_rate_on` / `jx_dwell_on`, and c by
     `impact_sqrt`, which Phase 1's `gen_identify` estimates per tape.
3. **Fit to the public scores of 6+ Rust bases** (5 minutes on 4 cores): put their public scores in a JSON file, then
   `uv run python -m experiments.day.gen_calibrate search --params P.json --scoreboard S.json --bots ... --seconds 6000
   --scale 1 --seeds 1 --around PRESET --spread 0.35 --vary impact_sqrt,jx_rate_on,jx_median,jx_after_extra,jx_diff_sd
   --trials 15 --jobs 4 --out F.jsonl`.
4. **Check before trusting it:** `uv run python -m experiments.day.gen_calibrate rank --opts BEST --seeds 2-6
   --seconds 6000 --real D --bots ...`. Trust a ranking only between bots whose gap on the draws is well beyond their
   pairwise se and whose order the check reproduces. Each validation score that lands is one more point:
   `--scoreboard` with `--seconds 12000`.
5. **Share the draws:** `uv run python -m experiments.day.gen_calibrate write --opts BEST --seeds 1-20 --dir
   data/arena/gen/r4 --latent-seeds 1-3`.

What it gets wrong, so far:
- the level runs 0.75-0.85x of round 2's validation scores and 1.1-1.2x of round 3's public ones;
- the pure takers (L9, B1) are overrated against the quoting L8 family by about 7% on round 3;
- the informed post-jump flow is about 4x the tape's, to get the momentum family's level;
- the mid changes a little too rarely (4.2 a second against 4.85 on round 2);
- the 2-tick spread share is a little low (0.08-0.11 against 0.11-0.14).
A gain that rests on the generator's own latent (the FILTER features) is partly circular: compare its gain on the
draws with its gain on the real public tape before reading it.

## A dedicated session (8 Nov, 02:20)

From round 3 on, the generator work moves to its own Claude session; its prompt is `docs/GENERATOR_SESSION_PROMPT.md`
(the data inventory, what is known, the open discrepancies, the method, the deliverables and the round-4 playbook).

## Raw-stream identification (8 Nov, gen-v3)

`gen_inventory` measures raw CSV fields without assuming a latent/book model. The compact table is
`docs/GENERATOR_COMPONENTS.json`; it records input SHA256s, candidate-law likelihoods, conditional 95% intervals,
half-tape fits, and observed lifetime/size dependence. Reproduce the table from the repository root:

```sh
uv run python -m experiments.day.gen_inventory r1=data/arena/round1/round1.csv r2=data/arena/round2/round2_public.csv r3=data/arena/round3/round3_public.csv sample1=data/sample.csv sample2=data/arena/playground/sample_v2.csv r1_private=data/arena/round1/private_reconstructed.csv --reconstructed r1_private --out data/arena/gen/gen_v3_inventory.json --summary-out docs/GENERATOR_COMPONENTS.json
```

- Public rounds 1-3: every insert increments the shared OrderId by exactly one, across both G and F orders.
  Every timestamp has six decimals and is strictly increasing, with a minimum gap of 1 microsecond. This supports
  one shared ID allocator and a serialization rule; it does not identify how many agents produced the orders.
- **IOC sizes fit a rounded lognormal**, clipped at one: `max(1, round(exp(N(mu,sigma))))`.
  The (mu, sigma) estimates are r1 (4.10576, 1.39594), r2 (4.10438, 1.40237), r3 (4.09358, 1.39656).
  CDF distances are 0.00186, 0.00224, 0.00181. Flooring loses 101.5 / 65.5 / 56.2 AIC units; the rounded
  Lomax (a genuine power-law tail) loses 2706.7 / 1519.1 / 1591.2. The earlier Hill estimate alone did not identify
  a Pareto law. The three estimates are compatible with shared settings; the original code's exact constants
  remain unproved. Confidence intervals condition on the fitted law and iid observations.
- **Base limit sizes also fit a rounded lognormal**: r1 (2.65811, 1.79913), r2 (2.65686, 1.80280), with CDF
  distances 0.00039 / 0.00105. Flooring loses 9074 / 4583 AIC units. This replaces a large empirical table with
  two parameters and an explicit rounding rule, and permits tail values beyond the observed maximum.
- **Round 3's G population is different.** Its rate is 196.39/s versus 178.31/s on r2. A single lognormal's best
  CDF distance is 0.01117 (roughly ten times the r2 discrepancy), and its apparent preference for flooring should
  not be interpreted as a changed rounding rule. There are 3,755 observed G lifetimes above 10 s, all with sizes
  53-406, median 153; r1/r2 have none. The size law and cancellation clock need a joint population model before
  a new round-3 preset is justified. Simply enlarging the base G law loses this distinction.
- Samples are structurally different: the original sample has G rate 7.38/s and sizes uniform 10-40; sample_v2
  has G rate 179.66/s and sizes uniform 20-40, F rate 6.00/s with lognormal (3.71155, 1.39968). sample_v2 has
  100,561 G inserts without observed cancels, so its lifetime censoring needs separate investigation. Neither
  sample is used to choose bots. The private reconstruction has missing IOC quantities and imputed cancels;
  its fitted IOC/cancel laws cannot identify the original generator's parameters.

`tape_gen` now accepts optional `latent.f_size_law` and `latent.g_size_law` objects: a `lognormal` with
`mu`, `sigma`, and `rounding`, or an inclusive integer `uniform` with `low`, `high`. F's law also supplies
post-jump informed orders **conditioned** on `jx_lead_min` (not clamped to it). All existing presets retain their
empirical tables and their byte-identical draws; a base draw and `r3_public_after` are pinned by SHA256 tests.
For a component experiment, add `--opts '{"f_size_law":{"law":"lognormal","mu":4.09358,"sigma":1.39656,"rounding":"round"}}'`
to `tape_gen` with an existing full params file. This is a size-law correction, not a claim of improved bot ranking.

Next: identify the extra round-3 populations jointly by size, lifetime and placement; test PnL-only recovery
against an existing public full-logs run before treating server PnL curves as recovered market prices.

## The PnL inversion check (8 Nov, gen-v3)

The proposed direct recovery of a signed 1-s mid path from PnL alone does **not** pass the local check.
`gen_pnl_probe` reuses the public F1/r3 and L3/r2 full logs, reproduces every recorded PnL sample with **zero
accounting error**, and measures the approximation against the actual market book from that run:

```sh
uv run python -m experiments.day.gen_pnl_probe logs/r3_F1_full logs/r2_L3_full --curves data/arena/round3/r3_F1_latent_filter_res data/arena/round3/r3_F3_latent_filter_b1_res data/arena/round2/r2_L3_taker_pure_res --out data/arena/gen/gen_v3_pnl_probe.json
```

If the local logs are absent, generate them with `exchange-simulator` and the corresponding committed candidate
on its public tape (the probe's docstring gives F1's exact command). No fresh bot runs are needed when they exist.

| Local test | F1 on r3 public | L3 on r2 public |
|---|---:|---:|
| Correlation, signed dPnL/100 versus signed mid change | -0.171 | 0.050 |
| Correlation, absolute dPnL/100 versus absolute mid change | 0.925 | 0.864 |
| Signed RMSE using **oracle** starting inventory, abs(position) >= 95 | 2.85 ticks | 2.64 ticks |
| Same oracle, also requiring no user fill in the second | 0.48 ticks | 0.95 ticks |
| Correlation of squared PnL/100 with squared mid moves in 60-s blocks | 0.957 | 0.802 |

The missing position sign, intrasecond trades and liquidation-depth marking prevent the simple inversion.
`result.json.mark_price` is an inventory-dependent liquidation VWAP (or last trade when flat), **not an end mid**:
F1's public mark is 9872 versus mid 9872.5, L3's 9690 versus mid 9689.5. These checks reject this shortcut, not every
possible inverse model using deterministic bot policies and multiple runs.

What survives is a **PnL-derived volatility proxy**, to compare the same bot across tapes and to add to the
simulation-based calibration objective. The one-second RMS of dPnL/100 is:
- L3: r2 public **3.471**, validation **4.789**, a **1.380x** ratio;
- F1: r3 public **4.082**, validation **4.280**, a **1.048x** ratio;
- F3: r3 validation **4.156** (no matching F3 public full-log check here).

The JSON includes 60-s proxy trajectories and counts of large proxy steps. These are not recovered prices,
jump counts or exact volatility parameters. On the public checks, the squared proxy underestimates true squared
mid moves by about 2.4 (r2) / 3.4 (r3) ticks²/s; do not apply one universal correction across bots or regimes.
Use the same proxy computed from generated bot runs to fit the validation curves directly.

## Filled-volume impact ablation (8 Nov, gen-v3)

Phase 1 regresses impact on filled lots, while v2 applies it to requested lots. `tape_gen` now exposes
`latent.impact_traded` (off by default) for this distinction, including zero impact for unfilled IOC orders.
Both ordinary and informed IOC orders use it. The original default draws remain byte-identical.
`gen_identify` also reports observed moves and standard errors for zero-filled isolated orders: r3 has 228,
mean -0.120 ticks their way (SE 0.0403). This is conditional evidence, not a causal estimate of their own impact.
On the 6,598 isolated orders the sqrt regression residual variance is 0.3522 using fills versus 0.3690 using
requested size, enough to warrant testing the distinction.

**The replacement preset fails.** All six Rust public scores reproduced to the unit before the comparison.
Three fresh 6,000-s seeds (301-303), same seed set for both arms, gave:

| Measure | Existing r3_public_after | Add impact_traded=true | Real r3 public |
|---|---:|---:|---:|
| L8 mean PnL | 457,399 | 803,328 | 427,819 |
| L9 mean PnL | 490,045 | 823,200 | 424,730 |
| B1F mean PnL | 560,290 | 886,413 | 505,212 |
| Six-bot Spearman | 0.60 | 0.60 | — |
| Asinh score error | 0.108 | 0.620 | 0 |
| FILTER gain on L8 / B1 | 20.3% / 15.8% | 9.3% / 7.8% | 13.1% / 16.4% |

Yet the first seed's big-order move curve improves markedly: at 0.5 / 5 s it changes from 2.78 / 3.03 ticks to
1.87 / 1.94, versus real 1.90 / 2.05. Its 1-tick spread share worsens from 0.901 to 0.912 (real 0.818), and
mid changes/s from 6.283 to 6.510 (real 5.774). These structural checks are one seed only. This is why matching
one impact curve is insufficient: the joint trading opportunities remain wrong. Keep the option for model
experiments; do not promote this arm or label its tapes r3c.

Reproduce from the root (build `arena-sim` first if absent). `PRESET:JSON` is now supported by
`gen_calibrate --opts` and `--around`, so an ablation can be specified without copying or editing a preset:

```sh
cargo build --release -p arena_sim --manifest-path rust/Cargo.toml
uv run python -m experiments.day.tape_gen --fit data/arena/round3/round3_public.csv --params-out data/arena/gen/v3_r3_params.json
uv run python -m experiments.day.gen_calibrate rank --params data/arena/gen/v3_r3_params.json --opts r3_public_after --bots L8,L3,L9,B1,L8F,B1F --seeds 301-303 --seconds 6000 --jobs 2 --keep --dir data/arena/gen/v3_check/baseline --out data/arena/gen/v3_check/baseline_scores.json
uv run python -m experiments.day.gen_calibrate rank --params data/arena/gen/v3_r3_params.json --opts 'r3_public_after:{"impact_traded":true}' --bots L8,L3,L9,B1,L8F,B1F --seeds 301-303 --seconds 6000 --jobs 2 --keep --dir data/arena/gen/v3_check/traded --out data/arena/gen/v3_check/traded_scores.json
uv run python -m experiments.day.gen_calibrate stats data/arena/round3/round3_public.csv data/arena/gen/v3_check/baseline/rank_6000s_301.csv data/arena/gen/v3_check/traded/rank_6000s_301.csv --jobs 2
```

The existing generated files and score JSONs are in `data/arena/gen/v3_check/`. Use a fresh output directory for
a changed parameter set. At the time of this ablation `gen_calibrate` reused existing tape paths without
validating their parameters; the provenance guard below now rejects that reuse. Older artifacts remain available
for explicit `score` / `stats` runs.

## Round 3's scheduled ladder population (8 Nov, gen-v3)

`gen_ladders` identifies exact same-side timestamp chains, with both inserts 2-7 ticks behind their own touch.
It replays the market book once and records placement, preexisting depth, scheduled cancels, remaining quantity
and the touch timeline. Cached input metadata and a source SHA256 guard against mixing tapes.

```sh
uv run python -m experiments.day.gen_ladders data/arena/round3/round3_public.csv --cache data/arena/gen/gen_v3_r3_ladders.npz --json data/arena/gen/gen_v3_r3_ladders.json
uv run python -m experiments.day.gen_ladders data/arena/round2/round2_public.csv --cache data/arena/gen/gen_v3_r2_ladders.npz --json data/arena/gen/gen_v3_r2_ladders.json
```

- R3 has **44,941 exact 2-ms links**, versus 19/23 at nearby 1/3-ms lags; r2 has only **8** in the same band.
  There are 23,586 chains and 68,527 identified orders (11.42/s). This is a labelled subset: singleton or broken
  batches remain unlabelled. The rate is below the roughly 18/s increase over r2.
- 43,112 of those pairs step one tick deeper. Sibling log sizes have correlation **0.950**, lifetimes **0.668**.
  Independent empirical size and lifetime draws cannot preserve this structure. Most chains have 2-6 members;
  51 longer chains may include chance links and require caution in a batch fit.
- Candidate sizes below 80: median **33**, lifetime median **0.604 s**; sizes 80+: median **153**, lifetime median
  **2.833 s**. Still resting at cancel: 78.77% / 96.02%. These are descriptive cuts, not identified component laws.
- **A pure band-exit cancel policy fails.** Of 56,062 candidates still resting at cancellation, 19,028 (33.94%)
  never previously left the 2-7 tick band. Only 45.54% cancel within 0.2 s of their first exit. For those with
  an exit, the delay median is 72.5 ms, p90 0.728 s. The check excludes already-filled orders and touch changes
  caused by the cancellation itself. Scheduled refreshes, another reference price, and repeated exits remain
  possible explanations; being outside the band at cancel alone does not identify the policy.

Next experiment: preserve complete joint batch marks (placement offsets, sizes, observed lifetimes) rather than
asserting an unproved cancellation rule. Exclude labelled orders from the background marginals and rate to avoid
double counting. Such an empirical batch model is an ablation, not recovery of the organisers' original code.

### Empirical batch ablation

The optional top-level `g_ladders` component in `tape_gen` has named `rate` (batch starts/s), `bid_share`,
`gap_us`, and `batches` (joint `[own_touch_offset, size, lifetime_us]` marks). Each sampled batch shares one
side; its children are scheduled independently of the background clock at exact integer-microsecond gaps.
Placement follows the current own touch. Lifetimes are sampled jointly and are not shortened by background
stale cancels. The mechanism is off when the object is absent; both pinned old tape hashes still match.

`gen_ladders --params BASE --params-out MIXTURE` fits complete 2-6 order chains and removes them from
background G rate, side share, size/offset marginals and lifetime quantiles. On r3 this labels 68,145 orders in
23,531 batches: background **185.030/s**, batch starts **3.92184/s**, total expected G rate **196.387/s**.
It leaves unidentified singletons, long chains and end-censored batches in the background.

This first ablation has a serious stated limitation: starts are Poisson at an unconditional rate. Real detected
chain starts per 60 s range **40-684**, mean **235.86**, sd **218.70**, Fano factor **202.78**. Marks also vary
with market state. Empirical lifetime marks are not a causal policy on a different price path. Those conditional
dependencies need separate identification; a match to the timing fingerprint alone cannot justify a new preset.

```sh
uv run python -m experiments.day.gen_ladders data/arena/round3/round3_public.csv --cache data/arena/gen/gen_v3_r3_ladders.npz --json data/arena/gen/gen_v3_r3_ladders_fit.json --params data/arena/gen/r3_params.json --params-out data/arena/gen/gen_v3_r3_batch_params.json
uv run python -m experiments.day.gen_calibrate rank --params data/arena/gen/r3_params.json --opts r3_public_after --bots L8,L3,L9,B1,L8F,B1F --seeds 304-306 --seconds 6000 --jobs 2 --keep --dir data/arena/gen/v3_ladders/baseline --out data/arena/gen/v3_ladders/baseline_scores.json
uv run python -m experiments.day.gen_calibrate rank --params data/arena/gen/gen_v3_r3_batch_params.json --opts r3_public_after --bots L8,L3,L9,B1,L8F,B1F --seeds 304-306 --seconds 6000 --jobs 2 --keep --dir data/arena/gen/v3_ladders/mixture --out data/arena/gen/v3_ladders/mixture_scores.json
```

Use a fresh output directory when parameters change. All six bots' settings and the original preset stay fixed.

Three fresh 6,000-s seeds (304-306), six bots, unchanged `r3_public_after` latent settings:

| Measure | Existing generator | Joint batch ablation | Real r3 |
|---|---:|---:|---:|
| L8 mean PnL | 462,266 | 438,924 | 427,819 |
| L9 mean PnL | 505,279 | 477,147 | 424,730 |
| B1F mean PnL | 569,193 | 539,156 | 505,212 |
| Six-bot asinh error | 0.1254 | 0.0729 | 0 |
| Six-bot Spearman | 0.60 | 0.60 | 1 |
| FILTER gain, L8 / B1 | 19.1% / 13.7% | 18.6% / 14.2% | 13.1% / 16.4% |

The score level is closer on these draws, but the paired L8 change is -23,342 with SE 27,501: three seeds
do not establish a reliable level improvement. Pure takers still beat L8 by too much. **Do not promote a new
preset or publish this as r3c.** Retain the component as an experimental structural improvement.

First-seed structural check (304): exact 2-ms band links **20 -> 44,640**, versus real **44,941**; sibling
log-size correlation **-0.195 -> 0.948**, real **0.950**; lifetime correlation **0.271 -> 0.669**, real **0.668**.
But the candidate-start count Fano factor is **0.755**, versus real **202.78**. Among orders still resting at
cancel, **71.6%** never leave the placement band in the mixture, versus real **33.9%**. Copying joint lifetime
marks does not reproduce the original policy's interaction with the market.

The same seed's 1-tick spread share improves **0.907 -> 0.888** (real **0.818**) and 60-s return sd
**23.11 -> 28.00** (real **32.18**), but mid changes/s worsen **6.225 -> 6.519** (real **5.774**), as does
the 5-s move after a large IOC: **2.64 -> 3.37 ticks**, real **2.05**. These are one-seed diagnostics.

Reproduce the structural comparisons with `gen_ladders` on each arm's `rank_6000s_304.csv` and:

```sh
uv run python -m experiments.day.gen_calibrate stats data/arena/round3/round3_public.csv data/arena/gen/v3_ladders/baseline/rank_6000s_304.csv data/arena/gen/v3_ladders/mixture/rank_6000s_304.csv --jobs 2
```

Shared artifacts: `data/arena/gen/v3_ladders/` contains both arms' tapes, score JSONs, first-seed ladder
measurements and `stats_304.json`; `gen_v3_r3_batch_params.json` contains the exact empirical component.
Next: identify batch intensity and joint marks conditional on observed activity, and a causal cancellation
policy. For the model-testing session, the identified deep ladders are also a reason to test whether pooling
all G inserts in a latent-price estimator contaminates it; this is a hypothesis for that session, not a bot change.

## Calibration cache provenance (8 Nov, gen-v3)

`gen_calibrate draw`, `rank` and `write` no longer silently reuse a tape merely because its filename exists.
Each new draw gets a `.csv.provenance.json` containing the canonical parameter hash, seed, duration, generator
and book source hashes, Python/numpy versions, output size and SHA256. Reuse checks both identity and content.
A mismatch or missing provenance fails with instructions to use a fresh directory; existing legacy tapes can
still be scored explicitly with `score` and measured with `stats`. No legacy file is relabelled as verified.

Generation is staged in a temporary directory and published only after success. Adding latent logging to a
verified tape must regenerate the same tape checksum before publishing the latent; a failed check preserves
existing outputs. `write` rejects an incompatible directory before replacing its README or params.json, and
records a shell-quoted reproduction command. This fixes a source of false ablation comparisons; it changes
no model parameters or generated tape bytes.

Validation: nine targeted cache tests cover reuse, changed parameters/seed/duration, legacy and altered files,
interrupted generation, latent logging consistency, and mixed-directory rejection. Full focused suite: **56
passed**, plus wiki lint with zero warnings/errors. Actual CLI smoke: two 40-s empirical-batch draws, one with
a latent path, then an identical cached rerun under `data/arena/gen/v3_cache_smoke/`.

```sh
uv run pytest python/tests/test_gen_cache.py python/tests/test_gen_ladders.py python/tests/test_gen_inventory.py python/tests/test_gen_pnl_probe.py python/tests/test_docs.py -q
uv run python -m experiments.day.gen_calibrate write --params data/arena/gen/gen_v3_r3_batch_params.json --opts r3_public_after --seeds 71-72 --seconds 40 --jobs 2 --latent-seeds 71 --dir data/arena/gen/v3_cache_smoke
```

## Activity and cancellation holdout (8 Nov, focused continuation)

`gen_ladder_mechanics` fits coefficients on r3's first3,000s and tests the second3,000s. The clock-defined
population and hypotheses were previously discovered using the full tape; this is a temporal coefficient
check, not a wholly independent discovery sample. Predictors use strictly prior book history.

```sh
uv run python -m experiments.day.gen_ladder_mechanics data/arena/round3/round3_public.csv --cache data/arena/gen/gen_v3_r3_ladders.npz --fills-cache data/arena/gen/ladder_mechanics/r3_fills.npz --out data/arena/gen/ladder_mechanics/r3_mechanics.json
```

A Poisson intensity model from prior1/5/30-s mid-change activity,5-s absolute moves and spread predicts
**4.200 batch starts/s** in the holdout, against observed**4.210/s** and constant training mean**3.659/s**.
Held-out log-score gain is**1.980 nats/s**, paired300-s-block interval**[1.662,2.303]**. Residual dispersion
falls**8.627 to4.076**, still far above one. The same activity features reduce log-size MSE**.4647 to.2301**.
The report contains standardization, coefficients and block results; this supports conditional activity models,
not a claim that independent Poisson starts fully describe the process.

Cancellation risk begins when a2-ms link identifies the order (the first child is recognized2ms late).
The replay records complete fills: risk then ends, so scheduled cancels of already-filled orders do not become
cancel events. Of68,527 detected orders,4 end before recognition,56,062 cancel while resting,12,455 are censored
by a full fill, and6 at tape end. Predictors use the left-limit book state, excluding a cancel's own touch update.
Exact time-boundary events belong to their event-time fold.

Size + current own-touch distance strongly outperforms size + age: **1.506 nats per held-out cancel**, block
interval**[1.258,1.762]**. Initial distance does not help over size + age. More age/activity cells do not improve
on the simpler current-distance model. Per-second cancellation hazards by size group:

| Current offset | Small, train/test | Size80+, train/test |
|---|---:|---:|
|2-4 ticks|.044/.059|.019/.022|
|8+ ticks|45.51/45.16|43.47/44.47|

These are cause-specific predictive hazards in the identified population. They do not prove the original
agent's clock, latent reference, or policy; exposure/cancel correlation alone is not causal identification.
The useful next model is activity-dependent batch flow and state-dependent cancellation, with residual
clustering and unidentified singleton orders still unresolved.

## Causal ladder exclusion (8 Nov, focused continuation)

The separate model probe reuses `LatentFilter` at F3's fixed settings (impact3, depth6), preserves the same
market book in every arm, samples50ms, fits frozen first-half forecast regressions with split-boundary purging,
and scores second-half0.4/1-s moves. This is an offline forecast test, not the full bot's adaptive ridge or PnL.

```sh
uv run python -m experiments.day.ladder_filter_probe data/arena/round3/round3_public.csv --ladder-cache data/arena/gen/gen_v3_r3_ladders.npz --out data/arena/gen/ladder_mechanics/filter_r3_delayed.json --rows-out data/arena/gen/ladder_mechanics/filter_r3_delayed_rows.npz
uv run python -m experiments.day.ladder_filter_probe data/arena/round2/round2_public.csv --ladder-cache data/arena/gen/gen_v3_r2_ladders.npz --out data/arena/gen/ladder_mechanics/filter_r2_delayed.json --rows-out data/arena/gen/ladder_mechanics/filter_r2_delayed_rows.npz
```

| R3 holdout |0.4s|1s|
|---|---:|---:|
|Baseline raw gap correlation|.321714|.268996|
|Causal clock exclusion correlation|.322735|.269672|
|Baseline gap-only MSE|7.485166|21.194435|
|Causal clock exclusion MSE|7.479307|21.186425|
|Paired MSE change, block95% interval|[-.016644,+.005136]|[-.040056,+.023976]|

Causal recognition removes39,426 eligible filter observations. Both small error improvements have intervals
crossing zero. R2 has only8 clock matches and effectively zero change. Removing every G in the2-7 tick band
clearly harms the gap forecast: r3 MSE**+.187209/+.461475**, r2**+.163402/+.126092**. Deep orders remain informative.

An explicitly exploratory arm, added after inspecting the primary results, delays all filter messages2ms to
recognize earlier children. It recovers all68,527 labels, and improves against an equally delayed baseline,
but the delay costs more than it recovers: versus the immediate baseline, MSE**+.006316/+.012618**. Noncausal
oracle and nonlinear OLS diagnostics remain in the reports;1-s nonlinear OLS extrapolates poorly and does not
justify a stronger performance claim. The primary five-arm results are unchanged in the extended reports.

No candidate or Rust strategy was changed. This feature change is dropped for now. The next user-directed
job is truth-validated identification of placement, impact and drift, then a75%/25% predictive gate and a
fast settings exporter for round4; the above50%/50% probe is not a substitute for that requested test.


## Filter identification checkpoint (8 Nov, 04:30 target)

The narrower job measures placement, impact and drift for the latent filter. All new code is offline;
no candidate bot or Rust strategy is changed. The process audit explicitly separates known-truth recovery
from estimation on public observations. Commands are in IDEAS.md's "Truth-first identification of the latent filter".
Artifacts live in `data/arena/gen/filter_process/` and `data/arena/gen/filter_placement/` in the main checkout.

- On r3b201-203, the oracle process fit recovers impact c=.047001, tau6.797-6.800s, diffusion3.987-3.994
  versus configured .047/6.8/4. The ordinary pre-impact F anchor covers the exact calm latent within half a
  tick on every audited observation. Injected orders and ambiguous rounded timestamps are treated separately.
- The public-observation fit recovers immediate synthetic impact within0.4%, but permanent c and decay tau
  are much less precise; conditional confidence intervals miss true c on two seeds. Five-to20-minute
  prefixes can give negative permanent c and tau near100s. These must not become exported process settings.
- On real R3, the observable impact model fails its heldout anchor-increment MSE gate:10.0019 versus9.9445
  for zero change. Requested-size impact beats filled-size on synthetic tapes, slightly loses on real tapes.
  All profiled real tau0.1-100s are within0.1% of minimum robust loss: decay is unidentified.
- Impact-adjusted1s anchor variance is .0566/18.00/27.79 ticks²/s on r1/r2/r3; R3's300s-block interval is
  [20.22,36.57]. This combines diffusion, jumps and anchor/model error. Synthetic recovery of total exogenous
  variance is98.1-99.3%; even calm synthetic prefixes show a positive rounding floor. Drift intervals all
  cross zero. Threshold exceedance rates are not latent jump rates. R3's5/10/20min variance7.83/14.14/29.11
  shows why a short-prefix estimate cannot establish a stable regime law.
- Placement uses G orders immediately before an ordinary F, within0.5/1/2/5ms, and the F-price interval
  `[price-sign-.5, price-sign+.5)`. Integrating its two possible floor states with a fixed half/half prior
  biases pi because the pre-G book already informs phase. EM learns that nuisance phase prior jointly from
  both sides, conditional on anchor-minus-bid and spread. Side-only reports freeze that joint prior.
  With the2ms window, fitted effective pi differs from exact safe latent labels by at most .00595/.00591/
  .00683 on201/202/203. Exact labels require the following10ms latent sample to precede every later insert;
  the audit excludes near-integer rounding ambiguities and assumes no unlogged standalone jumps.
- Existing F3 baseline is reproduced exactly:0.4s correlations .3043/.4053 and1s .2656/.3398 (first75/last25),
  insert score-1.20389. The current filter's `eps + pi` score is not a normalized probability over all prices,
  so optimizing eps by that score is invalid. The identification tool uses a normalized clamped price law.

A fitted placement/reference mixture is an observational hypothesis, not proof of two generator agents.
Near-F selection, F-price noise and hidden placement regimes can mimic it. The actual filter forecast gate
is required before suggesting new settings or structural changes. Until that result, retain F3's settings.
