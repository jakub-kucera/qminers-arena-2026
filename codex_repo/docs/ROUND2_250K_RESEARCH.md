# Round 2: supplied liquidity model plus50,000 (target319,920)

## Current verified improvement:296,715

No-passive plus ridge3x reached296715, with native CLI matching every audited
result field. Source `strategies/round2/round2_local_296715.py`, SHA256
`33ec43e71347d9bf3ea81e7ee48c2bfd48d2310abc784a33c1ed614f5218fd55`.
Fee0; actual/potential100; sampled drawdown6012; fills2335; volume271946;
first80=226129; final20=70586. Improvement over supplied269920 is26795;
the target319920 still needs23205. Lower drawdown than294098, but higher
than the supplied reference4658. No unseen-tape superiority is claimed.

Four combination cases were frozen before screening:

|Case|First80|30–60|60–80|
|---|---:|---:|---:|
|No-passive ridge3x|226129|80825|108116|
|No-passive flow0.2|229622|73573|113083|
|No-passive flow0.3|221242|68599|112300|
|No-passive flow0.2+ridge3x|229708|75455|112811|

Ridge3x won by combined30–80 gain188941, despite a lower total prefix than
some alternatives. It was frozen before full replay. The exact rule remains
positive30–60 and60–80, then maximize their combined gain. Archive:
`research/round2_t2_noquote_combo_20261107`.

### Causal forecast calibration: rejected after full check

Past raw forecasts and observed spreads were stored with features, then matched
to400ms outcomes. Only observed spread1 and absforecast>=0.1 entered the
calibrator; responseclip3, ridge prior20 toward identity, slopeclip0.5..1.5.
Tested memory300/1800s and blend50/100%. Later30–80 gains were185988,182162,
183312,182147 respectively (300/50,300/100,1800/50,1800/100).
Selected300s/50% full285091, final20=68685, fees0, drawdown6112, native parity.
Not promoted. Archive `research/round2_t2_forecast_calibration_20261107`.

### Stronger inventory skew: rejected on prefix

From294098, fixed skew0.1/0.25/0.5/0.75 produced first80 PnL211949,179713,
51274,-488322. Later30–80 gains167947,148230,74991,-240149 all underperformed
reference185349. No full candidate selected. Stronger reversal pressure can
cause costly repeated trading; this is not an automatic risk improvement.
Archive `research/round2_t2_inventory_response_20261107`.

All138 tests pass, including calibration maturity, stored forecast use, stale
and wide-label exclusion, bounded/decaying gain, and weighting all learner
sufficient statistics consistently using spread known at observation time.

### Match training spread to execution spread

From294098 (not the newly selected ridge3x source), three variants assign
weight0/0.25/0.5 to samples whose spread at observation exceeded1 tick.
Narrow-spread samples retain weight1. The weighted mass, covariance and cross
product use the same weight; zero-weight labels do not count toward warmup.
This changes learning, not the execution spread gate or target horizon.

|Wide-spread weight|First80|30–60|60–80|
|---|---:|---:|---:|
|0|222558|85774|106815|
|0.25|224023|86734|104281|
|0.5|218595|80604|103479|

Weight0 won the frozen later-period criterion with192589 and was selected
before full replay. It starts weaker, so prefix total is not the selection
criterion. No future spread or reconstructed past features enter training.

Full weight0 replay292908, final20=70350, zero penalties, native CLI parity.
Not promoted: later-prefix gain did not overcome its weaker early period.
Archive `research/round2_t2_training_spread_20261107`. All15 new candidates
across these four studies are terminal; no live process remains. Best296715.

## New user target and supplied reference

The user superseded250k with **at least50,000 above the supplied liquidity T2**.
Its unchanged source reproduced269920 in both native CLI and audit, so the
target is319920. Source SHA256:
`54658482f1be2a9c44e28f13f803caac50ec78da22aedbce1a3d074f9d7489e4`.
Archive `research/round2_t2_liquidity_supplied_20261107` contains exact source,
full audit, native results and curve. Fees0, actual/potential100, drawdown4658,
first80=209280,final20=60640. This is a supplied baseline, not our improvement.

