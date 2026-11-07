# Current objective: improve evolving main by at least10k

The user replaced the earlier319920 target with improving models from main
by at least10000 and explicitly confirmed that the drop means a sharp market
price decline. Continue checking upstream main as it changes; do not claim
future commits have already been reviewed. Competition server access remains
prohibited. All local public data has been repeatedly consumed.

## Current upstream evidence

Fresh fetches still show `36a041af7da57060f5cafe5bcc4f4772c23cd31b` on main in
`jakub-kucera/qminers-arena-hachathon-final-v2.9-fr-fr`. The user confirmed main.
Snapshot sources, native configuration, full results, price-window definitions
and timestamped goal update are archived in
`research/round2_main_sync_36a041af7da5_20261107`.

All six active-registry sources were replayed on the same full public tape:

|Main candidate|Native net PnL|
|---|---:|
|No-trade control|0|
|Guarded trend|-6116|
|Strict100 maker|-229801|
|Fast adaptation|-241010.88|
|Round1 transfer|-258271.22|
|Dual memory maker|-267529.75|

The active guarded-trend result matches independent native CLI in every field.
Main's frozen round1 score624076 is on different data and is not a round2
baseline. Main has not yet acquired the newer supplied T2 models. To avoid
claiming new progress by beating a stale weak reference, this local cycle
also requires **306715=296715+10000**. That extra guard is our conservative
comparison, not a replacement of the user's upstream requirement.

## Price-drop evidence

The no-trade full-tape profiler finds the largest sampled25s fall at elapsed
3850–3875s:9853.5 to9731.5, a122tick decline. The largest sampled100s fall is
3850–3950s:9853.5 to9707, down146.5ticks. These are diagnostics chosen only
from market prices, not strategy returns or trading-time rules. Sampling can
miss shorter extremes and quote jumps need not be permanent price moves.
The profiler's inherited 'development-only' text is stale here: input was the
full public tape, with the same verified hash as all strategy comparisons.

Using aligned native1s PnL samples:

|Model|Full PnL|25s drop window|100s drop window|Outside100s window|
|---|---:|---:|---:|---:|
|Reference296715|296715|14070|34433|262282|
|Flow magnitude500ms|304476|14523|35108|269368|
|Broad/narrow ensemble50%|297209|14115|33117|264092|

Flow-model improvement7761 comprises675 inside the100s fall and7086 outside.
The higher profit therefore does not arise solely in that fall. Its sampled
maximum drawdown nevertheless rises from6012 to10880; this material tradeoff
must accompany any recommendation. All these new models retain actual and
potential100 and zero fees. Window figures are descriptive, not fresh tests.

## New model studies

Flow magnitude adds bounded net-volume and square-root intensity features,
using market takers only. Fixed decay100/500/2000ms or all three were tested.
Prefix PnL220758/243617/219613/220977; later30–80 gains176570/196983/185875/173512.
500ms was frozen before full replay304476; native CLI parity verified.
Source SHA256`bbf2558137756bc7ce1f0daf332c4438fa1ef3afb74f1cd1bcd8f5dfac5f1780`.

The dual-head learner combines independently trained broad and narrow-spread
ridge models with fixed25/50/75% narrow weight. Prefix PnL223856/227777/225660,
later30–80 gains189239/195271/194168. Selected50% full297209, drawdown6121,
native parity; not the highest-PnL candidate. A preflight-only draft used
forbidden dynamic attribute access, was rejected before any replay, and was
replaced by explicit state assignment in the v2 study. This is compatibility
history, not an additional performance-selected variant.

Both studies were frozen under the former319920 objective before the user
changed it. Their archived protocol goals remain historical rather than being
rewritten. Subsequent impact-ablation and robust-shock studies explicitly use
the current local-cycle guard306715. No future-price features or time-of-crash
switches are added.

## Verified current-cycle result:316,031

The Huber6 residual-weighted learner scored316031, **+19316 over296715** and
above the conservative306715 cycle target. It also exceeds the fetched main
active/control baselines. The user-requested current-cycle increment is met;
future upstream commits must be reviewed separately. Final fresh fetch still
showed36a041a. No competition server or email was used.

Exact source `strategies/round2/round2_local_316031.py`, SHA256
`088c20f7cf726b9e1e5047e2adc8c305e5c2a9ed0f1064aced4b097042f608f6`.
Native CLI and audit agree on all result fields; fee0, actual/potential100,
filled orders2352, traded lots284784, first80=253707, final20=62324.
Maximum sampled drawdown remains10880, above the prior reference6012.

Two final studies were frozen before replay:

|Case|First80|30–60|60–80|
|---|---:|---:|---:|
|Net magnitude only|244267|91272|106686|
|Sqrt intensity only|248247|96933|108956|
|Depth-normalized net only|232589|80795|109730|
|Magnitude plus depth|249920|96013|112944|
|Huber3 weighted learning|253320|96558|111103|
|Huber6 weighted learning|253707|97253|112638|

Magnitude+depth won its study and verified310978 full, fee0, drawdown10880.
Huber6 won the other and verified316031. Huber weighting uses residuals of raw
forecasts stored at observation, only after400ms labels mature. Its weight
scales mass/covariance/xy consistently. This limits outlier influence in
learning; it is not a guaranteed stop-loss during a new shock. The final model
uses the35feature magnitude model, not the36feature depth alternative.

### Fine-grained shock and mirror checks

One-second sampling identifies a95.5tick fall over1s,100.5 over2s,122.5 over25s,
and156.5 over100s. These windows differ from the coarser25s-grid diagnostics
above. At the largest100s window (3936–4036s), the new model earns20223 versus
20131 for the reference; outside it,295808 versus276584: **+19224 outside**.
Thus the improvement is not concentrated in that price-drop window. Subtracting
its PnL is descriptive, not a replay with the crash removed from history.

The maximum model drawdown occurs at5398–5400s, during a sharp **upward** move
of the no-trade midpoint from9569 to9682.5 (+113.5). The model therefore still
has material reversal risk despite earning money during the principal decline.
See `crash_comparison.json` and `market_dynamics_1s.json` in the main-sync archive.

Synthetic mirror (positive prices mapped to20000-price and B/A swapped) also
scored316031 with zero fees, actual/potential100, and an identical6001-point
PnL curve. This supports directional symmetry, not unseen-market validity.
Mirror source/data fingerprints and full audit are archived in
`research/round2_mirror_316031_20261107`; the large derived tape stays gitignored.

All146 tests passed; candidate standalone checks, native parity, immutable
source hashes and risk accounting passed. All replay processes are terminal.
The public tape and its mirror are consumed research data, not fresh holdouts.
