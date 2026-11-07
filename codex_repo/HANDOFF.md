# Handoff for the next session

Prepared 7 November 2026 after round 1. Team: **ThatsMyQuant**. The user expects
the next session about an hour after round 1. No round-2 CSV has been provided.
The organizer has announced three separate datasets: downloadable public,
server validation with PnL-only feedback, and private scoring after the deadline.
Public is roughly half the size of either hidden dataset; the size metric is
unspecified. Internal public splits are not those organizer datasets.

## Start here

1. Check `git status` and read this file plus [the round-2 plan](docs/ROUND2_PLAN.md).
2. Preserve the final round-1 files and locate/fingerprint the new dataset.
3. Check whether the organizer changed rules or simulator interfaces.
4. Prepare a new experiment with the workbench, then profile only its development prefix.
5. Evaluate the predeclared candidates before beginning a large parameter search.

All commands below assume the `qminers-algo-arena` repository root. Use
`.venv/bin/python`; it is Python 3.13.16 and already works. Offline dependency
resolution through `uv sync` failed earlier; no environment rebuild is needed.

## Round 1 is frozen

| Item | Value |
| --- | --- |
| Verified local net PnL | **624,076.00** |
| Native inventory penalty | 1,700.00 |
| Fills / volume | 21,517 / 2,120,528 lots |
| End inventory / cash / mark | 100 / -377,124.00 / 10,029.00 |
| Maximum actual / potential inventory | 256 / 303 |
| Source | `strategies/round1_quote_flow_624076.py` |
| Identical submission | `strategies/round1_submission.py` |
| Evidence | `results/round1_624076.json`, `results/round1_submission.json` |
| Final round-1 commit / tag | `77bc241` / `round1-624076` |

Every result field matched a separate replay using the unmodified organizer
CLI. This is a **local result**. The user subsequently reported rank **8/61**
and server PnL **602,526.53**, versus Team 2's **792,696.00**. The exact
uploaded file, submission ID and scored dataset are not established; do not
bind that score to the 624K file or diagnose its difference without evidence.
See `results/round1_reported_leaderboard.json`.
The user said the round had basically ended. Do not claim we won: the reported
650K target was not beaten. The input Claude strategy scored 595,441.83 exactly;
our extension gained 28,634.17 net.

The final source SHA-256 is:

```text
0aaff6caee4c8708afb0f3bc54a8f1d3beaa5a641477db192be09cfeb6993b45
```

`data/round1.csv` has SHA-256:

```text
362e8208be1eeec32ad190d097774e26448f0d5149575a8e1b1efd1db1735940
```

Every part of round-1 data was eventually consumed during research. Later
round-1 comparisons are **sample tuning**, not fresh validation. The original
476,052 candidate had an earlier chronological selection protocol; subsequent
77 full and 121 screening Claude-extension comparisons consumed the whole tape.
See `results/round1_claude_research.json` and the
[archived historical notes](docs/ROUND1_RESEARCH.md).

## Where the requested older models are

| Net PnL | Preserved file |
| --- | --- |
| 498,056.00 | `strategies/round1_nonlinear_498k.py` |
| 523,999.00 | `strategies/round1_depth_524k.py` |
| 555,389.00, zero penalty | `strategies/round1_size_555389.py` |
| 571,237.25 | `strategies/round1_pipeline_571k.py` |
| 595,441.83, supplied model | `strategies/round1_claude_595k.py` |
| 605,752.82 | `strategies/round1_flow_606k.py` |
| 616,534.83 | `strategies/round1_flow_616535.py` |
| 619,281.99 | `strategies/round1_quote_flow_619282.py` |
| 622,920.99 | `strategies/round1_quote_flow_622921.py` |
| 624,076.00 | `strategies/round1_quote_flow_624076.py` |

Keep these files and their result manifests intact. Checkpoint bundles remain
in the workspace parent; `qminers-arena-checkpoint-624076.bundle` contains a
verified complete history through the final round-1 commit.

## What the final model does

It learns a 400 ms midpoint return online using 29 features: the earlier 15
flow/depth/count features, six fresh-quote/cancellation features, and eight
aggressive-flow features. Public orders are filtered to `owner == 'market'`.
Aggressors are grouped according to whether they remain visible after execution;
that is not a perfect G/IOC classification. Whole-order quantities are aggregated
before capping each order's group weight at 20 lots. Group decay is one second;
fresh-quote decay is 500 ms. Memory is long (`1e11` microseconds), the neutral
band is 0.18, and quote half-width is 0.45 ticks.

The planned inventory target is 100. Pending cancellations can release only
the provisional quote budget; actual reservations remain tracked against the
native 1,000-lot wall. Temporary actual breaches over 100 are paid in full.
Excess inventory is hedged by a 5 ms IOC, including from private fills. Cached
market prices expire after 100 ms, preventing indefinite EOF hedge retries.

## Rules and implementation traps

- Send, cancel and modify latency is 5 ms. Due user actions execute before
  a market row at the same timestamp. User orders never self-trade.
- Native acceptance wall is 1,000 lots. Time at actual `abs(position) > 100`
  costs 10,000 per second, regardless of the breach size. Rank **net** PnL.
- Use one standalone no-argument `BaseStrategy` subclass. Standard library
  subset and documented numeric packages are allowed; no file/network/system,
  introspection, forbidden builtins or extra simulator imports in submissions.
