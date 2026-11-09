# Round 4: W2 and the leading candidate audit

2026-11-08. Main source reviewed at `130022f`, merged into `gen-v3` at
`474e574`. Primary candidate: `python/bots/qminers/candidates/r4_W2_warm10k.py`.
Comparison: F5 / W1 at mass zero, MH3, X1R3. No candidate or strategy code changed.

No blocking implementation defect was found in W2. Its warm initialization is
correct, its public training statistics reproduce exactly, and its live updates
use matured labels. The principal limitation is evidence: its validation advantage
over F5 is only 1,789, with no consistent advantage across time blocks.

## Findings that affect model selection

1. **W2 has not demonstrated a repeatable improvement over F5.** Downloaded
   validation curves reproduce the handover's result: +1,789, or 0.102%, winning
   six of twelve 1,000-second segments. The paired segment t is 0.666, a descriptive
   statistic on one tape, not twelve independent trials. Its first 1,000 seconds
   make 126,496 against F5's 126,683: **-187** during the period the warm start was
   intended to improve. Keeping W2 as the highest recorded upload is reasonable;
   claiming it has a dependable advantage is not supported by these results.

2. **W2's public replay cannot validate the warm start.** Its prior uses the
   entire round-4 public tape, including the final quarter. A chronological split
   applied only to the reported replay PnL does not make that quarter unseen.
   This is already disclosed in the candidate's first line and the handover;
   it is not an undisclosed live-data leak. A fresh cold-F5 run regenerates
   `r4_stats.txt` byte for byte, confirming that the embedded prior can be obtained
   entirely from the public tape. The independent portal validation remains the
   useful comparison. No hidden validation observations were needed to reproduce
   the prior.

3. **MH3 and X1R3's local gains fail on the saved validation tape.** MH3 loses
   15,872 against F5 and X1R3 loses 27,812. The last four segments account for
   -16,689 and -24,685 respectively. That supports retaining the F5/W2 family;
   it does not identify a single faulty feature. X1R3 changes both the take rule
   and three filter parameters, so its aggregate loss cannot isolate either.
   MH3 also used 815 of the portal's 900 seconds according to the handover,
   leaving 85 seconds of observed headroom; W2 used 595 seconds. These runtimes
   are existing portal observations, not new timing measurements from this audit.

| Candidate | Public PnL, reported | Validation PnL, recalculated | Difference vs F5 | Segments won / 12 |
|---|---:|---:|---:|---:|
| F5 / W1 mass 0 | 1,029,443 | 1,752,785 | 0 | — |
| W2 mass 10,000 | 1,029,781, in sample | 1,754,574 | +1,789 | 6 |
| MH3 | 1,042,419 | 1,736,913 | -15,872 | 7 |
| X1R3 | 1,052,756 | 1,724,973 | -27,812 | 2 |

Every saved result reconciles as cash + final inventory × final mark − breach
penalty, with zero breach penalty. The engine settings in all four metadata
files agree: 5-ms latency, position limit 100, max potential position 1,000,
and breach penalty 10,000 per second. The recorded source/results association
comes from `data/arena/round4/HANDOVER.md` rows 100–103: the downloaded metadata
does not contain a submitted-source hash. Current local files and all inspected
result artifacts are hashed in the audit JSON; those hashes cannot retroactively
prove which bytes the portal received.

## Implementation checks

- W2 and W1 match F5's entire executable AST after removing only the module
  docstring, four warm constants, and the guarded warm initialization. W2 is
  F5 with a prior, not a new classifier or a changed execution policy.
- All 39 × 39 covariance entries, 39 response entries, and the source mass
  match `r4_stats.txt` exactly. Original mass 254,063.69739369614; 263,498 labels.
  The initialization rescales the sufficient statistics by 10,000 / source mass,
  sets mass 10,000 and label count 200, then fits on the first valid book before
  producing its signal (`r4_W2_warm10k.py:158`, `:443`, `:793`).
- The first ridge regularizer is 30. An independent Cholesky solver differs
  from the bot's Gauss-Jordan weights by at most **1.42e-14**. All coefficients
  are finite. The positive-definite solve succeeds without special handling.
- A label does not enter the fit before observation time + 400 ms; it enters at
  that time, and a label over one second late is discarded. `_learn` runs before
  the current observation is queued. The prior's 10,000 mass is gradually diluted
  by live labels; the 100,000-second model memory is not a 200-second half-life.
- **72 exposure cases** cover both sides, five inventory levels and pending,
  accepted and canceling same-side reservations. `_take` includes every live
  remaining quantity when calculating room (`:505`). Requesting a cancel does
  not release reserved capacity.
- Private callbacks correctly accumulate per-match quantities, update remaining
  lots, and release unfilled IOC remainder on cancellation. Two incremental
  partial fills on each side, a new-order rejection and a late cancel rejection
  pass (`:827`). This agrees with the actual `PrivateOrderEvent` contract in
  `simulator/models.py:185` and the simulator's activation/fill notification order.
- The one-tick spread gate and ordinary/jump take thresholds pass focused checks.
  Static upload validation passes for F5, W2, MH3 and X1R3: allowed imports,
  self-contained source, no runtime files/network/environment, under the size cap.
- MH3's source diff uses matured 100-ms and 600-ms auxiliary labels, stores the
  resulting feature tuple at observation time, and retains F5's private-order
  accounting. Its 64-entry queue at a minimum 20-ms observation interval covers
  these horizons. X1R3 retains that accounting too; its deliberate changes are
  the stronger-signal wide-spread take and RATE 3 / EPS 0.02 / DEPTH 10 filter.
  These two comparisons were source/static/result audits, not fresh full replays.

## Reproduction

With the repository environment and downloaded round-4 artifacts:

```sh
uv run python -m experiments.day.r4_warm_audit --repo . --out data/arena/gen/w2_audit/audit.json
uv run python -m experiments.day.r4_warm_audit --repo . --out data/arena/gen/w2_audit/audit.json --replay
uv run python -m arena.validate python/bots/qminers/candidates/r4_W2_warm10k.py all --format qminers --max-size 1MiB
```

The first command checks source identity, prior values, independent solving,
causal learning, order accounting and the downloaded curves without running a
market replay. The optional replay builds Rust with one worker, regenerates cold
F5's public statistics, runs W2 in Rust, then runs the unchanged W2 Python file
on the complete public tape. It leaves the original stats and candidates intact.
Results are under `data/arena/gen/w2_audit/`.

The public Rust rerun reproduces F5 **1,029,443** and W2 **1,029,781**. The
regenerated stats are byte-identical to the original. W2's full Python replay
matches Rust exactly on PnL **1,029,781**, **42,139 fills**, **585,414 lots**,
ending inventory **100**, breach penalty **0**, and PnL standard error
**42,436.03162041541**. Python cash 74,381 plus 100 × final mark 9,554
also reconciles exactly to that PnL.

Audited W2 SHA-256:
`17caee3c9d61e78d052d7ddedc5d9d6f9ac0f2fdfa207ab113c988c5cef0a763`.
Original and regenerated training statistics SHA-256:
`0c3a3411f3f242b68de4212f8f94113156e45a1935caf758771803e0ec029303`.

The full replay is a correctness/parity check on public data, not another
out-of-sample performance result. No new private validation tape was available.
