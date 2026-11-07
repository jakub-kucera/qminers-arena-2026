# Scripts index

Run modules from the repository root with `.venv/bin/python -m scripts.NAME`.

| Active tool | Purpose |
| --- | --- |
| `build_round2_candidates.py` | Build/check the six predeclared standalone sources and registry |
| `round2_workbench.py` | Snapshot, develop, select, freeze, audit and verify new round data |
| `round2_characterize.py` | Historical transfer checks; no round-2 model selection |
| `round2_server_results.py` | Record operator-reported validation/private PnL against immutable upload-source snapshots |
| `profile_round.py` | Read-only market diagnostics; use development data before selection |
| `compare_market_dynamics.py` | No-trade spread tails and pre-event sampled price dynamics on explicit development tapes |
| `round2_development_diagnostics.py` | Four controlled alpha/quote-width ablations on the existing public development prefix |
| `round2_inventory_probes.py` | Four public-development target/entry prototypes; inspect the recorded queue-churn limitations |
| `check_submission.py` | Conservative local check of documented export restrictions |
| `benchmark.py` | Native-config replay and diagnostic metrics for explicit sources |

Start with [HANDOFF.md](../HANDOFF.md) and the
[round-2 plan](../docs/ROUND2_PLAN.md). The existing virtual environment works.

## Historical research

The `round1_*`, `search_*`, `beat_*`, `challenge_*`, and associated validation
scripts are preserved experiment generators. Their paths remain stable because
they import one another and are referenced in result provenance. They are not
the default round-2 entry point.

`search_passive.run`, `search_queue`, `evaluate_set`, and `validate_round1.run`
assert zero penalty and at-most-100 potential exposure. They reject paid overlap
strategies such as the final round-1 model. `round1_standing_liquidity.run` and
the round-2 workbench audit the native 1,000-lot wall and include every penalty.

Historical `round1_claude_*` generators rebase from the immutable supplied
`strategies/round1_claude_595k.py`. Earlier feature generators use the frozen
`round1_private_554347.py`; the mutable round-1 submission file is not their
template. The round-2 generator uses the frozen `round1_quote_flow_624076.py`.

`stress.py` / `compare_candidates.py` generate artificial scenarios. Their
outputs are implementation/regime probes, not independent competition-data
validation. The previous generic `evaluate_set` remains unchanged so old
strict-risk experiments keep their original behavior.
