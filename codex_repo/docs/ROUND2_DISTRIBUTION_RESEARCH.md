# Round2 distribution-driven research

This study starts from the frozen162,253.08 checkpoint and holds its absolute
volatility sizing, inventory policy, exchange latency and penalties fixed.
All public data was already inspected before this study. Fitted labels use
only the first60%; later40% is beyond fitting but reused for model selection.
No organizer validation or private score has been supplied.

## What the data says

The no-trade extraction covers all2,193,064 messages,260,621 sampled public
feature frames and58,654 eligible grouped maker fills. Fill frames precede
execution by at least5ms. All33,296 training frames from the older18-feature
model were reproduced exactly, including timestamps and feature values.
Raw outcomes remain unclipped in the statistical report.

| Quantity | Resting-type G inserts | IOC-type F inserts |
| --- | ---: | ---: |
| Count | 1,069,859 | 53,423 |
| Median lots | 14 | 61 |
| Mean lots | 72.36 | 161.87 |
| 99th percentile lots | 940 | 1,543 |
| Largest lots | 72,482 | 26,005 |
| Volume supplied by largest approximately1% | 30.13% | 17.65% |

These distributions have long upper tails. A raw-volume imbalance lets a few
orders dominate; a single cap loses the distinction between small-order
consensus and large displayed size. The new features therefore retain both
counts and price centers in four remaining-size groups:1–10,11–50,51–200,>200.
These are observable size groups, not identified trader types. Remaining size
can shrink after partial executions.

Cancellation requests appear for almost every G insertion. Their median
scheduled lifetime is0.312seconds and99th percentile2.061seconds. Lifetimes
are similar across size groups. Requests can arrive after orders have filled,
so this is not the actual survival distribution of resting liquidity.
Message interarrival coefficient of variation is1.105; this alone does not
establish a Poisson arrival process or its independence.

The spread is one tick for83.87% of elapsed time and two ticks for11.62%.
The book is invalid for0.069%; spread tails are rare but reach112ticks.
Full-public volatility is more extreme than the earlier first60% profile:

| Nonoverlapping return horizon | Return SD, ticks | Excess kurtosis | Squared-move share of largest1% |
| --- | ---: | ---: | ---: |
| 10ms | 0.313 | 13,218 | 92.0% |
| 100ms | 1.094 | 3,187 | 82.4% |
| 400ms | 2.279 | 561 | 69.9% |
| 1second | 3.786 | 234 | 65.4% |
| 5seconds | 8.585 | 44 | 47.8% |
| 25seconds | 21.254 | 11 | 25.2% |

Rare moves dominate these variance estimates. Absolute100ms returns have
lag-one correlation0.204; the ten-minute return SD ranges0.373–1.661.
From minute60–70, spread>2 occurs13.0% of the time versus1.57% in minute10–20.
This supports treating the tape as changing liquidity conditions. It does not
identify an underlying stochastic process or justify a Gaussian tail model.

## Fill selection and loss tails

Values below are ticks per grouped maker fill, weighted by min(quantity,20).
They use public market fills, not hypothetical fills of our own order.

| Fill class | 5ms markout | 100ms | 400ms | 1second |
| --- | ---: | ---: | ---: | ---: |
| All eligible | +0.540 | +0.307 | +0.053 | +0.010 |
| Executed price level exhausted | +0.008 | −0.449 | −0.729 | −0.755 |
| Executed price level survives | +0.652 | +0.466 | +0.217 | +0.170 |
| Executed quantity>100 | +0.507 | +0.167 | −0.229 | −0.294 |

The ordinary market fill is a poor proxy for a quote behind a queue. Observed
queue exhaustion is used only to define offline sample weights, never as a
runtime input. It is not itself knowable before the execution.

Clipping targets also changes the apparent economics. In the later40%, the
weighted400ms raw mean is−0.072ticks but clipping at±3 makes it+0.048.
For exhausted levels across the full tape, raw−0.729 becomes−0.465.
This motivates testing less-clipped labels; it does not imply that a noisier
regression will improve a strategy. The actual backtests below decide that.

