# Round-1 leaderboard chart evidence

The user supplied processed statistics from all 61 leaderboard curves: 481
points per curve, 25 seconds apart, covering 12,000 seconds. They report that
their own curve matches their private log exactly. Raw curves and that log
were not supplied in this workspace; this document records their summary.

The rounded mean increments agree with reported final PnLs divided by 480.

| Team | Mean PnL / 25 s | SD / 25 s | SD / 4.83, conditional proxy |
| --- | ---: | ---: | ---: |
| Team 2 | 1,651 | 392 | 81.16 lots |
| Team 5 | 1,461 | 446 | 92.34 lots |
| Team 4 | 1,390 | 394 | 81.57 lots |
| Team 3 | 1,366 | 310 | 64.18 lots |
| ThatsMyQuant | 1,255 | 461 | 95.45 lots |

The reported price-change scale is 4.83 ticks per interval; its exact statistic
must be confirmed before treating it as a price-increment standard deviation.
The user reports our private-log median absolute inventory as 99. Our preserved
624,076 local run recorded 97; the exact source/log behind the server score is
still unmatched. Neither median is an inventory RMS measurement.

## Interpretation for round 1

Near-linear profits and roughly equal quarter contributions strengthen a
sustained high-turnover market-making/execution explanation. The leaders have
larger mean increments and smaller reported variation. Improving fill quality,
inventory recycling and queue decisions deserves priority over chasing rare
terminal bets on this tape.

This does not uniquely identify anyone's policy or inventory. With a consistent
marking convention, total PnL combines fill-edge profits, inventory revaluation,
penalties and liquidation-mark adjustments. Their variances and covariances
all contribute to the observed PnL variance. Inventory may change repeatedly
within a 25-second bin. Consequently the SD ratio above is only a conditional
effective-exposure proxy, not a reconstruction of holdings.

In particular, second place's ratio is approximately 92 lots. The blanket
inference that all leaders carry 60–80 lots does not follow even under the
simplified ratio assumption. Near-zero correlation with unsigned price changes
also does not rule out directional alpha when inventory changes sign.
Sampling every 25 seconds can hide shorter drawdowns and exposure excursions.

## How this should affect round 2

Treat this as a prior about round 1. Do not hardcode a 60–80 lot target, remove
trend/taker candidates, or assume the next dataset has the same economics.

First profile the new public tape's spread, queue depth, trade/cancel rates,
flow persistence, and conditional fill mark-outs. Dense two-way flow supports
testing queue-aware makers first; sparse persistent direction supports testing
trend/taker execution; changing regimes supports adaptation or switching.
Then use public chronological checks and a small recorded batch of server
validation submissions. The organizer private dataset remains unseen until
post-deadline scoring.

The next useful local diagnostic is exact fill-edge / inventory-revaluation /
fee / liquidation-mark attribution, plus true time-weighted RMS inventory and
holding times on an identified source/data pair. That diagnostic has not yet
been implemented; the chart summary alone cannot supply those components.

Machine-readable evidence is in `results/round1_reported_chart_analysis.json`.
