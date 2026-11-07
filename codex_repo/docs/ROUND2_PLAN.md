# Round-2 evaluation plan

No round-2 data has arrived yet. These candidates are prepared hypotheses;
historical results do not establish performance in the next round.

## Predeclared candidates

All files are standalone exports in `strategies/round2/`. The source registry
and hashes are in `strategies/round2/manifest.json`.

| Candidate | Hypothesis | Exposure |
| --- | --- | --- |
| `round2_transfer.py` | Transfer the final 624,076 round-1 maker unchanged | Planned 100; paid overlap, native wall 1,000 |
| `round2_strict100.py` | Preserve every reservation through cancel confirmation | Actual and potential at most 100 |
| `round2_fast_adapt.py` | 200 ms returns, 15-minute training memory, 0.12 neutral band | Planned 100; paid overlap |
| `round2_dual_memory.py` | Mix long and five-minute forecasts using matured prediction errors | Planned 100; paid overlap |
| `round2_guarded_trend.py` | IOC trend capture for thinner, persistent markets with a causal virtual-edge guard | Actual and potential at most 80 |
| `round2_flat.py` | No-trade control when no tested strategy shows an edge | Zero |

The maker candidates use the 29 public features of the final round-1 model.
The dual-memory model records both experts' predictions at observation time;
only their subsequently matured errors affect mixture weights. Its model
selection signal is forecast squared error, not realized trading PnL. That
distinction is an empirical question for the next dataset.

`scripts/build_round2_candidates.py` regenerates these files from immutable
sources and refuses to overwrite different content. `--check` verifies their
exact bytes, registry and local submission restrictions. It does not claim
new-round performance. Deliberate edits should use new candidate files and
updated provenance, rather than quietly rewriting frozen snapshots.

## When data arrives

Confirm the CSV identity and review any new organizer rules or engine version.
The current engine uses 5 ms order/cancel/modify latency, a 100-lot free
threshold, a 1,000-lot acceptance wall, and a 10,000-per-second breach penalty.
Preserve the final round-1 submission and all named archives.

Put the new tape under `data/` without overwriting an existing dataset. From
the repository root:

```bash
.venv/bin/python -m scripts.round2_workbench prepare --backtest data/round2.csv
```

Preparation reads schema and timestamps, hashes the input, snapshots all six
source files, and writes chronological prefixes. Entire groups of equal
timestamps stay together. It records the Python version, native rules and
engine/evaluator hashes. Existing nonempty experiment directories are refused.
The full dataset is not replayed during preparation.

The default directory `logs/round2` is reserved for the actual new tape. All
current smoke/historical work lives under `logs/round2_preparation`.

## Development: first 60%

```bash
.venv/bin/python -m scripts.profile_round \
  --backtest logs/round2/development.csv --output logs/round2/profile
.venv/bin/python -m scripts.round2_workbench screen --workers 3
```

Inspect spreads, touch sizes/order counts, event and trade rates, latency
crowding, and signal persistence. Compare net PnL, penalty, volume, actual and
potential inventory, and time blocks. The historical thin tape favored the
guarded trend hypothesis while dense tapes favored passive making; do not
assume the next tape matches either one.

Use development data for any new hypotheses. A custom study can snapshot
explicit source files with repeated `--strategy PATH` arguments to `prepare`.
Use a new `--output` directory for a different predeclared set. Existing
snapshots are immutable: modifying the original candidate after preparation
does not change the experiment. Editing a snapshot is rejected.

A new directory does not make previously inspected data fresh. Do not profile
the full new tape or repeatedly inspect the final segment while tuning.

## Selection: next 20%

```bash
.venv/bin/python -m scripts.round2_workbench select --workers 3
```

Every candidate runs continuously from the beginning through the 80% prefix.
Learner state, cash, inventory and live queues carry across the 60% boundary.
Selection uses the **net PnL increment between exact 60% and 80% time marks**;
lower sampled drawdown breaks a PnL tie. No strategy is restarted at the split.

