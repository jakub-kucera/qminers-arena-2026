# Beyond F5 / X1R3: research review, 8 Nov 2026

Reviewed main through `b48c16d` (08:53 CET). This is a research shortlist, not a tested
replacement bot. The only new measurement here is the IOC completion audit below.
No candidate, Rust strategy, or generator settings changed.

## What the existing results imply

F5 earns 1,029,443 on round4_public and 1,752,785 on validation. X1R3 earns 1,052,756
on public (+23,313, all six 1,000-s segments positive); this review has no validation
result for X1R3. MH3 improved public by 13k and the round-4 synthetic mean by 12k,
but lost 15,872 on validation. Its server runtime was 815 s of 900, versus F5's 609 s.
Sources: the candidates' headers, `data/arena/round4/HANDOVER.md`, and IDEAS rows
R4-MH / R4-X1 / R4-D1.

F5 already holds the full 100-lot position 58.4% of the time and is flat only 0.1%.
Its 546,161 aggressive filled lots cost 273,934 against the contemporaneous mid;
inventory motion earns 1,282,524. The 979 positions flipped within one second cost
55,981. These are accounting totals, not achievable savings. More accurate forecasts
cannot help while the desired position already agrees with a saturated inventory.
Sources: `data/arena/round4/stats.md`, F5 anatomy and forecast-gap sections.

The promising question is which *different executable action* has value, conditional
on the current position and on what the baseline would do shortly afterwards.

## 1. Signal-dependent price limits and completion of partial takes

**First experiment; concrete evidence, limited implementation.** X1R3 sends its IOC
at the touch (`TAKE_THRU=0`) and starts a 50-ms cooldown on submission. Its wide-spread
rule permits more states to trade, but does not address insufficient volume at that
touch or a touch moving during the order's latency.

New audit, F5's existing full-log run on real round4_public:

```sh
uv run python -m experiments.day.take_completion_probe data/arena/round4/py_f5_full --out data/arena/gen/r4_research/take_completion_f5.json
```

| Completion | Orders | Requested lots | Filled lots | Unfilled lots |
|---|---:|---:|---:|---:|
| Full | 3,474 | 455,266 | 455,266 | 0 |
| Partial | 1,345 | 230,693 | 90,803 | 139,890 |
| Zero | 50 | 7,523 | 0 | 7,523 |
| Total | 4,869 | 693,482 | 546,069 | 147,413 |

Unfilled volume is 21.26% of requested volume. Another 92 aggressive filled lots
come from orders other than submitted IOCs; those explain the anatomy's 546,161.
For 233 incomplete orders, the immediately next IOC is in the same direction within
100 ms. Those orders left 24,220 lots unfilled; 85.84% of the subsequent price limits
are worse, with a median deterioration of one tick. Within 75 ms: 160 orders,
17,742 missing lots, 85.63% worse; within 250 ms: 468, 49,351, 84.83% worse.

The next price is hindsight used for diagnosis. These are repeated requests, not
distinct missed opportunities, and the report measures neither available deeper
liquidity nor its causal profit. F5 evidence must be repeated on X1R3 before adoption.

Proposed policy: for direction d, current mid m, forecast alpha and safety margin e,
allow a marginal execution price p only while `d * (m + alpha - p) > e`.
Limit both marginal price and total VWAP; cap quantity by the existing position and
all outstanding orders. First try one additional tick only on strong, still-valid
signals with insufficient touch volume. Test immediate extra depth separately from
a retry after a confirmed partial fill/cancellation; never duplicate in-flight volume.
Use fresh information at the retry, actual simulator latency, and the baseline's
normal policy after the intervention.

Uniform `FT_THRU=1` and shorter cooldowns have already been tested and lost. The new
test conditions extra aggression on remaining edge and completion need. It succeeds
only if extra timely exposure beats the worse execution price in full-engine PnL.
First report how much can be gained even with hindsight choosing *only these actions*;
if little remains after costs, stop before building a learned execution model.

**Tested on F5 (IDEAS.md, "R4-T1", 09:35): dropped.** One extra tick while the marginal price keeps
`d * (mid + signal - p) > 0.25` gives r4 +4,308 (6/6 segments), but 88% of it sits in the fastest speed tercile
(r3 +464, r2 +2,497, r1 +131; r3b seed 203 -4,719). A retry within 50 ms of an incomplete take loses (r4 -4,497,
r3 -4,043, round-4 synthetic seeds -7k to -18k).

## 2. Learn action advantage against baseline continuation

**Largest policy opportunity, more work and overfitting risk.** At a decision state s,
compare a few actions: baseline, wait, reduce without reversing, and selectively
complete a valid take. Define the target as

`A(s,a) = PnL(t..T | action a, then baseline) - PnL(t..T | baseline)`.

Both branches start from the same state and see the same future tape, but have their
own fills, book, inventory, outstanding orders, cooldowns and later policy decisions.
At T include inventory marked consistently; report sensitivity to T or continue
through the remaining tape. Short horizon terminal inventory is not a free profit.
An approximate replay can screen ideas, but final labels/claims require executable
branches. Fit only on earlier blocks; future data can form matured training labels,
never live inputs. Start with a small residual model over the unchanged X1R3 forecast.

