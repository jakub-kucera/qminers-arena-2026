# Codex round-1 research archive — 7 November 2026

This package adds the strategy development, diagnostics, ML experiments, and metric optimization from the accompanying research session. It preserves successful and unsuccessful experiments as a separate workspace-shaped archive.

**This archive's final candidate is [round1_max_metric.py](outputs/qminers-algo-arena/strategies/round1_max_metric.py), with locally verified round-1 PnL of 436,047.** Its SHA-256 is `10b65baeb38b81bd2b60e2ad00b352bcf88c392a887113771326a01443cf9b43`.

The target repository already documents independent 476,052, 498,056, and 523,999 candidates. This archive does not replace those files or the repository's submission recommendation. It contributes a separate experimental line and its evidence; 436,047 is not claimed to be this repository's highest score.

## Main results

| Strategy in this archive | Full round1 PnL | Later 100 minutes, excluded from model fitting | Sampled maximum drawdown |
| --- | ---: | ---: | ---: |
| F4 reference | 399,096 | 209,052 | 1,045 |
| Previous Elastic Net | 406,325 | 212,856 | 894 |
| Final metric candidate | **436,047** | **228,714** | **827** |

The final file keeps the fitted Elastic Net coefficients and the pending-order inventory ledger. It removes a rule that withdrew quotes when external touch depth fell below 20 lots. It also sets `SESSION_S=None`, so an unverified public-tape duration does not cause an early shutdown on a longer private tape. The official scorer includes executable liquidation of any remaining inventory; the final round1 position was +100 lots.

The final optimization phase used 13 fixed policy settings, two chronological model-fitting/evaluation folds, and a batch-adjusted moving-block bootstrap. Removing the depletion filter improved 19 of 20 five-minute validation blocks. A separately recorded portability audit checked the end-time change. There were 38 new replays in that phase, including exact official-loader confirmations. All had zero position penalties; instrumented runs stayed within 100 lots of actual and reserved exposure.

At 50 ms latency, final later-half PnL was 123,595 versus the previous Elastic Net's 124,246. On sample_v2, it earned 263,777 versus the previous model's 262,373 and F4's 264,616. The evidence therefore includes trade-offs, rather than a universal-win claim.

Both public tapes had already been examined in earlier research. The chronological exclusions and this batch's multiple-comparison adjustment do not make them untouched private tests. No website/private evaluation of these files was performed.

## Replay the exact final file

From the **repository root**, with the authorized dataset saved at `data/round1.csv`:

```bash
uv sync
uv run python -m simulator.main --strategy research/codex_round1_20261107/outputs/qminers-algo-arena/strategies/round1_max_metric.py --backtest data/round1.csv --log-dir logs/codex_round1/reproduce --no-logs
```

Expected result on the matching tape: PnL **436,047**, zero position penalty. Dataset SHA-256:

```text
round1.csv:    362e8208be1eeec32ad190d097774e26448f0d5149575a8e1b1efd1db1735940
sample_v2.csv: dd4e00e281abe50c9a19e16c147ccbc0b5b69835fee567f00136402ef1e01d08
```

The exact source ran locally in approximately 72 CPU seconds. The measured 176 MiB working set included research-harness imports. The exported strategy itself imports only `math`, `struct`, and public simulator interfaces; it does not need CatBoost or scikit-learn at runtime. It passed the local documented-rule validator. The official simulator was unchanged at source commit `3f5bea730d5f341c6988b1fe2722998b66270ea0`.

## Read the reports

HTML reports are self-contained: clone/download this package and open them locally to view interactive plots. GitHub normally displays their source rather than rendering them.

- [Final metric optimization: text](outputs/Qminers-metric-optimization.txt) · [HTML](outputs/Qminers-metric-optimization.html)
- [Robust ML comparison: text](outputs/Qminers-robust-ML-results.txt) · [HTML](outputs/Qminers-robust-ML-results.html)
- [Initial round1 ML comparison: text](outputs/Qminers-round1-ML-results.txt) · [HTML](outputs/Qminers-round1-ML-results.html)
- [Round1 strategy diagnostics: text](outputs/Qminers-round1-diagnostics.txt) · [HTML](outputs/Qminers-round1-diagnostics.html)
- [Sample-v2 composite research: text](outputs/Qminers-composite-results.txt) · [HTML](outputs/Qminers-composite-results.html)
- [Initial local testing: text](outputs/Qminers-local-testing.txt) · [HTML](outputs/Qminers-local-testing.html)
- [Original strategy proposal](outputs/Qminers-strategy-proposal.txt) and [repository analysis](outputs/Qminers-analysis.txt)

Older reports retain their chronological recommendations and statements about actions taken at that time. Later reports supersede earlier rankings. Statements that no push had occurred describe the original research phase, before this archive was imported.

## Contents and provenance

- `outputs/qminers-algo-arena/strategies/`: exact standalone candidates, earlier models, and baseline copies. The names are scoped to this archive; notably its `round1_best.py` is the 399,096 F4 reference, not the target repository's 476,052 file with the same basename.
- `outputs/qminers-algo-arena/research/`: training, replay, export, statistical selection, diagnostics, risk/engine tests, compact result JSONs, model parameters, native CatBoost models, and frozen candidate sources.
- `research/*_results/` within that archived project contains plans, all candidate outcomes, freezes, hashes, and limitations, including losing trials and accounting corrections.
- `work/pasted-review/illustrative_flow06.py`: the historical comparison variant of the user-provided strategy.

Strategy, training/replay source, and native model bytes are preserved. One report builder has a display-only local path normalized. Historical metadata paths were normalized to this package's workspace-relative paths; they are provenance records, not current absolute filesystem paths. Original manifest hashes may refer to the original reports before path normalization. **[MANIFEST.json](MANIFEST.json)** verifies the actual archived bytes and also retains the original file hashes.

The official simulator is supplied by the enclosing repository, rather than duplicated here. Original team reference files are preserved with their provenance under the archive's `research/reference_strategies/`.

## Verify and continue research

```bash
uv run python research/codex_round1_20261107/verify_package.py
uv run python research/codex_round1_20261107/check_research_tests.py
```

The test wrapper runs in temporary space under the ignored `logs/` directory, because the historical engine probes write a result JSON. It preserves the archived evidence. Offline training additionally uses the versions in [requirements-research.txt](requirements-research.txt). Replaying the standalone final file needs only the repository's standard environment.

Market tapes, 173 binary replay/feature trace arrays, virtual environments, browser profiles, and large execution logs are intentionally excluded. The two included CSVs are small aggregate result tables, not market-event datasets. Place authorized datasets in the corresponding local data directory and regenerate traces before rerunning analyses that consume `.npz` files. The recorded reports already contain their plots and summarized results.

The `outputs/` and `work/` layout retains the original scripts' relative workspace assumptions. Some historical preparation scripts refer to the earlier team checkout in `work/jakub-arena`; use the included frozen references or provide that authorized checkout when reproducing those stages. Do not run historical preparation commands over the recorded results: several scripts deliberately refuse to overwrite a finished experiment. Create a separate scratch workspace for new experiments and preserve this archive as the record of what was actually evaluated.
