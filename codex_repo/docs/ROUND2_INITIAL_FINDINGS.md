# Round-2 public intake and initial findings

The incoming workspace-root `round2_public.csv` was moved, without overwriting
data, to `data/round2_public.csv`. SHA-256 was checked before and after moving:

```text
88ff641e962540c66fa1cc4a3547585d31838d0929340150690cabb4f3cfb9f4
```

The tape is 78,512,311 bytes, 2,193,064 events, and approximately 6,000 seconds
(100 minutes). Round 1 was 4,411,336 events over 12,000 seconds. In this public
CSV the duration, as well as file size, is approximately halved. This does not
justify multiplying PnL to forecast a hidden dataset.

## Scope

Preparation created `logs/round2/manifest.json`, immutable copies of the six
predeclared strategies, and the chronological public prefixes. All outcome
analysis and replay below used only the first 60% of public data, about one
hour. The next 20% and last 20% have not been replayed. No server validation
feedback or organizer private data has been used.

Round-1 reference diagnostics use its original first-60% prefix, about two
hours, and the same profiler source. Reported correlations are median block
correlations, with overlapping labels; they are not pooled significance tests.

## The surface looks similar; price dynamics do not

| Development-window measure | Round 1 | Round 2 |
| --- | ---: | ---: |
| Events / second | 367.59 | 364.92 |
| Median G insertion quantity | 14 | 14 |
| Median F insertion quantity | 61 | 61 |
| Median inter-event gap | 1,794 us | 1,794 us |
| Average spread | 1.070 ticks | 1.169 ticks |
| Maximum observed spread | 5 ticks | 61 ticks |
| Average bid-touch quantity | 1,316 lots | 1,187 lots |
| Average ask-touch quantity | 1,295 lots | 1,193 lots |
| Visible order count, sampled mean | 77.4 | 74.0 |
| Valid-book time at spread greater than 2 | 0.0763% | 2.9584% |
| Valid-book time at spread greater than 5 | 0% | 0.1028% |
| 25-second midpoint-return SD | 4.51 ticks | 16.46 ticks |
| Median absolute 25-second midpoint return | 3.0 ticks | 5.0 ticks |
| 90th percentile absolute 25-second return | 7.5 ticks | 24.0 ticks |
| 99th percentile absolute 25-second return | 11.0 ticks | 58.0 ticks |
| Adjacent valid-book midpoint jumps of at least 2 ticks | 0 | 214 |
| Adjacent valid-book midpoint jumps of at least 10 ticks | 0 | 27 |
| Depth-imbalance / 100 ms future-return median correlation | 0.305 | 0.128 |
| Depth-imbalance / 500 ms future-return median correlation | 0.338 | 0.093 |
| Trade-flow / 500 ms future-return median correlation | 0.253 | 0.129 |

The 25-second return SD is about **3.65 times higher**. Large visible midpoint
jumps and spread tails occur in round 2 despite similar message sizes/timing.
The largest adjacent valid midpoint move was 28.5 ticks, versus 1.5 in the old
reference. Some large micro-jumps occur with temporarily wide books; counts do
not prove every jump is a permanent efficient-price change. Extreme spreads
are brief, rather than the market being wide throughout the hour.

## Predeclared strategy tests

These are cold-start native audited replays of the first public hour. Every
private-event ledger and declared strict exposure contract passed. Scores are
net of the original native penalty; these are not server validation results.

| Candidate | Development net PnL | Penalty |
| --- | ---: | ---: |
| Round-1 transfer | -38,204.33 | 1,063.33 |
| Strict 100 maker | -37,267.00 | 0 |
| Fast adaptation | -31,746.00 | 1,450.00 |
| Dual-memory maker | -40,565.00 | 1,350.00 |
| Guarded trend | -3,019.00 | 0 |
| No-trade control | 0.00 | 0 |

The transfer's ten-minute PnL increments were approximately -15,349, +21,062,
+4,051, -40,727, -16,894 and +9,653. Its sampled drawdown reached 74,334.
Losses are not a uniform small execution-fee problem. Its approximate first-hour
round-1 reference was +184,350, sampled from the previously verified full-run
curve at 3,600 seconds. That reference is not an exact separately replayed prefix.

## Controlled development diagnostics

Four additional causal policies were evaluated on the same development data:

| Diagnostic | Net PnL |
| --- | ---: |
| Symmetric touch maker, no learned alpha | -32,858.35 |
| Invert the trained forecast | -232,827.82 |
| Symmetric maker with wider quotes | -87,445.31 |
| Trained forecast with wider quotes | -74,850.91 |

These are diagnostics, not selected submissions. Simple inversion is strongly
unhelpful, and widening quotes alone made this sample worse. The results are
consistent with a need to distinguish fill toxicity, jump risk and inventory
holding costs; they do not establish the cause by themselves. No active policy
tested in this initial pass is profitable on the development prefix.

## First inventory-policy prototypes

Four further development-only policies completed. Planned targets still permit
the original charged cancellation overlap; they are not strict exposure bands.

| Prototype | Net PnL | Median absolute inventory |
| --- | ---: | ---: |
| Signal-dependent target, 10-lot band | -58,102.08 | 42 |
| Signal-dependent target, 25-lot band | -93,758.25 | 49 |
| Selective directional entry | -55,295.00 | 0 |
| Target plus conditional aggressive reduction | -65,660.97 | 75 |

These implementations resized with cancel/replace. They submitted roughly
673K–798K orders for the target variants, versus 35K for the reference, losing
queue priority and changing which fills they received. Therefore the results
do not isolate a lower-inventory effect and do not establish that lower exposure
is intrinsically worse. A production dynamic sizer needs priority-preserving
shrinks, restrained target updates and measured fill quality. No such winner
has yet been established. The suite has 76 passing tests, including planned
target budgets and preservation of actual pending-cancel reservations.

## Next work and remaining evidence

Keep the later public segments available while developing new hypotheses.
Prioritize native fill/PnL attribution, post-jump continuation versus reversion,
conditional fill value, robust fair-price estimation, and inventory exit/target
control under the higher volatility. Do not assume a smaller constant position
cap or another quote-width grid alone creates an edge. Keep the trend/taker
family available, although its initial guarded prototype lost too.

The user's schedule plus the reported 15-minute delay implies a provisional
round-2 deadline of **00:15 CET on Sunday 8 November** (23:15 UTC Saturday).
Plan to have a verified source ready by **23:45 CET**, leaving margin for
server feedback and uploading. Further organizer changes can supersede this.

Evidence: `results/round2_initial_investigation.json`. Detailed public-dev logs
are under `logs/round2/`; generators are `compare_market_dynamics.py` and
`round2_development_diagnostics.py`. The final round-1 source remains unchanged.
