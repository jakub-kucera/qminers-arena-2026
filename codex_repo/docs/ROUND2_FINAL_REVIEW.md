# Review of the user's final round 2 submission

The supplied `../round2_local_317057.py` reproduces **317,057.00 net public PnL**
with zero penalties. Every result field matches between the audited native
replay and a separate unmodified organizer CLI replay. The independent fill
ledger matches the engine, and actual and potential exposure both stay at or
below 100 lots. No obvious correctness or look-ahead issue was found.

The original file was not edited. A byte-identical archive, including its CRLF
line endings, is [round2_final_317057.py](../strategies/round2_final_317057.py).
Its SHA-256 is
`4df2b5c12142242fcff6be80e8765833f3d7c54d97893b5707589929e67aa622`.
Evidence and provenance: [manifest](../results/round2_final_317057.json) and
[audited public replay](../results/round2_final_317057_public.json).

## What changed relative to the saved 294,098 pure taker

The strategy still predicts 400 ms midpoint changes online and uses IOC orders
to pursue a position within ±100 lots. It keeps the one-tick spread gate,
0.15-tick entry margin, 50 ms take spacing, and zero passive quote size.

Three additional features take the regression from 33 to 36 inputs:

- Signed aggressive volume over a 500 ms exponential decay, scaled by 500
  lots and clipped to ±3.
- Directional flow imbalance multiplied by the square root of recent gross
  activity, with the activity multiplier capped at three.
- Signed flow relative to the displayed liquidity on the opposing touch,
  clipped to ±3.

These preserve the difference between weak and intense pressure even when
normalized buy/sell imbalance is similar. They use only external market-taker
trades and current visible liquidity. They differ from the earlier large-flow
candidate's thresholded event grouping and price-center features.

The learner also weights observations using the forecast saved when they were
made. Labels mature after 400 ms and remain clipped to ±20 ticks. If the error
against the saved forecast exceeds six ticks, the observation receives weight
`6 / abs(error)` instead of one. This is causal, Huber-style online weighting;
it is not an iterative exact Huber regression fit. Ridge regularization rises
from `max(10, 0.001 * mass)` to `max(30, 0.003 * mass)`.

The internal position limit is explicitly 100, and quote reservations use all
live lots. The baseline already had a strict 100-lot take-room constraint, so
the gain does not come from a larger configured exposure allowance. The quote
reservation change is inactive with quote size zero. Individual contributions
of features, weighting and regularization have not been isolated by ablations.

## Profit and risk comparison

| Public metric | Prior pure taker | User's final |
| --- | ---: | ---: |
| Net PnL | 294,098 | **317,057** |
| Position penalty | 0 | 0 |
| Maximum actual / potential inventory | 100 / 100 | 100 / 100 |
| Median absolute inventory | 100 | 100 |
| Sampled one-second maximum drawdown | **6,222** | 10,880 |
| PnL standard error | 26,613.66 | 28,045.43 |
| Filled orders | 2,492 | 2,803 |
| Traded lots | 288,516 | 302,909 |
| First 60% PnL | 117,351 | **141,286** |
| Middle 20% PnL | 106,500 | **112,623** |
| Last 20% PnL | **70,247** | 63,148 |
| Later 40% combined PnL | **176,747** | 175,771 |

The final gains **22,959 (7.81%)** overall, with a higher drawdown. Its gain is
concentrated in the earlier part of the tape; the later 40% loses 976 relative
to the prior strategy. This prevents describing it as uniformly better.
All public data has been reused: these periods are diagnostics, not fresh
holdouts, and they do not determine the hidden result.

## Verification and status

All **116 tests pass**, including new checks that labels cannot train before
their horizon, robust weights use the saved forecast rather than later model
revisions, and impact features exclude our own aggressive trades and decay
when external trading stops. The standalone submission check also passes.
No strategy changes were made during review. All review processes finished.

The user identified this as the final submitted file. Its server submission ID,
validation score and private score have not yet been supplied here; the public
score is not substituted for any of them. The prior mutable
`strategies/round2_submission.py` still contains the historical 181 K maker;
the named final archive above identifies the user's selected source.
