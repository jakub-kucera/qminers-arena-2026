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
