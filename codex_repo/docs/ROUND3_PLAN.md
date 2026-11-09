# Round 3 intake and evaluation scope

The incoming workspace-root `round3_public.csv` was moved to
`data/round3_public.csv` without overwriting any existing file. SHA-256 before
and after the move:

`1021586b92a3d9dfdb70096e6b0af34d460813b139f1f51f56b73871cb5a2d15`

The file has 2,412,805 events, 86,670,643 bytes, and 5,999.993238 seconds between
its first and last timestamps. The schema is unchanged. The structural scan
checks timestamp monotonicity, valid operations, positive insertion prices
and sizes, and row shape. It does not fit models or evaluate later-period
performance. Head/tail rows were viewed during intake.

## Preserve a chronological check

`logs/round3/manifest.json` and the tracked copy
`results/round3_intake_manifest.json` freeze all sources and native hashes.
Only the first 60% is profiled or replayed in the initial study:

| Portion | Boundary / status |
| --- | --- |
| Development | Events before 3,599.997038 s; 1,439,836 rows |
| Middle 20% | Ends at 4,799.995685 s; reserved for later selection |
| Last 20% | Reserved for a subsequent local public check |

Equal-timestamp groups stay together. The full data and prefixes have separate
hashes. Public splits are not organizer validation or private data. After
preparation, the user said the round-3 simulator and dataset setup should be
the same as round 2. The preparation manifest retains its original pending
assumption as a historical record; this confirmation supports the rules used.

The user also asked that Python work pause after the existing initial runs
finish, to let another session finish first. Do not launch additional Python
analyses or replays until the user resumes this work. Lightweight documentation
and Git preservation can finish without starting Python.

The native configuration is unchanged: 5 ms order/cancel/modify latency,
100-lot penalty-free inventory threshold, 1,000-lot acceptance wall, and
10,000 per second outside the free threshold. All reported scores are net of
native penalties. Strict takers additionally assert actual and potential
exposure at most 100. Paid-overlap makers are audited against the native wall.

## Frozen references

These seven sources were chosen before observing round 3 strategy outcomes:

| Source | Hypothesis |
| --- | --- |
| `round2_final_317057.py` | User's final: robust online forecast, flow-impact features, pure taking |
| `round2_taker_liquidity_pure_294098.py` | Simpler pure taker without the final's robust/impact additions |
| `round2_taker_liquidity_269920.py` | Liquidity forecast plus one-lot passive probes |
| `r2_M4_flow_window.py` | Independent flow follower without a learned price forecast |
| `round2_distribution_ensemble_shock_180895.py` | Volatility-sized maker with round-2-pretrained fill heads |
| `round1_quote_flow_624076.py` | Fixed-exposure maker: tests whether spread capture returns |
| `round2_flat.py` | No-trade control |

Named source files and earlier round submissions remain unchanged. Candidate
copies under `logs/round3/sources/` are immutable. No round-3 parameters or
source alterations are part of this initial comparison. The custom audit
supports both strategy ledger interfaces and reconstructs cash/inventory
independently from private fills.

## Diagnostics and next decision

Both rounds' first 60% are compared with the same profiler: message sizes and
timing, scheduled cancellation lifetimes, actual book spreads and touch depth,
one- and 25-second price changes, and matched-horizon flow/imbalance statistics.
Signal correlations use overlapping labels and are descriptive. Screening
quote round trips are one-lot approximations, not executable strategy PnL.

After this initial screen, investigate mechanisms on development data. Freeze
a small shortlist before using the middle 20%; select using exact continuous
boundary PnL increments, then check the frozen selection on the final 20%.
Do not automatically consume the remaining public data to rank all references.
Record any server feedback separately against the uploaded source hash.

Commands from the repository root:

```bash
# Already prepared; do not run prepare into the populated directory again.
.venv/bin/python -m scripts.round3_intake profile
.venv/bin/python -m scripts.round3_intake screen --workers 2
```

`results/round3_development_profiles.json` and
`results/round3_initial_screen.json` contain the completed outputs when the
corresponding stages finish. Raw public data and replay logs remain ignored.
