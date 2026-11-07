# Handoff for the next session

Updated 7 November 2026: supplied server evidence has shifted priority to takers.
Read [taker research](docs/ROUND2_TAKER_RESEARCH.md) and the [seven-model shortlist](docs/ROUND2_TAKER_SHORTLIST.md).
New candidate `strategies/round2_taker_liquidity_269920.py` earns **269,920 public**, zero fees, strict actual/potential 100; every field matches independent organizer CLI. Server validation for this exact file is pending.
Imported T2 reproduces **194,391 public** and has operator-associated **490,359 validation**, submission `2d72ef32-8561-4299-8aaf-f8168bb6d003`. Imports, original paths, source hashes and server artifacts are recorded; the other repository was not modified.
**110 tests pass.** Six-candidate synthetic high-volatility stress batch is still in progress at this checkpoint; inspect `logs/round2/taker_stress/highvol_1p25/` and the final `results/round2_taker_stress_highvol_1p25.json` if present. No normal-speed stress batch has been started.
Use named immutable files: `round2_submission.py` still points to the earlier 181 K maker. Do not infer a new submission or server score from that mutable path. Public scores have been reused for selection. No private result is available.

## Historical distribution-study handoff (superseded status below)

Updated 7 November 2026 after the distribution-driven round 2 research.
Team: **ThatsMyQuant**.

Current source: [strategies/round2_submission.py](strategies/round2_submission.py), byte-identical to
`strategies/round2_distribution_ensemble_shock_180895.py`.
**180,895.19 net full PUBLIC PnL**, including 536.81 native penalties; every
field matched a separate unmodified organizer CLI replay. Source SHA-256:
`c6f6a25629cb3ba94924305f17793c8c8426dbe14b418e6607a73b5f132a3d75`.
All 16 new full-public candidates, two restarted diagnostics and four CLI checks
have finished. **No research process remains running. 105 tests pass.**

Read [distribution research](docs/ROUND2_DISTRIBUTION_RESEARCH.md),
`results/round2_distribution_comparison.csv` / JSON and
`results/round2_distribution_180895.json`. Full statistics and per-horizon
markout tables are tracked in `results/round2_distribution_statistics.json`
and `results/round2_distribution_markouts.csv`. Raw 103 MB extraction is ignored
under `logs/round2/distribution_research/observations.npz`.

This session keeps the saved absolute-volatility sizing constants unchanged;
the user's other session explores sizing. The new model averages two 55-feature
conditional-fill heads (public fills and actual/public blend), then actively
closes inventory opposed to observed>=2 tick jumps for 100 ms when spread<=2.
IOC exits have one-tick crossing allowance, native 5 ms latency and one pending
hedge. They do not open new directional targets. Native paid overlap remains:
maximum actual 184, potential 300, penalty 536.81; not a strict 100-lot strategy.

All fitted labels use first 60% public data only. Rich/public head:33,296
latency-aligned fills,400 ms labels clipped to 3 ticks. Mixed head also uses 9,479
mature actual maker fills of the frozen 162 K policy, with 5 x actual-fill weight
and 5 tick label clipping. Both 64-tree heads use identical 55-feature layouts;
ensemble weights are fixed 1/2. All online and offline inputs are public/causal;
queue exhaustion is an offline sample-weight diagnostic, never a future input.
The ensemble/shock combination was adaptively selected on consumed public data.

Current period PnL: first 60%128,236; middle 20%27,236.19; last 20%25,423;
later 40%52,659.19 versus 39,091.19 for the old 162 K checkpoint. Sampled 1 second
drawdown 6,779 versus 12,656. Restarting on the later 40% from empty state yields
46,184.19 versus 37,248.19 baseline. This is reused-public sensitivity analysis,
not new independent validation. Rare jumps account for a substantial gain.

Useful preserved alternatives:
- `strategies/round2_distribution_ensemble_174940.py`: strongest non-shock
  alternative 174,940.19; later 40%46,125.19; audited, no separate CLI replay.
- `strategies/round2_distribution_shock_175867.py`: simpler single-head shock
  model 175,867.19; later 40%51,313.19; independent CLI verified.
- `strategies/round2_distribution_mixed_170252.py`: actual/public fill head,
 170,252.19; independent CLI verified.
- `strategies/round2_distribution_rich_167958.py`:55-feature public-fill head,
 167,958.19; independent CLI verified.
- Earlier 162253,163429 and 144580 archives remain unchanged. The old seven-model
  Downloads export/table is historical and contains those original bytes.

The prior phase had 86 development-prefix replays and 14 new full-public
candidates; this phase adds 16 full-public candidates and two restarted tests.
No server/private score is established. Earlier pending server-PnL question
named 144580; always identify the actual uploaded immutable file before recording
feedback. The current submission pointer has changed repeatedly.

The GitHub SSH remote is the user's authorized repository. Last push failed
because github.com cannot resolve in this environment. Local commits/bundles
are not evidence of remote synchronization. Preserve the frozen round 1 source
and every named result; simulator/evaluator hashes are unchanged.