The33feature online ridge adds young-order imbalance and interactions with
far-order-count to the earlier29feature price model. Its variable named
dispersion is far-order count, not price volatility. Order age is first seen
in observed snapshots, not guaranteed exchange insertion age. No fixed trees.

Six structural cases were frozen and evaluated on consumed first80:

|Case|First80|30–60 gain|60–80 gain|
|---|---:|---:|---:|
|Reference|209280|79345|94688|
|Ridge3x|207915|80879|90133|
|Memory1800s|192259|76812|81749|
|Horizon800ms|173219|71130|82373|
|Flow bias0.3|207840|69990|100085|
|Flow bias0.2|210634|72945|96587|
|Age/concentration features|197614|74056|88655|

Ridge3x won among modifications by the frozen later-period criterion, but did
not beat the baseline. Full replay268433, final20=60518, fee0, drawdown3751;
native CLI exact parity. It is archived, not promoted for the PnL objective.
Its lower drawdown is useful evidence, not achievement of the new target.

Six independent execution cases retained the supplied33feature model:

|Case|First80|30–60 gain|60–80 gain|
|---|---:|---:|---:|
|IOC gap10ms|199017|72286|88235|
|IOC gap25ms|197243|73539|88316|
|IOC gap100ms|194383|73001|83084|
|Take edge0|180137|57733|85509|
|Take edge0.3|181008|68746|85757|
|No passive quotes|223851|78849|106500|

No-passive won before full replay. It removes the one-lot passive orders while
keeping online learning and IOC execution. The changed live trade history also
changes own-fill features and available room; attribution solely to avoiding
passive losses is not established. All candidate runs assert strict100.

The study/checkpoint tools now retain the declared goal in the report rather
than hardcoding250k. Reference-relative targets verify source identity, same
tape, and native/audit parity before resolving the required numerical score.
All133 tests pass, including feature dimensions and causal maturity across all
six structural variants. Repeated public data remains selection-biased.

### Verified execution winner:294,098

Full audit and independent native CLI agree on every result field for
`strategies/round2/round2_local_294098.py`, SHA256
`06acfa3b209a6a3ccbf7beb08ec0715774c87bf98becdeae07f52465c3380f09`.
Net294098, fees0, actual/potential100, sampled drawdown6222, fills2492,
volume288516, final inventory-100, final20 gain70247. Compared with supplied
269920: **+24178 (+8.96%)**, still **25822 below target319920**.
Drawdown rose from4658 to6222; better PnL does not mean lower risk here.
The selected source was frozen before full replay. Archive:
`research/round2_t2_execution_20261107`; exact user copy in outputs/round2-local-294098.

The model removes passive quotes (QUOTE_SIZE0), caps POSITION_LIMIT100 and
reserves all live quantities. Other forecast/execution parameters remain as
supplied. Fills drop from117072 to2492 while profit increases, illustrating
why filled-order count alone is not an optimization objective.

All scheduled experiments finished. Next hypothesis: calibrate forecast-taker
edge causally using stored past forecasts and matured400ms outcomes, or test
limited combinations of no-passive with flow bias/regularization. Do not assume
combination gains add. Keep target319920, no server/email, no unseen-data claims.

## Historical250k research

The user raised the target after the verified 167,412 composite. Preserve that
standalone source and its exact hash. No competition website/server access is
authorized. Emailing the model was a separately authorized one-time action.
All public data is consumed; subsequent experiments are sample-tuned research,
not fresh holdouts. Native latency, matching and penalty rules stay unchanged.

## Current checkpoint: H1 refinement, 230,611

The exact supplied H1 reproduced223,794 in audit and native CLI. It incurred
50 in fees, reached actual101 and potential104, and had sampled drawdown6,529.
ROOM_RESERVED fixed IOC reservations but passive quote admission still freed
cancel-pending reservations. A symmetric regression test now covers this gap.

Six cases were frozen before prefix evaluation. All use strict100 with full
pending reservations; differences below are one at a time from supplied H1.

