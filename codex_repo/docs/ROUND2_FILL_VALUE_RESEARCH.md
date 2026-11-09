# Conditional maker-fill value: first verified checkpoint

The first conditional-fill checkpoint earns **162,253.08 net** on the full
public tape, including 989.92 native position penalties. Every result field
matched a separate unmodified organizer CLI replay.

- Immutable source: `strategies/round2_fill_value_162253.py`.
- Source SHA-256: `1e06031145b06a67bd0b661c27af3d338b46b19b2514d29f1c9cd06046da3c49`.
- Evidence: `results/round2_162253.json` and `results/round2_fill_value_162253.json`.
- Previous checkpoint: `strategies/round2_volatility_144580.py`,144,580.19 net.

This is a reused-public model-selection result. The first public 60% supplied
training labels. The later 40% is beyond fitting but had already been inspected
for earlier models. Neither period is fresh organizer validation/private data.
No server score is established.

## A different learning target

The user asked this session to explore mechanisms other than absolute-volatility
sizing, which another session is researching. All sizing parameters remain
unchanged from the saved 144K baseline.

The new model predicts a proposed maker fill's 400 ms markout, conditional on
that fill occurring, rather than only forecasting an unconditional midpoint
return. A separate no-trade replay collected 33,296 public-market fill examples
from the first public 60%.

Each feature frame is at least 5 ms before the fill, matching the native order
latency. The executed price must have existed in that historical visible book
within two ticks of its touch. Candidate price is an available quote hypothesis;
future executed prices absent from that book are excluded. Features comprise
the candidate's relative price edge and signed causal flow/depth/fresh-quote
signals from the existing 29-feature representation. No absolute price,
timestamp or numeric order-ID arithmetic is a model input.

Labels are signed future-midpoint-minus-fill-price, clipped to +/-3 ticks.
They use the last valid midpoint strictly before the 400 ms target; invalid-book
gaps carry the last valid midpoint. Grouping combines partial matches at the
same price and weights each aggressive-order/price sample by at most 20 lots.

A 64-iteration histogram gradient-boosted model with 15-leaf trees, minimum 300
samples per leaf and L2 regularization 100 fits these 18-dimensional frames.
Its inline tree predictor matches the fitted estimator numerically. Runtime
needs no model files or sklearn imports; the standalone source embeds its
constants and uses only the existing documented APIs/standard library.

## How it controls quotes

The existing online forecast continues to set prices. If the pretrained model
predicts a negative fill markout, that side's planned quote budget can only
close existing inventory to zero; it cannot plan a reversal. Ordinary quotes
continue when the estimated edge is nonnegative. Existing queues shrink through
native modifications, retaining actual reservations until acknowledgement.

The original volatility cap, jump pauses, free 100-lot threshold, 1000-lot native
wall and all fees remain unchanged. These remain planned bounds, with temporary
paid overlap. The public run reached 300 actual/potential lots; all penalties
are charged. The model does not estimate fill probability or guarantee that a
prospective quote receives the sampled historical fill.

## Results

| Public period | Prior checkpoint | Fill-value checkpoint |
| --- | ---: | ---: |
| First 60%, used for fill-model fitting |112,379.00 |123,161.89 |
| Middle 20%, beyond fitting but reused |19,052.19 |24,343.19 |
| Last 20%, beyond fitting but reused |13,149.00 |14,748.00 |
| Full public net |144,580.19 |162,253.08 |
| Position penalties |636.81 |989.92 |
| Traded lots |950,692 |908,420 |
| Median absolute inventory |68 |67 |
| Sampled maximum drawdown |14,179 |12,656 |

The later 40% increment improved from 32,201.19 to 39,091.19. The full-public
gain is 17,672.89. These are model-selection observations, not an independent
performance guarantee. All ten sampled ten-minute blocks were positive.

## Other mechanisms tested

Twenty-four development comparisons tested passive exits, retaining favorable
front queues, public-fill conditional linear models, queue service-time entry
gates, event-time price forecasting, and a separate fixed 20-lot IOC family.
The IOC family uses no volatility sizing. None produced a promoted improvement.
The queue-wait 0.1 s prototype earned 114,996 on development but 143,252.19 over
the full public tape, below the prior checkpoint.

Four nonlinear unconditional-return models earned 140,647.19--144,168.19 full
public PnL. A 100 ms fresh-quote alpha feature set reached 147,744.19, with little
later-period improvement; 20 ms features and near-touch age features were weaker.
The conditional-fill objective produced the larger gain.

Follow-ups test two positive edge margins, faster fill-score refresh and the
100ms fresh-quote feature combination. Tree weights and volatility sizing stay
fixed. These are reused-public comparisons and must be verified before promotion.
The suite has 100 passing tests, including latency alignment, source export
equality, planned closing-only budgets and real pending-reservation handling.

Use immutable named files when reporting server feedback. The earlier async
question named the 144K checkpoint; do not attach a score to the 162K source
without identifying which file was actually uploaded.
