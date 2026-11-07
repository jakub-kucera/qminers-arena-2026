# Round 2: work toward 250,000 local net PnL

The user raised the target after the verified 167,412 composite. Preserve that
standalone source and its exact hash. No competition website/server access is
authorized. Emailing the model was a separately authorized one-time action.
All public data is consumed; subsequent experiments are sample-tuned research,
not fresh holdouts. Native latency, matching and penalty rules stay unchanged.

## Supplied R2-RA reference

Exact supplied RA reproduced 165,459 in both an audit and the unmodified CLI.
It aggregates signed market-aggressor flow for 250ms, consumes a 500-lot signal,
uses the original cumulative one-lot shadow gate, and adds a three-tick stop
from the signal midpoint. Stop recovery requires fresh qualifying flow.
Observed first80=136,040; final20=29,419; sampled drawdown14,844; volume384,300;
filled orders2,704. Native actual and potential exposure stay within100.
The precise75% split reproduces its header's136,152/29,307.
Source and verified comparison are in research/round2_ra_supplied_20261107.

## Hybrid experiment

Six predeclared candidates integrate RA into the adaptive maker/taker composite.
All keep one shared100-lot budget and retain pending cancellations. Stops either
flatten or return control to the maker. The original shadow remains unstopped.
The full selection maximizes combined minutes30-80 profit while requiring both
minutes30-60 and60-80 positive. No clock-specific regime switches are encoded.

| Flow window / stop / recent gate / stop response | First80 | Minutes30-60 | Minutes60-80 |
| --- | ---: | ---: | ---: |
| 250ms / 0 / 20 / flat | 162,604 | 39,231 | 89,394 |
| 250ms / 3 / 20 / flat | 171,470 | 43,199 | 91,481 |
| **250ms / 3 / 20 / maker** | **173,183** | **51,053** | **86,304** |
| 250ms / 3 / 0 / flat | 146,478 | 36,555 | 85,144 |
| 150ms / 3 / 20 / flat | 174,866 | 48,038 | 86,750 |
| Single callback / 3 / 20 / flat | 155,284 | 49,212 | 62,374 |

The bold candidate won the predeclared later-period rule and was frozen before
full replay. A higher total prefix alone does not override that selection.
Authoritative running/completed full outputs: logs/round2_ra_composite.

The frozen hybrid achieved **195,721 net PnL** in both the full audit and
unmodified native CLI, matching every result field. Final 20% profit: 22,538;
sampled maximum drawdown: 10,285; filled orders: 9,562; traded volume: 675,070.
Actual and potential exposure never exceeded 100 and penalties were zero.
It improves the previous 167,412 by 28,309, but is still 54,279 below 250k.
The exact source is `strategies/round2/round2_local_195721.py`, SHA256
`e2d55a7d606b1a679070bc386182c38d7bf8b35da8b5a77d6a55ae408b0118e2`.
The original emailed file remains unchanged. No new model was emailed/submitted.

## Passive-first RA execution rejected

Directional entries/flips quote passively for20/100ms, optionally improving the
touch by one tick, then cancel and cross. Stops flatten using IOC; terminal
cancellation confirmation is required before another order. All four variants
underperform original RA's136,040 first80 score:

| Wait / improvement | First80 | Minutes30-60 | Minutes60-80 |
| --- | ---: | ---: | ---: |
| 20ms / 0 | 100,219 | 28,228 | 55,520 |
| 20ms / 1 | 105,589 | 31,495 | 56,573 |
| 100ms / 0 | -10,265 | -4,370 | -3,843 |
| 100ms / 1 | 12,632 | 6,022 | 4,311 |

This rejects these grace periods on this tape; it does not prove all passive
execution is inferior. Their sources and failed results are preserved.

## Causal learning alternatives

Four further candidates use the frozen hybrid structure. Two add three bounded
features to the online ridge: accumulated unconsumed flow, last flow direction,
and active/nonstopped direction. Tree input indices remain unchanged. Compare
near-cumulative ridge memory with300-second memory; two controls use existing
features with300/900-second memory. Labels mature after400ms. The same prefix
selection rule applies; full results cannot be used to replace a frozen choice.
Authoritative outputs: logs/round2_ra_learning.

| Added flow-state features / ridge memory | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| Yes / 100,000s | 173,227 | 41,890 | 89,713 |
| Yes / 300s | 165,185 | 39,601 | 90,529 |
| No / 300s | 160,515 | 33,700 | 90,174 |
| **No / 900s** | **174,332** | **52,261** | **88,685** |

The900-second candidate won the predeclared later-period rule, was frozen,
and completed at **195,460** in both full audit and unmodified native CLI.
Every result field matches. Final20% contributed21,128. It is261 below the
previous195,721 result, so it adds no verified improvement. Additional features
did not improve the prefix selection metric. These nearby full results are
consistent with a useful hybrid gain across two memory settings on this tape;
they do not establish out-of-sample robustness.

Validation checkpoint:115 repository tests pass, including flow consumption,
expiry, stop rearming, partial-fill accounting, and cancellation reservations.
The250k goal is not established by these prefix results.

All scheduled runs in these three studies have finished. Best verified local
net remains195,721; gap to250k is54,279. Next bounded experiments should examine
the hybrid's selector/exit rules rather than expand arbitrary feature counts.
Do not change the native fee, latency or matching rules to inflate the metric.
