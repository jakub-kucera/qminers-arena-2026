# Round 2: local research checkpoint

Target: at least 150,000 native net PnL. Full local audit: **167,412**. No competition server
access or submission is authorized now. All experiments below are local.

| Frozen model | Full public net | First 80% | Last 20% increment | Penalty |
| --- | ---: | ---: | ---: | ---: |
| 60-second causal M2/maker switch, hurdle 20 | **167,412** | **151,012** | **16,400** | **0** |
| User-supplied M2 | 116,620 | 93,503 | 23,117 | 0 |
| Adaptive fill-value maker | 105,829 | 99,039 | 6,790 | 0 |
| 300-second causal M2/maker switch, hurdle 0 | 117,837 | 110,687 | 7,150 | 0 |

Native matching, 5 ms action latency and penalty parameters are unchanged.
All audits observed actual and potential exposure at or below 100 lots.
Public tape SHA256: `88ff641e962540c66fa1cc4a3547585d31838d0929340150690cabb4f3cfb9f4`.

The supplied M2 follows net market-aggressor volume of at least 500 lots.
It persists direction until the opposite large flow, uses a one-lot shadow
strategy's cumulative PnL above 10 to enable trading, and targets +/-100 using
IOC orders. Its trend coefficient is zero. Its full native CLI result was
independently reproduced. Exact source SHA256:
`c969089d0f140f73ba60fbb7ddbca97847c443d68a69bf8a2b058110837ce4ab`.
The supplied header's split result does not match our precise 80% timestamp;
only the measured split above is used. M2 loses 1,242 on round 1. Its round-2
net falls to 111,195 / 91,114 / 38,121 at 10 / 20 / 50 ms latency.

The adaptive maker combines online ridge pricing with the fixed conditional
fill-value boosted trees. Calibration updates only after 400 ms labels mature,
clips errors, and decays toward zero. A rejected entry can still reduce inventory
passively. This repaired the earlier static gate's later-period failure.

The composite keeps maker learning active and switches to M2 when its one-lot
shadow has both cumulative profit above 10 and positive trailing 300-second
profit. It retains cancellation reservations, permits one IOC in flight, and
excludes IOC fills from maker calibration. Shadow profitability is a friction
proxy; actual orders still incur native execution effects. It was frozen from
four candidates by combined profit on minutes 30-80, requiring both subperiods
positive. Full source SHA256:
`c5feae50878b5e2d60e59ef1e30fd174f3112e7a6bc21aa22c556ffd3064ed4d`.

The adaptive model was selected from six candidates; first-30-minute training
profit is in-sample. The entire public tape has now been consumed, including
score disclosures from the supplied model. Frozen selections reduce adaptive
reuse but do not restore an independent holdout. No private performance or
probability of reaching 150,000 on unseen data is established.

Five M2 alternatives on the consumed first 80%: crossing one extra tick 93,368;
five-second signal expiry 64,229; visible-resting-only flow 0; nonresting-only
flow and executed-plus-visible-rest both 93,503. These features do not improve
the original signal on this sample. Visibility is not participant identity.
Nearby original M2 thresholds remain profitable (82,799-94,849); this is a
sensitivity check, not a fresh validation or a reason to retune its defaults.

The next bounded experiment tested trailing-profit switching hurdles 20/40 ticks over
60 seconds and 50/100 ticks over 300 seconds. The first-80% scores were 151,012,
130,207, 125,942 and 89,988, respectively. The predeclared rule selected 60/20
from combined minutes 30-80 profit (44,698 + 63,611), before full replay.
Its full PnL exceeds supplied M2 by 50,792 (43.6%). All ten sampled ten-minute
increments are positive; sampled maximum drawdown is 13,138. These are
descriptive results from the same consumed tape, not independent observations.

Exact frozen winning source SHA256:
`c96141d18a50b9280539a90b160f2a1b13acb00ef96cd099a8484e12b4292877`.
The shared-budget architecture is unchanged from the 300-second composite;
the stronger recent-profit hurdle keeps the adaptive maker active when M2's
recent evidence is weak. There are no hardcoded profitable clock intervals.
Nearby 15/25-tick and 45/90-second variants are sensitivity diagnostics only;
their results cannot replace this frozen choice. See the archived result files.

The unmodified native CLI matches every audited result field. All 110 repository
tests pass, including mode-transition reservations, IOC exclusion from maker
calibration, and causal shadow-window checks. The deliverable is
`strategies/round2_composite_local.py`; it is byte-identical to the frozen source.
No strategy was submitted to the competition server.

| Sensitivity diagnostic | First 80% net | Minutes 30-60 | Minutes 60-80 |
| --- | ---: | ---: | ---: |
| 60 seconds / 15 ticks | 135,938 | 38,162 | 57,892 |
| 60 seconds / 25 ticks | 148,100 | 45,632 | 56,409 |
| 45 seconds / 20 ticks | 141,652 | 38,731 | 56,240 |
| 90 seconds / 20 ticks | 143,718 | 38,626 | 63,261 |

All nearby variants retain positive later periods. This supports a profitable
neighborhood on this tape but does not establish absence of overfitting. No
further search was used to replace the winner after its full result was seen.

Reproduce from the repository root with the existing Python environment:

```powershell
python -m simulator.main --backtest data/round2_public.csv --strategy strategies/round2_composite_local.py --log-dir logs/local_reproduction --no-logs
python -m unittest discover -s tests -q
```

Research archives contain exact candidate sources, predeclared selection rules,
all reported scores, native result and PnL curve, and verification fingerprints.
The source header is inherited unchanged to preserve its tested byte hash;
this document supplies its current architecture and verified performance.

More filled orders alone is not the objective:
native `fills` counts distinct user order IDs with a fill, not round trips.
