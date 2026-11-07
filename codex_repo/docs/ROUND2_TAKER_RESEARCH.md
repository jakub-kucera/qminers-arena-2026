# Round 2: forecast execution and liquidity features

The user supplied exact sources and server result artifacts from another
repository. T2 earned **490,359** on validation, whereas the supplied maker V2
earned 71,864.15 and E2 lost 41,499. This is evidence to prioritize aggressive
forecast execution. These maker results do not belong to our 180,895.19 source;
that particular file has no supplied server result.

The current new candidate is
`strategies/round2_taker_liquidity_269920.py`: **269,920 public PnL**, zero
penalties, with all result fields independently reproduced by the unmodified
organizer CLI. Its server validation is pending. T2 remains the strongest
reference with supplied server evidence. Use immutable named files from the
[shortlist](ROUND2_TAKER_SHORTLIST.md); the mutable submission pointer has not
yet been changed in this study.

## Reproduction and provenance

Eight supplied source files were copied unchanged into
`strategies/round2_imported/`. Seven result/metadata/one-second PnL artifacts
were copied into `results/round2_imported_server/`. The originals were not
modified. `results/round2_imported_feedback.json` records original paths,
source hashes, submission IDs and the operator's source associations. Server
metadata does not include an uploaded-source hash, so those associations are
operator-supplied rather than independently established cryptographic matches.

All four imported public references reproduced exactly: T2 194,391; M2
116,620; RA 165,459; M4 175,116. T2 also matches every field of a separate
original organizer CLI replay. M4 has no supplied server result. These scores
are on approximately 6,000 public seconds; supplied validation curves cover
approximately 12,000 seconds on a different tape. Duration alone does not
justify a PnL projection.

The new audit independently reconstructs cash and inventory from private fill
notifications, checks them against the native engine, and supports both the
`inventory` and `_pos` strategy interfaces. No native simulator/evaluator
source was changed. All taker replays assert actual and potential exposure at
most 100 lots and zero breach penalties. Cancel-pending and unaccepted orders
continue consuming same-side room. There are 114 passing tests, including five
new checks for reservations, shock expiry, external-flow isolation, causal
feature dimensions and the imported flow strategy's private ledger.

## Five structural experiments

All five start from the exact T2 source and preserve its 5 ms execution latency,
fixed 100-lot bound, all-live order accounting, 400 ms online ridge target,
long training memory, 50 ms take spacing and entry condition: a one-tick spread
and forecast exceeding half-spread plus 0.15. No volatility-sizing search was
performed. Public data was already consumed; these are sample-selected results.

| Change to T2 | Public PnL | Public penalty |
| --- | ---: | ---: |
| Unchanged reference | 194,391 | 0 |
| Remove the one-lot quote probes | 209,616 | 0 |
| Add 0.15 bias toward the last 500-lot external flow burst | 201,843 | 0 |
| Override take direction for 100 ms after a two-tick midpoint jump | 202,015 | 0 |
| Add 0.15 bias from a 125 ms / 575-lot external flow window | 227,839 | 0 |
| Add four online liquidity interactions | **269,920** | **0** |

Every source is archived in `strategies/round2_research/taker_variants/`;
`results/round2_taker_variant_specs.json` records generation provenance and
hashes. Three convenient named exports are in the shortlist. Probe removal
also changes the strategy's own-fill feature stream, so it is not a pure
execution-only attribution.

The four new liquidity features are young touch-order imbalance, that
imbalance times clipped far-book order count, external flow times that count,
and touch order-count imbalance times that count. Young means first observed
within 100 ms; far means more than four ticks from the touch. Only currently
visible market-owned orders enter those summaries. The extra four columns
expand the existing 29-feature online regression to 33. Labels mature before
use; there is no pretrained future-path lookup or fixed time/price target.

The liquidity candidate earns 114,592 in the first public 60% and 155,328 in
the later 40%, versus T2's 80,293 and 114,098. Sampled one-second maximum
drawdown is 4,658 versus 5,488. Exposure is not reduced: median absolute
inventory is 92 for both. This improvement supports testing the additional
forecast inputs, but remains a result selected on reused public data.

## Stress diagnostics

`scripts/round2_regime_tapes.py` constructs two 12,000-second synthetic tapes
from the public tape's three highest-volatility 1,000-second segments (indices
2, 3, 5). Their one-second midpoint standard deviations are approximately
3.83, 5.17 and 4.97 ticks. One version repeats them at normal speed; the other
compresses event spacing by 1.25 while leaving native 5 ms latency unchanged.

Orders are namespaced per repetition. At seams, previous scheduled-live
market orders are canceled and the next segment's no-trade book is seeded,
with prices translated to align reference midpoints. Strategy state carries
through seams. Exact boundary marks allow exclusion of two seconds on either
side of each seam. Tape and input hashes, source segments and transformations
are recorded in `results/round2_regime_tapes.json`.

These tapes reuse future-selected public segments, repeat events, reset books
and create artificial transitions. Excluding seam windows does not remove all
of those effects. They are stress diagnostics, not independent tests or
identified replicas of the validation tape. The supplied RA/M3 examples also
show that local/proxy improvements need not transfer to validation. Synthetic
scores are deliberately excluded from the shortlist's server column.

The six-candidate1.25-speed batch and one added V2 control have completed.
The final tracked artifact is `results/round2_taker_stress_highvol_1p25.json`.
The liquidity model earned846,899 versus T2 553,157 on this artificial tape.
V2 earned185,512.75 versus its actual supplied validation71,864.15: the proxy
does not reproduce its server outcome. See [further ideas](ROUND2_NEXT_IDEAS.md)
for the completed results and two new public candidates294,098 and263,059. The next useful
external observation is the exact liquidity candidate's server result and
submission ID, already requested from the user.
