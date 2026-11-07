# Round 2 handover (7 Nov, 19:00-00:00)

The template (`docs/HANDOVER_TEMPLATE.md`): copy it to `data/arena/round<N>/HANDOVER.md` at the start of round N,
fill it in during the round and finish it by deadline − 0:10; the template itself stays as it is. Committed and pushed so the other laptop has it (ON_THE_DAY.md, "Handover note"); the private
run's results and `leaderboard.json` go in this folder too.

## Round 2's public tape against round 1's (19:20, `data/arena/round2/round2_public.csv`, ignored by git; `uv run python -m experiments.day.round_start data/arena/round2/round2_public.csv --jobs 8 --out data/arena/round2/round_start`)
- **The same order flow:** 6,000 s (half of round 1's 12,000), 2,193,064 rows; G inserts 178/s (round 1 180), F (IOC) 8.9/s (8.0), F sizes median / p90 / p99 61 / 367 / 1,543 (61 / 360 / 1,543), G sizes 14 / 143 (the same); touch depth median 878 lots (1,065).
- **A different price process:** the mid changes 4.85 times a second (round 1: 2.57); the spread is 1 tick 83.9%, 2 ticks 11.6%, 3+ 4.4% (93 / 7 / 0); the price wanders about 550 ticks (10,000 -> 9,850 -> 10,000 at 3,000 s -> 9,480 at 4,200-4,500 s -> 9,765 -> 9,689 at the end; round 1's whole range was 107 ticks). Moves persist: after a trade the mid moves +0.44 ticks its way at 1 s and +0.39 at 60 s (trades over 58 lots +0.69 / +0.97); after a 1-tick move with no trade +0.60 at 1 s, +0.95 at 5 s, +1.47 at 60 s.
- **Every round-1 bot loses on it** (round_start, the files at their defaults, full / first 75% / last 25%): R1-C1 -219,331; R1-C5 -247,210; R1-C11 -263,201 (breach 6,999); R1-F8 -86,391; R1-F3 -216,175; the momentum runner -3.4M; pmaker -3,110, A0 -14,584, F1 -22,272 (barely trading). In Rust: R1-C12 -261,847, R2-FT1 (C12 + the forecast take) -88,432.
- **What works so far: less inventory.** R2-FT1 with EXPOSURE 30 (the hedge sells back above 30 lots) and DEAD_ZONE 0.3: +28,418 (in 23,430 / out 4,988, breach 0); the plateau EXPOSURE 20-45 x DEAD_ZONE 0.3-0.45 x FT_EDGE 0.1-0.25 is in 21-23.6k, full 28-35k (`results/r2_ft_grid2.csv`).
- **Run time:** R1-C11 took 121 s on this 2.2M-row tape under load, so about 240 s on a 12,000-s validation tape, and 2-3x that on a slower server: check every candidate's run time before uploading.

## The organisers' deck, round 2 so far (read 22:35; the shared deck's embedded data, as of 20:31 Prague)
- 36 submissions (33 completed, 1 failed) from 20 teams. Each team's best validation PnL so far: median 55,268, 25th percentile -15,878, 75th percentile 386,684 (just after our R2-M2's 376,082 at 20:28 the 75th percentile read 391,985; before it, 343,614 at 20:25). With 20 teams the 75th percentile sits between the 5th and 6th best, so about five teams' best was at or above ~387k: our 376,082 is roughly 6th by best validation score at 20:31. Our E2 (-41,499, 19:54) and V2 (+71,864, 20:12) appear in the series at their times, so the series is the validation score in Prague time.
- The deck labels the deadline "Round 2 submission deadline (00:15 Prague time)"; check the dashboard's own countdown before relying on it.
- The public tape's stats in the deck: start 10,000, end 9,689.5, high 10,007.5, low 9,455, one-tick share 0.84, 2,193,064 events, 197,588 trades, 6,999,892 lots.

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
- **The organisers' restatement (18:45):** three backtests. (1) **Public**: downloaded from the website, for training; **about half the length** of the other two. (2) **Validation**: every submission is run on it on the server, and we get **only the PnL, no logs**. (3) **Private**: the score, run after the deadline. Validation and private keep round 1's size (round 1's tapes were 12,000 s). Consequences:
  - the public tape is ~6,000 s: the first 75% to choose on is ~4,500 s, so use `pnl_segments --count 6` (or `--seconds 1000`) and expect noisier choices; prefer structural changes and learned weights over tuned constants even more than in round 1;
  - nothing in the bots depends on the length (SESSION_S 1e9, no wind-down), and the online model learns on each tape, so the shorter public tape costs only the warm-up's share;
  - compare an upload's validation PnL with **twice** its public PnL (the same rate per second); round 1's private run kept 0.93-0.98 of the public rate, so a ratio well under ~0.9 means overfit to the public tape;
  - no validation logs, so `tape_from_logs` can't rebuild the validation tape; it still works on any full-logs results folder we get (the private one after the deadline, if given).
- **Three datasets** (the user, from the organisers, 7 Nov ~18:00): (1) the public tape, local as in round 1; (2) on upload the portal runs a **private** tape, so an upload's score is no longer the public replay (round 1's portal was byte-identical to a local run); (3) after the round closes the final score comes from **another, different private** tape. So the portal's score on upload is an out-of-sample check, but the final is a third draw: use the upload score as a holdout of *the strategy family*, not as a tuning target (picking the best of many uploads by their private score overfits that tape just as tuning on the public one does).

## Re-tests
<!-- which of last round's choices were tested again this round, which were kept untested ("Choose the approach again each round") -->

## Leaderboard
<!-- leaderboard.json saved here; experiments.day.leaderboard_curves --read verdict; our standing -->

## Next round
<!-- round N+1's first candidate, and its first three actions -->

## Start here (18:25, from round 1)
- **Upload first:** `python/bots/qminers/candidates/r2_base_v5.py` (R1-C11, every constant at the top of the class) once round_start has run it on the new tape; then `r2_safe_v5.py` (no breach possible) as the second, different upload. Their two portal (private-tape) scores against their local ones are the first out-of-sample check.
- **What round 1's private tape said** (rebuilt from the portal's log, `uv run python -m experiments.day.tape_from_logs RESULTS_DIR PUBLIC.csv OUT.csv`; C12 reproduced within 0.07%): every ridge candidate kept 94-98% of its public PnL, F8 93%. The steps that generalised: C1 -> C5 (the in-flight cancels, the hedge, the 400-ms horizon; +41k public, +56k private) and the flow groups (C5 -> C9, +10k / +17k). The knob steps under ~10k (the cap, the quote features) moved the private PnL by noise. So on round 2: trust structural changes and the learned weights, distrust public gains under ~10k from constants.
- **Fast tuning:** `arena.qsim_rust ridge_maker D <R1-C11's --set line, round_start prints it> --grid ...` (~3 s a run, byte-identical to the Python files).
- **Which family** if the tape differs: the table "If the tape looks like X" at the end of this file (thin touch, big sweeps or informed flow: R1-F8 beside the ridge; 2-tick-heavy, deep, trending or weak impact: the ridge).
- **After each upload's portal log:** rebuild that private tape with `tape_from_logs` and rank the round's candidates on it.

