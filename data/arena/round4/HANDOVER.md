# Round 4 handover (8 Nov, 07:00-12:00)

The template (`docs/HANDOVER_TEMPLATE.md`): copy it to `data/arena/round<N>/HANDOVER.md` at the start of round N,
fill it in during the round and finish it by deadline − 0:10; the template itself stays as it is. Committed and pushed so the other laptop has it (ON_THE_DAY.md, "Handover note"); the private
run's results and `leaderboard.json` go in this folder too.

## Start here (written 8 Nov 04:50, before the tape)

Round 3 ended on R3-F5 or R3-F3 (whichever was marked final; data/arena/round3/HANDOVER.md, "Uploads"). On round 3's
validation tape: F5 +888,195, F3 +883,559, F1 +862,764, F4 +839,401, B1 +733,790. So the latent-price filter is worth +149,769 on
the server (F3 - B1), and F5's higher take bar away from jumps only +4.6k (a tie). Every other round-3 idea lost or tied
(round 3's "Dropped here").

### The first 30 minutes (Rust first; commands from the repo root)
0. Save the tape as `data/arena/round4/round4_public.csv` (unzipped). Below, `T=data/arena/round4/round4_public.csv`.
1. **Rank the round-3 bots in Rust (2 min):** `uv run python -m experiments.day.family_rust $T --jobs 8`. This runs T2, L1,
   L3, L8, L9, B1, F3, F4 and F5 and prints the first 75% and last 25%.
   - The filter's value on the new tape is F3 - B1 (round 3: +71k on its public tape, +150k on validation).
   - Start the Python first look beside it (6+ min): `uv run python -m experiments.day.round_start $T --jobs 6 --out
     data/arena/round4/round_start`. It gives the profile, the markouts, every candidate including R3-F5, F3, F4 and B1,
     and the next Rust grids.
2. **The filter's impact scale, the take bar and F5's jump rule, chosen on the first 75% (5 min).** In zsh:
   `F5=$(uv run python -c "import sys; sys.path.insert(0, 'python'); from experiments.day.family_rust import F5; print(F5)")`,
   then `uv run python -m arena.qsim_rust ridge_maker $T ${=F5} --grid FILTER_IMPACT=2,2.5,3 --grid FT_EDGE=0.15,0.2,0.25
   --grid FT_JUMP=0,3 --holdout 0.25 --threads 8 --sort holdout`. The best scale was x2 on round 2's tape (+22k) and x3 on
   round 3's.
3. **The tape's character, for the table below (in parallel):**
   - Speed and spread: `uv run python -m experiments.day.tape_character profile $T` (the price speed and the one-tick share).
   - Round 3's 2-ms ladders: `uv run python -m experiments.day.gen_ladders $T --cache data/arena/gen/r4_ladders.npz --json
     data/arena/gen/r4_ladders.json`.
   - The over-limit jump bet (1 min): `uv run python -m experiments.day.gap_burst $T --G 4,5,6,7 --hold 0.5,2 --jumps 20
     --jump-cfg 4:2,5:2,6:2,7:0.5`. Build a burst only if a cell nets positive and the filter fires ahead of most 20-tick jumps.
4. **The generator session's filter calibrator** (delivered 05:00, `python/experiments/day/filter_settings.py`, ~50 s):
   `uv run python -m experiments.day.filter_settings $T --minutes 20 --out data/arena/round4/filter_settings.json`. It
   keeps round 3's filter settings unless an alternative wins its held-out forecast gate; on round 3 all eight alternatives
   lost, the placement mixture included. Add any keys it exports to F5's line and compare in step 2's grid; use them
   only if they win both halves.
4b. **The warm start (R4-W1, round 3's private curves: our first 1,000 s was the weakest of the top 17):** save the base's
   ridge statistics on the public tape, `RIDGE_DUMP=data/arena/round4/r4_stats.txt uv run python -m arena.qsim_rust ridge_maker
   $T ${=F5} --threads 1`, and embed them in the upload file at PRIOR_MASS 1000 (`experiments.day.warm_embed`, being ported
   at 07:00). In Rust on r3b seeds 201-204 with round 3's statistics: +3.4k / +4.9k / +1.4k / +7.5k against F5, all in the first
   ~1,000 s (PRIOR_MASS 10000 about the same, 100000 loses).
5. **First upload by ~07:45:**
   - The base unchanged (F5, or F3 on a calm tape) as the paired reference.
   - Then step 2's winner as a Python file: copy the base and change only its constants. Check it against Rust: one
     Python run on `$T` must give Rust's PnL to the unit.
   - Then `uv run python -m arena.validate FILE all --format qminers`.

### Decision table
| The new tape | Start from | Why |
|---|---|---|
| Like round 3: volatile, ~30% of seconds at 5+ ticks/s, jumps, ladders | F5 | +888k on round 3's validation |
| Calm like round 1: ~1.2 ticks/s, a one-tick spread 93% of the time | F3 (bar 0.15, no jump rule) | F5's bar loses 24.8k on round 1; the filter still adds +14.5k to B1 there |
| Like round 2: volatile, no ladders | step 2's grid (FILTER_IMPACT by PnL on the first 75%) | impact x2 was +22k on round2_public; never F4: its likelihood-chosen impact lost 44,158 to F3 on round 3's validation |
| The filter loses (F3 < B1 on both halves) | B1 | the filter's model does not fit the new settings |
| Different rules (limit, latency, penalty) | recompute the breach arithmetic first | every taker sizes against EXPOSURE with its live orders |

### Tools from round 3 (each with its IDEAS.md row)
- `policy_search`: a CMA-ES over the take knobs; recipe in its docstring. In round 3 each search's gain stayed on the
  tapes it trained on (row "R3-P1"), so trust a point only if it wins both the real hold-out and the draws.
- `paired_rust`: paired 500-s segments between `--set` lines.
- `gap_burst`: step 3.
- `pretrain_forecast` with `rescale`: judge on held-out backtest PnL, not offline R^2 (three such gains became PnL losses in round 3).
- The F5 loss analysis (mid-based PnL, take holds, whipsaws): TODO.md, "F5 loss analysis tool".

### Leads still open
- **The generator session's placement finding:** about half of the real tape's new orders fit a placement relative to the
  visible touch, not the latent (held-out insert log-likelihood r3 -1.532 -> -1.451, r2 -1.063 -> -1.004; synthetic
  ~0.02-0.03). If its offline forecast test passes, put the mixture into F5's filter (Python and Rust). The filter
  sits at corr 0.40 against the true latent's 0.76 on synthetic tapes.
- **Round 3's private results and the teams' curves** (after 06:00): `experiments.day.leaderboard_curves`, as in round 2.
  The same shape as ours with a higher slope means a better forecast; a different shape means a different strategy.

### Upload discipline
**Round 4 allows 10 uploads** (the portal, ~07:15; round 3 used 7). Upload 1 (~07:10): `r4_W1_warm.py` with PRIOR_MASS 0, which is F5 exactly, so it is F5's validation score. Each upload is a paired test against the current base on the same
validation tape. A single run's noise is ~45k; switch the final only for a gain that also holds locally on both halves
of the public tape. Mark the final before 12:00.

## Round 4's tape and the first hour (07:00-07:15)
- **The tape** (`round4_public.csv`, 6,000 s, sha256 61c0b6d1...): the most volatile so far, 1-s mid sd 6.19 ticks (r3 4.49,
  r2 3.79), 60-s sd 59.2, net -445.5 / range 834.5, variance ratio 1.52, one-tick spread 81%. **Strong 1-5 s momentum**:
  after a trade the mid goes +1.42 / +2.41 ticks its way at 1 / 5 s (r3 +0.72 / +0.68); after a 1-tick mid move +2.81 / +6.16.
- **Ranking (Rust `family_rust`, confirmed for F5 by the organisers' Python simulator to the unit, 193 s):** F5 1,029,443
  (804,559 / 224,884), F4 1,026,780, F3 1,025,404, B1 907,100 (so the filter adds +118k, +13%), L8 901,311, L9 892,246,
  L3 851,547, T2 839,650, L1 827,782. Python first look (`round_start/report.txt`): momentum template 646,188, M4 554,443,
  M2 342,415, the taker -472,653, the runner -3.18M; every round-1 maker negative.
- **The filter calibrator** (`filter_settings.json`) kept round 3's settings (impact 3, round 1's pi, rate 2).
- **Nothing beats F5 on this tape** (all Rust, round4_public, against F5's 1,029,443):
  - filter impact 2-3.5 x take bar 0.15-0.3 x jump rule on/off: best +6.8k (impact 2, bar 0.3, no jump rule), neighbours ~F5;
  - horizons 0.7-2 s with bars up to 0.9: 1 s / 0.9 ties (-0.3k), the rest -15k to -87k;
  - a long second ridge blended (1-2 s, 30-50%): -48k to -255k; trend features -7.7k;
  - the jump rule (2/3/5 ticks, 5-30 s, edge 0.05/0.15, one-sided): best +14.2k (2 ticks), all of it in the first 75%;
  - no trading until 1k / 3k / 30k labels: -0.8k / -23.0k / -136.2k (and worse on r3, r2 and the seeds);
  - the warm start (R4-W1) with round 3's or round 4's own statistics: -1.7k to +0.3k.
  **So F5 unchanged is round 4's base and likely final.**

## Uploaded
| # | time | file | validation (12,000 s) | local r4 public (6,000 s) | read |
|---|---|---|---|---|---|
| 1 | 07:12 | `r4_W1_warm.py` at PRIOR_MASS 0 (= R3-F5 exactly; 1,029,443 on r4 public in Python too) | **+1,752,785** (se 56,235, breach 0, end +100 at 10,348; 94,615 fills / 1,111,284 lots; 10 min 9 s) | 1,029,443 | 146k per 1,000 s against the public tape's 172k (0.85x; round 3 0.87x). Per 1,000 s (k): 127, 169, 119, 101, 77, 95, 100, 142, 203, 219, 193, 207; max drawdown 13.3k; 4 25-s steps under -3k, 67 over +10k. Results folder `r4_W1_warm_res/`. |
| 2 | 08:04 | `r4_MH3.py` (F5 plus 100-ms / 0.6-s ridges as features; r4 public 1,042,419, +13.0k, 5/6 segments; round-4 synthetic +12.0k) | +1,736,913 (se 56,624; **13 min 35 s = 815 s of 900**) | 1,042,419 | **MH3 - F5 = -15,872** (7 of 12 1,000-s segments won, t -1.24; two -9k segments). The extra ridges cost 1.34x F5's server time. F5 stays the final: re-mark `r4_W1_warm.py` on the portal (the newest upload becomes final automatically). Results folder `r4_MH3_res/`. |
| 3 | 08:34 | `r4_W2_warm10k.py` (F5 with round 4's ridge statistics at PRIOR_MASS 10000) | +1,754,574 (se 56,200; 9 min 55 s) | 1,029,781 | **W2 - F5 = +1,789, a tie** (6 of 12 segments, t 0.67; every segment within +-2k; the first 1,000 s 126.5k against 126.7k: no slow start to fix on round 4). Results folder `r4_W2_warm10k_res/`. |
| 4 | 08:46 | `r4_X1R3.py` (F5 + wide-spread takes on strong signals + the filter at RATE 3, EPS 0.02, DEPTH 10; locally +23.3k on r4 with 6/6 segments, positive on all 8 tapes incl. the round-4 synthetic ones) | +1,724,973 (se 54,052; 10 min 7 s) | 1,052,756 | **X1R3 - F5 = -27,812** (2 of 12 segments, t -1.74; -15.7k and -6.5k in segments 9-10). Like MH3 (-9k in segments 10 and 12), it loses in the validation tape's last, most profitable third, where F5 makes 203-219k per 1,000 s: changes that add trades in fast markets lose there. **Final: W2 (+1,754,574, the round's best) or F5; re-mark it.** Results folder `r4_X1R3_res/`. |
| 5 | (to upload ~10:55) | `r4_W3_flow_depth.py` (W2 + FLOW2, signed flow over 0.1 s and 2 s as two ridge features, + R4-T1's depth take K 1 E 0.25; the warm start re-dumped with the 41 features, `data/arena/round4/r4_f2t1_stats.txt`, PRIOR_MASS 10000; Python = Rust 1,042,703, 42,919 fills, 159 s locally) | pending | 1,042,703 | Locally F2T1 - F5: r4 +9,976 (3/6 segments, t 0.87; mid tercile +12.2k, fast -2.1k, unlike MH3 and X1R3), r3 +2,980 (5/6, t 1.77), r2 +3,183, r1 +1,245, round-4 synthetic -6.0k / +9.8k / +10.5k, r3b seeds 201-210 +41,090 (6 of 10). **Keep W3 only if W3 - W2 is clearly positive (about +10k, most segments); else re-mark `r4_W2_warm10k.py`.** IDEAS.md, "R4-W3". |
<!-- each upload: file, time, why; local PnL; the validation PnL; the paired difference against the base per 1,000 s -->

## Portal against local
<!-- the validation tape against the public tape: PnL a second, fills and lots a second, as in round 3 -->

## Private run against public
<!-- after 12:00 -->

## Fill model and mark
The organisers' simulator as given (5 ms latency, FIFO). The PnL marks the position by walking the book
(simulator/simulator.py:1359), not at the mid, so a blown-out spread shows as a dip.

## Units map
Ticks and lots as in the tape; the position limit 100 (penalty 10,000/s beyond it, a continuous integral), orders refused past 1,000.

## Rule answers
<!-- anything new this round -->

## Re-tests
<!-- which round-3 choices were tested again on round 4's tape -->

## Leaderboard
<!-- leaderboard.json saved here; experiments.day.leaderboard_curves --read verdict; our standing -->

## Next round
None: round 4 is the last.
