# Round 3's private PnL curves (read 8 Nov ~07:00 from the portal's leaderboard chart)

Digitised from the chart's SVG paths ("PnL over time", linear view): all 53 teams at a 25-s grid, matched to the
ranking by their final value (every curve's end equals its listed PnL). The full series were not saved (the browser's
clipboard refused); re-read them from the page if needed. PnL in thousands.

## PnL per 1,000-s segment (k)
| team (rank) | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Team 1 (1) | 136 | 133 | 94 | 134 | 102 | 119 | 85 | 141 | 137 | 154 | 98 | 125 | 1,458 |
| Team 3 (2) | 97 | 98 | 104 | 112 | 88 | 93 | 96 | 129 | 115 | 122 | 85 | 102 | 1,241 |
| Team 2 (3) | 73 | 88 | 79 | 107 | 74 | 94 | 86 | 126 | 157 | 131 | 77 | 107 | 1,198 |
| Team 4 (4) | 74 | 83 | 70 | 111 | 69 | 87 | 80 | 121 | 139 | 124 | 77 | 101 | 1,134 |
| Team 6 (5) | 66 | 76 | 82 | 98 | 73 | 72 | 86 | 124 | 121 | 124 | 60 | 92 | 1,074 |
| Team 7 (6) | 90 | 82 | 59 | 112 | 52 | 82 | 81 | 110 | 129 | 124 | 58 | 94 | 1,072 |
| Team 8 (7) | 74 | 100 | 90 | 96 | 47 | 66 | 76 | 110 | 98 | 111 | 49 | 80 | 996 |
| Team 5 (8) | 80 | 82 | 40 | 93 | 42 | 78 | 75 | 109 | 108 | 114 | 72 | 84 | 978 |
| Team 9 (9) | 59 | 86 | 69 | 85 | 57 | 80 | 72 | 112 | 95 | 109 | 63 | 87 | 974 |
| Team 13 (10) | 66 | 72 | 66 | 99 | 50 | 68 | 69 | 102 | 110 | 109 | 47 | 72 | 929 |
| Team 14 (11) | 58 | 85 | 39 | 96 | 50 | 76 | 57 | 105 | 92 | 117 | 62 | 90 | 927 |
| Team 11 (12) | 62 | 63 | 44 | 90 | 58 | 70 | 40 | 95 | 107 | 106 | 46 | 94 | 875 |
| Team 19 (13) | 73 | 74 | 62 | 85 | 43 | 71 | 50 | 105 | 99 | 102 | 41 | 71 | 875 |
| Team 17 (14) | 61 | 70 | 37 | 91 | 38 | 69 | 69 | 107 | 75 | 111 | 51 | 79 | 858 |
| Team 12 (15) | 57 | 83 | 45 | 89 | 47 | 69 | 51 | 102 | 69 | 93 | 44 | 84 | 833 |
| Team 24 (16) | 53 | 81 | 71 | 75 | 21 | 61 | 50 | 106 | 90 | 97 | 50 | 77 | 832 |
| **ThatsMyQuant (17, us: R3-F3)** | **37** | 60 | **35** | 84 | 46 | 65 | 76 | 113 | 90 | 102 | **35** | 85 | 827 |

## Findings
- **Our first 1,000 s is the weakest of the top 17: 37k**, against 53-97k for ranks 2-16 and 136k for Team 1. By 100 s:
  us 7, 6, 9, 12, 21, 28, 30, 35, 36, 37k; Team 1 19, 26, 38, 46, 59, 111 (a +52k step at 500-600 s), 117, 124,
  131, 136k; Team 3 15, 21, 30, 38, 49, 74, ..., 97k; Team 2 11, 16, 27, 34, 47, 53, ..., 74k. The online
  ridge's warm-up (it needs MIN_LABELS / RIDGE_MIN labels before it trades well) costs ~20-35k against the peers
  and is the largest single fixable gap. **Round 4 idea: warm-start F3's ridge from the round's public tape**
  (the Rust ridge_maker has RIDGE_DUMP / RIDGE_WARM; the pretrain session found frozen models win in-round, so a
  warm start fitted on the same round, then learning online, should hold).
- **Segments 3 and 11 are also weak** (35k each; peers 37-104k and 41-98k): calmer stretches? To check against the
  segment's volatility on our validation curve.
- **Elsewhere we run at the peer group's rate** (segments 7-10: 76-113k, like ranks 9-16).
- **Same edge as the leaders:** our 25-s PnL increments correlate 0.48 with Team 1's, 0.58 with Team 3', 0.72
  with Team 2's. **But we take more losing steps:** 25-s drops over 3k: us 8, Team 2 6, Team 1 2,
  Team 3 1.
- The leaders' curves are smooth (no breach-sized steps except Team 1's +52k at 500-600 s): unlike round 2,
  round 3's winners did not win on a few huge bets.
