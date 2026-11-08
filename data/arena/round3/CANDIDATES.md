# Round 3 candidates (8 Nov)

The template (`docs/CANDIDATES_TEMPLATE.md`) for the improvement loop's state (`KICKOFF_PROMPT.md`, "The improvement
loop"): copy it to `data/arena/round<N>/CANDIDATES.md` once the round's first upload has completed, fill in "Round",
and leave the template as it is. The loop reads this file at the start of every iteration and writes it at the end,
so a compacted or restarted session, or the other laptop, picks up where it was. Committed (`.gitignore` keeps it).

## Round
- Deadline <HH:MM>; freeze <HH:MM> (deadline − 0:30, or − 2E if that is longer); E = <minutes an evaluation took>.
- T = <the engine's error, from the first upload: HANDOVER.md, "Portal against local">.
- Data: D = <folder>, DAYS = <...>. Training: <days>. Held out: <day, or the last 25%>, never used to choose a setting.
  Repeats checked (`experiments.prosperity.structure`): <none | which days repeat which>.
- The gate: `--modes <...> --gate <first|every> --holdout <...>`; scenarios still possible: <`--scenario ...` | none>.
- Calibrated settings (the plug-in's `ENGINE`, from `experiments.prosperity.calibrate`): <... | refused: why>.
- Scoring: `0.8·z1 + z2 + z3 + 1.2·z4`, each round's private PnL standardised over the teams with positive PnL, a zero or
  negative PnL scored as 0 (ON_THE_DAY.md, "How is PnL scored?"); this round's weight: <0.8 | 1.0 | 1.2>.
- Uploads left: <n>. The spending rule's budget of disagreeing scores left: <2> (ON_THE_DAY.md, "Spend the round's
  submissions by a rule written before the first score").
- The final rule, written now: <default: StepM's pick from `arena.compare` over the verified candidates against A0
  under the gate; between candidates within T of each other, the better stress worst, then the fewer changed settings>.

## Ready before the tape (00:00, from round 2)
- Base: `python/bots/qminers/candidates/r2_L8_quote_switch.py` (R2-L8: quotes only below 2.5 ticks/s of price speed; **+826,778 on round 2's validation, the round-2 final**), with `r2_L3_taker_pure.py` (R2-L3, +804,018) beside it. First experiment: QS_RATE on the new tape.
- References: `r2_L1_taker_liquidity.py` (+771,770), `r2_H1_flow_bias.py` (+567,740), `r2_M4_flow_window.py` (+441,088), `r2_V2_vol_exposure_dz18.py` (+71,864 on round 2's volatile tape, ~700k on round 1's calm one).
- `experiments.day.round_start` runs all of them (R2_L8, R2_L3, R2_L1, R2_H1, R2_T2, R2_M4, R2_V2); the triage, the decision table and the ranked ideas: `data/arena/round3/HANDOVER.md`, "Start here".

## Board
At most six live candidates; each must differ in kind from the others (the loop's step 2). Every number comes from a
command in "Trials". Pluses and minuses are measured facts, not hopes.

| id | file | what it is | pnl per gate mode | held out | worst day | stress worst | max dd | \|pos\| 99.7% | relies on | pluses | minuses | verified | portal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0 | <the first upload's file> | the baseline, as uploaded | | | | | | | | | | n/a | <score> |

## Dropped
<!-- id, why (with the numbers), the iteration -->

## Queue
<!-- the next experiments, best first. Each is pre-registered before it runs: id; the mechanism (why it should work in
this market, one line, from this data); the exact command; the training days; the rule that keeps it. -->

## Trials
<!-- every experiment run, in order: time; id; command; cells or bots tried; result; kept or dropped; commit -->
Trials so far: 0 experiments, 0 cells.

## Verifier verdicts
<!-- each verifier's report, verbatim, under the candidate's id and the time -->

### Ready before the tape (8 Nov 00:50): R3-B1 (`python/bots/qminers/candidates/r3_B1_huber_quote_switch.py`)
- R2-L9 (the Huber-robust pure taker, +873,719 on round 2's validation) plus R2-L8's one-lot quotes switched on only while the 5-s |mid change| rate is below QS_RATE 2.5 ticks/s; QS_RATE 0 is L9 exactly. validate OK, 29.9 KB.
- L9 / B1 (pnl; breach 0 everywhere; local run time): round2_public 317,057 / 318,954 (150 / 179 s); the mirror the same; round1 134,626 / **206,648** (+72k); hi_vol_fast1.25 1,020,848 / **999,473** (-21k); hi_vol 867,369 / 876,974 (+10k).
- The quotes pay on calm tapes and cost on the fastest one, more than they did on L1/L8: on a fast round-3 tape start from L9; on a calmer one from B1; grid QS_RATE (1.0-3.0) on the new tape first.

### R3-F1 (8 Nov 01:25): the latent-price filter in L9's ridge (`python/bots/qminers/candidates/r3_F1_latent_filter.py`)
- R2-L9 plus three ridge features from a hidden-Markov filter of the generator's latent reference bid: gap = E[lb] + 0.5 - mid, gap*|gap|/3, and the posterior sd. New market orders say where lb is (bids at lb - k, asks at lb + 1 + k, k 0/1/2, clamped one tick off the other touch), and market takers' fills move it by 3x tape_gen's impact table. FEATURE_COUNT 39. FILTER = 0 is L9 to the unit. validate OK, ~36 KB. The offline copy is `python/experiments/day/latent_filter.py`; the measurements are in IDEAS.md's R3-F1 row.
- F1 / L9 (pnl; breach 0 everywhere): **round3_public 480,469 / 424,730** (+55.7k; 500-s segments won 7/11, t +1.57; first 75% +46.2k, last 25% +9.5k); round2_public 303,720 / 317,057 (-4.2%); round 2's hi_vol_fast1.25 1,012,787 / 1,020,848 (-0.8%); round1 152,188 / 134,626 (+13%).
- Local run time on r3 205 s vs 187 s (+10%), about 360 s on the server. It trades more: 572k lots vs 460k on r3.
- Next: round 3's stitched tapes (running), TAKE_EDGE 0.3 on F1 and L9 (running), the Rust port behind a FILTER knob, then the sqrt-impact variant.
- 01:40, in Rust (`ridge_maker --set FILTER=1`; the Python F1's pnl.csv and result.json byte for byte on round2_public). FILTER 0 → 1, r3 public / hi_vol_fast1.25 / hi_vol / pub+mirror: L8 427,819 → 484,057 / 1,155,238 → 1,349,326 / 912,583 → 1,109,338 / 881,280 → 980,757; L3 425,321 → 490,181 / 1,181,416 → 1,330,385 / 904,944 → 1,092,788 / 876,078 → 983,281; L9 424,730 → 480,469 / 1,043,787 → 1,305,805 / 827,555 → 1,067,643 / 851,070 → 965,316; B1 433,922 → **505,212** / 1,048,313 → 1,323,666 / 853,801 → 1,107,567 / 872,624 → 1,008,798. F1 on validation: **+862,764** (0.90x the public tape's rate).

### R3-F2 (8 Nov 01:40): R2-L8 plus the filter (`python/bots/qminers/candidates/r3_F2_latent_filter_l8.py`)
- L8 (L1's one-lot quotes below QS_RATE 2.5, the plain ridge, POSITION_LIMIT 1000 / EXPOSURE 100) plus R3-F1's filter code and three features (FEATURE_COUNT 36). FILTER = 0 is L8. validate OK. Rust: 484,057 on r3 public, 1,349,326 on hi_vol_fast1.25. The Python parity run is next.

## Uploads (validation tape, 12,000 s; results folders in data/arena/round3/<file>_res/)
| # | time | file | validation pnl | fills / lots | sim time | local r3 public (6,000 s) | read |
|---|---|---|---|---|---|---|---|
| 1 | 01:24 | `r3_F1_latent_filter.py` (R3-F1 = R2-L9 + FILTER) | **+862,764** (se 46,223, breach 0, end -17 at 10,035) | 8,173 / 1,073,759 | 9 min 23 s | 480,469 (4,277 / 571,820) | per 1,000 s 72k against the public tape's 80k (0.90x); fills and lots a second 0.95x / 0.94x, PnL a lot 0.80 against 0.84: **the validation tape looks like another draw of the public tape's regime**, not round 2's faster volatile half (round 2: validation 1.38x the public rate). Per 1,000 s: 78, 44, 111, 19, 97, 68, 95, 55, 121, 45, 72, 57k; max dd 23k; 38 one-second PnL steps over 2k (public: 15 in 6,000 s). So rank on the public tape first; the stitched hi_vol_fast1.25 overstates. Sim time 63% of the 15-min limit. |
