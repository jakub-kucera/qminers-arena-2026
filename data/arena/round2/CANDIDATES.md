# Round 2 candidates (7 Nov, 19:00-00:00)

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

## Ready before the tape (18:15, from round 1)
Three files in `python/bots/qminers/candidates/`, R1-C11's model, every tunable constant at the top of the class with a
comment (LIMIT, POSITION_LIMIT the 1,000 wall, CANCEL_FREE, HEDGE, HEDGE_TICKS, DEAD_ZONE, INSIDE_TH, FLOW_CUT,
HORIZON_US, MODEL_MEMORY_US, QUOTE_SIZE, ...): change one there if round 2's rules move. round1.csv only
(`uv run exchange-simulator --strategy FILE --backtest data/arena/round1/round1.csv --log-dir logs/x --no-logs`, ~3 min
each); `arena.validate FILE all --format qminers` OK for all three. Segments: `experiments.pnl_segments` against B5.

| id | file | round1 pnl | penalty | fills | against B5 | use it when |
|---|---|---|---|---|---|---|
| R2-B5 | `r2_base_v5.py` | 619,281.99 | 1,610 | 21,460 | = R1-C11 to the cent | the default: rules unchanged (limit 100, 10,000/s, 5 ms) |
| R2-S5 | `r2_safe_v5.py` | 605,983.00 | 0 | 35,071 | -13.3k, behind in 12 of 12 (t -4.64) | no breach possible: the penalty is harsher, latency longer, or B5's hedge misbehaves on the portal |
| R2-L5 | `r2_learned_dz_v5.py` | 611,454.62 | 1,526 | 22,343 | -7.8k, ahead in 4 of 12 (t -2.13) | not as the upload on round1's evidence; a cheap second look if round 2's tape is 1-tick and B5's fills mark out worse |

