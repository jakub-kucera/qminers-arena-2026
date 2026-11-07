# Round 1 candidates (7 Nov, 13:00-18:00)

The template (`docs/CANDIDATES_TEMPLATE.md`) for the improvement loop's state (`KICKOFF_PROMPT.md`, "The improvement
loop"): copy it to `data/arena/round<N>/CANDIDATES.md` once the round's first upload has completed, fill in "Round",
and leave the template as it is. The loop reads this file at the start of every iteration and writes it at the end,
so a compacted or restarted session, or the other laptop, picks up where it was. Committed (`.gitignore` keeps it).

## Round
- Deadline 18:00 (the user, from the dashboard); freeze 17:30; E = ~1 min (R1-F3's simulation took 1 min 2.8 s): the last upload starts by 17:35, 17:45 at the latest.
- T = 0 on the public data (the portal is byte-identical to `exchange-simulator`; ON_THE_DAY.md, "From the playground"); recheck on the first upload.
- Data: D = data/arena/round1/<file>.csv (unzipped: `uv run python -m gzip -d`), one hour, one instrument. Training: the first 75% of the hour. Held out: the last 25% (`arena.qgrid --holdout 0.25`), never used to choose a setting. Repeats: none possible (one file).
- **SESSION_S / SESSION_US from the file's length** (round_start prints it), on the long side if the private hour may be longer: F2 with SESSION_S 3598 on the 5,750 s sample_v2 wound down after an hour and made +136k instead of +213k.
- The gate: their simulator, no fill model to choose; a change is kept only if it beats its parent on the first 75% and on the last 25%.
- Calibrated settings: none needed (their own simulator).
- Scoring: `0.8·z1 + z2 + z3 + 1.2·z4`, each round's private PnL standardised over the teams with positive PnL, a zero or negative PnL scored as 0 (ON_THE_DAY.md, "How is PnL scored?"); this round's weight: 0.8.
- Uploads left: 10. The spending rule's budget of disagreeing scores left: 2 (with T = 0 a public score only confirms the local run; it says nothing about the private hour).
- The final rule, written now: the verified candidate with the best last-25% PnL among those that beat A0 on both parts of the hour and stay within the limit with no breach; between two within 5% of each other, the one with the smaller max drawdown and the fewer settings changed from its file's defaults. A market-making candidate is preferred over a momentum one only if round_start's verdict is not MOMENTUM.

## Board
At most six live candidates; each must differ in kind from the others (the loop's step 2). Every number comes from a
command in "Trials". Pluses and minuses are measured facts, not hopes.

| id | file | what it is | pnl per gate mode | held out | worst day | stress worst | max dd | \|pos\| 99.7% | relies on | pluses | minuses | verified | portal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0 | python/bots/qminers/candidates/r1_F3_full_room.py | F3 with SESSION_S 1e9 (never winds down) | +425,553 (one file) | +110,540 | 899 | | 899 | 100 | a 1-tick market where trades barely run (round_start: WEAK, +0.22 ticks at 5 s) | first by far on round 1 (F4 +399k, F2 +273k, F1 +29k; momentum -1.3M to -5.7M); imbalance/depletion filters only cut volume | at +-100 most of the time (q50 98); ends at +100 | n/a | +425,553 (identical) |
| R1-F6 | python/bots/qminers/candidates/r1_F6_two_levels.py | R1-F5 + a second level (LEVELS 2, KEEP_DEPTH 2, SIZE_TOUCH 65, SIZE_DEEP 80, SIZE_NARROW 115, TOPUP 1), chosen on the first 75% (356,715) from a 27-cell plateau | +483,074 | +126,359 | | | | 100 (q50 42) | a 1-tick market (round 1's) | +27k full, +11k last 25%, 4/4 quarters over R1-F5; half the inventory (q50 42 against 95), pnl_se 8,867 | -35k on sample_v2 (a 2-tick market): fails the cross-check | n/a | |
| R1-F5 | python/bots/qminers/candidates/r1_F5_shrink_react.py | F3 + a shrinking-level guard (DEPLETE_LOTS 100, DEPL_FRAC 0.06) + REACT_CANCEL 1, chosen on the first 75% (340,516) | +455,822 | +115,306 | | | | 100 | as A0, minus fills from levels being eaten | +30k over A0 on the full tape and +4.8k on the last 25%; +8.3k over F3 on sample_v2 (271,947); plateau over 75-150 lots | the last-25% gain is below half pnl_se | n/a | |
| M1 | python/bots/qminers/candidates/r0_M1_runner.py | the momentum runner, sample's best cell (flow entry, 3-tick trail, ±100) | sample +297,208 | sample +67,065 | | | 1,115 | 100 | the tape's aggressive trades continuing for seconds | biggest on the sample, broad plateau | at ±100 all hour; flips pay the spread on 200 lots; lost 1.7M on a non-momentum synthetic tape | re-measure | |
| R2 | python/bots/qminers/families/momentum_runner.py --set FLOW_WINDOW_MS=2000 | the runner with a 2 s flow window | sample +305,374 | sample +71,955 | | | 987 | 100 | as M1 | less flip churn | as M1 | re-measure | |
| T1 | python/bots/qminers/template.py, the momentum PARAMS (lin_momentum 2 / 20 events, take_edge 2.5, clear_edge -1, make_size 0, limit 100) | the template as a momentum taker | sample +211,414 | sample +43,034 | | | | 100 | momentum over 20 events | the template's guards (limit, flatten) | windows count events, not time | re-measure | |
| P1 | python/bots/qminers/families/protected_maker.py | market maker that pulls quotes after aggressive trades | sample +2,018 | sample +2,592 | | | | 27 | a market that doesn't run after trades | the test of whether making pays here | barely fills on the sample | re-measure | |
| F2 | python/bots/qminers/candidates/r0_F2_maker_v2.py | F1 with QUOTE 100, SKEW 80, LIMIT 100: join the touch, keep the queue place | sample_v2 +212,831 (portal identical) | sample_v2 +48,200 | | | 232 | 100 | a market where trades don't run (sample_v2) | no adverse selection on sample_v2, linear PnL, 44 s on the server for 2M rows | -25k to -28k where markets trend (sample 1, ABIDES); sits at the limit 5% of the time | uploaded on the playground | +212,831 |
| F1 | python/bots/qminers/candidates/r0_F1_fallback.py | small market maker in their style, ±50 | sample -5,877 | sample -445 | | | | 24 | a spread worth earning | simplest, safe | picked off in momentum | n/a | |

## Dropped
<!-- id, why (with the numbers), the iteration -->

## Queue
<!-- the next experiments, best first. Each is pre-registered before it runs: id; the mechanism (why it should work in
this market, one line, from this data); the exact command; the training days; the rule that keeps it. -->
1. round_start (pre-registered: no choice made from it beyond which families to grid). `uv run python -m experiments.day.round_start D --jobs 10 --out data/arena/round1/round_start`. Mechanism: tells momentum from reversion on this tape (the mid's move 1/5/30 s after an aggressive trade).
2. If round_start says MOMENTUM: the runner's grid, `uv run python -m arena.qgrid python/bots/qminers/families/momentum_runner.py D --set SESSION_S=<len> --grid MIN_FLOW=<1,median,p90> --grid TRAIL_TICKS=2,3,5 --grid MAX_POS=50,100 --grid FLOW_WINDOW_MS=0,500,2000 --holdout 0.25 --jobs 10 --sort holdout`. Keep: beats A0 on both parts, no breach, its neighbours within 20%. Mechanism: aggressive trades on this tape are followed by a move their way for seconds.
3. Whatever the verdict: the protected maker's grid (`--grid PULL_MS=0,500,2000 --grid OFFSET=-1,0,1 --grid QUOTE=5,10`), as the test of whether resting quotes pay on recorded data. Mechanism: if the move after a trade doesn't continue, the spread is worth earning when quotes step out of the way of the trades.
4. The template as a momentum taker (`arena.qgrid python/bots/qminers/template.py D --set 'PARAMS.ASSET={...T1...}' --set SESSION_US=<len µs> --grid PARAMS.ASSET.lin_window=10,20,50 --grid PARAMS.ASSET.lin_momentum=1,2 --grid PARAMS.ASSET.take_edge=1.5,2.5 --holdout 0.25`), only if 2 confirms momentum.

## Trials
<!-- every experiment run, in order: time; id; command; cells or bots tried; result; kept or dropped; commit -->
Trials so far: 0 experiments, 0 cells.

## Verifier verdicts
<!-- each verifier's report, verbatim, under the candidate's id and the time -->
