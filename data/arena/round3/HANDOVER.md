# Round 3 handover (8 Nov)

The template (`docs/HANDOVER_TEMPLATE.md`): copy it to `data/arena/round<N>/HANDOVER.md` at the start of round N,
fill it in during the round and finish it by deadline − 0:10; the template itself stays as it is. Committed and pushed so the other laptop has it (ON_THE_DAY.md, "Handover note"); the private
run's results and `leaderboard.json` go in this folder too.

## Start here (8 Nov 02:55; round 3 closes 06:00, round 4 runs 07:00-12:00)

**The best file, and the one to keep as final: R3-F3** (`python/bots/qminers/candidates/r3_F3_latent_filter_b1.py`): R3-B1
(R2-L9's Huber-ridge forecast taker plus R2-L8's one-lot quotes only in slow markets) with the latent-price filter's three
ridge features. **+883,559 on round 3's validation tape** (590 s of the 15-min limit), 505,212 on round3_public.csv.
Check it is marked final on the portal before 06:00.

- **Reproduce in Rust (byte-identical to the Python file):** `uv run python -m experiments.day.family_rust
  data/arena/round3/round3_public.csv --bot B1F=B1:'--set FILTER=1'` (505,212); any knob: `uv run python -m arena.qsim_rust
  ridge_maker CSV <B1's --set line from family_rust.py> --set FILTER=1 --grid K=a,b --holdout 0.25`.
- **How to judge on round 3:** validation played like the public tape (0.87-0.90x its PnL a second, the same fills and
  lots a second; round 2's validation was the faster volatile half instead). So rank on round3_public, its last 25% as
  the holdout; the stitched tapes (`tape_character stitch`) overstate; the synthetic tapes (`data/arena/gen/r3b/`) only
  as a third check.
- **Standing:** the organisers' dashboard at 01:49: round 3's 75th percentile ~785-812k, median ~503k, so F3 is in the
  top ~15-20%; overall after two rounds we are 12th of 61 (0.8 z1 + z2 = 1.368; 5th is 2.847, 1st Team 2 3.507).
- **Another session works on the tape generator** (started from `docs/GENERATOR_SESSION_PROMPT.md`, in its own worktree
  and branch `gen-v3`): recovering the generator's model and settings from every tape and our validation PnL curves, a
  better round-3 preset (`data/arena/gen/r3c/` when ready) and the round-4 playbook (fit a new public tape in ~10 min,
  then generate look-alikes). It reports to this session by SendMessage; merge its branch when it says.
- **This session's full conversation** (every decision, number and agent report of round 3; JSONL, large: grep it,
  don't read it whole): `/Users/jakubkucera/.jakub.claude/projects/-Users-jakubkucera-Documents-qminers-arena/85c5a0de-831c-45d8-96d5-c489d86fe959.jsonl`.
- **No agents of this session are running;** every branch is merged into main (98e6d54).

### Uploads (validation tape, 12,000 s; folders in this directory; the table in CANDIDATES.md, "Uploads")
| # | time | file | validation | local r3 public | note |
|---|---|---|---|---|---|
| 1 | 01:24 | `r3_F1_latent_filter.py` (L9 + filter) | +862,764 | 480,469 | 563 s server time |
| 2 | 01:46 | `r3_F3_latent_filter_b1.py` (B1 + filter) | **+883,559** | 505,212 | +20.8k over F1, all in the calmer segments where the quotes switch on |

### What round 3 established (details and commands in the IDEAS.md rows named)
- **The tape:** round 2's generator again, a bit more volatile (68% of 60-s blocks volatile; 389 jumps of 3+ ticks in
  6,000 s). R2-L8 is the robust base on round 3's own tapes; R2-L9's Huber/impact features cost ~10% on the volatile
  stitched tapes ("Round 3's first look: the family on its own tapes").
