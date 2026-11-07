# Round 2 distribution-driven research

Subsequent evidence: [taker research](ROUND2_TAKER_RESEARCH.md) records the supplied server results and new 269,920 public candidate. The maker study below is historical; it has not established server transfer for its 181 K source.

This study starts from the frozen 162,253.08 checkpoint and holds its absolute
volatility sizing, position limits, exchange latency and penalty rules fixed.
All public data was already inspected before this study. Fitted labels use
only the first 60%; later 40% is beyond fitting but reused for model selection.
No organizer validation or private score has been supplied.

The strongest of 16 new full-public candidates is
`strategies/round2_distribution_ensemble_shock_180895.py`:180,895.19 net,
including 536.81 native penalties. Every result field matches an independent unmodified organizer CLI replay.
This exceeds the earlier public high 163,429.08 by 17,466.11 (10.69%).
The separate verified 162,253.08 checkpoint is the ablation baseline below.

## What the data says

The no-trade extraction covers all 2,193,064 messages,260,621 sampled public
feature frames and 58,654 eligible grouped maker fills. Fill frames precede
execution by at least 5 ms. All 33,296 training frames from the older 18-feature
model were reproduced exactly, including timestamps and feature values.
Raw outcomes remain unclipped in the statistical report.

| Quantity | Resting-type G inserts | IOC-type F inserts |
| --- | ---: | ---: |
| Count | 1,069,859 | 53,423 |
| Median lots | 14 | 61 |
| Mean lots | 72.36 | 161.87 |
| 99 th percentile lots | 940 | 1,543 |
| Largest lots | 72,482 | 26,005 |
| Volume supplied by largest approximately 1% | 30.13% | 17.65% |

These distributions have long upper tails. A raw-volume imbalance lets a few
orders dominate; a single cap loses the distinction between small-order
consensus and large displayed size. The new features therefore retain both
counts and price centers in four remaining-size groups:1–10,11–50,51–200,>200.
These are observable size groups, not identified trader types. Remaining size
can shrink after partial executions.

Cancellation requests appear for almost every G insertion. Their median
scheduled lifetime is 0.312 seconds and 99 th percentile 2.061 seconds. Lifetimes
are similar across size groups. Requests can arrive after orders have filled,
so this is not the actual survival distribution of resting liquidity.
Message interarrival coefficient of variation is 1.105; this alone does not
establish a Poisson arrival process or its independence.

The spread is one tick for 83.87% of elapsed time and two ticks for 11.62%.
The book is invalid for 0.069%; spread tails are rare but reach 112 ticks.
Full-public volatility is more extreme than the earlier first 60% profile:

| Nonoverlapping return horizon | Return SD, ticks | Excess kurtosis | Squared-move share of largest 1% |
| --- | ---: | ---: | ---: |
| 10 ms | 0.313 | 13,218 | 92.0% |
| 100 ms | 1.094 | 3,187 | 82.4% |
| 400 ms | 2.279 | 561 | 69.9% |
| 1 second | 3.786 | 234 | 65.4% |
| 5 seconds | 8.585 | 44 | 47.8% |
| 25 seconds | 21.254 | 11 | 25.2% |

Rare moves dominate these variance estimates. Absolute 100 ms returns have
lag-one correlation 0.204; the ten-minute return SD ranges 0.373–1.661.
From minute 60–70, spread>2 occurs 13.0% of the time versus 1.57% in minute 10–20.
This supports treating the tape as changing liquidity conditions. It does not
identify an underlying stochastic process or justify a Gaussian tail model.
These are visible-book midpoints carried through invalid snapshots; quote
gaps and rebuilding can contribute to the tails alongside price movement.

## Fill selection and loss tails

Values below are ticks per grouped maker fill, weighted by min(quantity,20).
They use public market fills, not hypothetical fills of our own order.

| Fill class | 5 ms markout | 100 ms | 400 ms | 1 second |
| --- | ---: | ---: | ---: | ---: |
| All eligible | +0.540 | +0.307 | +0.053 | +0.010 |
| Executed price level exhausted | +0.008 | −0.449 | −0.729 | −0.755 |
| Executed price level survives | +0.652 | +0.466 | +0.217 | +0.170 |
| Executed quantity>100 | +0.507 | +0.167 | −0.229 | −0.294 |

