---
title: Applying the literature to the Arena's event models
type: concept
updated: 2026-11-08
---

# Applying the literature to the Arena's event models

## Summary
For round 4's F5 family, the most useful literature transfer is a compact history of typed events, followed by a test of unexpected flow against already-expected flow.
Discrete execution control, change detection on predictive errors, and temporal generator checks are useful supporting methods.
These are proposals, not new trading results; most pre-event wiki measurements concern Prosperity and must not be treated as findings about the current Arena.

## What the sources say

**Hawkes-structured history, with event types kept separate.**
[Acero, Plank & Zhang](../sources/hawkes-structured-mm.md) represent history with a few
exponentially decayed arrival counts per side. For a mixture-of-exponentials kernel,
these counts form a sufficient state in their model; their network learns the decay
rates. The feature definition, eq. 4, was rechecked on the PDF image:
`literature_md/hawkes-structured-mm/hawkes-structured-mm.md:141` (p. 3, checked).
The results are from a chosen Hawkes simulator, not a real-tape trading test.
[Sitaru et al.](../sources/decomposed-ofi.md) motivate retaining adds, cancels and trades
as separate channels rather than collapsing them into net OFI; their forecasting
finding is reported in `literature_md/decomposed-ofi/decomposed-ofi.md:33` (p. 2).

**Unexpected flow, not just the signed total.**
In the MRR model, the price innovation contains the observed trade sign minus the
sign expected immediately before the trade. This distinguishes a routine continuation
of buying from an unexpected buy. Eq. 16.18 and the conditional expectation definition
were checked on the PDF image: `literature_md/trades-quotes-prices/trades-quotes-prices.md:6241`
(p. 328, checked). That is an impact model, not a guarantee of future returns after
the trade. See [Bouchaud et al.](../sources/trades-quotes-prices.md).

**Control includes future inventory and execution.**
[Guilbaud & Pham](../sources/limit-and-market-orders.md) choose among passive quotes,
price improvement and market orders through a discrete state policy. Their fill-rate
estimation uses time spent in each state, not merely a classifier on orders that filled
(`literature_md/limit-and-market-orders/limit-and-market-orders.md:226-248` (p. 7–8)).
Their simulated gain is largely reduced variance; it is not evidence that our taker
should become a passive market maker. [Huang et al.](../sources/queue-reactive-model.md)
condition event rates on queue state and study filling before the opposite queue
empties (`literature_md/queue-reactive-model/queue-reactive-model.md:277-287` (p. 16)).

**Detect a change in the model's performance.**
[Adams & MacKay](../sources/online-changepoint-detection.md) maintain probabilities for
different times since a change, each with its own predictive distribution. Algorithm 1
was rechecked on the PDF image: `literature_md/online-changepoint-detection/online-changepoint-detection.md:103`
(p. 3, checked). Exact per-update work grows with history; pruning/truncation is needed
for bounded practical cost. Applying it to matured forecast errors is our proposed
adaptation; the paper's financial example concerns changes in return variance.

**Generator realism includes event order.**
[Yeo, Cha & Hwang](../sources/lob-irreversibility.md) show that a calibrated queue-reactive
generator can match an overall path statistic while missing the contribution of event
ordering (`literature_md/lob-irreversibility/lob-irreversibility.md:272-288` (p. 7–8)).
Crucially, their irreversibility scores did not add stable forecasting value beyond
book/history features (`literature_md/lob-irreversibility/lob-irreversibility.md:266` (p. 7)).
The raw sections were read; this is support for a generator diagnostic, not an alpha signal.

## Where they disagree

- **The older wiki says event types/queues may be unavailable.** Those observations
  concern Prosperity's snapshot interface. The present Arena has persistent IDs,
  price-time priority and callbacks with snapshots and trades (`STARTER.md:32`,
  `STARTER.md:77`). That makes event-based methods more plausible, while visible-depth
  censoring and unfilled market orders still limit what the live bot can reconstruct.