Historical first144K checkpoint and earlier research follow.


Read [the volatility research report](docs/ROUND2_VOLATILITY_RESEARCH.md) and
`results/round2_submission.json`. Public data is `data/round2_public.csv`:
100 minutes, 2,193,064 rows, SHA-256
`88ff641e962540c66fa1cc4a3547585d31838d0929340150690cabb4f3cfb9f4`.
The first investigation showed much higher volatility and every initial active
reference lost. Its historical evidence remains in
[ROUND2_INITIAL_FINDINGS.md](docs/ROUND2_INITIAL_FINDINGS.md).

The user's absolute-volatility sizing idea produced the main improvement.
Regular 100 ms preceding-midpoint returns estimate absolute variance with a
three-second decay. Planned cap is floor-to-five(200/sigma_squared), bounded
10..100. Native priority-preserving shrinks retain real reservations until ACK;
100 ms jump pauses and immediate cancellation of invalid books remain active.
These are planned bounds: full-run actual exposure reached 162, potential 300;
all native fees were paid. Time-weighted development actual exposure fell from
about 72 lots below sigma 2 to about 11–13 above sigma 4.

There were 56 development replays before six sources were frozen at
`logs/round2_selection_v1`. The selected inverse-variance source made
**+19,052.19** on the middle public 20% and **+13,149** on the frozen last 20%.
The fixed-cap alternative lost 36,742 on the middle segment; the signal-target
alternative lost 18,551. All public segments have now been consumed. The
selection file's `final_segment_inspected=false` is a historical selection-time
flag; `final_report.json` records the completed check. Future public outcomes
are sample tuning, not fresh validation.

Three post-freeze alpha ablations and three risk-weighted/adaptive learners
completed on development only. Best development gain was 113,837 versus the
checkpoint's 112,379; these small gains have not replaced the verified source.
The user then asked us to leave volatility calibration to their other session.
Keep all sizing constants fixed in this session's further maker experiments.
Twenty-four alternative-mechanism development replays completed: passive exit
quotes, queue-priority retention, conditional fill edges, queue waiting-time
gates, event-time price forecasts and a separate fixed-size IOC family without
volatility sizing. Queue-wait0.1s made114,996 on development but 143,252.19 on
the full public tape, below 144,580.19, so it was not promoted.
There are now 86 completed development replays and 96 passing tests. See
`results/round2_alternative_mechanisms.json`.
Four symmetric pretrained nonlinear-alpha candidates completed full public
replays under `logs/round2/pretrained_alpha`:140,647.19--144,168.19 net, with no
promotion. They fit only first 60%
public flow/book features, with no price/time/IDs. Exported tree predictions
match the fitted estimator. Risk parameters are unchanged. First 60% PnL is
in-sample and later 40% is beyond fitting but previously inspected globally;
neither is fresh organizer validation. Frozen candidate sources are tracked
under `strategies/round2_research/pretrained`, with fit specs in
`results/round2_pretrained_specs.json`. The conditional-fill checkpoint above is now the current submission.
There are now 62 development replays and 87 passing tests. Exact study sources,
native hashes and results are in `results/round2_development_progress.json`;
the first frozen shortlist is tracked under `strategies/round2_shortlist_v1`.

No organizer server-validation or private score exists yet. A question asking
for server PnL and submission ID is pending; associate any reply with the exact
uploaded source. The organizer uses downloadable public, separate PnL-only
server validation, and private scoring after the deadline. Local public splits
are not either hidden dataset. The provisional shifted deadline is Sunday
**00:15 CET**, with a ready-by target of **23:45 CET**.

The user emphasized round 2 could differ substantially. The round-1 chart
analysis is a prior only; the new public tape confirmed a different regime.
No raw leaderboard curves/private user log have been supplied here.

## Start here

1. Check `git status` and read this file plus [the round-2 plan](docs/ROUND2_PLAN.md).
2. Preserve both verified submissions and named archives; match source/data fingerprints.
3. Check whether the organizer changed rules or simulator interfaces.
4. Develop new hypotheses on the existing development prefix; label any subsequent public checks as sample tuning.
5. Record server feedback against exact files; compare materially different policies before large searches.

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
The suite now has **76** passing tests after the initial public investigation.
The recorded checks are in `results/round2_preparation_checks.json`.
Preparation checkpoint tag: `round2-preparation-20261107`.
The final preparation history is also backed up in the workspace parent at
`backups/qminers-arena-round2-preparation.bundle`; older checkpoint bundles
remain at their original paths.

Historical characterization completed all 18 candidate/tape combinations; see
`results/round2_historical_characterization.json`. The transfer reproduced
624,076 exactly on round 1, the strict maker scored 606,310 without penalties,
the dual-memory maker scored 622,789.99, and guarded trend scored 225,487 on the
thin original sample. These are historical checks, not fresh round-2 evidence. The
`logs/round2` experiment has since been prepared; see the
volatility research report for the current verified selection.
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
