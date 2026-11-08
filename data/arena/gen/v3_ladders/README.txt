Round 3 ladder ablation; experimental, not r3c.
Code: gen-v3, model/evaluation commit f70f8b2, latest handoff 648ee87.
Exact commands and results: docs/GENERATOR_PLAN.md, "Empirical batch ablation".
Baseline params: data/arena/gen/r3_params.json + r3_public_after.
Mixture params: data/arena/gen/gen_v3_r3_batch_params.json + r3_public_after.
Seeds: 304-306, 6000 seconds; six bots L8,L3,L9,B1,L8F,B1F; jobs 2.
Both arms and their scores are retained. stats_304.json and first-seed ladder measurements compare against real r3.
Mean score error improves but rank remains wrong and three-seed level change is uncertain. Conditional batch intensity and cancellation behavior fail; no preset promotion.
These full tapes were made before the new provenance guard. Use gen_calibrate score/stats to evaluate them explicitly; use a fresh directory for another generation run.