- **No clustering on Prosperity is not a negative result for round 4.** The generator
  work measures consecutive F orders on the same side at about .539 on R4 versus .501
  on R3 (IDEAS row "Round 4 needs directional flow and a new generator fit"). This
  motivates a history test but does not identify Hawkes self-excitation: a shared latent
  state can cause the dependence too.
- **Better fit has repeatedly failed to produce better trades.** R4-S1's extra raw F-flow
  and cancellation features explain at most .08% and .07% additional 400-ms variance,
  respectively (`data/arena/round4/stats.md:139`). Its placement asymmetry looked stronger
  but yielded little PnL. R4-C1's speed calibration and R4-D1's drift/jump filters also
  failed. A useful proposal must add conditional history or a different decision target,
  rather than relabel those features.
- **The public winner is not the validation winner.** X1R3 improved public by 23,313
  but lost 27,812 to F5 on validation (`data/arena/round4/HANDOVER.md:103`). Use F5/W2
  as the benchmark; a generator that endorses X1R3 cannot certify further improvements.
- **A correction to the earlier classifier motivation:** large-residual downweighting
  was already ablated. Huber off gained only about .1k on real R4, with other deltas
  mostly losing (`data/arena/round4/stats.md:167`). A distributional target remains
  untested, but removing Huber alone is not an outstanding discovery.
- **New evidence while this review was in progress:** main `d95ab9e` added R4-FA,
  the filter-reaction audit. Contradictory fresh placements mostly lag the filter;
  nudging the forecast toward them adds worse takes than it removes in the offline
  decision screen. Re-entries never reach the current filter's depth gate. This
  rejects the earlier fresh-placement change-point proposal on R4; it is not a full
  strategy-PnL result. A residual-calibration detector and a market-order sign-surprise
  test are different proposals and must not be confused with that rejected filter fix.
  Source: IDEAS row "R4-FA", `python/experiments/day/filter_audit.py:1`.

## What it means for our code

**Priority 1: compact typed history for the classifier.** Our adaptation of the
Hawkes representation is to keep separate histories of buy/sell market fills, fresh
bid/ask placements, and reliably identified bid/ask cancellations. Start with two
fixed time scales per channel, rather than learning a large recurrent network. Let a
small nonlinear classifier model interactions with gap, spread and depth. A sequence
such as ask cancellation followed by buying may carry different information from
the same counts arriving in the opposite order; this is a hypothesis to test.

F5 already has exponentially decayed trade flow at 500 ms and fresh-order statistics
(`python/bots/qminers/candidates/r3_F5_jump_bar.py:38`,
`python/bots/qminers/candidates/r3_F5_jump_bar.py:296`,
`python/bots/qminers/candidates/r3_F5_jump_bar.py:366`). More decays alone are therefore
an ablation, not a new edge. Compare (a) current features, (b) typed fast/slow histories,
and (c) a few cross-event interactions or an order-aware short history, at equal model
capacity. The classifier target and chronological evaluation are specified in
[the round-4 research review](../../../docs/ROUND4_RESEARCH_REVIEW.md).

Use the *live-observable* stream. Aggregate multiple fills with the same market taker
ID before treating them as one market-order event. Raw-tape F orders that never fill
are not automatically observable. A disappearing ID is not necessarily a cancellation:
account for trades and the visible-depth boundary. An old order becoming visible again
is not necessarily a fresh placement. Predict an event using the state before that
event, then update the state. Match extracted features to callback output before fitting.

**Priority 2: test conditional impact of surprising flow.** Fit a small causal model
of the next observed market-order side, then examine whether its surprise predicts
additional post-event movement beyond F5, controlling for filled size, current book,
gap and raw flow. Keep expected and unexpected components separate. This applies the
checked MRR idea; it does not impose its constant coefficient or martingale assumptions
on our tape. If the sign predictor is linear in existing features, its residual alone
does not enlarge a linear model's feature span: nonlinear/state-dependent impact is
the distinct hypothesis. Do not rewrite `_lf_trade` until that distinction earns value.