|Case|First80 PnL|30–60 gain|60–80 gain|
|---|---:|---:|---:|
|Strict baseline|171579|46580|84595|
|Label clip3|163111|41750|83835|
|Label clip6|169049|45761|86166|
|Price horizon200ms|167154|43525|78298|
|Take edge0.05|148913|39587|79348|
|Flow bias0.2|179883|47862|87284|

Bias0.2 wins the declared combined later-period criterion. Frozen before full
replay, it achieved **230611**, zero fee, actual/potential100, drawdown6444,
final20 gain50728. Native CLI matches every audit result field. Source:
`strategies/round2/round2_local_230611.py`; SHA256
`21ce75eb06000e908667813324c870c208e615940406ce4c9f63045bc5a4fb32`.
Audit/protocol/source archive: `research/round2_h1_refine_20261107`.
The improvement over previous222966 is exactly7645; improvement
over supplied223794 is6817. Target250000 remains unmet by19389.

The architecture is H1's online29-feature ridge predicting400ms mid movement,
label clip20, one-second fits and near-cumulative memory. IOC entries use
spread<=1 and50ms pacing; the250ms/500lot RA signal, cumulative shadow gate10
and stop3 reduce the same-direction threshold by0.2. Maker quotes remain1lot.
No embedded fixed tree or fill-residual calibration is used in this winner.

### Failed combinations preserved

Four H1 strict-baseline hybrids reused the222966 calibrated maker with quote
sizes25/100, either only at wide spreads or whenever forecast take was inactive.
All used one shared100lot budget; IOC fills were excluded from maker labels.
Prefix results: maker25_wide38579, maker100_wide31892,
maker25_inactive23402, maker100_inactive31678. Later60–80 gains were5869,
-1922,-7599,-10969 respectively. None warranted a full replay or promotion.
Archive: `research/round2_h1_maker_20261107`. This disproves simple additive
benefit for these specific implementations, not every possible hybrid.

The earlier200ms fill-label/residual-ridge combination also completed. Later
30–80 gains for ridge5 blend25/50/75% and ridge25 blend50% were136259,144716,
146848,138133, all below222966's150423. No full replay promoted. Archive:
`research/round2_residual_horizon_combo_20261107`.

All132 tests pass, including cancel-pending reservation symmetry, shared maker
and IOC room, and excluding taker fills from maker calibration. All data has
been repeatedly consumed; no unseen superiority, fresh holdout, or organizer
server result is claimed. No new email or competition submission was made.

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

## Conditional fill-value calibration

Four candidates split mature fill-value residuals by direction and optionally
spread (one tick versus at least two). They retain the 400ms maturation delay,
stale-label rejection, quantity-weighted update, +/-0.5 correction cap, and
300-second decay toward zero. A 50% blend with the global correction was also
tested. Each fill records the prediction's spread bucket before its future
markout is known; IOC fills remain excluded.

| Conditioning / group weight | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| Direction / 50% | 166,762 | 35,079 | 96,221 |
| Direction / 100% | 168,201 | 38,582 | 95,402 |
| Direction and spread / 50% | 162,241 | 32,730 | 97,059 |
| **Direction and spread / 100%** | **184,910** | **50,370** | **97,870** |

The predeclared rule froze the last candidate. Full audit and native CLI both
returned **205,350**, with exact result-field parity. Final 20% contributed
20,440; sampled maximum drawdown was 12,130; actual/potential exposure stayed
within 100; penalties were zero. This is +5,661 net over 199,689, while drawdown
is higher than the earlier 10,610. The metric remains native net PnL.
Exact source: strategies/round2/round2_local_205350.py, SHA256
`505d19d3d36397e4cc9e689ac8130b79167d3823664af54c13ac8f5be91ead33`.

The follow-up update/decay test was declared before its prefix replays:

| One changed parameter | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| Update rate 0.01 | 184,980 | 52,696 | 96,172 |
| Update rate 0.1 | 159,987 | 35,285 | 96,494 |
| Decay 60 seconds | 167,904 | 37,179 | 95,425 |
| Decay 900 seconds | 167,779 | 34,997 | 96,854 |

Rate 0.01 is frozen for a full replay; do not infer a meaningful improvement
from its tiny prefix gain alone. Authoritative outputs: logs/round2_calibration_dynamics.

