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
Trials so far (this worktree): 4 experiments, 34 cells.
- 21:20-20:30 (the fable worktree): **the round-2 generator and ten 12,000-s draws** (`uv run python -m experiments.day.tape_gen --fit data/arena/round2/round2_public.csv --params-out logs/r2_params.json`, then `--params logs/r2_params.json --seed 1..10 --seconds 12000 --out logs/r2_gen/seedN.csv`; g_rate 178.3/s, f_rate 8.9/s, iid sides, lifetimes 0.27-0.32 s; the impact table 0.01 ticks at 10 lots to 1.0 at 500+, no jumps). **The draws carry round 2's short-term volatility but none of its drift**: 1-s sd of the IOC price 3.6 against 4.9 real, 10-s 5.9 against 12.8, 60-s 13 against 34, 300-s 26 against 84; a draw's price ends 10,002 -> 10,148 where the public goes 10,000 -> 9,690 through a 500-tick crash. So they answer only the drift-free case. Candidates on the ten draws (mean / sd / min over the draws, all ten positive unless said; the breach summed over the draws), `arena.qsim_rust ridge_maker` for the ridge line (byte-identical to the Python files) and `arena.qgrid` for the rest:
  | candidate | public | draws mean | sd | min | breach (10 draws) |
  |---|---|---|---|---|---|
  | R2-E2, 30 lots | 47,098 | 246,389 | 3,510 | 239,616 | 0 |
  | E2 at 100 lots | -87,574 | 502,929 | 7,761 | 493,261 | 359k |
  | R2-V2 (speed-scaled, 100) | 167,288 | 487,001 | 8,376 | 473,550 | 330k |
  | V2 at 30 | 123,196 | 204,872 | 4,240 | 196,503 | 72k |
  | codex round-2 file (`r2_X2_codex_untested.py`: inverse-variance exposure 200/var, floor 10, a 100-ms pause after 2-tick jumps) | 144,580 (round 1 618,081) | 349,222 | 9,957 | 330,033 | 19k |
  | R2-M2 with its gate | 116,620 | -13 | 40 | -134 | 0 (the gate never opens) |
  | R2-M2 without the gate | 118,374 | -234,564 | 19,711 | -276,203 | 0 (every draw negative) |
  | R2-FH1 (no gate, stop 3) | 132,005 | -247,856 | 16,914 | -276,751 | 0 (every draw negative) |
  Reading: on a drift-free round-2 draw every ridge maker is far positive and the momentum line is a pure drift bet (flat with the gate, -235k without); the public tape's +117k for M2 and +132k for FH1 is its drift and crash. E2 at 30 lots lost 41.5k on the validation tape, which the draws cannot reproduce: the server's tapes carry the drift. R2-FH1 is dropped for upload as it stands; M2 only with its gate; the codex file sits between E2-30 and V2 on the draws and below V2 on both real tapes, with far fewer breaches.