- **The latent-price filter** (a hidden-Markov filter of the price new orders are placed around) adds +11% to +29% on
  every base and tape, both halves, and +7-23% on round 1 ("A filter of the generator's hidden fair price"). Its own
  settings are at their best at the defaults (impact x3, rate 2, round 1's placement); a jump-aware version and
  regime-switched placement lose on the real tape.
- **The generator** ("The tape generator's structure", "Calibrating the generator to round 2's validation scoreboard"):
  a latent price moved by c*sqrt(lots) per market order; calm and volatile regimes; jumps in the volatile one; market
  orders priced off the latent. tape_gen v2 ranks round 2's 14 validation bots at Spearman 0.974; preset
  `r3_public_after` ranks round 3's six public scores at 0.60 (pure takers ~7% too high). Its jumps are cleaner than the
  real tape's: the true latent would predict the 0.4-s move at corr 0.76 against the filter's 0.40 on synthetic tapes,
  but the real tape's latent is not recoverable the same way.
- **Dropped here (each with numbers in its row):** burst sizing over the 100-lot limit (the far side is thin after a
  jump; never pays, "Burst sizing on R2-L9"); a pretrained MLP/HGB forecaster, frozen or stacked (+94 on the held-out
  last 25%; synthetic training data hurts; "A pretrained forecaster of the 400-ms move"); S1 gap maker and S2 quiet
  maker (positive alone, +48k / +32k, but cannot share the 100 lots with the taker), S4 hybrid (-139k), S3 jump catch
  (+77k alone, round-3-shaped); a reduce-only early exit FT_EXIT and a wide-spread exit (ties or losses; "R3-F3's
  loss anatomy"); the QS_RATE x FT_EDGE grid on L8 (flat).
- **Where the PnL is:** 82% of it from 3 s before a jump to 10 s after; every kind of take earns on average (the
  riskiest states most); the losses are jumps against a full position ("Round 3's tape: where money can be made").
- **Side results for round 4:** the Rust feature dump (`RIDGE_FEAT_LOG`, 30 s a tape); a numpy online ridge that makes
  F3 10% faster with identical PnL (R3-P2's file with `PRE = 0`); `experiments.day.family_rust`.

### Next (in order)
1. Keep F3 final. A spare upload: plain R3-B1 (`r3_B1_huber_quote_switch.py`) measures the filter's real gain on the
   server (F3 - B1), worth knowing for round 4.
2. The untested direction the statistics agent left: more size or a lower take bar just after jumps or while inserts
   land wide (where takes earn most); burst sizing lost, so it is a weak lead.
3. Round 4 at 07:00: copy `docs/HANDOVER_TEMPLATE.md` to `data/arena/round4/`; run `family_rust` with the FILTER bases on
   the new public tape (F3's base first); ask the generator session to run its playbook on it; upload F3 first as the
   paired base.

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


**Status of the ideas above at 02:55:** 0 done (the QS_RATE x FT_EDGE grid is flat on round 3); 1 done (pretrained
MLP/HGB, frozen and stacked: no held-out gain; an online tree model untested); 2 untested; 3 partly (FT_EXIT, a
reduce-only exit, dropped; a separate 2-5 s exit model untested); 4, 5 and 7 untested; 6 done (B1's quotes inside the
filter bot are F3; a sized gap quote, S4, fights the taker); 8 untested (frozen models only win in-round); 9 not
possible (no private logs for round 2); 10 done (Team 1 bet over the limit on jumps; our simulator's thin post-jump
book makes that lose).

## Uploaded
See "Start here", "Uploads"; the folders `r3_F1_latent_filter_res/` and `r3_F3_latent_filter_b1_res/` are here.

## Portal against local
Validation (12,000 s) against the local public tape (6,000 s): F1 0.90x and F3 0.87x the public PnL a second; fills and
lots a second 0.94-0.96x. F3 minus F1: +20.8k on validation against +24.7k locally on half the length (about half the
expected gain). Server time F3 / F1 1.05x, as locally (1.06x).

## Private run against public
Not yet (after 06:00).

## Fill model and mark
The organisers' simulator as given (5 ms latency, FIFO, mark at the end); the Rust port reproduces it byte for byte.

## Units map
Ticks and lots as in the tape; the position limit 100 (penalty 10,000/s beyond it), orders refused past 1,000.

## Rule answers
Nothing new this round.

## Re-tests
Round 2's L-family re-ranked on round 3's own tapes ("Round 3's first look"); L9's choice did not carry over (L8 base).

## Leaderboard
Round 3's live percentiles from the organisers' dashboard (01:49): p25 176k, median 503k, p75 785k; overall 12th.

## Next round
First candidate R3-F3; its three first actions are in "Start here", "Next" item 3.

## History (written before and early in round 3)

## Update 8 Nov 00:25: R2-L9 is the new base
- R2-L9 (`python/bots/qminers/candidates/r2_L9_taker_huber.py`, the stats session's last taker) made **+873,719 on round 2's validation tape** (submission bc0a2c50-d4bd-46ae-bc23-ee556d21ffe5, uploaded at the 00:14 deadline): +46.9k over R2-L8, +69.7k over R2-L3. It is L3's pure taker with a **Huber-robust fit** (HUBER_DELTA 6) and impact features at 500 ms (36 features).
- So round 3 starts from L9 (and L8's regime-switched quotes on top of it is the first combination to try), and a better learner (robust losses, then non-linear models) ranks above execution tweaks: every execution tweak tried on L3 lost or tied, while the robust fit gained +70k on validation.

## Update 8 Nov 00:45: the takers in Rust (fast grids)
- The Rust `ridge_maker` reproduces R2-T2, L1, L3, L8 and L9 to the byte on `round2_public.csv` (pnl.csv, result.json; `test_ridge_maker_round2_takers`): 10-13 s a run against 140-180 s in Python, 4 threads a grid. The `--set` line of each is in `rust/README.md` ("R2-T2 ... R2-L9") and `rust/arena_sim/src/strategies/ridge_maker.rs`'s doc comment; L9's is L3's and `--set POSITION_LIMIT=100 --set IMPACT_US=500000 --set HUBER=6.0 --set RIDGE_MIN=30 --set RIDGE_FRAC=0.003`.
- First look (public tape only, not a choice): L9 with L8's quote switch (`--set QUOTE_SIZE=1 --grid QS_RATE=1.5,2.5,3.5`) 325,171 / 318,954 / 322,695 against L9's 317,057 (in 75% 253,490 / 250,191 / 253,836 against 248,287); HUBER 4 / 6 / 9 317,046 / 317,057 / 316,329.

## Rule for round 3: Rust first (8 Nov, 01:05)
- Round 2's last 90 minutes ran every L-family test in Python (2-6 min a run) because the winners' Rust twin was only built after midnight; batches of 5 cells instead of hundreds. Now T2, L1, L3, L8 and L9 are in the Rust ridge_maker byte for byte (10-13 s a run; the --set lines in rust/README.md and this file's fast-grid note).
- So: grid every setting in Rust (`uv run python -m arena.qsim_rust ridge_maker CSV --threads N <sets> --grid ...`); use Python only for the final check of the file to upload. The moment a new bot wins on validation, start an agent porting its change to ridge_maker while the round goes on.

## Start here before the tape (written 00:00, 8 Nov, from round 2)

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