Completed full audit and native CLI both returned **209,795**, with exact
result-field parity, zero penalties and maximum actual/potential exposure100.
Final20% profit was24,815; sampled maximum drawdown10,557; filled orders10,405;
traded volume737,360. This is +4,445 over the0.03 calibration rate and +10,106
over the199,689 model. The full source is strategies/round2/round2_local_209795.py,
SHA256`df93cf43167894a1fe00a67b459f32d655ecbc8a5d5a2e4f036f54645e05af90`.
The public result is not independent evidence of unseen-data profitability.

## Native-fee burst revisit

The round-1 note explicitly left larger-spread rounds open for investigation.
Four bounded round-2 probes use the unchanged 10,000-per-second breach fee,
100-lot soft limit, 1,000 potential hard limit and 5ms native action delay.
Admission requires spread at least four ticks, a prediction of at least 0.5
in the quote direction, aligned inventory within 100 and a positive fill gate.
The larger maker budget is 250 or 1,000. Recovery triggers after 0 or 20ms;
risk-increasing quotes are canceled and capacity remains reserved until actual
confirmation. There is a one-second cooldown after recovery. These are virtual
local research policies, not a change to rules or the current recommended risk.

| Potential cap / recovery trigger | First 80% net | Native fee | Actual peak | Breaches | Total breach ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| 250 / 0ms | 159,227.00 | 150.00 | 183 | 3 | 15.000 |
| 1,000 / 0ms | 157,924.00 | 150.00 | 183 | 3 | 15.000 |
| 250 / 20ms | 158,698.38 | 1,038.62 | 183 | 3 | 103.862 |
| 1,000 / 20ms | 177,457.10 | 770.90 | 183 | 2 | 77.090 |

The last candidate narrowly passes both predeclared reference thresholds:
first80 net >176,875 and minutes30-80 net >141,049 (observed141,951.44), with
both subperiods positive. It is frozen for a full audit and native CLI check.
Every breach duration is logged and their sum reconciles to the engine fee.
**No burst reached 900 lots.** A 1,000-lot allowance is not evidence of an
actual near-full-capacity entry. The longest observed breach was43.034ms,
demonstrating that the20ms trigger is not an exit-time guarantee.

Full audit and unmodified CLI both returned **199,870.10 net**, with every
field matching: gross 200,641, fee 770.90, final-20% gain 22,413, actual peak
183, two breaches, and no 900-lot event. The fee reconciles to 77,090 microseconds.
This is only 181.10 above its 199,689 reference and below the penalty-free
205,350 candidate, so it is preserved as a diagnostic rather than promoted.
No claim is made that all penalty-paying policies are unprofitable or that
larger filled bursts have been demonstrated in this round.

Validation checkpoint:124 repository tests pass. All full audit/CLI checks above
finished and their parity was verified. Current best209,795 leaves40,205 to the
250k goal, which remains active. Preserve all12 candidates from this stage.
No competition-server access or additional email occurred. The next hypothesis
is a small regularized online residual model that augments the existing four
calibration groups with flow alignment and signed prediction, with features
stored before labels mature and a predeclared bounded experiment.

## Online residual model and fill diagnostics

Four candidates fit a six-feature ridge model to matured fill-value residuals:
four direction/spread indicators, lagged RA-flow alignment, and signed price
prediction. Features are stored with the pending label, never reconstructed
using future state. The fit has300-second memory, quantity weights, a one-second
fit cadence and a +/-0.5 output cap. Ridge strengths5/25 and blends50%/100% were
declared before replay. The current209,795 model remains unchanged.

| Ridge / model blend | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| 5 / 50% | 186,355 | 53,068 | 97,164 |
| 5 / 100% | 167,857 | 35,140 | 94,878 |
| 25 / 50% | 165,228 | 36,385 | 91,485 |
| 25 / 100% | 167,686 | 35,497 | 94,035 |

Ridge5/blend50% won the predeclared later-period rule and was frozen for full
audit/native CLI checks. Replacing calibration entirely did not improve it.