- Keep original matching engine and scoring configuration unchanged. Review
  new round rules when supplied; these statements describe the current starter.
- A cancellation rejection does not reject the original order. A pre-ACK
  cancellation can be rejected before ACCEPTED at the same timestamp. Preserve
  the original reservation and retry only after acceptance. The final model
  waits for ACCEPTED before cancellation. `tests/test_pending_cancel.py` covers
  the rejected-cancel race for experimental variants.
- Never erase resting/pending quantity merely because cancellation was sent.
  Private fill ledger and remaining quantities must match the native engine.
- Delayed labels must mature before fitting; buffers must cover the chosen
  horizon and observation interval. Do not silently drop all long-horizon labels.
- Old `search_passive.run`, `evaluate_set`, `search_queue` and `validate_round1.run`
  enforce zero penalty / at-most-100 potential exposure. They reject the final
  paid-risk model. Use `round2_workbench` or `round1_standing_liquidity.run`.
- The new workbench marks split boundaries without advancing the engine clock.
  Sparse prefix tails are marked at the exact cutoff with all breach time
  charged, while native result fields remain unchanged.

## Round-2 preparation and state

The [candidate registry](strategies/round2/manifest.json) contains six standalone
sources. They are predeclared hypotheses, **not round-2 winners**. The generator
uses the immutable round-1 624,076 archive, not the mutable submission filename.
`round2_dual_memory.py` is a new causal mixture: long and five-minute ridge
forecasts are scored using predictions recorded before their future labels.
The faster model gets more weight only after those outcomes mature.

`scripts/round2_workbench.py` provides prepare / screen / select / final.
Use `public-check` rather than the legacy `final` command name. Every result
from this tool is local public-data evidence, never organizer private scoring.
It snapshots sources, hashes data and evaluator, preserves chronological time
groups, resumes incomplete identical comparisons, freezes the selected source,
and verifies the final replay against the original CLI. It leaves round 1 intact.

The workflow has a synthetic end-to-end smoke test and a forced paid-breach
integration test. The latter checks exact native equality and exact-split
penalty accounting; modifying a frozen source is rejected. The test suite has
**66 passing tests** at the original preparation checkpoint; **70** after the
organizer-protocol update and server-score ledger tests.
The recorded checks are in `results/round2_preparation_checks.json`.
Preparation checkpoint tag: `round2-preparation-20261107`.
The final preparation history is also backed up in the workspace parent at
`backups/qminers-arena-round2-preparation.bundle`; older checkpoint bundles
remain at their original paths.

Historical characterization completed all 18 candidate/tape combinations; see
`results/round2_historical_characterization.json`. The transfer reproduced
624,076 exactly on round 1, the strict maker scored 606,310 without penalties,
the dual-memory maker scored 622,789.99, and guarded trend scored 225,487 on the
thin original sample. These are historical checks, not fresh round-2 evidence. No actual
`logs/round2` experiment has been prepared, and no round-2 submission is selected.
If an experiment has `final_report.json`, its final segment has been evaluated;
the selection file's flag records the state at selection time, not current freshness.
This segment is internal to the PUBLIC tape. Organizer private scoring happens
only after the deadline. Server validation PnL is model-selection feedback;
log every query and exact source using `scripts/round2_server_results.py`.
No round-2 server scores are recorded yet. A repeated query of the same fixed
validation tape is not an independent sample. Do not multiply public PnL by two
and present that as an expected private score.

The next structural research priorities are in
[ROUND2_STRUCTURAL_IDEAS.md](docs/ROUND2_STRUCTURAL_IDEAS.md). The prepared six
candidates do not yet implement those new queue-value or latent-flow models.

## Lessons that should save time

The useful round-1 gains were robust order counts, depth, size cohorts, causal
quote/flow information, and lower cancel/replace delay. The largest late gain
came from the supplied model's 400 ms labels and much longer training memory.
First-hour rankings often failed to predict the best full replay. Preserve
chronological validation and continuous state before spending the next round
on many slight variants.

Wide quoting, large persistent overbooking, blanket IOC entries, shadow fill
models, online trees, fixed trees, and neural residuals did not beat the final
maker on the consumed round-1 tape. This is evidence about that tape only.
The thin original sample behaves very differently; the guarded trend candidate
exists to cover that market hypothesis. Re-test mechanisms when the next
round's spread, liquidity and signal persistence change.

## Git, team and external state

Branch `main` retains organizer commit `3f5bea7`; simulator files are unchanged.
Origin is exactly:

```text
git@github.com:jakub-kucera/qminers-arena-hachathon-final-v2.9-fr-fr.git
```

Pushes last failed because this environment could not resolve `github.com`.
The GitHub connector returned 404 for the repository. The user previously
pushed successfully from their terminal. Do not claim local commits were
pushed. Try a bounded push after a checkpoint; if unavailable, provide:

```bash
git push origin main --follow-tags
```

TEAM.txt contains **ThatsMyQuant**, **Astra**, **Sol**, and reported token counts
for this session only. Other repositories/sessions are explicitly out of scope.
Account subscription and dollar pricing are unknown. No organizer invitation
status has been verified. Keep committing concrete progress and update this
handoff and the scoped usage estimate as work continues.
