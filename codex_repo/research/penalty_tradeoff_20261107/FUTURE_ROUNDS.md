# Penalty economics to revisit in future rounds

Recorded 7 November 2026 after the round-1 penalty study. This is a research
hypothesis and proposed experiment, not a newly validated strategy.

## What the existing tests establish

The current simulator charges 10,000 PnL units per second while actual absolute
inventory exceeds 100. The charge is independent of the excess quantity; exactly
100 is free. The separate hard potential-exposure cap is 1,000. Recheck these
rules and contract/PnL units against each new round before reusing this analysis.

Fourteen candidates and two controls were screened. No candidate passed the
promotion gates. The frozen active diagnostic allowed potential exposure up to
1,000 but reached only 160 actual lots. Its full-round gross PnL was 553,230,
penalty 1,338.23, and net PnL 551,891.77, versus the baseline's 554,347.
Two actual breaches lasted a combined 0.133823 seconds. Both recovered before
the configured 100 ms forced-recovery trigger. Latency stress also lost money.

Some other probes did reach 1,000 actual lots. A continuous 1,000-lot cap lost
gross profit and incurred large penalties. Thus high-cap trading was tested;
what remains unresolved is whether a liquidity-aware, deliberately brief,
near-full-capacity entry and exit can earn enough incremental profit. The
160-lot diagnostic alone cannot answer that question. A permitted cap or a large
submitted order is not evidence of actual filled exposure.

See [the recorded results](summary.json) and [the original report](report.html).
Both public tapes had already been used; these results are not fresh holdout
evidence and do not rule out every possible penalty-paying policy.

## Why a wider spread might change the decision

A flat time charge can be distributed across a larger quantity. If 900 extra
lots beyond the 100-lot baseline are actually filled and unwound, the penalty
alone implies these incremental round-trip profit thresholds:

| Actual total breach time | Total penalty | Penalty per additional lot |
| --- | ---: | ---: |
| 5 ms | 50 | 0.0556 |
| 20 ms | 200 | 0.2222 |
| 100 ms | 1,000 | 1.1111 |

Values are PnL units, not necessarily ticks. These are arithmetic scenarios,
not demonstrated fill sizes or achievable exit times. For actual incremental
quantity Q, breach duration T seconds and fee rate R, the fee per lot is R*T/Q.
Smaller fills raise the hurdle; longer exits raise it proportionally.

Larger spreads may increase passive round-trip revenue while the time charge
stays fixed. However, quoted spread is not realized profit: crossing a wider
spread to enter or exit costs more, displayed depth may be insufficient, and
adverse selection, queue position and partial fills can overwhelm the benefit.
Large passive fills followed by a fast passive exit must be demonstrated.

Evaluate incremental net PnL against the same 100-lot baseline. If incremental
gross PnL is measured from actual execution prices and final marked inventory,
it already incorporates spread/slippage effects; subtract the actual engine
penalty once. For a forecast before execution, use expected executable trading
edge minus execution costs and R times expected breach duration, with a margin
for uncertainty and long exit-time tails. Avoid multiplying independent average
fill size, edge and duration when these are correlated.

## Proposed bounded experiment for a new round

1. Verify the new rules, fee rate, tick value, latency and hard exposure cap.
   Establish the existing 100-lot strategy's score on the same new tape.
2. Before viewing validation results, freeze a small set of burst sizes, entry
   thresholds and recovery triggers. Include the unchanged baseline and a
   smaller-burst control. Preserve chronological validation data for one final
   comparison and account for all screened candidates.
3. Admit bursts only when executable depth, predicted edge and estimated exit
   time jointly cover the penalty and execution costs. Use causal inputs only.
   Account for all live and pending orders under the unchanged hard cap.
4. Test targeting roughly 900-1,000 actual lots when feasible, then returning
   within 100 promptly. Reserve capacity for recovery, cancel risk-increasing
   orders, and model callbacks, cancellation latency, partial fills and IOC
   depth faithfully. A recovery trigger is not an exit-time guarantee.
5. Log actual peak inventory, filled incremental quantity, every breach's
   duration and fee, realized execution prices, recovery fills and rejections.
   Report how often intended near-capacity bursts were actually achieved.
6. Compare incremental net PnL, drawdown and tail exit times across chronological
   periods and latency/depth stress. Require gains after all fees and consistent
   validation performance, not merely a higher gross score or one lucky burst.

Current decision: retain the penalty-free round-1 model. Reopen this hypothesis
if a future round offers materially larger executable spread/edge relative to
the unchanged fee, sufficient two-sided liquidity, and measured rapid recovery.
Wider quoted spreads alone are not a promotion criterion.
