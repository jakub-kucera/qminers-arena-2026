# Strategy index

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
The 624K model permits short paid breaches over 100 lots, rather than enforcing
a strict 100-lot bound. The native acceptance wall remains 1,000.

## Round-2 hypotheses

The [registry](round2/manifest.json) records exact source hashes, intended roles
and risk contracts. No round-2 winner is selected.

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