Completed full audit/native CLI: **212,912 net**, exact field parity, zero fees,
actual/potential exposure <=100, final20 gain26,557, sampled drawdown10,719.
The source is strategies/round2/round2_local_212912.py, SHA256
`d15c8979b2539cb77af89b3de1d2db34cd397094b8eb67a35ffb5d54726b2712`.
It improves209,795 by3,117; it does not establish unseen-data superiority.

Independent read-only instrumentation of the209,795 reference reproduced every
native first80 result field, including184,980 net. The following per-lot means
cover eligible, matured maker-fill observations and are quantity-weighted:

| Side / cached spread | Predicted value | Clipped400ms mid markout | Raw400ms mid markout | Future-touch markout |
| --- | ---: | ---: | ---: | ---: |
| Buy / <2 | 0.258 | 0.233 | 0.203 | -0.340 |
| Sell / <2 | 0.287 | 0.277 | 0.280 | -0.263 |
| Buy / >=2 | 0.124 | 0.096 | -0.346 | -1.129 |
| Sell / >=2 | 0.123 | 0.283 | 0.355 | -0.450 |

No observed correction reached its0.5 bound, including the4,786 event samples
of quote gates. Increasing that bound is not supported by this diagnostic.
The difference between raw and clipped wide-buy markouts motivates testing
tail treatment, without hardcoding a buy-side restriction. These overlapping
markouts are descriptive, not independent returns or realized round trips;
future-touch values hypothetically cross the book and are not actual exits.
Taker observations are recorded separately; the maker prediction is not a
calibrated taker forecast. See logs/round2_calibration_diagnostics/diagnostics.json.

Two further bounded protocols were declared before their replays:

- Fill-calibration horizons100/200/800/2,000ms, each with one-second stale
  tolerance after maturity. The fixed tree and price learner remain400ms.
- Calibration-label clipping at+/-6, +/-12, downside6/upside3, or unclipped,
  applied identically to buy and sell directions. The learned correction
  remains bounded0.5 with rate0.01. These test the measured tail discrepancy.

The original public tape is fully consumed. These are causal research probes,
not an untouched validation set. All candidates and failures must be retained.

The horizon screen completed as follows; the200ms candidate won the later-period
rule and was frozen before full replay:

| Fill-label horizon | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| 100ms | 188,693 | 47,796 | 96,895 |
| **200ms** | **189,889** | **53,318** | **97,105** |
| 800ms | 186,248 | 51,308 | 95,002 |
| 2,000ms | 164,000 | 34,426 | 96,350 |

Tail treatment did not beat the reference's148,868 combined minutes30-80 gain,
despite some higher totals including the first30 training minutes:

| Calibration label treatment | First 80% | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| +/-6 | 186,162 | 51,028 | 95,444 |
| +/-12 | 176,750 | 43,339 | 93,850 |
| Downside6 / upside3 | 186,339 | 52,598 | 95,485 |
| Unclipped | 169,338 | 39,169 | 91,577 |

No tail candidate is promoted or selected for full replay. The diagnostic's
tail discrepancy is real, but changing label clipping alone did not convert it
into a better later-period native score.

The frozen200ms candidate completed at **222,966 net**, with every native CLI
result field matching its full audit. Final20% contributed33,077; sampled
drawdown10,262; fills10,838; volume763,978; fees0; maximum actual/potential
exposure100. Exact file: strategies/round2/round2_local_222966.py, SHA256
`85a53b3f77b71d1b642c796fb67f17b61c7263031a5763967fbac5e4aada4c67`.
This is +13,171 over209,795 and +10,054 over the separately tested residual
ridge model. It changes only fill-calibration maturity/stale tolerance;
the price learner and fixed tree keep their400ms target. The two improvements
have not yet been combined.

All128 tests pass and all replays in this stage finished. All12 candidates
plus parity-checked diagnostics are archived. The250k objective remains active,
with27,034 left. Next: a predeclared small combination study, then possibly
price-aware deeper maker quotes when the entry gate would otherwise withdraw.
Quote-price improvements must be reflected in calibration targets so the
learner does not confuse a different execution price with predictive alpha.
No competition-server access or additional email occurred. Public-data reuse
remains a material limitation; no unseen-data profit guarantee is established.
