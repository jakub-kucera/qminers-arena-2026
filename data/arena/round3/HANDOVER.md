# Round 3 handover (8 Nov)

The template (`docs/HANDOVER_TEMPLATE.md`): copy it to `data/arena/round<N>/HANDOVER.md` at the start of round N,
fill it in during the round and finish it by deadline − 0:10; the template itself stays as it is. Committed and pushed so the other laptop has it (ON_THE_DAY.md, "Handover note"); the private
run's results and `leaderboard.json` go in this folder too.

## Round 3 result (read 8 Nov 06:48 from the portal's leaderboard, Round 3, private backtest)
- **17th of 53, +827,253 private** with R3-F3 (validation +883,559: private/validation 0.94). Winner Team 1 +1,458,005;
  2nd Team 3 1,240,532; 3rd Team 2 1,198,048; 10th 929,224; median of the 52 positive teams ~745k.
- **z3 = 0.467** (mean 694,136, sd 284,949 over the 52 positive teams). **Overall after three rounds (0.8 z1 + z2 + z3,
  z1/z2 from the organisers' deck): 15th of 61, 1.835;** 1st Team 1 5.918, 5th Team 5 3.893 (gap 2.06).
  Round 4 weighs 1.2: a top-3 round 4 (z4 ~1.8-2.7) is worth +2.2-3.2.
- `leaderboard.json` here (the round-2 file's format; no PnL series). The teams above us made ~0.9-1.46M: the same gap
  as round 2 (our family is the field's middle-upper band; the leaders take more from the jumps).

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
| 3 | 02:57 | `r3_B1_huber_quote_switch.py` (F3 without the filter) | +733,790 | 433,922 | the filter on the server: F3 - B1 = **+149,769 (+20.4%)**, against ~+124k expected from the local +71,290 (+16.4%); round 4 starts from the filter bots |
| 4 | 03:22 | `r3_F5_jump_bar.py` (F3 with a 0.25 take bar, 0.15 for 5 s after a 3-tick jump) | +888,195 | 515,670 | F5 - F3 = +4,636, a tie (9 of 12 1,000-s segments, t 0.51); loses ~25k on round 1's calm tape |
| 5 | 04:34 | `r3_F4_filter_bank.py` (F3 with the impact scale chosen online by likelihood) | +839,401 | 512,175 | F4 - F3 = **-44,158**: choosing the filter's impact by likelihood loses on the server |
| 6 | 05:00 | `r3_F10_blend150.py` (F5 plus a 150-ms ridge, 50/50) | +818,039 | 535,244 | F10 - F5 = **-70,156**: shorter horizons lose on the server (the r3b seeds said so) |
| 7 | 05:20 | `r3_F6c_policy_s3_const.py` (F5 with the policy search's search-3 constants) | +868,327 | 518,573 | F6c - F5 = **-19,868** (the seeds said +51.6k); **F5 is the final** |

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
  loss anatomy"); the QS_RATE x FT_EDGE grid on L8 (flat); after 03:00: a burst over the limit triggered by the
  filter's gap (every cell loses on both real public tapes; with the true latent only ~+20k a synthetic tape; "A
  gap-triggered burst over the limit"), a ladder-order selector in the filter (FILTER_LADDER, loses the first 75%),
  the filter variants and R3-F4's filter bank ("A better state for R3-F3's latent-price filter").
- **Where the PnL is:** 82% of it from 3 s before a jump to 10 s after; every kind of take earns on average (the
  riskiest states most); the losses are jumps against a full position ("Round 3's tape: where money can be made").
- **Side results for round 4:** the Rust feature dump (`RIDGE_FEAT_LOG`, 30 s a tape); a numpy online ridge that makes
  F3 10% faster with identical PnL (R3-P2's file with `PRE = 0`); `experiments.day.family_rust`.

### Next (in order)
1. Keep F3 final. (Done 02:57: plain R3-B1 made +733,790, so the filter earns +149,769 on validation.) Plain R3-B1 (`r3_B1_huber_quote_switch.py`) measures the filter's real gain on the
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
Round 3's private leaderboard (pasted from the portal at ~06:25; `leaderboard.json` here): **we are 17th of 53 with +827,253**, R3-F5's
private run against its +888,195 on validation (0.93x; round 2's final went 873,719 -> 742,470, 0.85x). 52 teams profitable: mean
694,136, median 729,472, sd 287,729 (the sample sd matches the dashboard's round-2 z of 0.398), so **our z3 = 0.463**. The top:
Team 1 1,458,005 (z 2.68, first again after round 2's 1,875,116), Team 3 1,240,532, Team 2 1,198,047, Team 4 1,134,420,
Team 6 1,073,870, Team 7 1,071,858; 10th 929,224. The top six made 1.30x-1.76x our PnL, about round 2's ratio (1.6x-2.5x),
so the gap narrowed but stayed. Round 3's weight is 1.0, as round 2's (the user, 8 Nov ~06:35), so our total is 0.8 x 1.212 + 0.398 + 0.463 = **1.831, 15th of 61**
(teams with no round-3 result counted at z 0); 10th has 2.276, 5th 3.883; Team 1 5.89, Team 2 5.26, Team 3 4.81 lead.

## Fill model and mark
The organisers' simulator as given (5 ms latency, FIFO, mark at the end); the Rust port reproduces it byte for byte.

## Units map
Ticks and lots as in the tape; the position limit 100 (penalty 10,000/s beyond it), orders refused past 1,000.

## Rule answers
Nothing new this round.

## Re-tests
Round 2's L-family re-ranked on round 3's own tapes ("Round 3's first look"); L9's choice did not carry over (L8 base).

## Leaderboard
Round 3's live percentiles from the organisers' dashboard (01:49): p25 176k, median 503k, p75 785k. Final: 17th of 53,
z3 0.467, overall 15th of 61 (1.835); `leaderboard.json` here ("Round 3 result").
At 02:38 (the dashboard's data, 40 teams, 84 submissions, 3 failed): the best validation PnL a team, p25 289k, median
546k, p75 848k (868k at 02:33); the field is rising, F3's +883,559 is 35k over p75. At 03:26 (47 teams, 137
submissions, 8 failed): p25 391k, median 606k, p75 876k, so F3 is 7k over p75. Our private results so far
(team ThatsMyQuant): round 1 602,527 (8th of 61), round 2 742,470 (22nd of 59; 10th had 1,017,551, 5th 1,195,019);
overall 12th, z1 1.212 + z2 0.398 = 1.368 (total = 0.8 z1 + 1.0 z2, z over the round's profitable teams).

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

## Audit (8 Nov)

An independent check of round 3's record against main at 659515d, 02:50-03:30; every command and number is in
IDEAS.md's row "Round 3 audit".

**The record reproduces.** In Rust on round3_public: L3 425,321, L8 427,819, L9 424,730, B1 433,922, F3 (B1F) 505,212,
F1 (L9F) 480,469, L3F 490,181, L8F 484,057, each to the unit; the Python F3 full-logs run 505212.00. The hand-merged
`ridge_maker.rs` (98e6d54) changed no default: BURST_*, FILTER_JUMP, FILTER_VQS and FT_EXIT* are inert at their
defaults, every round-3 experiment's base line reads 505,212, and `test_arena_rust.py` passes.

**Experiments whose conclusion could flip on the right base** (largest plausible PnL first; `$F3` is
`family_rust.B1` and `--set FILTER=1`):
1. **FT_EDGE on F3.** R3-F1's row kept 0.15 on a 0.7k holdout difference on the stitched hvf tape, which this handover
   says overstates. On F3, 0.25 wins on r3 public (+6.2k) and on r3b seeds 201-203 (+16.3k / +14.8k / +3.8k), both
   halves (in 75% +30.4k, out 25% +10.7k); 0.35 loses on two seeds. Over the four tapes 0.15 / 0.2 / 0.25 / 0.3 /
   0.35 make 3.499M / 3.526M / 3.540M / 3.516M / 3.465M (0.2 and 0.25 ahead on all four), but on r3 public alone the
   paired 500-s segments give t +0.60 (5 of 12 won), seed 202's 1,000-s ones t +1.48 (8 of 12): consistent in
   sign, not significant on any one tape. Plausibly
   +5-15k on a 12,000-s validation tape. The fix is one constant, F3 with `TAKE_EDGE = 0.25`; that needs a new
   candidate file, so the audit did not write one. Re-test: `uv run python -m arena.qsim_rust ridge_maker data/arena/round3/round3_public.csv data/arena/gen/r3b/seed20{1,2,3}.csv $F3 --grid FT_EDGE=0.15,0.2,0.25,0.3 --holdout 0.25`.
2. **QS_RATE on F3.** Only gridded on L8 without the filter (the "QS_RATE x FT_EDGE grid on L8 (flat)" above, whose
   numbers were nowhere: now in the audit row). On F3: 3.5 +3.2k (both halves), 3.0 +1.3k, 5.0 +2.3k, 2.0 -9.0k,
   always on -16.6k. On r3b seeds 201-203 3.5 loses 22-25k a seed (381k fills against 122k: the draws quote far more
   at 3.5, and makers are unvalidated there). Keep 2.5. Re-test: `... $F3 --grid QS_RATE=2.5,3.0,3.5,5.0` on the same tapes.
3. **S3 (jump catch) with the taker**, dropped above as unable to share the 100 lots, never run. As a jump take inside
   F3 within the limit (BURST_JUMP 5 in 200 ms, BURST_EXP 100): +3.0k (first 75% +5.1k, last 25% -2.1k), max drawdown
   15.0k to 7.7k; 3 ticks -5k to -12k. A tie. Re-test: `... $F3 --set BURST_EXP=100 --set BURST_JUMP_MS=200 --set BURST_GAP_MS=2000 --set BURST_THRU=1 --set BURST_MS=0 --grid BURST_JUMP=4,5,6`.
4. **The quiet-trade take within the limit** (the burst row's control on B1F, +5.6k on r3 public, all in the last 25%):
   on r3b seeds 201-203 -325 in total. A tie.
5. **The FILTER base.** B1F was "the best FILTER base" on the whole public tape but is third on its last 25% (126,880
   against L3F 132,240, L8F 130,021). On r3b seeds 201-203 B1F leads L3F by 10-20k and L8F by 16-34k: F3 stays.
6. **Burst sizing over the limit**: grids 1, 2 and 4 ran on L9 without the filter, only the quiet trigger on B1F. The
   penalty's arithmetic does not depend on the base, so a flip is unlikely (no re-test).
7. **S4** (taker plus the gap quote) ran on F1, not F3; S1-S3's correlations are against R2-L8. Descriptive only.

On the right base already: the FILTER settings, FILTER_JUMP, FILTER_VQS, FT_EXIT / FT_EXIT_WIDE and R3-P2 (each on
B1F at 505,212).

**F3's order handling** (r3 public, the Python full-logs run and the Rust twin's prediction log,
`experiments.day.quote_audit`): nothing worth fixing.
- 0 orders refused, breach 0; |position| at 100 54% of the time, 90-99 28%. 243,871 orders, 191,323 cancels, 512
  cancels too late: 510 one-lot fills after our cancel was sent, -1.0k at 5 s.
- Quotes: 47,795 one-lot fills, +0.41 a lot at the fill and +0.35 / +0.55 at 5 / 30 s (+16.7k / +26.3k). 199 filled
  while QS_RATE's switch was off (resting from before): -1.1k; cancelling them at the switch (Rust `QS_PULL` 1) costs
  9.7k. 3,872 filled with the filter's gap 0.5+ against them: -0.62 a lot at 1 s but +0.47 at 5 s; withdrawing that
  side (`QUOTE_GAP` 0-1.0) costs 4-7k. DEAD_ZONE and KEEP_TH are at their top (others -6k to -10k).
- Takes: 563,769 lots, +0.90 a lot at 5 s. The quotes' reserve costs at most a lot a take (8,051 lots fewer than F1,
  -1.4%), and the limit's bound binds anyway at POSITION_LIMIT = EXPOSURE = 100. Fills arrive synchronously and an IOC
  in flight is reserved, so no take is sized on a stale position. FT_THRU 1 -95.5k, FT_GAP_MS 20 -11.0k.
- On validation the quotes made about 111k extra fills for +20.8k (0.19 a fill) against 48.7k for +24.7k locally
  (0.51): their edge a fill there was ~40% of the local one. The results folders hold only pnl.csv, so the cause is
  not visible; the run's full logs on the portal, if offered, would show it.

**Record fixes.** CANDIDATES.md's Rust FILTER bullet (01:40) moved from the R3-S section to R3-F1's. The QS_RATE x
FT_EDGE grid's numbers are in the audit row. "Dropped here" above lists S1-S3, whose IDEAS.md rows say `measured`:
only S1 was combined with the taker (as S4); S3 inside F3 is a tie (item 3); S2 was never combined.