The ordinary market fill is a poor proxy for a quote behind a queue. Observed
queue exhaustion is used only to define offline sample weights, never as a
runtime input. It is not itself knowable before the execution.

Clipping targets also changes the apparent economics. In the later 40%, the
weighted 400 ms raw mean is−0.072 ticks but clipping at±3 makes it+0.048.
For exhausted levels across the full tape, raw−0.729 becomes−0.465.
This motivates testing less-clipped labels; it does not imply that a noisier
regression will improve a strategy. The actual backtests below decide that.

Descriptive 60-second block-bootstrap intervals for 400 ms means are
−0.873..−0.575 for exhausted levels and+0.171..+0.268 for surviving levels.
Longer dependence and repeated model selection remain; these are not
confirmatory confidence intervals for trading PnL or hidden performance.

The strongest new directional association is the imbalance of touch orders
first seen within 100 ms: correlation with clipped 400 ms fill value is 0.209 in
first 60% and 0.153 later. A high count of visible orders more than four ticks
from the current touch is associated with poorer fill outcomes in both
segments. Age means observed visibility age, not inferred original birth time.
Neither association establishes a causal effect. The baseline linear-alpha
age experiment previously failed; the new use predicts conditional fill value.

## Models and checks

The rich model expands the conditional-fill head from 18 to 55 inputs: size-group
count imbalances and price centers, fresh-quote counterparts, touch visibility
age, and direction-invariant liquidity state. It keeps the separate 29-feature
online quote forecast and every existing volatility-sizing constant.
Trees fit 33,296 first 60% labels,400 ms horizon,±3 clipping and 20-lot weight cap.
All tree exports match the fitted estimator within 1e−10.

The actual-fill probe wraps the frozen 162 K strategy with read-only feature
capture. Its first 60% PnL remains exactly 123,161.89. It records 9,480 grouped
maker executions;9,479 have matured 400 ms targets. A mixed model combines
these actual fills with public fills; a second model fits actual fills alone.
Policy-selected fills are biased, so neither is a randomized experiment.

| Candidate | Full public net | First 60% | Later 40% | Status |
| --- | ---: | ---: | ---: | --- |
| Previous checkpoint | 162,253.08 | 123,161.89 | 39,091.19 | Independent CLI verified |
| Rich 55-feature fill model | 167,958.19 | 123,418.00 | 44,540.19 | Independent CLI verified |
| Larger-loss target, original 18 inputs | 161,974.19 | 122,899.00 | 39,075.19 | Native audited |
| Greater weight on exhausted-level fills | 152,422.00 | 112,558.00 | 39,864.00 | Native audited |
| Longer 1 second target | 150,452.19 | 111,992.00 | 38,460.19 | Native audited |
| Actual incumbent fills only | 156,707.19 | 120,189.00 | 36,518.19 | Native audited |
| Actual/public blend | 170,252.19 | 127,230.00 | 43,022.19 | Independent CLI verified |
| Fill head sets both quote prices | 160,256.19 | 114,082.00 | 46,174.19 | Native audited |
| Rich head retreats negative-edge entry quotes | 168,085.19 | 123,280.00 | 44,805.19 | Native audited |
| Only young-touch feature added | 155,715.00 | 116,023.00 | 39,692.00 | Native audited |
| Young-touch plus two liquidity-state features | 166,190.19 | 122,938.00 | 43,252.19 | Native audited |
| Equal rich/mixed head ensemble | 174,940.19 | 128,815.00 | 46,125.19 | Native audited |
| Ensemble plus quote retreat | 173,359.19 | 127,071.00 | 46,288.19 | Native audited |
| Rich head plus narrow-spread shock exit | 175,867.19 | 124,554.00 | 51,313.19 | Independent CLI verified |
| Rich head plus wider-spread shock exit | 175,197.19 | 124,191.00 | 51,006.19 | Native audited |
| Mixed head plus narrow-spread shock exit | 176,692.19 | 127,346.00 | 49,346.19 | Native audited |
| Ensemble plus narrow-spread shock exit | **180,895.19** | **128,236.00** | **52,659.19** | Independent CLI verified |

