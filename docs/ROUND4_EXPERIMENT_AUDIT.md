# Round-4 experiment coverage and measurement audit

8 Nov 2026, audit through main `3630577`. The competing teams' scores above 2.5M are
user-reported; no rival source or validation curves were available. This review does
not establish a route to that score. Strategy fixes and corrected strategy replays
belong to the other session; no candidate or Rust strategy was edited here.

## Confirmed findings

1. **Profit-gate direction normalization loses invariant information.**
   `rust/arena_sim/src/strategies/profit_gate.rs:95` multiplies every base feature
   by direction. F5 column 24 (group-volume share) and 38 (posterior standard
   deviation) are unchanged by reflecting prices and swapping sides. The target
   `d * (future_mid - mid) - half_spread` is also unchanged, yet those two gate
   inputs change sign. A linear model cannot assign a common nonzero uncertainty
   or volume-share effect through those terms on both sides. An executable Rust
   harness calling the actual constructor confirms only columns 24 and 38 differ
   in a mirrored pair. This is a model-specification issue; the historical failed
   PG trials do not rule out a gate with the right feature parity. W2 has PG off.

2. **The action oracle uses the wrong sampling weights for whole-pool estimates.**
   `python/experiments/taker/action_oracle.py:84` draws one row per equal time stratum;
   `:246` scales the unweighted positive sum by pool/sample size. An event in a
   stratum of size N_h has inclusion probability 1/N_h, not n/N. Correct estimates
   of a pool sum use `sum_h N_h * A_h`; the corresponding mean divides by N.
   The original seed-4 sample has all 780 branches, one per nonempty stratum.
   Reweighting the existing results requires no new simulation:

   | Action | Mean as reported | Event-weighted mean | Positive pool as reported | Event-weighted positive pool |
   |---|---:|---:|---:|---:|
   | WAIT | -25.90 | -28.34 | 147,231 | 146,466 |
   | Stop flip at flat | +3.30 | +2.83 | 88,914 | 86,921 |
   | TAKE_NOW | -20.44 | -24.64 | 209,048 | 193,053 |
   | REDUCE | -70.45 | -72.68 | 233,742 | 168,825 |
   | COMPLETE | -230.62 | -356.19 | 41,643 | 54,543 |

   These are **the first 780 branches**, not a reweighting of all 955. REDUCE has
   no second batch, so its 234k vs 169k correction also applies to the final table.
   Population sizes vary 37–266 within its strata. Existing branch PnLs and full
   strategy replays remain valid. Uncertainty estimates should respect the sampling
   design and temporal dependence. Neither negative average intervention value nor
   non-additive hindsight positive sums establish the attainable value of a learned
   selective policy; the recorded “no action change has headroom” is too broad.

3. **K1's 1-s and 5-s t-statistics treat overlapping labels as independent.**
   `python/experiments/taker/take_classes.py:25` says spacing avoids overlapping
   labels, but defaults to 0.4 s for every horizon. The original real-R4 test has
   2,381 points / 380 F5 takes, reproduced exactly. Among its 2,380 adjacent pairs,
   0 overlap at 0.4 s, 2,010 at 1 s and 2,368 at 5 s. Its `score` uses an IID
   standard error at every horizon. The longer-horizon t-statistics do not have
   the stated interpretation; use temporal blocks or horizon-appropriate spacing.
   No correction to the t-statistics is estimated here. Overlap does not alter
   the arithmetic markout sums or prove any strategy gain. Also checked the tape
   vs logged initial mid: only 7 test points differ, by at most 0.5 tick, so that
   mismatch is not the main issue in this test.

4. **W3's documented switches do not restore the claimed controls.**
   `python/bots/qminers/candidates/round4/r4_W3_flow_depth.py:27` says `FLOW2=0` restores
   W2. In fact FEATURE_COUNT becomes 39 while WARM_XY still has 41 entries, so the
   guard at line 163 silently skips the prior. Disabling FLOW2 and TAKE_DEPTH_K
   together starts mass=0, labels=0; W2 starts mass=10,000, labels=200. Likewise,
   PRIOR_MASS=0 leaves FLOW2 and depth enabled, contrary to the inherited header's
   claim of exact F5 equivalence. This is an ablation/control trap, not a defect
   in the submitted default W3 or evidence that a recorded Rust ablation used it.

