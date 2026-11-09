
Improvement concentration: +998 within the largest100s decline, only +28 outside, versus316031. Retain316031 as conservative reference;317057 is an experimental candidate, not a robust promotion.

# Latest seven-minute follow-up

Seven-minute local study, 8 Nov 2026 Prague
main unchanged at 36a041af7da57060f5cafe5bcc4f4772c23cd31b.
Selected robust_depth: net PnL 317,057; improvement +1,026. Requested +10,000 NOT achieved.
Audit and independent native CLI match every result field.
Fees 0.0; max actual 100; max potential 100.
Sampled max drawdown 10880.0; final20 PnL 63148.0.
Largest100s market decline3936-4036: strategy PnL 21221.0; outside 295836.0.
Rebound5398-5400: strategy PnL -10880.0.
Architecture: previous Huber6/ridge3x pure taker plus signed500ms flow normalized by current opposing top depth, clipped +/-3 (36 features).
Three frozen variants; selected using30-80percent gain, then full comparison. Repeatedly consumed public data; no fresh holdout or private validation. Small improvement is not proof of generalization.
Source SHA256 4df2b5c12142242fcff6be80e8765833f3d7c54d97893b5707589929e67aa622.
No competition server accessed or submission made.


# Handoff for the next session

Latest: **round-3 intake completed; Python work is paused at the user's request**.
Do not start further Python until the user resumes work: another session needs
to finish first. All profiler and seven-model screening runs have finished.
Read [round-3 initial findings](docs/ROUND3_INITIAL_FINDINGS.md) and
[the evaluation plan](docs/ROUND3_PLAN.md).

New data: `data/round3_public.csv`, moved from the workspace root with matching
SHA-256 `1021586b92a3d9dfdb70096e6b0af34d460813b139f1f51f56b73871cb5a2d15`.
2,412,805 events over about 6,000 seconds. Only the first 60% was profiled or
replayed; middle20% and last20% remain reserved. Head/tail rows were viewed
at intake. The user says the rules/setup should be the same as round2.

First-hour reference net PnL: final317057 **256,652**; pure294098 **241,354**;
liquidity269920 **225,327**; M4 **171,089**; maker180895 **23,840** (350 fee);
flat0; round1 maker **âˆ’238,022.52** (3,889.52 fee). Takers have zero penalties
and actual/potential inventory100/100. No source was changed or newly fitted
offline for round3; online learning within the replay remains causal.
All independent fill-ledger audits passed. No extra CLI replay was started
after the user asked to pause Python. Results: `results/round3_initial_screen.json`
and `results/round3_initial_investigation.json`; immutable preparation record:
`results/round3_intake_manifest.json`.

Matched first-hour diagnostics: 1s price SD4.11 vs round2's2.90; average touch
quantity986 vs1,190; spread>1 tick17.48% vs12.24%. The forecast-taker family
is the leading initial hypothesis. Do not extrapolate the scores to hidden
tapes or consume the reserved public40% without deliberate frozen selection.

## Round-2 final review

Latest: **user's final round 2 submission reviewed on 8 November (CET)**.
Original: `../round2_local_317057.py`; untouched byte-identical archive:
`strategies/round2_final_317057.py`. Source SHA:
`4df2b5c12142242fcff6be80e8765833f3d7c54d97893b5707589929e67aa622`.
**317,057 public net, zero penalties**, all result fields independently matched
original organizer CLI; actual/potential exposure100/100. Drawdown10,880
versus6,222 for the earlier294,098 pure taker. Later40%175,771 versus176,747;
the22,959 total gain is concentrated earlier. **116 tests pass.**
Read [final review](docs/ROUND2_FINAL_REVIEW.md) and
`results/round2_final_317057.json`. Three new flow-impact features, causal
Huber-style weighting and3x ridge are the substantive changes. The user calls
this the final submission; its server score/ID are pending, not inferred from
the filename or public result. Review processes are finished. The mutable
`round2_submission.py` remains the old181 K maker; use the named final archive.

## Earlier structural-taker handoff

Updated 7 November 2026 after structural taker followups.
Read [further ideas and completed experiments](docs/ROUND2_NEXT_IDEAS.md),
[taker research](docs/ROUND2_TAKER_RESEARCH.md), and the
[nine-model shortlist](docs/ROUND2_TAKER_SHORTLIST.md).

- **294,098 public**, zero penalties: `strategies/round2_taker_liquidity_pure_294098.py`.
  Every result field matches an independent original organizer CLI replay.
  Source SHA: `4d46c848817325c0266377e36be4ecc6c96d5963ff4dcdda5cb0a33b73f68e22`.
  It removes all one-lot quotes from269,920. Public drawdown6,222 versus4,658,
  and median inventory100 versus92. It does not inherit a server score.
- **269,920 public** liquidity forecast remains the first candidate for which
  the user was asked for validation. Its server result is still pending.
- **263,059 public**, drawdown3,418: `strategies/round2_taker_largeflow_263059.py`.
  Adds learned large-aggressor features. Audited native replay, no separate CLI.
- Imported T2 reproduces **194,391 public**, with supplied **490,359 validation**,
  submission `2d72ef32-8561-4299-8aaf-f8168bb6d003`. Original files were not modified.
  Source associations are operator-supplied; server metadata has no upload hash.

The forecast-funded extra-tick experiment made262,394 and was not promoted.
All three followups, two original CLI checks (T2/269,920) plus the new294,098
CLI check, the execution diagnostic and seven-source fast stress comparison
have completed. **114 tests pass. No research process is running.**
Normal-speed synthetic tape exists but has not been replayed.

The synthetic fast tape gives269,920 liquidity846,899, T2 553,157 and V2 185,512.75.
V2's actual supplied validation is71,864.15, illustrating that this synthetic
tape is not a hidden-score estimator. See `results/round2_taker_stress_highvol_1p25.json`.

The one-lot LIMIT probes accounted for113,810 lots,29.75% of269,920-model volume.
Its IOC orders filled268,715 of381,598 requested lots; only84 of3,346 IOC
orders were completely unfilled. Removing probes changes both exposure and
own-fill forecast inputs; do not attribute its gain only to maker avoidance.

Use immutable named files. **`round2_submission.py` still points to the old
181 K maker**; no automatic competition upload or pointer change was made.
All public scores were reused for selection; no private score is available.
Best next mechanisms: actual fill-conditional return targets, distinct entry
and holding horizons, and post-sweep replenishment rather than blind momentum.

The plain SSH push was interrupted after hanging without output. A bounded
noninteractive retry failed: github.com could not resolve. Origin was not
updated. Keep local commits and the verified complete-history bundle at
`../backups/qminers-arena-round2-takers.bundle`. Source checkpoint178876f
preserves all three followups. The distribution-study handoff below is history.

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
about 72 lots below sigma 2 to about 11â€“13 above sigma 4.

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

---

*The notes below are from PÅ™emysl's research branch (`research/codex-round1-ml-metric-optimization`, last commit 8 Nov 00:07), merged here on 9 Nov; main's notes above run to 8 Nov 01:13.*

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

L8 independently reproduced296181, zero penalty,75762 fills,356731 volume on identical round2_public native engine. Other-tape header scores unverified. No strict potential-exposure audit run for L8. Compared to317057: +20876 for experimental candidate.
All seven-minute experiment processes completed.