The first rich-model improvement is mostly after fitting: first 60% adds 256.11
and later 40% adds 5,449.00. More conservative target weighting removes too many
profitable opportunities. A higher predictive mean among accepted fills does
not imply higher total PnL; lost turnover and inventory closing matter.
The mixed model's higher whole-tape score includes a larger fitting-period
gain and trails the rich model after fitting. Preserve both for comparison.

## Why the execution change helps

After jumps of at least 2 ticks, separated by at least 100 ms, the public tape has
406 eligible shock observations. Signed follow-through averages+2.525 ticks at
100 ms, with median+1.5. Most occur with a wide spread. Among 75 narrow-spread
cases, the 100 ms median is+1 tick and mean+4.533; the mean is strongly tail-sensitive.
These midpoint statistics alone do not establish executable trading profits.

The existing maker pauses new quotes after a shock but can keep inventory
pointing against the move. The new rule attempts to close that inventory for
100 ms following an observed jump when spread<=2. Its IOC has a one-tick
price allowance beyond the observed opposite touch, native 5 ms activation,
one pending hedge at a time, and no new directional exposure target. The
existing normal excess-inventory hedge remains active. Paid overlap with
pending maker orders still exists: this is not a strict 100-lot strategy.

The ensemble averages the rich public-fill head and the actual/public-fill
head with fixed 1/2 weights,128 total trees, and identical 55-feature semantics.
No extra fitting uses later public labels. The final combination was selected
adaptively after inspecting reused-public component results.

The new model earns 52,659.19 after fitting versus 39,091.19 for the checkpoint,
and 25,423 in the last 20% versus 14,748. Its one-second sampled maximum drawdown
falls from 12,656 to 6,779; median absolute inventory changes 67→64. Maximum actual
inventory is 184 and potential-at-submission is 300, within the native 1,000 wall.

Some protection is concentrated in rare events. For the simpler 175,867 shock
model,8,680 of its 13,614.11 gain over the 162 K baseline occurs in minute 80–90.
This supports keeping a strong non-shock alternative and does not prove a
private-data gain. Both clipping and quote-conservatism alternatives lost;
descriptively cleaner predictions were not automatically better strategies.

## Restarted later-period diagnostic

Two additional native replays start the later 40% with empty strategy and book
state, rebasing timestamps exactly in microseconds. The baseline makes 37,248.19
and the new ensemble/shock model makes 46,184.19 (+8,936). Both are lower than
their continuous-run later 40% figures. The improvement survives this reset,
but online state matters. Orders born before the cut are not reconstructed;
this deliberately changes initialization and is not a new holdout or server test.

All 16 full-public candidate runs and the two restarted runs have finished.
All four independent CLI checks also matched every result field. No jobs remain running.

## Reproduce and inspect

- Full statistics: `results/round2_distribution_statistics.json`.
- Horizon/group table: `results/round2_distribution_markouts.csv`.
- First four fits: `results/round2_distribution_fit_specs.json`.
- Native audited results: `results/round2_distribution_initial_models.json`.
- Verified model: `strategies/round2_distribution_rich_167958.py` and its
  `results/round2_distribution_rich_167958.json` result.
- Mixed candidate: `strategies/round2_distribution_mixed_170252.py`.
- Strongest candidate: `strategies/round2_distribution_ensemble_shock_180895.py`.
- All candidate paths and metrics: `results/round2_distribution_comparison.csv`
  and JSON.
- Cold-start evidence: `results/round2_distribution_restarted.json`.
- Ignored raw extraction: `logs/round2/distribution_research/observations.npz`.

Run `python -m scripts.round2_distribution_collect` in a new output directory
for a new extraction, then `round2_distribution_stats` and
`round2_distribution_models`. Use `.venv/bin/python`; the documented data and
source hashes identify this exact tape and pipeline. Native simulator files
are unchanged. The full test suite currently has 105 passing tests, including
latency alignment, strict label maturity, and price-reflection symmetry of
the new odd/even features, bounded shock exits and exact ensemble arithmetic.
