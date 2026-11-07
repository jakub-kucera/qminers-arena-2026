# Round 3 handover (8 Nov)

The template (`docs/HANDOVER_TEMPLATE.md`): copy it to `data/arena/round<N>/HANDOVER.md` at the start of round N,
fill it in during the round and finish it by deadline − 0:10; the template itself stays as it is. Committed and pushed so the other laptop has it (ON_THE_DAY.md, "Handover note"); the private
run's results and `leaderboard.json` go in this folder too.

## Update 8 Nov 00:25: R2-L9 is the new base
- R2-L9 (`python/bots/qminers/candidates/r2_L9_taker_huber.py`, the stats session's last taker) made **+873,719 on round 2's validation tape** (submission bc0a2c50-d4bd-46ae-bc23-ee556d21ffe5, uploaded at the 00:14 deadline): +46.9k over R2-L8, +69.7k over R2-L3. It is L3's pure taker with a **Huber-robust fit** (HUBER_DELTA 6) and impact features at 500 ms (36 features).
- So round 3 starts from L9 (and L8's regime-switched quotes on top of it is the first combination to try), and a better learner (robust losses, then non-linear models) ranks above execution tweaks: every execution tweak tried on L3 lost or tied, while the robust fit gained +70k on validation.

## Start here (written 00:00, 8 Nov, from round 2)

Round 2's whole story is in `data/arena/round2/HANDOVER.md`, "Round 2 results, marked" (every upload, its validation score, what transferred). The short version: on the server's volatile tapes **the forecast taker won** (R2-L8, the forecast taker with quotes only in slow markets, +826,778 on validation; R2-L3, the pure taker, +804,018), the learned maker with size lost, big-order momentum worked (+376k to +468k), and the edge sits in the bursts.

### The first candidates to run on the new tape (all in `python/bots/qminers/candidates/`)
| Role | Bot | Round 2 validation | What it is |
|---|---|---|---|
| **Base** | `r2_L8_quote_switch.py` (R2-L8) | **+826,778** (round 2's final) | L1 with its one-lot quotes on only while the 5-s price speed is below QS_RATE 2.5 ticks/s: L3 in bursts, L1 in calm |
| Reference | `r2_L3_taker_pure.py` (R2-L3) | +804,018 | the 33-feature online ridge, 400-ms forecast, IOC takes within 100 lots, no quotes |
| Reference | `r2_L1_taker_liquidity.py` (R2-L1) | +771,770 | L3 with one-lot quotes (better on calm tapes) |
| Reference | `r2_H1_flow_bias.py` (R2-H1) | +567,740 | T1 + the big-flow bias (the composite) |
| Reference | `r2_M4_flow_window.py` (R2-M4) | +441,088 | the big-order follower, 125-ms window, self-gated (zero on calm tapes) |
| Reference | `r2_V2_vol_exposure_dz18.py` (R2-V2) | +71,864 | the learned maker with speed-scaled exposure (round 1's line; ~700k on round 1's calm tape) |

`uv run python -m experiments.day.round_start data/arena/round3/<file>.csv --jobs 8 --out data/arena/round3/round_start` ranks all of them (and the older families) on the new tape.

### The 15-minute triage
1. Move the tape to `data/arena/round3/`; `uv run python -m experiments.day.round_start <csv> --jobs 8 --out data/arena/round3/round_start` (profile: spread mix, touch depth, aggressor sizes and rates, markouts; every candidate ranked).
2. The tape's character: `uv run python -m experiments.day.tape_character profile <csv>` (the 1-s mid sd, the one-tick share, the big-order rate), `uv run python -m experiments.day.wide_spread <csv>` (does a wide spread predict size or direction), and the price speed (the mean |mid change| in ticks/s: round 1 1.23, round 2 3.22 with 1.56-7.43 per 600 s).
3. Build the validation-like stitched tapes from the new public tape's fast segments: `uv run python -m experiments.day.tape_character stitch <csv> --dir <dir> [--only hi_vol]` (round 2: they rated takers at ~0.9 of the server's level, flow bots at 0.62).
4. Run L8, L3 and L1 on the public tape, its mirror (prices 20,000 - p, sides swapped) and the stitched tapes; check the run time (L1 took 7 m 47 s on the server; limit 15 min).

### Decision table
| If the new tape is ... | Start from | Then |
|---|---|---|
| volatile like round 2 (price speed 2.5+ ticks/s, big moves after big orders) | **L8** (L3 beside it) | upload L8 first (after tuning QS_RATE); test the ideas below on the taker |
| calm like round 1 (about 1.2 ticks/s, one-tick spread 93%) | **L8** (quotes on) and **V2** / R1-C12's maker line | the maker earned ~700k on round 1; check quotes vs takes on the new tape's segments |
| mixed (calm stretches and bursts) | **L8** | tune QS_RATE (the speed threshold) on the public tape's first 75% |
| big orders move the mid well beyond the spread within 5 s | add **H1's bias** or **M4** as a reference | the composite (forecast + big-flow bias) won +77k in round 2 before the liquidity features came |
| different rules (limit, latency, penalty) | recompute the breach arithmetic first | every taker sizes against EXPOSURE with all live orders counted (TAKE_ROOM_LIVE 1) |

### Upload discipline (round 2's lessons)
- About 15 uploads a round (inferred: 5 left at 22:25 after ~10); **any submission can be marked final**, so an experiment costs one upload.
- Each upload is a **paired experiment** against the current best on the same validation tape: compare per-1,000-s segments of the two pnl.csv files (`data/arena/round2/*_res/pnl.csv`); a single score's noise is ~50k, a paired difference's much less.
- Switch the final only for a clear validation margin (~25k+) backed by the local tapes; with near-identical bots, the higher validation score is fine.
- **Mark the final before the deadline** (round 2's was 00:14/00:15 Prague, not 24:00): check the dashboard.

## Ideas to try in round 3 (ranked; each with its first experiment)
0. **Tune L8's quote switch on the new tape first** (it won round 2: +826,778): QS_RATE 1.5 / 2.5 / 3.5 ticks/s (`uv run python -m arena.qgrid python/bots/qminers/candidates/r2_L8_quote_switch.py <csv> --grid QS_RATE=1.5,2.0,2.5,3.0,3.5 --holdout 0.25`), chosen on the public tape's first 75%, checked on calm and fast segments separately and on the stitched tapes; then the 5-s window.
1. **A non-linear forecast for the taker.** Everything so far used a linear ridge. First: an online gradient-boosted or tree model (sklearn is allowed in the sandbox) on L3's 33 features, refit every N seconds on the matured labels, or trees pre-fitted on the public tape's first 75% and continued online; compare the take PnL on public / mirror / stitched tapes. Watch the run time (the server is ~1.75x slower).
2. **A profit-after-execution target.** The ridge predicts the mid's 400-ms move; the take decides on profit after paying half the spread and the 5-ms delay. First: label each sampled moment with the net PnL a 100-lot IOC at the far touch would have made 400 ms later (spread and latency included), fit the ridge on that, take when the predicted net PnL > 0.
3. **Separate entry and exit models.** The taker holds until the opposite take fires. First: a second ridge at a 2-5 s horizon that decides hold / close (flatten when it turns against the position while the entry model is silent); the jump exit (a crude stand-in) lost, so test against L3 on all tapes.
4. **Multi-horizon forecasts for the taker.** First: 100-ms and 1-s ridges beside the 400-ms one, their predictions as inputs or a blend; (makers' blends were tried in round 1; the taker only at single horizons: 300 / 400 / 600 ms).
5. **An ensemble with a recalibrated threshold.** Averaging L3's and L5's forecasts shrank them, so fewer takes cleared the fixed 0.15 bar (ensemble -36k to -80k on the fast tape). First: scale the averaged forecast back to the single model's variance, or lower TAKE_EDGE with it.
6. **The quote switch's own refinements**: a second speed threshold for the take's bar, or quotes two-sided only when the forecast is near zero.
7. **The stats session's absorbed-flow idea.** After a big buy, distinguish fresh sellers replenishing the ask (temporary pressure) from sellers withdrawing (continuation). First: two features (new ask lots at the touch within 250 ms after a 500+ lot buy, and ask cancels in that window), added to L3's ridge.
8. **Warm-starting the ridge from the public tape.** Worth ~3k on round 1's maker; the taker learns fast, so expect little; cheap to try (RIDGE_DUMP / RIDGE_WARM in the Rust ridge_maker).
9. **Rebuild round 2's private tape after the round** if its results come with full logs (`uv run python -m experiments.day.tape_from_logs RESULTS_DIR PUBLIC.csv OUT.csv`), and rank every round-2 bot on it: the best guide to what transfers.
10. **Find what the top teams had.** Round 2's 75th percentile reached 940k (best of ~7.5 uploads each). Read the organisers' deck (the PnL curves per team, if published) and the private leaderboard when it comes; compare curve shapes with L3's (it earns most in bursts).

## Uploaded
<!-- each upload: file, time, why; local PnL under all / worse / --resting; the metrics expected (arena.backtest --metrics) -->

## Portal against local
<!-- the portal's figures against our backtest of the same file on the same days; the ratio (T); which fill mode and mark fit -->

## Private run against public
<!-- the private (hidden) run's PnL against the public one, per product -->

## Fill model and mark
<!-- the engine settings that matched the portal: --resting/--queue, --match-trades, --mark, --limit-penalty, --fee -->

## Units map
<!-- exchange unit → engine unit (1 / PRICE_SCALE) → each product's tick; their timestamps → 0..999,900; where each limit comes from -->

## Rule answers
<!-- which ON_THE_DAY.md items the rules or probes answered (written under each item, with the source), and the ones still open -->

## Re-tests
<!-- which of last round's choices were tested again this round, which were kept untested ("Choose the approach again each round") -->

## Leaderboard
<!-- leaderboard.json saved here; experiments.day.leaderboard_curves --read verdict; our standing -->

## Next round
<!-- round N+1's first candidate, and its first three actions -->
