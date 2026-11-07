# Historical round-1 research notes

Captured from the README at commit `77bc241`, before round-2 preparation.
Some sections below describe superseded submissions. The authoritative current
state is in [HANDOFF.md](../HANDOFF.md) and the preserved result manifests.
Commands in these notes assume the repository root as the working directory.
All round-1 data has been consumed; none of these later comparisons is a fresh holdout.

---

# Qminers trading hackathon starter

**Round 1: current verified leader is `strategies/round1_submission.py`,
624,076.00 NET PnL.** Identical named copy: `strategies/round1_quote_flow_624076.py`.
The unmodified organizer CLI reproduces this score exactly. It extends the
user-supplied 595,441.83 model with fresh quote-price centers and size-capped
aggressive-flow groups, with a 0.45-tick quote half-width. It includes
1,700.00 in inventory penalties and uses
the native 1,000-lot acceptance wall and latency-bound IOC
hedges. Both `strategies/round1_claude_595k.py` (595,441.83) and the previous
`strategies/round1_pipeline_571k.py` (571,237.25) remain preserved, as do
`strategies/round1_flow_606k.py` (605,752.82) and
`strategies/round1_flow_616535.py` (616,534.83), along with
`strategies/round1_quote_flow_619282.py` (619,281.99) and
`strategies/round1_quote_flow_622921.py` (622,920.99).
The earlier zero-penalty candidate is `strategies/round1_size_555389.py`
(555,389, actual/potential inventory at most 100).

Source hashes and all metrics are in `results/round1_submission.json`. These
results are sample-tuned and have not been scored by the competition server.
The corrected user-reported target is approximately 650K, still not reached.
The supplied 595,441.83 strategy was reproduced exactly; the selected extension
improves it by 28,634.17 net. Comparison results and source hashes are recorded
in `results/round1_claude_research.json`.

```
strategies/   template_strategy.py, an empty strategy to copy and fill in; trend_follower.py, a simple working one
data/         sample.csv.gz, a synthetic hour of trending prices to start on; the rounds downloaded from the website go here too (git-ignored)
logs/         simulator output (git-ignored)
simulator/    the exchange simulator package
explorer/     the backtest explorer package
```

## Setup