## Experiments to run on round 2's tape
Round 2 is generated differently, so round 1's settings are priors, not answers. D = `data/arena/round2/<file>.csv` (unzip first). `C5` below = `--set POSITION_LIMIT=1000 --set EXPOSURE=100 --set CANCEL_FREE=1.0 --set HEDGE=1 --set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000 --set DEAD_ZONE=0.18` on `uv run python -m arena.qsim_rust ridge_maker D --threads 6 --holdout 0.25` (Rust, ~3 s a run; defaults = R1-C1).

### Protocol (every experiment)
- **The portal's score is a private tape (round 2 on).** Keep a table: each upload's local public PnL against its portal (private-tape) PnL. A strategy whose ratio holds across uploads generalises; one that loses its edge on the private tape is overfit to the public one. Upload few, different candidates (e.g. the safe one, the base, one tuned variant) rather than many near-copies, and choose the final by local evidence plus that ratio, not by the highest single private score.
- Choose only on the first 75% (`in_pnl`), prefer the centre of a flat neighbourhood; then check once: the last 25%, `uv run python -m experiments.pnl_segments NEW/pnl.csv BASE/pnl.csv` (12 segments), the paired block bootstrap. Round 2's own CSV only.
- Replacement bar against the current best: about +9k full, +4.5k on the last 25%, ahead in 8 of 12 (scale them by the new tape's pnl_se).
- A Rust pick becomes a Python file that matches Rust to the cent (`uv run exchange-simulator --strategy FILE --backtest D --log-dir logs/X --no-logs`), then `uv run python -m arena.validate FILE all --format qminers`, run time well under 900 s. Upload a safe candidate in the first hour; the final by T-15 min.

### Triage (the first 15 minutes)
1. `uv run python -m experiments.day.round_start D --jobs 6`: the spread mix (1 vs 2+ ticks), touch depth, aggressor sizes and rate, markouts after trades, the file's length; every candidate ranked.
2. Side by side on D: R1-C9 (`r1_C9_codex_v4_flow_groups.py`), R1-C5, R1-F8b, and the no-learning control (`C5 --set MIN_LABELS=1000000000`). The gap C5 minus control says what learning is worth on this tape.
3. `uv run python -m experiments.day.latent_price D`, `uv run python -m experiments.day.spread_episodes D`, `uv run python -m experiments.day.tape_gen --fit D --params-out logs/r2_params.json`: is there still a hidden price the inserts lead, how long 2-tick episodes last, the arrival rates.
4. Check the rules: the limit, the penalty, the latency and the acceptance wall (the hedge and EXPOSURE depend on them).

| If the tape shows | Start from |
|---|---|
| mostly 1-tick spreads, learning worth a lot (C5 >> control) | the ridge line: R1-C9 / C5, then experiments 1-10 |
| learning worth little (C5 ~ control) | the hand-built maker R1-F8b and its Rust grid (`take_maker`); the ridge only for its forecast |
| 2-tick-heavy spreads | re-grid INSIDE_TH and DEAD_ZONE first; the sweep join (F7's MOM_JOIN) and price-improving inserts matter more |
| moves after a trade beyond the spread within ~50 ms (round_start's short markouts) | reconsider takers (momentum taker, burst taker within the limit) |
| a different penalty, limit or latency | recompute the breach arithmetic (cost per breach = penalty/s x latency) before keeping CANCEL_FREE and HEDGE; EXPOSURE = the new limit |
| trending or regime changes within the hour | shorter MODEL_MEMORY_US, inventory skew (SKEW_K), an online change-point guard |
| several instruments | one model per instrument first; cross-instrument features later |

### Experiments (priority 1 = first)
| # | Pri | Experiment | Command / knobs | Tests | Keep if |
|---|---|---|---|---|---|
| 1 | 1 | Port v4's flow-group features to Rust (`ridge_maker`, a `FLOWGROUP` knob) | match `r1_C9_codex_v4_flow_groups.py` to the cent on round1 (605,752.82) | makes R1-C9 griddable | parity exact |
| 2 | 1 | Horizon x dead zone x inside on the new tape | `C5 --grid HORIZON_US=100000,200000,400000,600000,1000000 --grid DEAD_ZONE=0.1,0.14,0.18,0.22,0.26 --grid INSIDE_TH=0.2,0.3,0.4` | round 1's plateau moved? | the bar |
| 3 | 1 | Learning's value and memory | `C5 --grid MIN_LABELS=200,1000000000 --grid MODEL_MEMORY_US=30000000,300000000,100000000000` | is the generator stationary? | informs the memory |
| 4 | 1 | Pipelining and the hedge | `C5 --grid CANCEL_FREE=0,0.5,1.0 --grid HEDGE=0,1 --grid HEDGE_TICKS=1,3,10` | does a cancel still land first; breach cost | the bar, penalty counted |
| 5 | 1 | The learned dead zone | `C5 --set FILL_LEARN=1 --set FILL_H_US=400000 --set FILL_MIN=-0.2 --set FILL_WARM=200 --set FILL_BIN=0.1 --grid FILL_MIN=-0.3,-0.2,-0.1,0` | a dead zone without a grid | ties or beats exp. 2's best (robustness) |
| 6 | 2 | Slow placement features (C6) | `C5 --set PLACE=1 --grid PLACE_US1=300000,400000,700000 --grid PLACE_US2=1000000,3000000` | does the placement share pay at slow constants here | the bar |
| 7 | 2 | Second model blended | `C5 --grid BLEND_W=0.2,0.4,0.6 --grid H2_US=100000,200000,1000000` | two horizons | the bar |
| 8 | 2 | Event-time label (C7's) | its branch `worktree-agent-a15d341eebc469bba` (`LABEL_MODE`, `LABEL_K`, `PRED_SCALE`), merge first | next-change target | the bar |
| 9 | 2 | Other features at the new horizon | `C5 --grid DEPTH5=0,1 --grid FLOW2=0,1 --grid LAST_AGG=0,1 --grid STD=0,1` | slower features at 400 ms | the bar |
| 10 | 2 | Quote size and exposure | `C5 --grid QUOTE_SIZE=100,200,300 --grid EXPOSURE=90,100 --grid MAX_ORDERS=4,8` | room usage | the bar |
| 11 | 2 | Inventory skew | `C5 --grid SKEW_K=0,0.01,0.025,0.05,0.1` | a trending tape needs it | the bar |
| 12 | 2 | F8's take on the ridge, sized against EXPOSURE (fix first: it sized against the 1,000 wall) | `C5 --set TAKE_LOTS=30 --grid TAKE_OWN=400,800 --grid TAKE_DEPLETE=150,250` | dying-touch take on top of the forecast | the bar, penalty counted |
| 13 | 2 | Ridge strength and refit speed | `C5 --grid RIDGE_MIN=1,3,10,30 --grid FIT_US=250000,1000000 --grid OBSERVATION_INTERVAL_US=10000,20000,50000` | model fit settings | flat on round 1; re-check only |
| 14 | 3 | Queue-position fill value (Moallemi & Yuan; `IDEAS.md`, "Learner ideas from the wiki's literature") | `C5 --set FILL_LEARN=1 --grid FILL_Q=50,200,1000` | step back only the orders at a bad queue place | the bar |
| 15 | 3 | Robbins-Monro learned offsets (Fernandez-Tapia) | new Rust knobs: DEAD_ZONE and INSIDE_TH updated from each period's realised fill markouts, step n^-0.6, Polyak averaging | learned execution | ties exp. 2's best |
| 16 | 3 | Book exhaustion rate (Zhao & Linetsky) | new feature: decayed aggressor lots per second / touch lots, bid minus ask | adverse-selection gauge | the bar |
| 17 | 3 | Cancel-only OFI (Sitaru et al.) | new feature from order ids in the snapshots: lots that left the touch without a trade | decomposed flow | the bar |
| 18 | 3 | A Kalman latent price from insert placements (Das 2005; the generator's latent mid) | new feature: filtered price from where inserts land, minus the mid | the hidden fair value | the bar |
| 19 | 3 | A logistic next-change classifier (Gould & Bonart) | exp. 8 with LABEL_MODE 2, or a separate logistic model blended | direction target | the bar |
| 20 | 3 | Hand-built line on the new tape | `uv run python -m arena.qsim_rust python/bots/qminers/candidates/r1_F8_take_join.py D --grid SIZE_NARROW=60,115,200 --grid DEPLETE_LOTS=50,100,200 --grid DEPL_FRAC=0.06,0.12,0.25 --threads 6 --holdout 0.25` | the fallback if learning fails | beats the ridge line |
| 21 | 3 | Generator check | `uv run python -m experiments.day.tape_eval --params logs/r2_params.json --real D --seeds 1-30` | can generated tapes rank candidates on this round | F7-vs-F6-type pairs rank as on the real tape |
| 22 | 3 | Ceilings on the best candidate | `uv run python -m experiments.day.ceilings logs/<best full-logs run>` | where the remaining money is (queue place, room, taking) | guides the next idea |
| 23 | 4 | Takers, only if triage shows fast moves | `families/momentum_taker.py`, `families/burst_taker.py` grids (IDEAS rows) | a trending or impact-heavy tape | the bar |
| 24 | 4 | A nonlinear model (sklearn is allowed), if the run time allows | small online tree / kNN on the 23 features, blended | nonlinearity | the bar and run time < 300 s |

## If the tape looks like X
From `IDEAS.md`, "Which round-1 strategy survives which change of tape" (6 draws a regime of round 1's fitted generator,
`experiments.day.tape_regimes`). The draws tie C5, C1 and F8 on the unaltered model (real round 1: C5 > C1 > F8), so
read these as which family to start from, then choose the knobs on round 2's own tape. Learning paid in every regime
(C5 +65-396k over its never-learning control) and the hedge's breach penalty stayed small (C5's 16k at worst).

| If the tape looks like (round_start's profile) | Start from | Draws |
|---|---|---|
| a 2-tick spread most of the time | the ridge, not F8: C1, or C5 with HORIZON_US 100000 | C1 +65k over C5; C5 +153k over F8 |
| a thin touch (~1/4 of round 1's ~900 lots) | F8 (`take_maker`) | F8 +167k over C5 |
| a deep touch (~4x) | C5, DEAD_ZONE 0.25 | C5 +94k over F8; dz 0.25 +48k |
| twice the IOC rate | C5 and F8 tie; C5 with HORIZON_US 100000 or DEAD_ZONE 0.25 | +47k / +39k over C5 |
| big IOC orders sweeping 2+ levels | F8 | F8 +271k over C5 |
| a trend (strong impact, more buys than sells) | C5 as it is (not HORIZON_US 100000: -69k) | C5 +42k over F8, +63k over C1 |
| weak impact, a flat mid | C5 or C1 (F8 far behind) | C5 +319k over F8 |
| IOC orders that predict the next move | F8, then C5 with DEAD_ZONE 0.25 | F8 +27k over C5 |