R4-PG already learned `d * future_mid_move - half_spread`, including a horizon ending
at the next opposite signal, and lost. That target values a standalone trade. It does
not subtract the baseline buying shortly afterwards, account for the actual filled
quantity, or value the inventory and subsequent decisions displaced by the trade.
A positive markout therefore does not prove an intervention helps. This is the
specific distinction to preserve; another profit gate with the old target is not new.

Begin with sparse branch experiments at actual decision points and a restricted-action
oracle. Do not sum overlapping local advantages into a claimed portfolio PnL. If there
is useful headroom, learn where it is using current inventory, executable depth,
forecast margin, time since a causally detected move, and recent filter evidence.
Train where actions can differ; a global R-squared improvement is insufficient.

**Result (R4-A1, 8 Nov 10:15, `experiments.day.action_oracle`):** no headroom in the restricted
actions on round4_public. Exact Rust branches from F5's own decisions (WAIT, TAKE_NOW, REDUCE,
flip stopped at flat, COMPLETE), valued at +300 s against F5's continuation: every action's mean
is at or below zero, no state cell reaches t 2 and holds across the 1,000-s blocks, and 41-61% of
skipped takes leave the PnL unchanged (F5 makes the same trade 50-150 ms later at the same price).
The rule from WAIT (a take only if the signal persists to the next decision) loses 134k, as the
oracle's mean predicted (-126k); the best cell as a rule (FT_FLIP_M) loses 7.9k-29.4k. IDEAS.md,
"R4-A1".

The 56k short-whipsaw loss motivates inspection, but uniform flip bars, post-jump flip
bars and stopping at flat already failed. A live classifier must distinguish continuation
from exhaustion before the event ends. The hindsight end of a jump is not a feature.

## 3. Audit filter reaction to contradictory observations

**Potential new information; establish the failure first.** The filter uses a 17-state
grid anchored to the previous bid. An accepted insert whose likelihood is EPS for
every state leaves the posterior unchanged; an insert farther than FILTER_DEPTH is
ignored. A cluster of fresh orders might therefore indicate a latent displacement
before the visible bid lets the grid follow it. Whether this matters often enough on
real round 4 is unmeasured.

Instrument normalized predictive likelihood, the count of constant-likelihood updates,
depth exclusions, boundary mass, and disagreement between fresh bid and ask placement
evidence. Match them to later *decision changes* and executable value. Also distinguish
new IDs from old orders re-entering the visible depth before treating them as arrivals.
Do not call the latter a confirmed bug without the audit.

Only if supported, add an observation-driven change-point proposal: before conditioning
on the current observation, mix the continuation prior with a broad candidate prior,
`p_minus = (1-h) * p_cont + h * p_change`, then update each branch with its own
clamp-aware insert likelihood and update the branch odds. Set h using past evidence;
if the current insert constructs a proposal, do not count that same insert twice as
independent confirmation. Preserve mass on an adaptive grid rather than folding a
large displacement onto an edge. Require corroborating fresh evidence, especially on
unclamped orders, before a large change. Pass surprise/disagreement to a small action
model only if they add value beyond the existing mean, nonlinear gap and sd.

**Audited 8 Nov 09:30 (IDEAS.md, "R4-FA"; `experiments.day.filter_audit`): no such failure.** The fresh orders that
contradict F5's filter lag it on r4 and r3. After 3+ aggressive surprises within 0.5 s (112/h on r4), the mid moves
3.2 / 7.4 ticks against them at 0.4 / 1 s, the way the filter's gap already points. Nudging the forecast towards them
drops better takes than it adds. Re-entries never reach the filter. The proposal is dropped.

This is not a recommendation to widen the grid or add unconditional jumps. R4-D1
already tried those: WJ5 won 40,411 / 31,345 / 20,971 on synthetic seeds 511-513 but
lost 13,757 on real r4. Drift and informed-side observations also failed. Better latent
tracking on our generator and better insert likelihood do not validate this proposal.

## Decision and acceptance criteria

Start with selective execution: it has a measured symptom and needs no new global
forecast. Then build the restricted action-advantage audit. Keep the filter proposal
as a bounded diagnostic, not another broad parameter search.

Use X1R3 as the baseline, report paired PnL in chronological blocks and after excluding
the best event/window, and choose a small policy before evaluating later blocks.
The repeatedly inspected last 25% is now exploratory, not an untouched holdout.
A mirror checks symmetry, not independence. Earlier rounds test regime sensitivity;
our wide6 tapes test robustness but cannot decide the winner. They miss marginal
policy effects even when baseline rankings look good. A paired server validation
upload, performed by the main session/user, is stronger evidence than more tuned draws.

Keep Python comfortably below the 900-s server limit; small state diagnostics and a
small action head are preferable experiments to another costly online ridge expansion.
No 10-20% PnL gain is established here. Another knob grid has weak prospects for that
size of advance; a meaningful gain needs better execution, better action targets, or
new causal information at decisions where the position can actually change.