- 20:50 (the fable worktree): **the big order's impact by size on round 2 public** (a price-time replay; the mid move in the order's direction at 1 / 5 / 15 / 30 / 60 / 120 / 300 s): 300-500 lots +1.21 / +1.41 / +1.51 / +1.10 / +1.93 / +1.61 / +0.35; 500-800 +1.54 / +1.62 / +1.92 / +1.60 / +1.25 / +1.46 / +1.26; 800-1,200 +2.00 / +2.43 / +3.23 / +2.64 / +3.15 / +3.06 / +5.44; 1,200-2,000 +2.21 / +2.55 / +2.78 / +3.13 / +2.46 / +3.95 / +3.70; 2,000+ (n 81) +2.85 / +1.90 / +0.17 / -1.09 / -4.92 / +2.54 / -4.77; the share positive at 30 s 0.51-0.53 with an sd of 21-23 ticks: the impact is complete within 15 s and does not reverse, small against the noise, and it adds up over ~2,800 orders of 500+ a tape. **R2-RE** (`r2_RE_hysteresis.py`, M3 plus FLIP_LOTS: a big order against the held side must be at least this to flip; 0 = M3): `--grid FLIP_LOTS=0,800,1200,2000 --grid MIN_LOTS=400,500` (8): 0 / 500 130,251, 0 / 400 121,221, 800 / 400-500 72.9-82.8k, 1,200 39-40k, 2,000 1.6-13.1k: every flip is worth more than the spread it pays (the latest big order is the best predictor); dropped.
- 20:15 (the fable worktree `worktree-fable-r2-cascade`): family 14 `python/bots/qminers/families/flow_holder.py` (hold EXPOSURE lots on the side of the last MIN_LOTS+ aggressor; GRACE_MS 0 = the board's momentum agent, reproduced to the cent: `--grid GRACE_MS=0,100,1000 --grid MIN_LOTS=333,500,650` (9): 0 / 500 118,374 (in 97,133 / out 21,241), 0 / 650 117,451 (70,731 / 46,720), 0 / 333 101,017; a passive entry with a 100-ms grace -5,954 and -37,089, 1,000 ms +10,222 and +30,439: the impact lands inside 100 ms, so the entry must cross). `--set GRACE_MS=0 --grid FLAT_S=0,10,30,90 --grid EXIT_PASSIVE=0,1 --grid CLEAR_ONLY=0,1` (16): FLAT_S and EXIT_PASSIVE tie (big orders come every ~2 s), CLEAR_ONLY 1 50,675 (18,601 / 32,074). `--grid STOP=5,10,20` then `2,3,4` (6): **STOP 3 132,005 (in 109,253 / out 22,752), 4 129,685 (107,626 / 22,059), 5 126,863 (104,510 / 22,353), 2 123,062, 10 117,669, 20 116,738**; max drawdown 17,140 against 19,543, pnl_se 29.3k. Candidate R2-FH1 `python/bots/qminers/candidates/r2_FH1_flow_stop.py` (GRACE_MS 0, STOP 3), one run 132,005.00, validate OK. The stop is the only knob above the base; its gain is mostly in the first 75% (+12.1k) with +1.5k on the last 25%. `--grid MIN_LOTS=400,500,650 --grid STOP=3,4` on R2-FH1 (6): 500 / 3 top in 75% (109,253) and full; 400 / 3 108,834 in but 13,884 out; 650 / 3 80,023 in, 32,804 out, max drawdown 10,534 (500: 17,140), pnl_se 26.2k (29.3k): the bigger signal trades half as much with half the drawdown. On round1.csv R2-FH1 makes -159,378 (3,605 fills): a bet on round 2's kind of tape (impact 1.3-2 ticks a big order), as the momentum agent is.


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

### R2-M2 and R2-M1, 20:45 (the momentum agent's; `python/bots/qminers/candidates/r2_M2_flow_trend.py`, `r2_M1_tsmom.py`)
- **R2-M2:** hold 100 lots the way of the last market aggressive order of MIN_LOTS 500+ lots, flip by IOC at the touch when the next one comes the other way; a self-gate (a one-lot shadow of the signal must be up 10+ ticks) keeps it off on round-1-like tapes. Round 2 public 116,620 (in 95,379 / out 21,241), 1,940 fills, breach 0, pnl_se 30,565, 11 s a run; 10 of 12 500-s segments positive, but 49k of it in the 3,500-4,000-s crash. Round 1 public -1,242 (ungated -157,078), rebuilt private 0. MIN_LOTS 333-500 a plateau (in 94-98k). Latency-sensitive: at 10 / 20 / 50 ms instead of 5 it makes 111k / 91k / 38k. Always ~100 lots exposed. Why: on round 2 a 500-800-lot aggressor moves the mid +1.28 ticks by 5 s, 800-1,500 lots +2.08 (round 1: under the 1-tick spread).
- **R2-M1:** hold 100 lots the way of the mid's 120-s move once it reaches 12 ticks: round 2 87,156 (in 51,111 / out 36,045) on only 75 fills; round 1 -23,695 (no gate). Weaker evidence.
- Against R2-V1 (169,263, 6 of 6 segments ahead of its base, ~670k on round 1): M2 earns less, in fewer and lumpier bets, and uses the whole limit, so the two can't run side by side without splitting it.

### 20:55: R2-E2's validation score, and R2-V2
- **R2-E2 on the server's validation tape** (uploaded 19:54; `r2_E2_low_exposure_keep_res/validation_result.json` at the repo root): **-41,499.00** (fills 39,523, volume 1,310,730, end -30 at a mark of 10,482, breach 0, pnl_se 19,267, |pos| 30 throughout, simulation time 314 s). Expected about +94k (twice the public 47,098): ~7 pnl_se below. The validation price ends ~480 ticks UP (the public ends ~310 down), but direction is not the cause: on the public tape mirrored (prices 20,000 - p, sides swapped; `data/arena/round2/round2_public_mirror.csv`) E2 makes 46,216, the same as the 47,098 unmirrored. So the 30-lot bot's public edge did not carry to the validation tape: the round-2 public tuning (exposure 30, the take, the dead zone) does not transfer as is.
- The server took 314 s for E2 against ~180 s expected locally: about 1.75x slower. R2-V1/V2 run ~1.2x E2 locally, so expect ~6.5 min there (limit 15).
- **R2-V2** (`python/bots/qminers/candidates/r2_V2_vol_exposure_dz18.py`): R2-E2 (dead zone 0.18, 29 features) plus the absolute speed-scaled exposure (EXPOSURE 100, VOL_REF 2.5, VOL_EXP 2, VOL_US 5 s, VOL_MIN 10, VOL_MAX 100, VOL_NOHEDGE 1). round2_public 167,288.05 (breach 3,840, 21,637 fills, 88 s), round1.csv 699,370.05 (breach 7,356, 188 s), rebuilt private 681,633 (Rust); byte-identical to Rust on both tapes; validate OK. FLOWGRP_CAP 100-1,000, FLOWGRP 1 and a big-aggressor lean add nothing on it.

### 21:05: R2-FH1 (the user's other session, `.claude/worktrees/fable-r2-cascade/python/bots/qminers/candidates/r2_FH1_flow_stop.py`, not in main)
- The flow holder: R2-M2's rule (hold 100 lots the way of the last 500+-lot aggressor, IOC flips) plus STOP 3 (flatten after 3 ticks against the position since the signal). round2_public 132,005 (in 109,253 / out 22,752), the mirrored public 132,005 (symmetric), **round1.csv -159,378** (no self-gate; R2-M2 with its gate -1,242); validate OK. Riskier than M2 on a calm private tape; usable only with M2's gate.
- Suggested upload order (the user, exploration against exploitation): R2-V2 (the likely final and the decisive question after E2's -41.5k), then R2-M2 (the other family), then re-upload the chosen final last.
### R2-V1 / R2-V2, 20:05 (`python/bots/qminers/candidates/r2_V1_vol_exposure.py`, `r2_V2_vol_exposure_dz18.py`; the trend agent's)
- R2-E2 plus an exposure that follows the tape's speed: at every valid book, exposure = clip(100 x (2.5 / fast)^2, 10, 100), fast the mid's |change| in ticks a second decayed over 5 s; the hedge stays at 100 (VOL_NOHEDGE 1), so a shrinking exposure stops new risk but forces no IOC. Round 1 runs at 1.23 ticks a second (exposure 100 nearly always), round 2 public at 3.22 (1.6-7.4 per 600 s). V1 adds two trend features (mid minus its 2-s / 60-s EWMA) at DEAD_ZONE 0.3; V2 is E2's 29 features at DEAD_ZONE 0.18.
- | tape | V1 | **V2** | E2 (30 lots) | E2 at 100 lots |
  |---|---|---|---|---|
  | round 2 public (in / out) | 169,262.76 (127,172 / 42,091) | **167,288.05 (125,149 / 42,139)** | 47,098 (35,094 / 12,004) | -87,574 |
  | round 1 public | 670,461.77 | **699,370.05** | 294,949 | 699,697 |
  | round 1 rebuilt private | 660,398 | **681,633** | 287,960 | 684,271 |
- Both Python files equal Rust ridge_maker to the byte (pnl.csv, result.json) on both public tapes; validate OK; run time 88-112 s for 6,000 s, 188-220 s for 12,000 s (with a second simulator running).
- V2 against E2 on round 2, 1,000-s segments: ahead in 6 of 6, t 9.01, worst +12,783. On round 1 V2 is E2 at 100 lots (12 segments, mean -27, t -0.45).
- Recommended upload: V2 (one rule on E2, no new features; keeps round 1's regime whole). Expect the validation score near twice the public (about 330k) on a round-2-like tape, near round 1's rate (about 700k) on a calm one.

### 21:25: R2-V2 on the validation tape (uploaded 20:12; the folders moved to `data/arena/round2/r2_V2_vol_exposure_dz18_res/` and `r2_E2_low_exposure_keep_res/`, ignored by git: result.json, metadata.json and the 1-s pnl.csv, no logs)
- **R2-V2: +71,864.15** (fills 42,407, volume 1,817,976, end -10 at a mark of 10,482, breach 13,372, pnl_se 35,997, |pos| q50 / q68 / q95 60 / 100 / 100; simulation time 5 min 37.5 s). Expected ~+335k if the validation tape were like the public (twice 167,288): the ratio is 0.21. Positive in 8 of 12 1,000-s segments: -5,671 -2,176 -8,187 +14,368 +13,272 +11,666 +19,956 +12,715 +6,269 +4,559 -5,924 +11,017; max drawdown 20,840.
- **R2-E2 on the same tape:** -41,499, per 1,000 s -5,617 -10,359 -2,462 +5,295 -4,156 -655 -4,049 +1,460 -13,930 +3,350 -12,659 +2,283; max drawdown 48,780. V2 beats E2 by +113k on the validation tape: the exposure that scales up to 100 when the tape is slow is what pays there; the fixed 30 lots lose.
- The validation tape is less favourable than the public one for this family (0.21 of the public rate for V2, negative for E2) but V2 stays positive with a modest drawdown.

### 21:45: R2-M2 on the validation tape (uploaded 20:28; `data/arena/round2/r2_M2_flow_trend_res/`, ignored by git)
- **R2-M2: +376,082.00** (fills 4,086, volume 530,500, end +100 at a mark of 10,480.2, breach 0, pnl_se 57,594, |pos| 100 throughout, simulation time 36.9 s). Twice its public 116,620 would be 233k: it beat that. Per 1,000 s: +43,228 +36,420 +13,919 +31,046 +55,619 +36,624 +61,556 +15,251 +48,196 -11,400 +24,777 +20,846 (11 of 12 positive), max drawdown 22,662. Not the drift: holding 100 lots through the whole ~+480-tick rise makes ~48k.
- Its 25-s PnL steps correlate -0.02 with R2-V2's on the same tape: the two families earn from different things.
- So big-order momentum is real on round 2's server tapes and worth ~5x the learned maker there (V2 +71,864, E2 -41,499). **R2-M2 is the round-2 final** unless the private tape is unlike validation; its self-gate keeps it out of calm tapes (round1.csv -1,242).

### 22:05: R2-M3 (`python/bots/qminers/candidates/r2_M3_flow_stop_gated.py`)
- R2-M2 plus FH1's stop (STOP 3: once the mid has moved 3 ticks against the signal since it was set, flatten by IOC; no new target until the next big order), M2's self-gate kept (the one-lot shadow follows the unstopped signal). STOP 0 reproduces M2 to the cent.
- round2_public 130,251 (in 107,499 / out 22,752; M2 116,620 / 95,379 / 21,241), breach 0, max drawdown 17,140 (M2 19,543); the mirrored public the same; round1.csv -1,242 and the rebuilt private 0, both identical to M2; validate OK; 8 s / 16 s. STOP 2-5 all above M2 (121-130k); MIN_LOTS 400 lower at every STOP. Against M2 by 1,000-s segment: 6 of 6 ahead, mean +2,272, t 1.38, but +10.5k of the +13.6k in one segment.
