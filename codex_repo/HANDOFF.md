# Handoff for the next session

## Latest goal: evolving main plus at least10k, with price-crash diagnostics

The user superseded319920 with improving main models by at least10000 as main
improves, and confirmed that "drop" means sharp price decline. Fresh fetches
still show origin/main36a041af7da57060f5cafe5bcc4f4772c23cd31b in the same repo.
All6 active-registry references were audited on full native round2: no-trade0,
guarded trend-6116 (independent CLI parity), others-229801 to-267529.75.
There are no newer T2 models in current remote main. Preserve exact snapshots.

Current-cycle criterion met at **316,031**: +19,316 over the stronger local
reference296,715, exceeding the conservative306,715 guard. This does not
claim future main commits have already been evaluated. Before further work,
fetch main, inspect new commit diffs/README/HANDOFF and new models (not only
registry entries); benchmark any newer relevant baseline on the same tape.

Exact source strategies/round2/round2_local_316031.py; SHA256
088c20f7cf726b9e1e5047e2adc8c305e5c2a9ed0f1064aced4b097042f608f6.
Native audit/CLI agree all fields. Fees0, actual/potential100, first80=253707,
final20=62324, drawdown10880, fills2352, volume284784. Output copy is under
outputs/round2-local-316031 with verified_result/current_goal_result/analysis.

Architecture: no-passive35feature ridge3x,400ms labels,50ms IOC pace, spread1
execution; adds500ms signed flow magnitude and sqrt intensity to liquidityT2.
Huber6 residual weighting uses forecasts stored at observation and matured
labels, weighting all sufficient statistics equally. No crash-time gates.
It does not include the depth feature from the separate310978 alternative.

Price-crash diagnostics: largest1s-sampled100s decline156.5ticks at3936–4036s.
New/reference gain inside20223/20131, outside295808/276584 (+19224 outside).
The worst drawdown10880 is at5398–5400s, during a113.5tick upward midpoint
rebound. Risk is higher than old296715's6012 despite better PnL; disclose it.
Mirror price20000-p, sideB/A swap produced identical316031 and all6001 PnL
samples, zero fee and strict100. This is synthetic consumed data, not holdout.

Latest studies: flow_magnitude500ms full304476; dual_head_v2 blend50% full297209;
impact_ablation magnitude+depth full310978; robust_shocks Huber6 full316031.
All were selected by positive30–60 and60–80 and maximum combined gain before
full replay. Early studies retain historical319920 goal in frozen protocols;
later studies use306715. See docs/ROUND2_MAIN_PLUS10K.md and research archives.
All146 tests passed. Every replay is terminal; no live process remains.

Do not access competition server or send emails/submissions. Earlier167412
email was explicitly one-time. Research-branch Git pushes remain authorized.
Do not alter original simulator/rules or immutable historical source files.
All public data consumed; no guaranteed unseen superiority or private score.

## Historical checkpoint: 167,412 local result, no server access

The user prohibits all competition website/server access, including read-only
checks. Continue locally. Read [the current results](docs/ROUND2_LOCAL_PROGRESS.md)
before the historical sections below. Best audited full public replay is
167,412 net PnL from a causal maker/M2 switch; supplied M2 scores 116,620 and
the adaptive maker 105,829. All have zero penalties and maximum 100-lot exposure.
The target is now 150,000, not the earlier 100,000. The local replay exceeds it.
All public segments have been consumed. Do not claim an untouched holdout.
The frozen candidate uses a 60-second window and 20-tick shadow-profit hurdle.
Check the archived verified_result.json for native CLI parity and sensitivity.
Historical statements
below about reserved segments, pending tests, and server access are superseded.

## Research branch update: composite model failed reserved validation

Read [ROUND2_COMPOSITE_FINDINGS.md](docs/ROUND2_COMPOSITE_FINDINGS.md) first for
the latest research-branch state. Main's initial investigation is preserved
below as history. The new public goal is at least 100,000 net PnL. It is not
achieved. Thirty-four additional development variants were evaluated; a
fill-conditioned boosted-tree gate made 85,435 in the first hour, including
training-period profit, but lost 21,593 on minutes 60-80 after being frozen.
The no-trade control won that validation comparison; it is not a solution to
the user's profit goal. No model was promoted. First 80% is now consumed;
last 20% remains unreplayed. Do not run public-check on the flat selection and
declare success. All local replay processes for this study have finished.

Next investigate why the static conditional gate failed, including causal
online calibration/adaptation and inventory reduction when the gate withdraws
quotes. Keep the final public segment reserved for a genuinely frozen next
candidate. Do not relabel minutes 60-80 as fresh validation after using them
for development. Server validation remains a separate possible evidence source.
The benchmark, matching engine, latency and penalties were unchanged. All 98
merged repository tests passed, and exported tree predictions matched sklearn.
Exact sources, protocols and results are archived under research/round2_*.

Prepared 7 November 2026 after round 1. Team: **ThatsMyQuant**. The user expects
the next session about an hour after round 1. Round-2 public data has now arrived
and is at `data/round2_public.csv`. Read
[ROUND2_INITIAL_FINDINGS.md](docs/ROUND2_INITIAL_FINDINGS.md) before doing more work.
Only the first public 60% has been replayed; all six active/control references
and four development diagnostics have completed. Every active policy lost on
that prefix. Four further inventory/entry prototypes also lost; their naive
resizing caused large queue churn and does not isolate the effect of smaller
positions. See the findings and source hashes before reusing these prototypes.
No round-2 winner or server score is established. The provisional
deadline is Sunday **00:15 CET** with a planned ready-by time of **23:45 CET**.
The organizer has announced three separate datasets: downloadable public,
server validation with PnL-only feedback, and private scoring after the deadline.
Public is roughly half the size of either hidden dataset; the size metric is
unspecified. Internal public splits are not those organizer datasets.
The user emphasized that round 2 could differ substantially. The later
[round-1 chart summary](docs/ROUND1_CHART_EVIDENCE.md) strengthens steady-making
hypotheses for round 1, but does not establish the next regime or a target
inventory size. Preserve the maker and trend/taker alternatives and let new
public evidence decide. Raw leaderboard curves/private log are not in this repo.

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
initial findings for current status. No round-2 submission is selected.
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
