# Round-2 composite research: current target not achieved

**Historical study:** the current target is 150,000 and subsequent adaptive
models exceed the old 100,000 target. See [current local progress](ROUND2_LOCAL_PROGRESS.md).
All public data is now consumed; the user prohibits competition server access.
The remaining text records the earlier static-model experiment, not current status.

The goal remains a good solution reaching at least 100,000 net PnL under the
native competition metric. No round-2 strategy has been promoted or submitted
to the website by this research branch. The original matching engine is intact.

## Evidence that changed the investigation

The user's reported Team 2 426,000 fills motivated execution experiments.
Native `fills` is the count of distinct filled user order IDs, not execution
events or completed cycles. Increasing it alone did not create profitability.
The strict baseline made -37,267 on the first public hour, with 11,596 filled
orders and 653,160 traded lots. A 10-lot child-order variant made 46,499 filled
orders but still lost 12,285; its eight-live-order cap also reduced exposure.

Clipping the online learner's 400 ms return labels to +/-3 improved the result
to -6,838 at 688,520 lots. An instrumented replay reproduced every native result
field exactly. Its volume-weighted fill markout was +0.236 price units after
100 ms, but only +0.034 after 400 ms. Hypothetically crossing the future touch
to exit at 100 ms would instead give -0.362 per lot, before latency/depth costs.
These are overlapping descriptive markouts, not independent round-trip profits.

Shorter prediction horizons, the earlier 15-feature model, more inventory skew,
mechanical aggressive exits, whole-book centers/cohorts, and quoting nearer the
middle of wide spreads all remained negative in development. A simple 5s/30s
trend alternative made +7,414 but was inconsistent across ten-minute periods.
Generic boosted midpoint-return models had useful forecast correlations but
lost money on the later development half.

## The composite model and its limits

The candidate combines the robust 29-feature online ridge fair-price learner
with a fixed gradient-boosted conditional-fill-value model. The gate estimates
400 ms midpoint markout for each quote side and withdraws quotes below a
threshold. It uses 27 causal public features, excluding two own-fill features,
100 trees of maximum depth 3 and at most 7 leaves, and 20 ms refreshes.
Native 5 ms latency, full pending-order reservations and strict 100-lot exposure
are preserved. The exact export is 79,693 bytes and uses no file/network I/O.

Training used 7,370 observed private fill callbacks from the first 30 minutes,
with a ten-second purge at the boundary, clipped +/-3 markouts and square-root
quantity weights. Features came from observations available before each fill.
Exported predictions matched sklearn to absolute tolerance 1e-12 on later
observations. Model samples are conditioned on the original quoting policy;
they do not establish counterfactual fill profitability under every new policy.

| Gate threshold | Later development 30m PnL | Full development hour, including training |
| --- | ---: | ---: |
| -0.1 | 35,505 | 84,893 |
| 0 | 34,855 | 73,333 |
| 0.1 | 36,097 | 85,435 |

The threshold 0.1 source was frozen before inspecting the next public 20%.
Only that active candidate and no-trade were evaluated there. It lost
**21,593**, taking its first-80% score to **63,842**. No-trade won. The positive
development score did not survive the reserved check, so this candidate was
rejected. The last 20% was not replayed or profiled. The workflow's frozen flat
file is only the outcome of this failed comparison, not a recommended strategy
or achievement of the user's 100,000 target.

## Scope, reproducibility and next action

Thirty-four new development variants were tested across structural, horizon,
drift, inventory-value, nonlinear, conditional-fill, book-shape and gap-quote
batches, in addition to six reproduced controls and the prior upstream work.
The later development half was excluded from model fitting but had already
been inspected; it was not a fresh model-selection holdout. First 80% is now
consumed evidence. Do not reuse it and call it untouched validation.

The 100k goal remains active. Investigate the failed interval's fill quality,
inventory drift, gate behavior and regime change; then test a bounded causal
adaptation policy. A recalibration may help, but is not yet demonstrated. Guard
against trapping inventory when both quote values deteriorate. Keep the final
20% reserved for one frozen follow-up, and distinguish any organizer server
feedback from public backtests. Repeated tuning needs new evidence rather than
a claim that a successful development score proves generalization.

Working results: `logs/round2_fill_value_validation/validation.json` and
`selection.json`. Immutable archived evidence is under
`research/round2_fill_value_validation_20261107/`; fitted sources and their
training protocol are under `research/round2_conditional_fill_20261107/`.
All 98 repository tests passed. There is no server or private-round score.