Descriptive60-second block-bootstrap intervals for400ms means are
−0.873..−0.575 for exhausted levels and+0.171..+0.268 for surviving levels.
Longer dependence and repeated model selection remain; these are not
confirmatory confidence intervals for trading PnL or hidden performance.

The strongest new directional association is the imbalance of touch orders
first seen within100ms: correlation with clipped400ms fill value is0.209 in
first60% and0.153 later. A high count of visible orders more than four ticks
from the current touch is associated with poorer fill outcomes in both
segments. Age means observed visibility age, not inferred original birth time.
Neither association establishes a causal effect. The baseline linear-alpha
age experiment previously failed; the new use predicts conditional fill value.

## Models and checks

The rich model expands the conditional-fill head from18 to55 inputs: size-group
count imbalances and price centers, fresh-quote counterparts, touch visibility
age, and direction-invariant liquidity state. It keeps the separate29-feature
online quote forecast and every existing volatility-sizing constant.
Trees fit33,296 first60% labels,400ms horizon,±3 clipping and20-lot weight cap.
All tree exports match the fitted estimator within1e−10.

The actual-fill probe wraps the frozen162K strategy with read-only feature
capture. Its first60% PnL remains exactly123,161.89. It records9,480 grouped
maker executions;9,479 have matured400ms targets. A mixed model combines
these actual fills with public fills; a second model fits actual fills alone.
Policy-selected fills are biased, so neither is a randomized experiment.

| Candidate | Full public net | First60% | Later40% | Status |
| --- | ---: | ---: | ---: | --- |
| Previous checkpoint | 162,253.08 | 123,161.89 | 39,091.19 | Independent CLI verified |
| Rich55-feature fill model | 167,958.19 | 123,418.00 | 44,540.19 | Independent CLI verified |
| Larger-loss target, original18 inputs | 161,974.19 | 122,899.00 | 39,075.19 | Native audited |
| Greater weight on exhausted-level fills | 152,422.00 | 112,558.00 | 39,864.00 | Native audited |
| Longer1second target | 150,452.19 | 111,992.00 | 38,460.19 | Native audited |
| Actual incumbent fills only | 156,707.19 | 120,189.00 | 36,518.19 | Native audited |
| Actual/public blend | 170,252.19 | 127,230.00 | 43,022.19 | Independent CLI pending |

The first rich-model improvement is mostly after fitting: first60% adds256.11
and later40% adds5,449.00. More conservative target weighting removes too many
profitable opportunities. A higher predictive mean among accepted fills does
not imply higher total PnL; lost turnover and inventory closing matter.
The mixed model's higher whole-tape score includes a larger fitting-period
gain and trails the rich model after fitting. Preserve both for comparison.

Quote-placement and compact-feature followups are still running at this
checkpoint; this report will be updated with their outcomes.

## Reproduce and inspect

- Full statistics: `results/round2_distribution_statistics.json`.
- Horizon/group table: `results/round2_distribution_markouts.csv`.
- First four fits: `results/round2_distribution_fit_specs.json`.
- Native audited results: `results/round2_distribution_initial_models.json`.
- Verified model: `strategies/round2_distribution_rich_167958.py` and its
  `results/round2_distribution_rich_167958.json` result.
- Mixed candidate: `strategies/round2_distribution_mixed_170252.py`.
- Ignored raw extraction: `logs/round2/distribution_research/observations.npz`.

Run `python -m scripts.round2_distribution_collect` in a new output directory
for a new extraction, then `round2_distribution_stats` and
`round2_distribution_models`. Use `.venv/bin/python`; the documented data and
source hashes identify this exact tape and pipeline. Native simulator files
are unchanged. The full test suite currently has103 passing tests, including
latency alignment, strict label maturity, and price-reflection symmetry of
the new odd/even features.