**Priority 3: execution/control with measured transitions.** Use the discrete-control
literature to organize the prior review's action-advantage experiment: state includes
inventory, executable depth, forecast and in-flight orders; actions include waiting,
taking, and completing an eligible partial take. Use actual latency, prices and later
baseline decisions, with consistent terminal inventory value. A full HJB solver or
large RL training run is not needed to measure restricted-action headroom. Passive
pre-entry already filled too rarely in our experiments; do not infer a queue edge
from a paper that assumes generous passive execution.

**Diagnostics, not standalone alpha:**

- Change detection can monitor whether a new classifier's predictive relation has
  changed. Use matured, preferably non-overlapping errors and conditional calibration
  near actionable thresholds; separate rising noise from a change in predictive slope.
  Compare a detector with simple rolling controls. Initial action should be to shrink
  the experimental model toward F5, not liquidate every position or reset the whole
  ridge on volatility. R4-C1 already rejected simple speed-bin rescaling; the different
  hypothesis is a time-local change in predictive skill, which remains unmeasured.
- Compare real and synthetic lagged event transitions conditional on comparable book
  states. Test whether recent placement evidence precedes same-side F fills and whether
  depletion is followed by replenishment or further taking. Use consistent clock and
  event representations. A classifier that distinguishes real from synthetic paths,
  or forward from reversed paths, is a diagnostic; it is not a trading model.
- Use the existing [selection-bias methods](validation-and-overfitting.md) on paired
  block PnL when comparing several candidates. Preserve event dependence in resampling
  and record every trial. These tests cannot make a repeatedly inspected holdout fresh
  or resolve a distribution shift between public and validation tapes.

## How to test it here

1. Audit event features against the actual callback feed. Choose a small set of
   channel/time-scale configurations before looking at later blocks.
2. On real R4, train on earlier blocks and predict later ones. Purge labels crossing
   boundaries, keep mirrors in the same fold, and fit normalization/calibration only
   on the training side. Assess both near-boundary decisions and rare large moves.
3. Compare current inputs, typed history, and interactions/order with the same model
   and target. For the surprise probe, measure post-event returns; explaining the
   instantaneous price move is not forecasting it.
4. Require incremental predictive value beyond the current forecast, then executable
   PnL versus F5/W2. Report chronological blocks and sensitivity to the best episode.
   Do not promote on log loss, R-squared, next-sign accuracy or synthetic PnL alone.
5. Check earlier rounds for sensitivity and generated tapes for stress. A paired server
   upload by the main session/user is stronger evidence of transfer. Keep Python below
   the 900-s runtime cap. No new model was trained or traded in this literature review.

**Low priority for this round:** generic A–S/GLFT quoting, plain imbalance/OFI, a fresh
Das-style latent filter, agent-archetype classification, or full RL on our generator.
The first two overlap established code/tests; the filter already has a stronger
placement observation and informed-side updates failed; archetype labels are absent;
and synthetic policy gains already have a known transfer failure. This is a priority
judgment for F5, not a claim that those methods never work.

## Sources
[Hawkes-structured history](../sources/hawkes-structured-mm.md),
[decomposed OFI](../sources/decomposed-ofi.md),
[MRR and price impact](../sources/trades-quotes-prices.md),
[limit and market orders](../sources/limit-and-market-orders.md),
[queue-reactive model](../sources/queue-reactive-model.md),
[online change detection](../sources/online-changepoint-detection.md),
[event-order realism](../sources/lob-irreversibility.md),
[learning a hidden value](../sources/learning-market-maker.md),
[classifying agents](../sources/classify-trading-agents.md),
[fill probability and returns](../sources/market-makers-dilemma.md).
