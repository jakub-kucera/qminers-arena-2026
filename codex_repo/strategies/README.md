# Strategy index

Latest: [nine-model taker shortlist](../docs/ROUND2_TAKER_SHORTLIST.md), [research](../docs/ROUND2_TAKER_RESEARCH.md). Pure liquidity taker: CLI-verified public294,098; liquidity parent269,920 has lower drawdown. Both await server feedback. Imported T2: public194,391, supplied validation490,359. `round2_submission.py` / its manifest still identify the historical181 K maker below.

## Frozen round 1

`round1_submission.py` is byte-identical to `round1_quote_flow_624076.py`.
The verified local score is **624,076.00 net**, including 1,700.00 in penalties.
Its result manifest is [round1_624076.json](../results/round1_624076.json).

| Score | Named archive |
| --- | --- |
| 498,056 | [round1_nonlinear_498k.py](round1_nonlinear_498k.py) |
| 523,999 | [round1_depth_524k.py](round1_depth_524k.py) |
| 555,389, strict / zero penalty | [round1_size_555389.py](round1_size_555389.py) |
| 571,237.25 | [round1_pipeline_571k.py](round1_pipeline_571k.py) |
| 595,441.83, supplied input | [round1_claude_595k.py](round1_claude_595k.py) |
| 605,752.82 | [round1_flow_606k.py](round1_flow_606k.py) |
| 616,534.83 | [round1_flow_616535.py](round1_flow_616535.py) |
| 619,281.99 | [round1_quote_flow_619282.py](round1_quote_flow_619282.py) |
| 622,920.99 | [round1_quote_flow_622921.py](round1_quote_flow_622921.py) |
| 624,076.00 | [round1_quote_flow_624076.py](round1_quote_flow_624076.py) |

Other earlier checkpoints remain at their original filenames. All later round-1
tuning used previously consumed data; none guarantees transfer to round 2.
The 624 K model permits short paid breaches over 100 lots, rather than enforcing
a strict 100-lot bound. The native acceptance wall remains 1,000.

## Round-2 hypotheses

The verified local public checkpoint is [round2_submission.py](round2_submission.py),
byte-identical to [round2_distribution_ensemble_shock_180895.py](round2_distribution_ensemble_shock_180895.py).
It earns 180,895.19 net including 536.81 penalties, with exact native CLI equality.
The prior 162 K source remains at [round2_fill_value_162253.py](round2_fill_value_162253.py).
The earlier 144 K archive remains at [round2_volatility_144580.py](round2_volatility_144580.py).
[Distribution research](../docs/ROUND2_DISTRIBUTION_RESEARCH.md) compares 16 new candidates;
[the earlier table](../docs/ROUND2_MODEL_COMPARISON.md) preserves the seven-model export.
The new model's later 40% increment is 52,659.19 on already-consumed public data.
This is not a server/private score; see the
[research report](../docs/ROUND2_DISTRIBUTION_RESEARCH.md).

The [registry](round2/manifest.json) records exact source hashes, intended roles
and risk contracts for the original preparation controls.

- [Direct transfer](round2/round2_transfer.py): unchanged executable round-1 model.
- [Strict maker](round2/round2_strict100.py): retain all pending-cancel reservations.
- [Faster adaptation](round2/round2_fast_adapt.py): shorter labels and memory.
- [Dual-memory maker](round2/round2_dual_memory.py): causal long/fast forecast mixture.
- [Guarded IOC trend](round2/round2_guarded_trend.py): alternate sparse/trending-market hypothesis.
- [No-trade control](round2/round2_flat.py): reference if tested active strategies lose.

Each is a standalone file with one no-argument `BaseStrategy` subclass. Use
the [round-2 workbench](../docs/ROUND2_PLAN.md) to snapshot sources, keep new
evaluation data separate, and verify the selected result with the original CLI.
Do not overwrite preserved round-1 models or call historical tests round-2 evidence.