Boundary marks are diagnostic reads. They do not move the native clock, add
callbacks or alter any native result field. If a sparse prefix ends before
its cutoff, the evaluator carries its final state to the cutoff virtually and
charges any remaining breach time. Boundary timestamps are marked before
activity at that timestamp; periods use a consistent half-open convention.

The winner is copied to `logs/round2/frozen_submission.py`; its hash and
selection criterion are stored in `selection.json`. Once this selection is
frozen, changing the source is rejected. The no-trade control may win if the
other candidates lose on validation. That is evidence to reconsider the
development hypotheses, not a reason to search the final segment.

## Final evaluation: last 20%, after freezing

```bash
.venv/bin/python -m scripts.round2_workbench final
```

This runs only the frozen source on the full tape, reports the last-20% PnL
increment separately, and repeats the full replay with the unmodified organizer
CLI. All native result fields must match exactly. A completed final report is
reused rather than rerunning or reranking candidates.

Full-session PnL includes development and selection periods. The last-20%
increment is a chronological evaluation only if those outcomes were not
inspected previously. The online strategy may still learn causally as labels
mature during that period; source and hyperparameters remain frozen.

If a final run is interrupted, repeat the same command with the same frozen
source. Audit results are cached with provenance checks, and CLI verification
can finish without selecting a new model. Do not use the result to tune the
same final segment and continue calling it untouched.

Before publishing a round-2 submission, preserve any existing round-2 export,
then copy the verified frozen source and report to tracked paths such as
`strategies/round2_submission.py` and `results/round2_submission.json`. Check
source hashes, local submission rules, tests and Git status; commit and push.
The workbench deliberately leaves round-1 files intact.

## Reproducibility and recovery

- `development.json` and `validation.json` checkpoint completed cases, so the
  same unchanged comparison can resume missing cases after an interruption.
- Inputs, source snapshots and the native/evaluator fingerprint are checked
  at every command. Changed data, changed rules, edited snapshots, or mismatched
  cached reports are rejected. Use a new study directory for reviewed changes.
- Wait for process-pool commands to exit before removing their generated output
  directories. Keep raw datasets, promoted strategies, Git history and backups.
- Historical search scripts often assume zero penalty and a 100-lot cap. Use
  the new workbench for mixed strict and paid-risk candidates.
- Historical characterization is available via
  `python -m scripts.round2_characterize --workers 4`. Its output is explicitly
  historical and does not choose a round-2 submission.

## Validation already performed during preparation

The test suite covers label maturity, pre-observation forecast scoring,
adaptation after a synthetic reversal, strict reservation through cancellation,
timestamp-group splits, immutable sources, exact native boundary behavior with
paid breaches, sparse cutoff accounting, and the full paid-risk workflow.
A six-candidate synthetic smoke study also completed prepare / screen / select /
final with an exact CLI match. These establish implementation behavior, not
round-2 profitability.

## Historical characterization

All 18 runs completed using native fees and private-event ledger checks. The
transfer's round-1 result matched the immutable 624,076 checkpoint field for
field. All strict exposure contracts passed. Values below are net PnL.

| Candidate | Original thin sample | Sample v2 | Round 1 |
| --- | ---: | ---: | ---: |
| Transfer | -80,846.00 | 294,271.00 | 624,076.00 |
| Strict 100 | -46,259.00 | 293,659.00 | 606,310.00 |
| Fast adaptation | -54,055.01 | 291,840.00 | 598,600.00 |
| Dual memory | -71,845.00 | 294,902.00 | 622,789.99 |
| Guarded trend | 225,487.00 | 0.00 | 0.00 |
| Flat control | 0.00 | 0.00 | 0.00 |

The market-making and trend hypotheses behave very differently. The dual-memory
candidate retained most of the dense-tape performance, but does not solve the
thin-sample failure. Preserve the alternative families and let the new tape's
development/validation evidence decide. No candidate was tuned or selected as
the round-2 winner from this historical comparison.

Exact hashes, fees, exposure metrics and final adaptive state are recorded in
`results/round2_historical_characterization.json`.
