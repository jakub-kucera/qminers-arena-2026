# Round 2 taker shortlist

Public PnL covers approximately6,000 seconds. Supplied server validation covers12,000 seconds on different data. All public data has been reused for selection; absent validation means this exact file has no supplied result. Imported server source associations were supplied by the operator.

| Model | File | Public net PnL | Server validation | Public drawdown (1s) | Difference |
| --- | --- | ---: | ---: | ---: | --- |
| Liquidity pure taker | [round2_taker_liquidity_pure_294098.py](../strategies/round2_taker_liquidity_pure_294098.py) | 294,098.00 | Not supplied | 6,222 | Liquidity forecast without passive probes; more inventory and higher drawdown |
| Liquidity forecast | [round2_taker_liquidity_269920.py](../strategies/round2_taker_liquidity_269920.py) | 269,920.00 | Not supplied | 4,658 | T2 plus four online liquidity and young-order features |
| Liquidity + large flow | [round2_taker_largeflow_263059.py](../strategies/round2_taker_largeflow_263059.py) | 263,059.00 | Not supplied | 3,418 | Four learned large-aggressor features; lower public drawdown |
| Forecast + flow bias | [round2_taker_flowbias_227839.py](../strategies/round2_taker_flowbias_227839.py) | 227,839.00 | Not supplied | 6,094 | 125 ms aggressive-flow window biases the forecast |
| Pure taker | [round2_taker_pure_209616.py](../strategies/round2_taker_pure_209616.py) | 209,616.00 | Not supplied | 7,671 | T2 without one-lot passive quotes |
| T2 reference | [r2_T2_take_only_safe.py](../strategies/round2_imported/r2_T2_take_only_safe.py) | 194,391.00 | 490,359.00 | 5,488 | Imported 400 ms ridge forecast with strict live-order reservations |
| Distribution maker | [round2_distribution_ensemble_shock_180895.py](../strategies/round2_distribution_ensemble_shock_180895.py) | 180,895.19 | Not supplied | 6,779 | 55-feature maker ensemble, volatility sizing, shock exits |
| M4 flow window | [r2_M4_flow_window.py](../strategies/round2_imported/r2_M4_flow_window.py) | 175,116.00 | Not supplied | 12,039 | Imported 125 ms / 575-lot flow trigger; no learned price forecast |
| RA flow + stop | [r2_RA_flow_window.py](../strategies/round2_imported/r2_RA_flow_window.py) | 165,459.00 | 467,703.00 | 14,844 | Imported 250 ms flow window plus 3-tick stop |

T2 remains the strongest supplied server result. The269,920 liquidity candidate has lower public drawdown and median exposure than the294,098 probe-free variant; both are independently CLI-verified and await server feedback. The263,059 large-flow candidate is a lower-drawdown alternative with an audited native public replay.

All listed takers had zero public breach penalties and actual/potential exposure at most100. Maker181 paid536.81, already deducted. Synthetic stress results are separate, not server estimates.

Absolute paths, source hashes and further risk metrics: [CSV](../results/round2_taker_shortlist.csv) / [JSON](../results/round2_taker_shortlist.json). See [further ideas](ROUND2_NEXT_IDEAS.md) for these followups.
