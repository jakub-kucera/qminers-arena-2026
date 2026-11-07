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
| `round2_jump_models.py`, `round2_jump_followups.py` | Robust-label and jump/spread mechanism experiments, with immutable source snapshots |
| `round2_queue_inventory.py`, `round2_queue_combinations.py` | Native queue-preserving shrinks and causal inventory targets; planned bounds permit paid overlap |
| `round2_conditional_market_fills.py` | Forecast public-fill markouts using preceding features and causally matured labels |
| `round2_fill_attribution.py` | Exact native PnL decomposition and descriptive post-run fill markouts |
| `round2_regime_features.py` | Development comparisons of jump-state features and order-size cohorts |
| `round2_volatility_exposure.py` | User-proposed absolute-volatility sizing; causal 100 ms sampling, inverse-volatility/variance caps |
| `round2_volatility_followups.py`, `round2_variance_followups.py` | Small development batches testing faster absolute-volatility adaptation |
| `round2_shortlist.py` | Freeze six development-chosen candidates and reuse exact audited prefixes before continuous middle-public20% selection |
| `round2_volatility_ablations.py`, `round2_risk_weighted_learning.py` | Development-only post-freeze alpha ablations and observation-time risk-weighted learners |
| `round2_inventory_exit_quotes.py`, `round2_queue_value.py` | Separate closing quotes and queue-priority opportunity value, with risk sizing fixed |
| `round2_queue_wait.py`, `round2_queue_close_only.py` | Queue service-time entry gates using observed trades and cancellations |
| `round2_next_move.py`, `round2_nextmove_timing.py` | Event-time prediction targets and latency-eligible label frames |
| `round2_conditional_with_fixed_risk.py` | Conditional public-fill models on the unchanged saved risk policy |
| `round2_dislocation_taker.py` | Independent fixed20-lot IOC family, with no volatility sizing |
| `round2_pretrained_alpha.py` | Symmetric offline tree forecasts trained only on public first 60%; later 40% comparisons explicitly separated and reused |
| `round2_pretrained_fill_value.py` | Conditional maker-fill markouts with pre-fill 5 ms frames, pretrained only on public first 60% |
| `round2_full_public_study.py` | Immutable-source native audits for reused-full-public follow-up studies |
| `round2_fresh_quote_alpha.py` | Faster fresh-quote centers and observable near-touch age features, with risk sizing fixed |
| `round2_fill_value_followups.py` | Fixed-weight fill-value margins, score refresh and fresh-quote combinations |
| `round2_distribution_collect.py`, `round2_distribution_features.py` | Public-only55-feature frames, raw multi-horizon fill outcomes, exact5ms alignment |
| `round2_distribution_stats.py` | Size/lifetime distributions, time-weighted spreads, return tails, conditional markouts and jump follow-through |
| `round2_distribution_models.py`, `round2_distribution_ownfills.py` | First60% nonlinear fill heads; actual-policy/public-fill comparisons |
| `round2_distribution_compact.py`, `round2_distribution_pricing.py` | Compact feature ablations and conditional-fill quote-price alternatives |
| `round2_distribution_ensemble.py`, `round2_distribution_shock_exit.py`, `round2_distribution_combinations.py` | Fixed-weight fill ensembles and affordable observed-shock inventory exits |
| `round2_distribution_restart.py` | Explicitly reused-public later40% cold-start diagnostic with exactly rebased timestamps |
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
