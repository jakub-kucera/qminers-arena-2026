# Round-2 absolute-volatility exposure research

The first verified local public checkpoint earns **144,580.19 net**, including
**636.81** in native position penalties. The audited evaluator and a separate
unmodified organizer CLI replay matched every result field.

- Ready source: `strategies/round2_submission.py`.
- Immutable copy: `strategies/round2_volatility_144580.py`.
- Source SHA-256: `4080cb3fc553d91a2849b6434e6dc563081b42d710b74c5bbcf2d0c4e1e62cba`.
- Evidence: `results/round2_submission.json` and `results/round2_144580.json`.
- Public data SHA-256: `88ff641e962540c66fa1cc4a3547585d31838d0929340150690cabb4f3cfb9f4`.

This is not a server-validation or organizer-private score. No such result has
been received. The ready source is a reproducible checkpoint, not evidence of
a competition win.

## What changed

The user's suggestion was to set exposure by the absolute level of volatility.
The successful policy estimates absolute realized variance from regular 100 ms
midpoint returns. Samples use the last valid midpoint preceding the sample
boundary, never a subsequently observed price. An exponentially decaying
estimate with a three-second time constant has units of ticks squared per
second; its square root, sigma, is ticks per square-root second.

The planned symmetric inventory cap is:

```text
cap = clamp(5 * floor((200 / sigma_squared) / 5), 10, 100)
```

At sigma 1, the cap is 100; at sigma 2 it is 50; at sigma 4 it is 10.
This is absolute tick volatility, without normalization by a rolling historical
volatility baseline. The cap updates at most every 100 ms, in five-lot steps.

The quote policy also clips online 400 ms return labels to one tick, pauses
quotes for 100 ms after visible midpoint moves of at least two ticks, avoids
spread greater than two, and requests cancellation immediately when a valid
two-sided market book is unavailable. Resting orders shrink through native
modify requests, preserving priority. Real reservations remain until the
matching engine acknowledges the shrink; overlapping cancellations retain
the original native costs and acceptance wall.

These are planned quote bounds, not instantaneous actual-position limits.
Existing inventory exits through fills; an unexpected jump can arrive before
the estimate or outstanding actions react. The full public replay reached
162 actual lots and 300 potential lots, charging the native penalty in full.

## Development comparisons

All values below use only the first public 60%, about one hour. The initial
reference transfer lost 38,204.33. The comparison holding the robust forecast,
jump guard and native quote behavior constant is particularly useful:

| Exposure rule | Development net PnL |
| --- | ---: |
| Fixed planned 25 | 32,969.00 |
| Fixed planned 50 | 45,698.00 |
| Fixed planned 75 | 39,036.00 |
| Inverse sigma, tau 60s, budget 100 | 63,992.00 |
| Inverse sigma, tau 10s, budget 100 | 93,679.00 |
| Inverse variance, tau 10s, budget 200 | 101,646.00 |
| Inverse variance, tau 3s, budget 200 | 112,379.00 |

The selected policy's development sampled maximum drawdown was 5,483, versus
22,299 for fixed50. These are tuned development results, not independent
confidence estimates. There were 56 development replays, including the initial
controls, before the six-source chronological shortlist was frozen.

## Chronological selection and final public check

Sources were frozen before the middle public 20% was replayed. Every candidate
ran continuously from the beginning, carrying learned state, live orders,
cash and inventory across the development boundary. Selection ranked the
net PnL increment on that middle segment:

| Candidate | Middle public 20% net increment |
| --- | ---: |
| Inverse variance tau3/risk200 | **19,052.19** |
| Inverse variance tau10/risk200 | 17,784.19 |
| Inverse sigma tau3/risk100 | 7,293.19 |
| No-trade control | 0.00 |
| Signal-target maker | -18,551.00 |
| Fixed50 maker with 500 ms jump pause | -36,742.00 |

Only the selected source then received a frozen-source final-public 20% check,
which earned **13,149.00**. Its full public result is 112,379 +19,052.19
+13,149 =144,580.19. All ten sampled ten-minute blocks were positive.
Full public sampled maximum drawdown was 14,179, with 13,117 filled orders,
950,692 traded lots and end inventory -100. Public data is now consumed;
subsequent models must not reuse it while describing its outcomes as fresh.

## Did actual exposure change with volatility?

Instrumentation reproduced every native development result field. Time-weighted
actual inventory was approximately:

| Observed sigma, ticks/sqrt(second) | Mean absolute actual inventory |
| --- | ---: |
| At most2 | 72 |
| Greater than2, at most4 | 21 |
| Greater than4, at most8 | 11 |
| Greater than8 | 13 |

These observations establish the intended exposure behavior on development
data. They do not make the cap an instantaneous position guarantee. Detailed
disjoint volatility bins, the native PnL identity and descriptive fill markouts
are in `results/round2_volatility_attribution.json`.

## Follow-ups and remaining work

Three development-only forecast ablations kept the frozen source unchanged.
No learned alpha earned 77,677.65; original unclipped labels earned 94,200;
clean-endpoint labels earned 112,574. Three risk-weighted/adaptive learners
subsequently reached 112,073, 113,009 and 113,837 on development. These small
later gains have not replaced the verified checkpoint and have no fresh later
public evaluation. The total development replay count is now 62; 87 tests pass.

Server feedback must be attached to the exact uploaded source and submission
ID using `scripts/round2_server_results.py`. Compare the current checkpoint
against materially different follow-ups, avoiding many nearly identical server
queries. Organizer validation and post-deadline private scoring remain separate
from these public-data diagnostics. The provisional deadline is 00:15 CET;
keep a verified source ready before 23:45 CET.
