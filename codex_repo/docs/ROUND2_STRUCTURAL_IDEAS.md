# Structural experiments for round 2

The user reported ThatsMyQuant 8th/61 at 602,526.53, against Team 2's
792,696.00. The gap is 190,169.47, or 31.56% of our reported server PnL. The
exact uploaded source and scored dataset remain unmatched. The local 624,076
replay is a different piece of evidence. See the reported leaderboard manifest.

The ranking cannot identify the winner's strategy. Better execution, prediction,
turnover, sizing or a combination could explain the gap. Our local final model
paid only 1,700 in penalties; eliminating that fee alone cannot explain a gap
of this size. Do not claim the winner used a particular method without evidence.

The subsequent [round-1 curve analysis](ROUND1_CHART_EVIDENCE.md) strengthens
the steady execution/fill-quality hypothesis for that tape. Its inventory
estimates require qualifications. These priorities remain conditional on the
new round-2 public tape: a different spread, depth or flow regime can favor
another family. No fixed 60–80 lot target follows from the old leaderboard.

The six prepared candidates are useful controls and adaptation alternatives.
They do not yet implement the queue-value or latent-flow architectures below.

## 1. Queue-conditional profitability and joint quote control

**Hypothesis:** an unconditional future-midpoint forecast does not rank the
orders that will actually fill. Toxic events preferentially fill bad quotes.

Model two quantities separately: probability of filling before cancellation or
adverse price movement, and expected net mark-out conditional on filling.
Condition on actual quantity ahead, cancellations ahead, replenishment behind,
order age, spread, flow class and the 5 ms cancellation race. Then choose keep,
cancel, price and quantity using expected reward and the value of queue priority.

A useful decision score is fill probability times conditional profit, less
inventory opportunity cost and expected breach cost. Fit/calibrate both parts
and replay the resulting policy in the native engine; forecast MSE alone is
not the objective. Preserve good queue position when its value exceeds a small
forecast change, and cancel before a likely toxic fill when latency permits.

**First probe:** measure fill probability and 5/20/100/400 ms fill mark-outs by
queue position and observable state, using development data. Reject the idea
if state-conditioned actions do not improve subsequent chronological net PnL.

Earlier own-fill and shadow-value prototypes failed on round 1. The shadow
sample was dominated by nonfills (about 3% filled). Do not repeat the same
single regression over mostly zero-payoff examples: separate fill likelihood
from fill-conditional outcomes and account for policy-dependent samples.

Queue-reactive models motivate treating event rates as book-state-dependent;
this is a proposed competition-specific adaptation, not a proven winner:
[Huang, Lehalle and Rosenbaum](https://arxiv.org/abs/1312.0563).

## 2. Latent fair price and observable flow archetypes

**Hypothesis:** new quotes and aggressive orders contain different information
depending on their behavior. Averaging all volume can drown out informed flow.

Estimate an underlying fair price using fresh quote centers, cancellations,
aggressive limit prices, and a robust state-space filter. Learn offsets for
different observable size, distance, lifetime and burst patterns. Estimate
their subsequent toxicity causally and weight the informative classes more.
The current model's two broad aggressive groups and a size cap are only a
coarse approximation to this hypothesis.

Order IDs identify an order's observed lifetime; they do not establish trader
identity. Do not infer undocumented participant IDs, memorize ID arithmetic,
or assume an agent-based generator. Persistent behavioral types are a testable
hypothesis, not an announced property of the competition.

**First probe:** show stable out-of-time differences in future mark-out between
observable classes, then test a robust latent-price estimate in both maker and
selective-taker policies. Discard classifications that only work in one block.

Micro-price research supports considering a richer estimator than the midpoint;
the specific filter/archetype model remains to be built:
[Stoikov](https://www.tandfonline.com/doi/abs/10.1080/14697688.2018.1489139).

## 3. Optimize inventory turnover and capacity value

**Hypothesis:** capacity can be tied up in positions with weak remaining edge,
blocking later profitable opportunities. Our local absolute-inventory median
was 97 lots; that motivates measurement, but does not by itself prove inefficiency.

Estimate the value of holding each inventory level under the current forecast,
queue state and expected exit time. Choose a target among a small inventory grid
and allocate the 100-lot free budget to the most valuable opportunities. Allow
an IOC reduction or reversal when the opportunity cost of waiting exceeds its
spread and latency cost. Use the actual fee cliff beyond 100, not a generic
quadratic inventory penalty.

**First probe:** decompose PnL into spread capture, post-fill adverse movement,
inventory drift, hedge costs and penalties. Measure time-to-exit and blocked
profitable fills at the limit. Test completed-cycle net PnL per inventory-time,
not just filled volume. More turnover is only useful if its additional trades
remain profitable after costs.

## 4. Event-time prediction and selective maker/taker switching

**Hypothesis:** fixed 400 ms labels mix very different numbers of events across
regimes. Predict the next price move and queue-depletion time, plus flow-burst
continuation/termination, rather than using one universal time horizon.

Use a small multi-horizon/event-time classifier or temporal model. Post passive
quotes in range-bound states; take liquidity only when the estimated move pays
for entry, expected exit, latency and any risk costs. Focus IOC entries on
specific events such as likely queue depletion or persistent informed bursts.
Do not reuse a blanket prediction threshold: earlier broad IOC hybrids failed.

**First probe:** rare-event precision and calibrated net-edge estimates, followed
by an independent chronological policy comparison. Include a passive-only and
no-trade control. A larger neural model without a better target is not the plan.

Flow clustering and short-term alpha have established modeling precedents:
[Cartea, Jaimungal and Ricci](https://epubs.siam.org/doi/10.1137/18M1176968).

## 5. Conditional queue prepositioning

**Hypothesis:** a quote placed before a price becomes the touch can earn useful
priority that a touch-following strategy misses after its 5 ms delay.

Allocate part of the same exposure budget to the next likely touch only when
its predicted priority value exceeds the cost of reducing current-touch size.
Compare with unconditional ladders, which failed on round 1. The API only
permits shrinking orders; a tiny priority seed cannot later be enlarged while
claiming preserved priority. Budget sizes and cancellations must be real.

**First probe:** queue rank and profit of fills after a seeded price becomes
the touch, net of lost current-touch fills, cancellation races and all penalties.

## Order of work

First establish the exact submitted file behind 602,526.53 and the new public
data's regime. Then instrument the current maker's profit/exit decomposition.
Build one queue-conditional policy and one latent-price/archetype model, with
the existing strict and transfer references. Inventory control is the next
structural layer. Keep model-family trials distinct from minor parameter tuning.

Use public chronology for development diagnostics and a small predeclared batch
of server-validation submissions. Log every server query against exact source
bytes. Validation feedback used for selection is consumed evidence. Only the
organizer's private post-deadline backtest determines the final score. Public
being smaller does not establish a linear PnL multiplier or identical regimes.