Findings 1–3 were immediately handed off; no corrective strategy trial was run.

## Earlier findings closed by the other session

- BUCKET overwrote FLOWGRP because the feature index did not advance. Main
  `de983ca` fixes it. Corrected BUCKET 1 / 15 lose 1,086 / 7,312 on real R4.
- FLOW2 shifted the intended dropped columns from 13/15/22 to 13/17/24. Main
  `3630577` reruns mask 16916480; intended drops still lose about 18.8k / 18.9k
  versus F2 / F2T1. W3 itself has feature dropping off.
- The historical long-horizon screen was **not** corrupted by the observation
  queue. Cap 512 reproduces its 1.5-s / 2-s PnLs exactly: 1,012,285 / 973,348.
  Cap 64 instead retains only 14,904 / 158 labels and earns 764,517 / -19,453.
  This is a useful configuration hazard, but not a newly invalid historical test.

## Coverage probe completed before the audit-only instruction

Checked 34 worktrees and 115 candidate files; no forgotten winning branch was
found. Some R4-named initial experiments ran on R3 before the new public tape,
but many were subsequently rerun on real R4. The ensemble/MOE families therefore
cannot broadly be called untested on R4. One BL50_150 R4 job failed with a missing
binary; that particular cell is missing, not a measured loss. The old untracked
round-2 candidate remains untouched and untested.

A missing test was a full 39-feature nonlinear fit on a real-R4 prefix, followed
by actual held-out execution. Train before 3000 s, calibrate in 3000–4200 s,
evaluate after 4200 s, with 1.4-s boundary purges. Candidates: ridge, two small MLP
fits and two shallow boosted-tree fits. Choose by calibration MSE after the bot's
actual ±2 forecast clamp. The ridge won calibration; neither nonlinear family
improved the control. The replay wrapper changes only the forecast after 4200 s.

- F5 PnL 1,029,443; selected frozen-ridge replay 1,027,063: **-2,380**.
- First 4,200 s identical; three 600-s test differences -1,532 / -388 / -460.
- Test clipped MSE: online F5 3.31041, frozen ridge 3.31626. The frozen ridge's
  unclipped MSE 2.91814 is not comparable to F5's clipped output.
- Dropped here. No validation improvement is claimed; other model designs remain
  untested. The simulator completed successfully; an initial curve-report origin
  error was corrected in the audit tool, then the saved replay was reported again.

The synthetic wide6 README explicitly withholds qualification for strategy
selection/pretraining. Results there and on older rounds are useful stress tests,
but requiring every R4 idea to win them is stronger than the evidence supports.

## Reproduction and artifacts

`data/arena/gen/r4_experiment_audit/audit.json` records source/input hashes, the
compiled Rust check, W3 controls, classifier overlap counts, and oracle weights.
Generate the input logs using the original K1 and action-oracle commands in
IDEAS.md, then run:

```sh
uv run python -m experiments.audits.r4_experiment_audit --repo . --pred P/pred_r4.csv --cache P/ts_r4.npz --oracle P/a1/r4 --out data/arena/gen/r4_experiment_audit/audit.json
uv run python -m experiments.audits.r4_full_model_probe dump data/arena/round4/round4_public.csv --out data/arena/gen/r4_full_model
uv run python -m experiments.audits.r4_full_model_probe fit --out data/arena/gen/r4_full_model
uv run python -m experiments.audits.r4_full_model_probe replay data/arena/round4/round4_public.csv --out data/arena/gen/r4_full_model
uv run python -m experiments.audits.r4_queue_capacity_probe data/arena/round4/round4_public.csv --out data/arena/gen/r4_queue_capacity --jobs 3
```

The full-model tool needs the experiment environment's numpy/sklearn; candidate
files are unchanged. The gate audit additionally requires rustc. Existing reports
and replay outputs are in the paths above; no raw tape or large artifact is committed.