- R2-S5: CANCEL_FREE 0.0, HEDGE False: every live order, being cancelled or not, counts toward LIMIT (R1-C1's rule), so
  inventory + one side's orders never pass it, and nothing crosses the spread.
- R2-L5: the Rust ridge_maker's FILL_LEARN (FILL_Q 0) ported line for line, FILL_H_US 400000, FILL_MIN -0.2, FILL_WARM
  200, FILL_BIN 0.1; FILL_LEARN False gives B5. The port, checked on R1-C5's base, reproduces
  `uv run python -m arena.qsim_rust ridge_maker data/arena/round1/round1.csv --set POSITION_LIMIT=1000 --set EXPOSURE=100
  --set CANCEL_FREE=1.0 --set HEDGE=1 --set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000 --set DEAD_ZONE=0.18
  --set FILL_LEARN=1 --set FILL_H_US=400000 --set FILL_MIN=-0.2 --set FILL_WARM=200 --set FILL_BIN=0.1` to the cent
  (597,805.83, 21,975 fills, penalty 1,770.17). On C5 it was +2.4k over C5 (595,442); on v5's 29 features it costs 7.8k:
  the richer forecast already does what the learned zone did.

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

### R2-E1, 19:35 (`python/bots/qminers/candidates/r2_E1_low_exposure.py`): the first round-2 upload
- R2-FT1 (R1-C12 + the forecast take) with its literals named; EXPOSURE 30 (the hedge sells back above 30 lots), DEAD_ZONE 0.3, the take at 0.25 ticks over half the spread, 200 lots, one per 50 ms.
- round2_public.csv (`uv run exchange-simulator --strategy python/bots/qminers/candidates/r2_E1_low_exposure.py --backtest data/arena/round2/round2_public.csv --log-dir logs/e1 --no-logs`): pnl 28,418.00 (first 75% 23,430 / last 25% 4,988), 14,068 fills, breach 0, |inv| q997 30; byte-identical to the Rust ridge_maker; 81.6 s (about 165 s on a 12,000-s tape; limit 900 s); validate OK.
- Chosen on the first 75% from a plateau (EXPOSURE 20-45 x DEAD_ZONE 0.3-0.45 x FT_EDGE 0.1-0.25: in 21-23.6k). Every round-1 bot loses on this tape (R1-C11 -263k, R1-F8 -86k).
- Expect the validation PnL near twice the public (about 57k) if the tape is the same kind; much less means the regime differs.

### 19:45: exposure x dead zone x queue-keeping on three tapes (Rust ridge_maker, R2-FT1's sets; `--grid EXPOSURE=30,100 --grid DEAD_ZONE=0.18,0.3 --grid KEEP_LOTS=0,20 --set KEEP_TH=0.3 --holdout 0.25`)
| EXPOSURE / DZ / KEEP | round 2 public (in / out) | round 1 public | round 1 private (rebuilt) |
|---|---|---|---|
| 30 / 0.18 / 0 | 31,066 (19,871 / 11,195) | 290,938 | 282,541 |
| **30 / 0.18 / 20** | **47,098 (35,094 / 12,004)** | 294,949 | 287,960 |
| 30 / 0.3 / 0 (R2-E1) | 28,418 (23,430 / 4,988) | 287,058 | 281,395 |
| 30 / 0.3 / 20 | 47,311 (34,673 / 12,638) | 287,948 | 280,843 |
| 100 / 0.18 / 0 (R2-FT1) | -88,431 (-76,201 / -12,231) | 688,311 | 663,746 |
| 100 / 0.18 / 20 | -87,574 | 699,697 | 684,271 |
- The exposure is the regime choice: 30 lots wins on round 2's trending tape and costs ~400k on round 1's; the validation upload tells which regime the server's tapes are. Queue-keeping (KEEP 20) adds +16-19k on round 2 at exposure 30 and +4-20k on round 1 at 100. R2-E2 (30 / 0.18 / KEEP 20) is being written as a Python file.
- The momentum agent (interim, 19:37): holding 100 lots on the side of the last 500+ lot aggressor makes +118,374 on round 2 public (in 97,133 / out 21,241; pnl_se 30.6k), flat over MIN_LOTS 333-650 (`r2_M2_flow_trend.py`, in its worktree): big orders move the mid +1.3-2.0 ticks by 5 s on this tape (round 1: +0.5).

### R2-E2, 20:05 (`python/bots/qminers/candidates/r2_E2_low_exposure_keep.py`)
- R2-E1 + R2-Q1's queue-keeping (on the dead-zone step-back, the touch order is shrunk to KEEP_LOTS 20 by modify instead of cancelled while the forecast toward its side is at least -KEEP_TH 0.3); EXPOSURE 30, DEAD_ZONE 0.18.
- round2_public.csv: pnl 47,098.00 (first 75% 35,094 / last 25% 12,004), 18,012 fills, breach 0, |inv| q997 30; byte-identical to the Rust ridge_maker; 90 s (about 180 s on a 12,000-s tape); validate OK.
- On round 1's tapes (Rust, the same sets): 294,949 public, 287,960 rebuilt private (EXPOSURE 100 there makes ~690k): it bets on the trending regime.

### R2-E3, 20:20 (`python/bots/qminers/candidates/r2_E3_conf_exposure.py`, the inventory agent's; it named it R2-E2)
- R2-E1 with a confidence-dependent exposure: EXPOSURE 50, but a side's quoting may reach only CONF_EXP 10 lots unless the forecast its way is at least CONF_TH 0.05 ticks; the take, the skew and the hedge keep the 50. DEAD_ZONE 0.3 (E1's). No queue-keeping.
- round2_public.csv 58,360.74 (first 75% 37,695 / last 25% 20,665), penalty 1,515, 15,301 fills; the Python file equals Rust to the cent; validate OK. Round 1 public 333,542, rebuilt private 330,245 (E1 287,058 / 281,395).
- Not yet combined with R2-E2's queue-keeping (E1 + KEEP: +19k on round 2).

### R2-V1, 20:40 (`python/bots/qminers/candidates/r2_V1_vol_exposure.py`, the trend agent's): the front-runner for the final
- R2-E2 (E1 + queue-keeping) plus TREND (the mid against its 2-s and 60-s averages, 31 features) and an exposure set by the absolute price speed: exposure = clip(100 x (VOL_REF 2.5 / the decayed |mid change| ticks a second over VOL_US 5 s)^VOL_EXP 2, 10, 100); VOL_NOHEDGE 1 (a shrinking exposure only stops adding; the hedge still waits at 100). DEAD_ZONE 0.3.
- round2_public.csv 169,262.76 (first 75% 127,172 / last 25% 42,091), breach 5.2k, 19,249 fills; byte-identical to Rust; validate OK; 112 s here (about 225 s on 12,000 s). Against E1 + KEEP (47,311): ahead in 6 of 6 1,000-s segments, mean +20,325, t 8.03, worst +9,927.
- Round 1 (Rust): public 670,462, rebuilt private 660,398 (the fixed-exposure version of the same cell 670,358 / 659,575): the scaling costs nothing there. Round 1's price speed is 1.23 ticks a second (flat), round 2's 3.22 (1.56-7.43 per 600 s).
- Open: DEAD_ZONE 0.18 gives 164,752 on round 2 and likely more on round 1 (being gridded with TREND on all three tapes).
