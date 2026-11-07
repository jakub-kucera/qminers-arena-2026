# Further round 2 mechanisms

These ideas follow the supplied T2 validation result and the locally verified
269,920 liquidity forecast. They preserve all live/cancel-pending reservations
and the 100-lot bound. They do not search absolute-volatility exposure sizing,
which the user's other session is investigating.

## Executed followups

| Mechanism | Public net PnL | Public one-second drawdown | Public penalty |
| --- | ---: | ---: | ---: |
| Frozen liquidity forecast | 269,920 | 4,658 | 0 |
| Remove all one-lot passive probes | 294,098 | 6,222 | 0 |
| Add four large-aggressor features | 263,059 | 3,418 | 0 |

Sources are `strategies/round2_taker_liquidity_pure_294098.py` and
`strategies/round2_taker_largeflow_263059.py`. All public data has been reused
for selection. Neither altered file inherits T2's server validation score.
See `results/round2_taker_extensions_public.json` for exact native results,
hashes and exposure audits. Every result field for294,098 matched an independent unmodified organizer
CLI replay; the verified manifest is
`results/round2_taker_liquidity_pure_294098.json`.

Probe removal changes both execution and the own-fill feature stream. It also
raises median absolute inventory from 92 to 100. Its gain cannot be attributed
entirely to avoiding bad maker fills. It cuts submitted passive orders and
changes the space available for aggressive trades. The lower drawdown of the
large-flow variant is descriptive of this tape, not an established risk bound.

The large-flow feature block groups fills by external taker order ID before
applying a 500-lot threshold. It tracks direction and execution-price center
with 500 ms decay; each aggressor's weight is capped at four. Four causal inputs
are appended to the online ridge, taking it from 33 to 37 features. Original
feature groups cap some event weights at 20 lots, which motivates separating
tail-size orders; existing raw flow already includes their quantities.

## Next hypotheses, in priority order

1. **Predict executable returns.** Current labels are future midpoint changes.
   A useful direction can vanish before the native 5 ms arrival, or the IOC may
   not fill. Separately predict fill probability and subsequent signed return
   conditional on a fill. Label only after the relevant outcomes mature. A
   shadow fill must model actual IOC limits and displayed depth; first
   observable quote after 5 ms is an approximation, not exact counterfactual
   execution. Evaluate with unchanged native fills and net PnL.
2. **Budget execution cost from forecast strength.** Allow at most one extra
   tick on an IOC when `abs(signal) - half_spread - 0.15 >= 1`. This preserves
   the original model-implied margin at the worse price. It is not a guarantee
   of true edge. A separate adaptive experiment starts from frozen269920 and
   changes no size/risk rule. It earned **262,394**, with zero penalties, below
   the parent269,920. It is retained as a negative result rather than promoted;
   `results/round2_edge_budget_public.json` records the audit.
3. **Separate entry and holding horizons.** A 100 ms model can time an entry
   while a 1–2 second model tests whether the flow persists. Compare the policy
   against the current 400 ms forecast, which holds inventory between signals.
   Treat opening, closing and reversing as distinct actions with their actual
   crossing costs. Avoid automatic early exits that simply add spread costs.
4. **Measure replenishment after a sweep.** A large buy followed by fresh ask
   liquidity may be absorbed; a large buy followed by disappearing asks may
   continue. Interaction features should distinguish executed depletion from
   canceled/disappearing quotes using only the visible trade/book history.
   The small gain from an unconditional shock override does not settle this.
5. **Adapt to forecast failure, not just changing volatility.** Maintain slow
   and fast models and score predictions made before their labels matured.
   Compare calibration and after-cost trade outcomes as well as squared error.
   Any maker/taker routing requires credible execution accounting; simplistic
   shadow maker fills can overstate the maker's opportunity.

## Synthetic stress evidence and limits

The initial six-model fast stress batch completed. Full net scores were:
liquidity846,899; M4 715,161; pure T2 653,732; flow-biased T2 612,369;
T2 553,157; maker181 412,444. Removing two-second seam windows gives
847,108;714,972;657,177;614,557;557,229;413,255 respectively. These are
12,000-second synthetic tapes made from repeated public segments, not server
scores or independent evidence. The maker's positive result specifically
prevents treating this construction as proof that all makers fail in the
hidden regime. The exact supplied V2 control earned185,512.75 on this synthetic tape
(187,468.75 excluding seam windows), with26,156.25 of native penalties. Its
supplied server score is71,864.15. This mismatch further rules out using the
synthetic construction as a hidden-score estimator.

An execution-only diagnostic counts submitted, filled and canceled lots by
native request type. It must reproduce every baseline result field exactly.
IOC misses are not automatically lost profitable trades: some avoided losses.
The completed diagnostic is `scripts/round2_taker_execution.py`, with results
in `results/round2_taker_execution.json`; every baseline result field matched.
The269,920 model submitted387,093 one-lot LIMIT requests, filling113,810 lots
(29.75% of total traded volume). It submitted3,346 IOC orders for381,598 lots:
3,262 had a fill, totaling268,715 lots (70.42% of requested IOC quantity). Only
84 IOC orders had no fill at all. This points more toward partial execution
than a large population of completely missed entries; deeper fills still
need to justify their additional cost.

All three followups, the execution diagnostic, the independent294,098 CLI
check and the seven-source fast stress comparison have completed.
**114 tests pass.** No research process remains running. The normal-speed
synthetic tape was generated but has not been evaluated. All new candidates
still require source-specific server feedback.
