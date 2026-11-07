# Round-2 model comparison

All scores are net PnL on `data/round2_public.csv`, about 100 minutes. Paths are relative to the repository root.

Fill-value models are pretrained only on the first 60% public data. Their last 40% increments are beyond fitting, but all public outcomes have been reused for model selection. No server/private scores are available.

| Model | Path | Full net PnL | Last 40% | Penalty | Median abs inventory | Sampled max DD | Independent CLI |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Fill value + fresh quotes | [strategies/round2_fill_fresh_163429.py](../strategies/round2_fill_fresh_163429.py) | 163,429.08 | 39,005.19 | 739.92 | 67 | 12,795 | Audit only |
| Fill value, +0.1 edge margin | [strategies/round2_fill_margin_163043.py](../strategies/round2_fill_margin_163043.py) | 163,043.19 | 39,360.19 | 336.81 | 63 | 12,768 | Audit only |
| Fill value, zero edge margin | [strategies/round2_fill_value_162253.py](../strategies/round2_fill_value_162253.py) | 162,253.08 | 39,091.19 | 989.92 | 67 | 12,656 | Match |
| Fill value, fast refresh | [strategies/round2_fill_fast_161706.py](../strategies/round2_fill_fast_161706.py) | 161,706.19 | 39,059.19 | 386.81 | 67 | 12,748 | Audit only |
| Fill value, -0.1 edge margin | [strategies/round2_fill_loose_158097.py](../strategies/round2_fill_loose_158097.py) | 158,097.19 | 37,262.19 | 386.81 | 68 | 13,401 | Audit only |
| Fresh quote alpha only | [strategies/round2_fresh_quote_147744.py](../strategies/round2_fresh_quote_147744.py) | 147,744.19 | 32,394.19 | 286.81 | 69 | 14,220 | Audit only |
| Volatility-sized baseline | [strategies/round2_volatility_144580.py](../strategies/round2_volatility_144580.py) | 144,580.19 | 32,201.19 | 636.81 | 68 | 14,179 | Match |

Every row passed native position-wall and private-ledger auditing. Independent CLI means a second replay through the unmodified organizer CLI matched every field. Audit-only rows have not received that extra replay.

The current `strategies/round2_submission.py` is byte-identical to `strategies/round2_fill_value_162253.py`. The top-scoring163429 source is separately preserved; it is not yet promoted over the verified 162253 checkpoint.

## Mechanisms and review targets

- **Fill value + fresh quotes:** Same fill-value trees plus four100ms fresh-quote alpha features; risk sizing unchanged.
- **Fill value, +0.1 edge margin:** Require predicted fill edge at least0.1 tick for opening/reversing exposure; unchanged pretrained trees.
- **Fill value, zero edge margin:** Current submission. Conditional fill value from public first 60%,5ms latency-aligned features,400ms future markout.
- **Fill value, fast refresh:** Refresh fill-value forecast at 5 ms rather than 20 ms; same weights and risk sizing.
- **Fill value, -0.1 edge margin:** Looser conditional fill-value gate, allowing predicted edge down to-0.1 tick.
- **Fresh quote alpha only:** Online learner with four extra 100 ms fresh-quote features; no pretrained fill-value gate.
- **Volatility-sized baseline:** Earlier verified checkpoint: online29-feature forecast, fixed saved inverse-variance sizing; no offline pretraining.

The four leading fill-value variants share the same pretrained 18-feature tree model. The fresh-quote variant adds four online alpha features; it does not recalibrate volatility sizing. All risk parameters remain fixed as requested.

Training implementation: `scripts/round2_pretrained_fill_value.py`. Quote integration: `fill_value_source`. Its conditional feature mapping depends on the saved 29-feature definitions and native order bookkeeping; port those definitions explicitly before combining with a different strategy.

The previous144K source has no offline fitted model. It remains the clearest reference for measuring the incremental fill-value mechanism.

Machine-readable versions: [CSV](../results/round2_model_comparison.csv), [JSON](../results/round2_model_comparison.json). JSON includes source/data hashes, fills, volume, actual/potential maxima and all chronological increments.
