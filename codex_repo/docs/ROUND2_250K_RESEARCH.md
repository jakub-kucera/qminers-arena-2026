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

## Selector and stop follow-up

Six one-factor alternatives around the frozen 195,721 source were declared
before replay. All used the same consumed first 80% and later-period rule.

| Changed parameter | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| Recent-profit gate 10 | 157,661 | 47,083 | 77,775 |
| Recent-profit gate 40 | 171,123 | 46,946 | 82,542 |
| Lookback 30 seconds | 170,071 | 55,719 | 70,656 |
| Lookback 120 seconds | 148,438 | 33,170 | 86,273 |
| Stop 2 ticks | 170,857 | 39,920 | 90,722 |
| **Stop 5 ticks** | **176,875** | **48,715** | **92,334** |

Stop 5 won the predeclared rule and is frozen for full audit/CLI comparison.
These results suggest a profitable stop-distance neighborhood on this tape,
but no large improvement from simply changing the selector's parameters.

The full stop-5 audit and native CLI both returned **199,689**, matching every
result field. Final 20% profit: 22,814; sampled maximum drawdown: 10,610;
filled orders: 9,662; traded volume: 686,722; penalties: zero; actual/potential
exposure: at most 100. This improves 195,721 by 3,968 but leaves a 50,311 gap.
Exact source: `strategies/round2/round2_local_199689.py`, SHA256
`5f69e437ea77d9d494f19427162c26dab6718e76ead392bb6835cb9e19f83343`.
The source and result are archived in research/round2_ra_selector_20261107.

## Shadow-policy alignment and hysteresis

Four separate hypotheses tested a stopped virtual follower and entry/exit
hysteresis (enter above 20 recent profit, exit below 5 or 0). The independent
shadow stop uses its own signal anchor and virtual inventory. All underperform
the reference's 173,183 first-80% score and its later-period selection score:

| Shadow / exit threshold | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| Unstopped / 0 | 155,759 | 33,091 | 88,942 |
| Unstopped / 5 | 153,993 | 36,413 | 80,173 |
| Stopped / no hysteresis | 156,336 | 32,482 | 86,662 |
| Stopped / 5 | 162,585 | 42,465 | 81,749 |

Rejected for promotion; no full replay selected. Causal shadow-stop and
hysteresis tests pass. Failed hypotheses are retained, not silently dropped.

## Flow quality follow-up

A further five-candidate protocol tests returning to market making after
250/1,000/3,000ms without a qualifying flow fire, or requiring net flow to be
at least 25%/50% of gross signed-callback volume. Shadow accounting stays as
in the reference. Causal expiry and conflict-filter tests pass. Authoritative
outputs: logs/round2_ra_flow_quality. No claim of fresh validation is made.

| Flow filter | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| Freshness 250ms | 153,622 | 57,120 | 51,741 |
| Freshness 1,000ms | 157,144 | 50,780 | 62,236 |
| Freshness 3,000ms | 156,114 | 36,495 | 75,594 |
| Net/gross at least 25% | 173,183 | 51,053 | 86,304 |
| Net/gross at least 50% | 157,022 | 33,777 | 86,575 |

The 25% filter reproduces the reference's prefix result; other filters lose
profit. No full replay selected because none improves the reference. All
15 candidates from this follow-up are retained, including failures.

Current checkpoint: **199,689 verified**, **250k goal still active**. All runs
above finished and all 119 repository tests pass. No additional email or
competition submission occurred. Suggested next hypothesis: separate online
fill-value calibration by direction or spread, rather than further widening
the selector parameter search. Any new tests must be causal and predeclared.
