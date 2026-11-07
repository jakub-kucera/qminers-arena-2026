# Round 2 taker shortlist

Public PnL covers approximately 6,000 seconds. Supplied server validation covers 12,000 seconds on a different tape. All public data has been reused for selection; blank validation cells mean this exact file has no supplied server result. Source associations for imported server results were supplied by the operator.

| Name | File | Public net PnL | Server validation | Public penalty | Difference |
| --- | --- | ---: | ---: | ---: | --- |
| Liquidity forecast | [round2_taker_liquidity_269920.py](../strategies/round2_taker_liquidity_269920.py) | 269,920.00 | Not supplied | 0.00 | T2 plus four online liquidity and young-order features |
| Forecast + flow bias | [round2_taker_flowbias_227839.py](../strategies/round2_taker_flowbias_227839.py) | 227,839.00 | Not supplied | 0.00 | 125 ms aggressive-flow window biases the forecast |
| Pure taker | [round2_taker_pure_209616.py](../strategies/round2_taker_pure_209616.py) | 209,616.00 | Not supplied | 0.00 | T2 without one-lot passive quotes |
| T2 reference | [r2_T2_take_only_safe.py](../strategies/round2_imported/r2_T2_take_only_safe.py) | 194,391.00 | 490,359.00 | 0.00 | Imported 400 ms ridge forecast with strict live-order reservations |
| M4 flow window | [r2_M4_flow_window.py](../strategies/round2_imported/r2_M4_flow_window.py) | 175,116.00 | Not supplied | 0.00 | Imported 125 ms / 575-lot flow trigger; no learned price forecast |
| RA flow + stop | [r2_RA_flow_window.py](../strategies/round2_imported/r2_RA_flow_window.py) | 165,459.00 | 467,703.00 | 0.00 | Imported 250 ms flow window plus 3-tick stop |
| Distribution maker | [round2_distribution_ensemble_shock_180895.py](../strategies/round2_distribution_ensemble_shock_180895.py) | 180,895.19 | Not supplied | 536.81 | 55-feature maker ensemble, volatility sizing, shock exits |

**First new validation comparison:** liquidity forecast, public 269,920. **Strongest supplied server result:** T2, validation 490,359. The latter does not apply to the modified liquidity file. All takers in this table stayed within actual and potential 100 lots on their local full-public replay. The maker permits paid overlaps.

Absolute paths, source hashes and additional risk metrics: [CSV](../results/round2_taker_shortlist.csv) / [JSON](../results/round2_taker_shortlist.json). Synthetic stress scores are deliberately separate from this table.
