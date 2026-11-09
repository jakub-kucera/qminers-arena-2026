# Round 4's private PnL curves (read 9 Nov from the portal's leaderboard)

Read from the leaderboard chart's own data (the Recharts component's `entries`: 52 teams, 481 points 25 s apart),
reduced to the cumulative PnL every 1,000 s and differenced into segments. The last segment ends at the listed
final PnL (the series stops at 11,999.96 s). The full series were not saved (a JS call returns ~1,000 characters);
re-read them from the page if needed. PnL in thousands; the top 20 of 52.

## PnL per 1,000-s segment (k)
| team (rank) | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Team 1 (1) | 274 | 248 | 178 | 141 | 176 | 126 | 187 | 226 | 130 | 238 | 182 | 152 | 2,258 |
| Team 3 (2) | 234 | 230 | 133 | 146 | 162 | 119 | 193 | 195 | 135 | 233 | 150 | 130 | 2,060 |
| Team 2 (3) | 243 | 235 | 170 | 124 | 151 | 120 | 184 | 152 | 55 | 249 | 149 | 125 | 1,957 |
| Team 6 (4) | 243 | 219 | 147 | 124 | 110 | 120 | 176 | 197 | 106 | 232 | 142 | 121 | 1,937 |
| Team 7 (5) | 244 | 224 | 150 | 121 | 136 | 88 | 184 | 188 | 118 | 216 | 148 | 113 | 1,930 |
| Team 5 (6) | 231 | 211 | 140 | 105 | 144 | 104 | 172 | 182 | 126 | 233 | 139 | 108 | 1,895 |
| Team 4 (7) | 222 | 217 | 132 | 127 | 115 | 108 | 174 | 195 | 119 | 232 | 137 | 108 | 1,886 |
| Team 9 (8) | 221 | 217 | 119 | 115 | 130 | 80 | 173 | 190 | 111 | 231 | 136 | 87 | 1,810 |
| Team 8 (9) | 208 | 210 | 126 | 94 | 138 | 79 | 178 | 182 | 107 | 211 | 134 | 98 | 1,765 |
| Team 22 (10) | 223 | 206 | 109 | 108 | 109 | 80 | 181 | 181 | 113 | 230 | 125 | 91 | 1,756 |
| Team 11 (11) | 230 | 210 | 106 | 101 | 132 | 84 | 169 | 181 | 124 | 212 | 116 | 83 | 1,748 |
| Team 18 (12) | 219 | 214 | 108 | 111 | 108 | 78 | 175 | 180 | 107 | 230 | 120 | 76 | 1,726 |
| Team 14 (13) | 210 | 199 | 114 | 116 | 135 | 76 | 184 | 168 | 109 | 215 | 118 | 81 | 1,725 |
| Team 12 (14) | 214 | 205 | 106 | 110 | 108 | 87 | 176 | 178 | 107 | 223 | 111 | 99 | 1,724 |
| Team 13 (15) | 207 | 207 | 147 | 100 | 130 | 87 | 162 | 179 | 112 | 174 | 117 | 88 | 1,710 |
| Team 21 (16) | 220 | 198 | 113 | 96 | 112 | 86 | 174 | 177 | 104 | 215 | 107 | 101 | 1,703 |
| **ThatsMyQuant (17, us: R4-W2)** | 209 | 204 | **100** | 97 | 115 | 78 | 174 | 167 | 105 | 226 | **111** | **74** | 1,660 |
| Team 23 (18) | 186 | 203 | 123 | 98 | 109 | 70 | 167 | 174 | 86 | 210 | 133 | 88 | 1,647 |
| Team 25 (19) | 213 | 197 | 102 | 97 | 96 | 70 | 173 | 164 | 101 | 206 | 127 | 82 | 1,628 |
| Team 15 (20) | 210 | 201 | 104 | 116 | 89 | 71 | 163 | 164 | 93 | 213 | 122 | 81 | 1,627 |

Ranks 21–52 (cumulative at 1,000 / 6,000 / 11,000 s, final; k): Team 24 207 / 768 / 1,534 / 1,625; Team 17 207 / 786 /
1,511 / 1,599; Team 20 202 / 759 / 1,525 / 1,597; Team 26 193 / 758 / 1,507 / 1,596; Team 19 186 / 771 / 1,509
/ 1,592; Team 10 197 / 740 / 1,503 / 1,570; the last, Team 48, 98 / 341 / 674 / 699.

## Findings
- **The warm start closed round 3's warm-up gap:** our first 1,000 s made 209k against a 222k median for ranks 2–16
  (round 3: 37k against 53–97k). R4-W2 tied F5 on validation (the first 1,000 s 126.5k against 126.7k), so these
  curves cannot separate the warm start from the tape: round 4's first 1,000 s was among the three most profitable
  segments of every top-20 team.
- **We trailed the ranks 2–16 median in every segment** (−13, −7, −26, −14, −15, −9, −2, −14, −6, −4, −23, −25k;
  −158k in total). Our worst relative segments were 3, 11 and 12 (−23k to −26k). Among the top 20 our segment
  ranks were 17, 15, 20, 17, 11, 15, 11, 17, 15, 10, 18, 20.
- **Team 1's +598k over us is spread over all 12 segments** (+12k to +78k each), with no single jump step like
  round 2's: a steadily better forecast or execution.
- **The field moved together:** every team's segments rise and fall alike (segment 10 is 174–249k for the whole top
  20, segment 6 70–126k), so the tape's speed sets the level and the strategy sets the rate.
