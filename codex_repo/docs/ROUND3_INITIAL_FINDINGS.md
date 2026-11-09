# Round 3 initial investigation

The file is now `data/round3_public.csv`, preserved byte for byte. It contains
2,412,805 events over 5,999.993238 seconds, compared with round 2's 2,193,064
events over approximately 6,000 seconds. SHA-256:
`1021586b92a3d9dfdb70096e6b0af34d460813b139f1f51f56b73871cb5a2d15`.

The user says the rules and public/validation/private setup should be the same
as round 2. The existing native configuration was used. See
[the frozen intake plan](ROUND3_PLAN.md) for source selection and provenance.

**All findings below concern only the first 60% of each public tape**, about
one hour. The remaining round-3 40% has not been profiled or replayed. Head/tail
rows were viewed for intake; structural validation and hashing read the whole
file without computing later-period performance.

## Market changes

Both development prefixes were measured with the same no-trade profiler and
the same ten-minute signal blocks.

| Development metric | Round 2 | Round 3 |
| --- | ---: | ---: |
| Events per second | 364.92 | 399.96 |
| Actual traded market lots per second | 1,146.82 | 1,175.63 |
| Mean spread, ticks | 1.169 | 1.233 |
| Time with spread above one tick | 12.24% | 17.48% |
| Time with spread above two ticks | 2.96% | 4.04% |
| Mean best-bid quantity, lots | 1,186.84 | 997.38 |
| Mean best-ask quantity, lots | 1,193.47 | 974.84 |
| One-second midpoint-return SD, ticks | 2.90 | 4.11 |
| 25-second midpoint-return SD, ticks | 16.46 | 20.13 |
| Adjacent valid midpoint jumps of at least two ticks | 214 | 322 |
| Adjacent valid midpoint jumps of at least ten ticks | 27 | 26 |
| Median resting-type insertion size, lots | 14 | 17 |
| Median IOC-type insertion size, lots | 61 | 60 |
| Median inter-event gap, microseconds | 1,794 | 1,627 |
| Median scheduled cancellation lifetime, seconds | 0.3201 | 0.3203 |

Round 3 has more updates, around 17% less displayed quantity at the best
prices, and around 42% more one-second price volatility in this first hour.
The one-second volatility increase appears in all six ten-minute blocks:

| Minutes | Round 2 SD | Round 3 SD |
| --- | ---: | ---: |
| 0–10 | 2.345 | 3.035 |
| 10–20 | 1.320 | 4.647 |
| 20–30 | 3.022 | 3.736 |
| 30–40 | 3.677 | 3.890 |
| 40–50 | 3.382 | 5.047 |
| 50–60 | 3.015 | 3.970 |

Order sizes and scheduled lifetimes remain broadly similar. Actual traded
market volume rises only about 2.5%, despite roughly 9.6% more events per
second. More frequent moderate jumps do not imply uniformly worse extreme
tails: the count of jumps of ten ticks or more is nearly unchanged, and time
above a ten-tick spread is lower. Visible midpoint jumps can include temporary
quote effects rather than permanent underlying-price moves.

## Signals and implications

The median ten-minute correlation between trade-flow imbalance and the next
500 ms midpoint change rises from 0.126 to 0.159. The comparable touch-quantity
imbalance correlation rises from 0.082 to 0.105. These overlapping-label
statistics are descriptive, without a significance claim.

Blindly following each signal still loses on the profiler's one-lot
round-trip approximation after crossing costs. For example, trade-flow
following at 500 ms averages about −0.877 ticks in round 3. Selective forecasts
and realistic holding/execution policies must therefore be assessed through
native strategy replays; a positive correlation alone is insufficient.

The initial evidence favors checking forecast takers and flow-based policies
before committing to maker development. The frozen reference screen tests
that directly. No new source or round-3 parameter fit is part of this study.
Detailed profiles: `results/round3_development_profiles.json`.

## Completed frozen-reference screen

These are native replays of the **first public hour only**, with unchanged
source files. They are not full-public or server scores.

| Source | Net PnL | Penalty | Sampled drawdown | Max actual / potential |
| --- | ---: | ---: | ---: | ---: |
| User's round-2 final, 317057 | **256,652** | 0 | 10,094 | 100 / 100 |
| Pure liquidity taker, 294098 | 241,354 | 0 | 10,548 | 100 / 100 |
| Liquidity taker with probes, 269920 | 225,327 | 0 | 9,578 | 100 / 100 |
| M4 flow window | 171,089 | 0 | 16,488 | 100 / 100 |
| Volatility-sized maker, 180895 | 23,840 | 350 | 6,876 | 186 / 300 |
| Flat control | 0 | 0 | 0 | 0 / 0 |
| Round-1 maker, 624076 | −238,022.52 | 3,889.52 | 246,163.52 | 300 / 457 |

All seven completed and passed the independent cash/inventory ledger checks
and their declared risk contracts. All four takers stayed within actual and
potential 100 lots. Native terminal PnL equals the exact development-boundary
mark for each replay. No independent original-CLI rerun was started after the
user requested the pause. Prior-round checks of these same source files remain
separate evidence; they do not establish any round-3 server result.

Forecast takers lead this screen. The selected round-2 final exceeds the simpler
pure taker by 15,298 (6.34%) and has slightly lower sampled drawdown here. The
maker gap is much larger than its penalties, so fees alone do not explain it.
This favors further taker research when work resumes, without assuming the
remaining public tape or hidden server tapes have the same regime.

Machine-readable results: `results/round3_initial_screen.json` and
`results/round3_initial_investigation.json`. Sources and hashes are frozen in
`results/round3_intake_manifest.json`.

## Pause

The user requested that Python work pause when the existing runs finish so
another session can finish first. **All runs are finished; no Python process
from this session remains running.** No additional Python analysis, independent
CLI replay or later-public check should start until the user resumes work.