[uv](https://docs.astral.sh/uv/) is a fast Python package and project manager; install it with `curl -LsSf https://astral.sh/uv/install.sh | sh` (or `pip install uv`).

```bash
uv sync                                        # Python 3.13 and everything else, into .venv
uv run python -m gzip -d data/sample.csv.gz    # the simulator reads plain CSV only; one file at a time, the same for each downloaded round
```

`data/sample.csv.gz` is synthetic and its price trends: one resting order per side, and every few seconds an aggressive order takes part of the touch, after which the quotes keep moving in that direction tick by tick for a few seconds and then give part of the move back. `strategies/trend_follower.py` is a simple trend-following strategy: it sends a one-lot IOC order at the touch in the direction of the trades it has just seen. The rounds are recorded market data and look nothing like the sample.

## Writing a strategy

A strategy is one `.py` file defining one subclass of `BaseStrategy` (with several, the alphabetically first is used), constructible with no arguments:

```python
from simulator.models import OrderBookSnapshot, OrderRequest, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy


class MyStrategy(BaseStrategy):
    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        """After every market event: the public book and all trades since the previous call."""

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        """Every state change of your own orders."""
```

| Call                                                   | Effect                                                         |
| ------------------------------------------------------ | -------------------------------------------------------------- |
| `self.send_order(OrderRequest(side, price, quantity, order_type, client_order_id=None))` | submit; returns the order id (`u000000001`, ...) immediately |
| `self.cancel_order(order_id)`                          | cancel your resting order                                      |
| `self.modify_order(order_id, new_quantity)`            | shrink your resting order                                      |
| `self.now_us()`                                        | simulation time in µs                                          |

`Side.BUY` / `Side.SELL`, `OrderType.LIMIT` / `OrderType.IOC`; prices and quantities are positive integers (prices in ticks).

Submissions run on Python 3.13 with numpy 2.5.4, pandas 3.0.6, scipy 1.18.1 and scikit-learn 1.9.1 available, and are statically checked first: besides the standard library and those packages, import only `simulator.models` and `simulator.strategy.BaseStrategy`. Modules giving system, network, file, threading or introspection access (`os`, `sys`, `io`, `socket`, `subprocess`, `threading`, `importlib`, `inspect`, `gc`, ...), builtins like `open`/`eval`/`exec`/`getattr`/`type`, dunder attributes and `str.format` are rejected.

## Running a backtest

```bash
uv run exchange-simulator --strategy strategies/trend_follower.py --backtest data/sample.csv --log-dir logs/sample --progress
```

`logs/sample/result.json` holds the outcome (`pnl`, `cash`, `inventory`, `mark_price`, `breach_penalty`, `traded_volume`, `fills`, `pnl_se`, time-weighted quantiles of `|inventory|`) and `pnl.csv` the PnL sampled every second. Without `--no-logs` the directory also gets `run.jsonl`, `events.csv`, `book_deltas.csv` and `trades.csv`, several hundred MB per full round. Use `--no-logs` when you only need the result and the PnL curve; it is much faster. `--public-depth N` (default 20) sets how many ticks of the book you see.

## Exploring a backtest

```bash
uv run backtest-explorer --log-dir logs/sample     # http://127.0.0.1:8050, --port to change
```

A Dash app over a full-logs run (not `--no-logs`): best bid/ask with your fills marked, your PnL over time, the reconstructed order book at any clicked time, and the event log.

## How the exchange works

**One instrument, replayed.** Each CSV row is a market participant's action:

```
Time,Operation,OrderId,Side,Volume,Price,Lifespan
0.003823,Insert,1000001,B,43,9999,G
```

`Time` in seconds; `Operation` is `Insert` or `Cancel` (of `OrderId`); `Side` `B`/`A`; `Lifespan` `G` = resting limit order, `F` = immediate-or-cancel. The tape is fixed and does not react to you; your orders only add to and take from the book it builds.

**Matching.** Price-time priority. An incoming order (market or yours) matches against the opposite side while prices cross, each fill at the resting (maker) order's price; a LIMIT residual rests at the back of its price level, an IOC residual is cancelled. Market orders can trade with yours; your orders never trade with each other. No fees.

**Latency.** Every `send_order`, `cancel_order` and `modify_order` takes effect at $t + 5\text{ms}$, where $t$ is the simulation time at which you call it: it is applied just before the first market event with timestamp $\ge t + 5\text{ms}$, so the book may have moved by then. An order you place is therefore never filled within 5 ms, and a cancel can lose the race against a fill.

**Feeds.**
- `on_order_book_change` fires after every market event, with a snapshot of every individual order (id, side, price, quantity, `owner` `"market"`/`"user"`) within `public_depth` ticks of the best price on each side, and the list of trades (market-vs-market included) since the previous call. Fills caused by your own order activating appear in the next call's `trades`.
- `on_private_order_update` fires synchronously for your orders: `ACCEPTED`, then one `PARTIALLY_FILLED`/`FILLED` per match (`fill_price`, `filled_quantity`, `remaining_quantity`), `CANCELED` (your cancel, or an IOC residual), `MODIFIED`, or `REJECTED`. Cancelling anything but your own resting order, or a modify that doesn't shrink it, is `REJECTED`; a modify of an unknown id is silently ignored.

**Limits and scoring.** With inventory $I$ (signed), resting same-side quantity $R$ and order quantity $q$ ($s = \pm 1$ for buy/sell):

$$|I + s (R + q)| > 1000 \Rightarrow \text{order REJECTED at acceptance}$$

$$\text{penalty} = 10{,}000 \cdot \int \mathbb{1}\big[|I(t)| > 100\big] dt \quad (\$ \text{ per second})$$

$$\text{PnL} = \text{cash} + \text{markout}(I) - \text{penalty}$$

$\text{markout}(I)$ is the cash from liquidating $I$ against the resting *market* orders on the opposite side, best price outwards (volume beyond the book at the last swept price, or at the last traded price if that side is empty). It is computed at the end and every second for `pnl.csv` and `pnl_se`.

## Current submission candidate

Submit **`strategies/arena_strategy.py`** as the single strategy file. Its
`ArenaStrategy` constructor needs no arguments. The file uses only `math`,
`collections`, and the permitted simulator imports. No fitted weights, external
files, sample prices, order IDs, or known session-end time are embedded.

It learns a two-second midpoint forecast online from market trade flow, price
momentum, and top-of-book imbalance. Training observations mature only after
their prediction horizon; stale observations across long gaps are discarded.
The model starts trading after 200 matured observations and uses a rolling,
regularized fit. It continues learning from already-observed outcomes throughout
the run, including during evaluation segments.

The entry threshold budgets for both sides of an IOC round trip, using the
current spread as the estimated exit spread, plus a small buffer. Predictions
control a target inventory between -80 and +80. Execution sends at most 20 lots
at the market touch, with one IOC outstanding at a time. Partial fills update
inventory immediately; unfilled quantities remain reserved until the terminal
response. Own taker trades do not contribute to the trade-flow signal. Brief
one-sided quote transitions are ignored; persistent one-sided books permit
inventory reduction only. Stale trade flow causes a target of zero when a usable
book is available.

The original trend follower also includes the cancellation fix shown on page 49
of the Getting Started slides.

### Run and verify

From the repository root, after setup:

```bash
uv run python -m simulator.main --strategy strategies/arena_strategy.py --backtest data/sample.csv --log-dir logs/arena --no-logs
uv run python -m unittest discover -s tests -v
uv run python -m scripts.check_submission strategies/arena_strategy.py
uv run python -m scripts.benchmark --backtest data/sample.csv --compare-flow --output logs/validation
uv run python -m scripts.stress --output logs/stress
```

In the existing local environment, `.venv/bin/python` can replace `uv run python`
to run without triggering dependency synchronization. The strategy itself does
not need numpy/pandas/scipy/sklearn. The local submission check is conservative
and covers documented restrictions used here; it does not replace the server's
unavailable checker.

The benchmark uses the official CLI limits, checks the strategy's cash and
inventory against the engine on every private event, records maximum actual
and submitted potential inventory, and saves input/source hashes. Its 15-minute
PnL blocks come from one continuous replay, preserving both book and model state.
Drawdown is measured on the simulator's one-second PnL curve.

### Measured results and limits

The first 2,700 seconds were used for development. The final segment was evaluated
after the current strategy settings were fixed; it was not used to select those
settings. All segments belong to the same synthetic sample, not separate market
datasets.

| Strategy | Full sample PnL | Final ~15 min PnL increment | Maximum absolute inventory | Penalty |
| --- | ---: | ---: | ---: | ---: |
| No trading | 0 | 0 | 0 | 0 |
| Corrected starter | 1,878 | 415 | 1 | 0 |
| Fixed flow reference, same execution and 80-lot cap | 148,441 | 36,653 | 80 | 0 |
| ArenaStrategy | 225,926 | 56,000 | 80 | 0 |

The fixed-flow reference is one untuned comparator, not an optimized competitor.
The starter comparison also changes position size substantially. ArenaStrategy
ended flat; its sampled maximum drawdown was 617. Reproduce these figures using
the benchmark rather than relying on the table after making changes.

The 11 trading unit/integration tests include 10,000 randomized partial-fill/cancel
sequences, inventory reservations, ledger agreement, matured-label timing,
stale-label rejection, and the starter cancellation regression. Fifteen additional
synthetic stress runs cover flat markets, noise, persistent trends, trade flow
opposing the trend, and a switch from trend to noise. All respected the exposure
cap and incurred zero penalties. Noise runs returned 0, -66, and -6. After a
trend-to-noise change, the strategy lost 1,765–2,232 in the second half while the
model adapted. The inventory cap is not a bound on financial drawdown.

The user-reported server playground evaluation matches these local results at
the displayed precision, including fills, volume, inventory, cash, mark-out,
penalty, standard error, and inventory quantiles. The matching local candidate
and reported metrics are archived in `logs/submissions/playground_verified/`.
This verifies that the reported submission ran successfully; later source edits
still need server validation.

**Unseen recorded-market performance remains unverified.** The bundled sample is
expressly synthetic; high sample PnL is not evidence of a competition-winning
strategy. Use actual round data in `--backtest` when it becomes available, retain
chronological evaluation, and verify round aggregation, deadlines, and runtime
limits.

### When round data arrives

Start with market diagnostics and an unchanged baseline:

```bash
uv run python -m scripts.profile_round --backtest data/round1.csv --output logs/round1/profile
uv run python -m scripts.benchmark --backtest data/round1.csv --compare-flow --output logs/round1/baseline
```

The profiler sends no orders. It measures event frequency, time-weighted spreads
and touch quantities, sampled visible depth, and the behavior of trade flow,
momentum, and queue imbalance over 5 ms, 20 ms, 100 ms, 500 ms, 2 s, and 5 s.
It reports these by chronological block. Pending observations are bounded by
the longest horizon and sampling interval rather than total file size.

Entry quotes are evaluated at decision time + 5 ms, using the book **before**
any market row at that exact timestamp. Original-touch IOC orders that would
miss are excluded from conditional quote-edge means and counted separately.
The one-lot round-trip estimates include both spreads. They are screening
statistics, not executable strategy PnL: they omit impact, the ability to schedule
an exit from actual callbacks, and latency after that exit decision. Use the
simulator for final decisions. Overlapping labels also make naive statistical
significance claims inappropriate.

Nine diagnostic tests cover timing, missed IOC entries, EOF censoring,
chronological-block boundaries, time weighting, memory bounds, round-trip costs,
and timestamp validation. Together with the trading checks, there are 20 tests.

For context, the playground has about 14.94 events/second, a constant two-tick
spread whenever both sides exist, and one resting market order per side. These
conditions are especially simple. The current strategy starts each run with
zero model weights and learns anew, but its two-second horizon, five-minute
model memory, execution sizing, and risk cap still require assessment on round
data. Preserve a chronological validation segment before changing them.

## Experimental alternatives for round data

The server-tested baseline remains `strategies/arena_strategy.py`. Two additional
single-file candidates are ready for comparison:

- `strategies/guarded_strategy.py` adds a recent-edge gate to the same causal
  prediction and IOC execution. It scores matured virtual opportunities even
  while exposure is paused, so learning and recovery do not require live trades.
  A negative recent score reduces the permitted inventory to zero; positive
  scores gradually restore the cap. The score uses a midpoint/spread proxy,
  rather than actual latency-adjusted fill PnL, and is not a confidence interval.
- `strategies/passive_strategy.py` posts five-lot limit orders with a 60-lot
  inventory cap, inventory-skewed prices and withdrawal of quotes vulnerable to
  aggressive flow. It measures visible quantity ahead of its orders, preserves
  stable quote priority, and waits for cancellation acknowledgement before
  replacement. Pending cancels reserve their remaining quantity. It uses neither
  IOC exits nor a learned adverse-selection model; those are potential extensions
  if round data supports passive trading.

Both candidates pass the local documented-restriction checker. They have not
been submitted to the competition server. Their code is self-contained because
submission files cannot import other strategy modules; shared changes to the
baseline and guarded implementation must therefore be reviewed in both files.

```bash
uv run python -m scripts.compare_candidates --output logs/candidates/final_stress
uv run python -m scripts.benchmark --backtest data/round1.csv \
  --strategy strategies/arena_strategy.py \
  --strategy strategies/guarded_strategy.py \
  --strategy strategies/passive_strategy.py --output logs/round1/candidates
uv run python -m scripts.perf_check --rows 1000000 --output logs/performance_final
```

Candidate evaluation covers six artificial regimes (flat, noise, continuation,
flow opposing the trend, trend-to-noise, and trend-to-noise-to-trend) across six
seeds. Seeds 11/29/47 overlap earlier stress work; 101/211/307 were additional
cases. All 108 strategy runs respected their respective exposure caps and had
zero inventory penalties. These are artificial validation scenarios, not
recorded market data.

In the noisy halves after trends disappeared, the guard reduced the combined
loss from 9,574 to 3,384, about 65%. On the three additional seeds the reduction
was about 76%. The guard also gave up profits during favorable periods: total
PnL over the six complete trend-to-noise tapes fell from 88,452 to 76,321.
Recovery tests demonstrate that the guard can resume when virtual outcomes
improve, while some weak regimes remain paused. It should be compared as a
risk/return alternative, not treated as an unconditional improvement.

The passive candidate earned 16,838 summed over the six flat tapes and 6,204
on the six noise tapes, but lost 66,981 on the continuation tapes. On the
playground it returned -3,329, versus 225,926 for the baseline and 225,487 for
the guarded candidate. These results show strong dependence on market regime;
choose a family using chronological round-data validation.

The performance test builds one million events over a 100-second simulated
session, with 100 price levels and ten market orders per level on each side,
plus sustained IOC flow and cancellations/replenishment. Each candidate runs
in a fresh process and reports throughput, peak RSS, exposure, fills and ledger
agreement in `performance.json`. The directional candidates may correctly stay
flat on this stationary tape; passive matching exercises actual resting fills.
Speed figures depend on hardware and book shape and do not establish compliance
with the organizer's still-unspecified runtime limits.

There are now 28 tests. Additional coverage includes pausing and recovery from
virtual labels, stable exposure caps, cancel/fill races, partial residuals,
queue priority, and sustained aggression in the performance generator.

The supplied slides still leave cross-round aggregation, hidden-data splits,
submission quotas/deadlines, and enforced runtime/memory limits unspecified.
Those facts need to be obtained from competition announcements or organizers.

## Best tested candidates on sample_v2

Nineteen passive configurations were screened on the first 30% of v2. Six were
compared over the first 60%, then a three-file shortlist was frozen before
examining the reserved tail. Full-file validation replays preserved queue and
inventory state across that split. No candidate was changed after validation.

| Submission file | Quote size | Inventory cap | Full v2 PnL | Sampled maximum drawdown | Maximum observed inventory |
| --- | ---: | ---: | ---: | ---: | ---: |
| `strategies/passive_v2_q60.py` | 60 | 90 | 191,958 | 218 | 90 |
| `strategies/passive_v2_q90.py` | 90 | 90 | 190,953 | 180 | 90 |
| `strategies/passive_v2_q20.py` | 20 | 60 | 74,953 | 66 | 55 |
| Original `strategies/passive_strategy.py` | 5 | 60 | 18,562 | 31 | 19 |

All had zero position penalties. Q60 ranked first on development data and kept
its lead on the reserved tail; it is the primary v2 candidate. Q90 is close in
PnL with lower observed one-second drawdown. Q20 provides a smaller exposure cap.
Much of the gain comes from larger quotes and increased inventory utilization.
The finalists also disable the trade-flow veto; that filter discarded profitable
fills on development data. Improving inside the spread did not beat the stronger
join-at-touch configurations in this search.

Approximate PnL increments on the reserved tail were 74,788 (Q60), 74,396 (Q90),
29,325 (Q20), and 7,114 (original). These increments start at the last one-second
PnL sample before the split, at most one second early. Full-file PnL figures
above are exact simulator outputs. Q60 was also replayed through the unmodified
CLI and its entire result matched the audited search exactly.

Each file is a standalone submission and passes the local documented checks.
The server has not evaluated these new candidates. Thirty tests now pass,
including exhaustive inventory-envelope checks at every integer inventory state
for each finalist, with both sides reserved and cancellations still in flight.
Search definitions, frozen source hashes, block results and validation outputs
are saved under `logs/sample_v2/search/`; `final_report.json` summarizes them.

```bash
uv run python -m simulator.main --strategy strategies/passive_v2_q60.py \
  --backtest data/sample_v2.csv --log-dir logs/v2_q60 --no-logs
```

The finalists remain regime-dependent: on the original trending playground,
Q60 returned -1,332, Q90 -4,465, and Q20 -9,684. These losses and the different
inventory usage matter when comparing candidates for round 1. The v2 tail has
now been used for validation; further tuning needs a fresh validation period or
new data. The search script refuses to repeat selection after its shortlist is
frozen, to avoid silently reusing the reserved data.

## Current highest-scoring v2 submission

**`strategies/passive_v2_champion.py` returns 283,959 on the full sample_v2 file.**
It exceeds the reported 263,000 reference by 20,959 (about 8%). The unmodified
simulator CLI reproduces the audited search result exactly. Source/data hashes
and full metrics are in `logs/sample_v2/champion_report.json`.

The strategy can maintain up to four orders per side. When an opposite-side fill
frees inventory capacity, it replenishes that capacity without canceling an older
order at the same price. This preserves the older order's queue priority. All
resting orders, pending submissions and pending cancels reserve their remaining
exposure. The net inventory envelope stays within -100 to +100. A neutral band
around the estimated fair price avoids shifting a quote back a full tick for
small signals. Quotes can replenish after 5 ms. No session-end timing, input-file
access, future rows or fitted sample weights are used.

Measured v2 metrics: 4,300 filled orders, 391,649 lots traded, end inventory +1,
zero position penalties, and maximum drawdown 300 on the one-second curve. All
inventory quantiles from 50% through 99.7% are 100: the strategy uses the full
position allowance frequently. This is substantially more exposure than the
initial candidate. It returned +689 on the original trending playground, which
is another synthetic diagnostic rather than independent market validation.

Thirty-three tests pass. New tests check that replenishment preserves the older
order, and exercise 10,000 randomized layered fill/cancel transitions with exact
ledger agreement and both exposure bounds enforced. The file passes the local
checker for documented submission restrictions; the competition server has not
yet evaluated this new file.

This improvement was further tuned on the already evaluated v2 sample. The
original reserved tail is no longer an independent validation set. Round-1
performance remains unverified.

```bash
uv run python -m simulator.main --strategy strategies/passive_v2_champion.py \
  --backtest data/sample_v2.csv --log-dir logs/champion --no-logs
```

## Round-1 submission and evaluation

**Earlier validated candidate: `strategies/round1_best.py`.** The model
returns **476,052** on the supplied full `data/round1.csv`, exceeding the reported
430,000 reference by 46,052. The unmodified simulator CLI reproduces the entire
result from the audited replay exactly. The new model has not yet been evaluated
by the competition server.

| Metric | Result |
| --- | ---: |
| PnL | 476,052 |
| Filled orders | 22,245 |
| Traded lots | 2,309,320 |
| End inventory | +100 |
| Position penalty | 0 |
| Maximum actual/potential inventory | 100 / 100 |
| Maximum drawdown on the 1-second curve | 890 |
| PnL standard error | 10,442.37 |

The data has 4,411,336 events over 12,000 seconds. Initial profiling and model
screening used only earlier chronological segments. Eighteen model definitions
were screened on the first 30%, and five were developed on the first 60%.
Three candidates were frozen and compared over the next 20%. The chosen model
was then frozen before its only evaluation on the final 20%.

Exact PnL increments were 280,322 on development, 98,121 on the selection
validation segment, and **97,609 on the previously untouched final segment**.
Every ten-minute block of the full replay was profitable. Boundary PnL was
recorded inside the engine at exact simulation times; it does not use rounded
one-second samples or reset inventory/queue state. Selection validation ends
just before the last row of its prefix to exclude artificial EOF order draining.
Online coefficients continue updating causally during all segments; model
selection and algorithm definitions stay fixed during final evaluation.

The five features are signed trade flow, short-term momentum, bid/ask queue
imbalance, normalized order-flow imbalance from changes at the touch, and
spread-scaled imbalance. Regularized online regression predicts 100 ms midpoint
responses. Outcomes only become training labels once their horizon has passed.
The model starts each run with zero fitted weights and a bounded observation
buffer; it uses no external files or precomputed round-specific trading path.

Passive execution can maintain up to eight orders per side. Replenishment keeps
older orders' queue priority. Pending submissions and pending cancels retain
all remaining exposure until confirmed. Individual orders can reach 200 lots
when moving between -100 and +100; the signed inventory plus all outstanding
same-side reservations still remains within the 100-lot bound. The strategy
frequently uses that full allowance: absolute-inventory quantiles are
86 / 100 / 100 / 100.

Thirty-nine tests pass. They cover the five-dimensional solver, mature-label
timing, order-flow sign, inventory reservation at every integer state, exact
boundary valuation without changing simulator results, and existing fill/cancel
and execution regressions. The final file passes the local documented-rule
checker. Source and input hashes, selected candidates, and complete metrics are
saved in `logs/round1/submission_report.json`; a copy of the exact verified
submission is archived under `logs/round1/submission/`.

```bash
uv run python -m simulator.main --strategy strategies/round1_best.py \
  --backtest data/round1.csv --log-dir logs/round1/reproduce --no-logs
```

The user-provided submission deadline is 18:00 Europe/Prague. Results apply to
this supplied round file. A separate hidden scoring file may behave differently.
The final segment is now consumed; further tuning requires a fresh validation
period or explicit treatment as tuning on already evaluated data.

## Preserved round-1 tuning candidate: 498,056

`strategies/round1_nonlinear_498k.py` preserves the exact source that scored
**498,056** in the audited full round-1 replay, with zero position penalty and
maximum actual/potential inventory of 100 / 100. Its SHA-256 is
`dcb0e143ab0d2d324f01162b4dd935356f492c7434b716ab324c4d2f983ffb64`.
It adds three signed nonlinear transformations to the five original features,
uses ridge strength 0.001, and reduces inventory skew to 0.05. The original
476,052 candidate remains available as `strategies/round1_best.py`.

Tracked result manifests live in `results/`, including the 498,056, 476,052,
and playground 283,959 versions. The 498,056 result comes from further tuning
on already evaluated round-1 data; it has no fresh independent holdout. See
`results/round1_498056.json` for metrics and verification status. The preserved
source is intentionally byte-identical to the experiment, including its older
five-feature module description; its actual feature count is eight.

Research code, strategy milestones, tests and result manifests are versioned
in Git. Raw competition data, detailed replay logs and the local environment
remain excluded by `.gitignore`.

The subsequent robust-depth candidate is preserved independently as
`strategies/round1_depth_524k.py`, with audited PnL **523,999**, zero penalty,
and maximum actual/potential inventory 100 / 100. Its thirteen features include
order-count imbalance, per-order quantities capped at 100 lots, and liquidity
within two ticks of each touch. This extends the eight-feature 498,056 model;
it does not replace that archived source. Full metrics and source/input hashes
are tracked in `results/round1_523999.json`. It also uses already consumed data.

`strategies/round1_depth_nonlinear_534k.py` preserves a later **534,332**
audited round-1 replay with zero penalty. It adds signed nonlinear transforms
of touch order-count imbalance and capped-quantity imbalance, for fifteen
features in total. Metrics and verification status are tracked in
`results/round1_534332.json`. This is another sample-tuned version; the earlier
498,056 and 523,999 files remain separately preserved.

Later sample-tuned milestones are preserved as `strategies/round1_queue_538k.py`
(**538,075**) and `strategies/round1_queue_545k.py` (**544,764**). The latter
samples training observations every 20 ms and may replenish free exposure
while cancels are pending. Pending cancellations still reserve their remaining
quantity until confirmation. Both actual and potential inventory stay within
100 lots; all replay penalties are zero. Result manifests are tracked in
`results/round1_538075.json` and `results/round1_544764.json`.

Transfer checks for the 534,332 model returned 270,735 on sample v2 and -13,506
on the original thin-book sample. These are checks on previously consumed data,
not independent validation. Their metrics are saved in
`results/round1_534k_transfer.json`; the round-1 candidates are specialized for
the denser round-1 market. Forty-three tests pass, including 10,000 randomized
fill/cancel/reject transitions with overlapping quote replacements.

`strategies/round1_inside_551k.py` preserves an audited **550,873** round-1
replay: zero penalty, maximum actual/potential inventory 100 / 100, sampled
maximum drawdown 744. It quotes one tick inside spreads of at least two ticks
only when predicted price edge after inventory skew exceeds 0.25 ticks.
The 0.10 threshold scored 520,553; the 0.50 threshold scored 545,129. The
threshold is selected from the same already evaluated round-1 file.
Metrics and verification status are tracked in `results/round1_550873.json`.

`strategies/round1_private_554k.py` preserves an audited **554,318** round-1
replay. It extends the 550,873 candidate by replenishing from cached desired
quotes immediately after cancellation confirmations, provided the cache is no
older than 5 ms. Partial-fill notifications update inventory and cash without
triggering that cached replenishment. Invalid public books clear the cache.
Actual/potential inventory remain bounded by 100, with zero penalty. Metrics
and verification status are in `results/round1_554318.json`.

## Latest round-1 submission: 554,347

Use the single standalone file `strategies/round1_submission.py`. Its executable
AST matches the exact scored experiment; only the module description was
updated. The canonical file was separately replayed through the unmodified CLI,
and every result field matches its audited replay.

| Metric | Result |
| --- | ---: |
| PnL | 554,347 |
| Position penalty | 0 |
| Maximum actual/potential inventory | 100 / 100 |
| Filled orders | 37,087 |
| Traded lots | 2,192,606 |
| End inventory | +100 |
| Cash | -448,553 |
| Mark-out price | 10,029 |
| PnL standard error | 11,205.47 |
| Maximum drawdown on the 1-second curve | 834 |

The model uses fifteen causal features, 100 ms matured return labels sampled
every 20 ms, and one-second regression refits. Per-order quantities are capped
at 20 lots for robust imbalance features. Inventory skew is 0.025 and the
neutral fair-price band is 0.10 ticks. Selective one-tick inside quotes require
a spread of at least two ticks and predicted edge after skew above 0.30 ticks.
Confirmed cancellations replenish from desired quotes at most 5 ms old;
invalid books clear this cache. All pending exposure remains reserved.

The final 0.30 inside threshold scored only 29 more than 0.25 (554,318), so
that difference provides little evidence of an improvement on another file.
The exact 0.25 version is preserved as `strategies/round1_private_554k.py`, and
the byte-identical 554,347 experiment as `strategies/round1_private_554347.py`.
All ten-minute PnL increments are positive. Forty-seven tests pass, including
inside-quote thresholds, non-crossing prices, mature-label timing, randomized
order races, exact exposure reservations, and stale/invalid cache behavior.

```bash
.venv/bin/python -m simulator.main --strategy strategies/round1_submission.py \
  --backtest data/round1.csv --log-dir logs/round1/reproduce_final --no-logs
```

This exceeds the 550,000 comparison threshold by 4,347. The other team's exact
current score is unknown. The final result is sample-tuned, has no new holdout,
and has not yet been evaluated on the competition server. Earlier model files
and their metrics remain preserved; Git tags identify the score milestones.

The size-cohort extension is preserved as `strategies/round1_size_555389.py`:
**555,389**, verified field-for-field with the unmodified CLI, zero penalty,
maximum actual/potential inventory 100 / 100. It adds eight count-imbalance
features separating quantities 1–5, 6–20, 21–100 and >100 lots at the touch and
within two ticks. It has 23 features. Metrics and source/input hashes are tracked
in `results/round1_555389.json`; 48 tests pass. This is still sample-tuned.

New research scripts use the frozen `strategies/round1_private_554347.py` as
the baseline, so promoting a different `round1_submission.py` cannot silently
change the research templates. Experimental tree families explicitly record
whether they fit earlier periods or the entire supplied file. Full-sample
training scores are in-sample evidence, not independent validation.

## Verified net-PnL leader: 571,237.25

`strategies/round1_pipeline_571k.py` and `strategies/round1_submission.py` are
byte-identical. The unmodified CLI exactly reproduces the audited result:
24,015 fills, 2,247,040 traded lots, final inventory +100, cash -429,793,
mark-out price 10,029 and **1,869.75 penalty**, leaving **571,237.25 net PnL**.
Maximum actual inventory was 256 and maximum potential exposure at submission
was 358, below the native 1,000-lot acceptance wall. These are temporary charged
breaches of the 100-lot free threshold, not a strict 100-lot strategy.

The predictor remains the fifteen-feature causal learner. New orders pipeline
while old cancellations are pending; excess inventory is hedged with IOC orders
that also wait five milliseconds. Net PnL includes every charged breach and
liquidation/hedge execution. Fifty-one tests pass. Earlier strict-100 versions
and their source hashes remain preserved. The corrected target is around 650K.
