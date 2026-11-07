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
