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
4. **The generator session's filter settings tool**, if delivered (`data/arena/gen/gen_v3_handoff.txt`, deliverable C,
   due 06:45): run it on `$T`, add its `--set` keys to F5's line, and compare in step 2's grid. Use it only if it wins
   both halves.
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
About 15 uploads a round (round 3 used 4 by 05:00). Each upload is a paired test against the current base on the same
validation tape. A single run's noise is ~45k; switch the final only for a gain that also holds locally on both halves
of the public tape. Mark the final before 12:00.

## Uploaded
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
