# Results: Qminers Algo Trade Arena 2026 (team ThatsMyQuant)

The Arena ran 7–8 Nov 2026 in Prague: a playground, then four 5-hour rounds, each scored by our final bot's PnL on a
private tape that nobody saw before the deadline. This page records where we finished, the bot behind each round
and what the field's curves showed. Sources: the portal's leaderboards (`data/arena/round<N>/leaderboard.json`, all four
checked against the live site on 9 Nov), the dashboard's submission list, and each round's `HANDOVER.md`.

## Where we finished

**16th of 61 overall, score 2.489.** This is computed from the four published leaderboards with the Info page's
rule: Score = 0.8·z1 + z2 + z3 + 1.2·z4, where zᵣ is the PnL standardised over the round's teams with positive PnL
(sample sd; this reproduces the organisers' own z1 1.212 and z2 0.398), and a team at or below zero scores as 0.
The organisers announced the official standings at the closing ceremony and on Discord; this page has not been
checked against that list.

| Round | Final bot | Its upload score | Private PnL | Private / upload | Rank | z | Weight | Points |
|---|---|---:|---:|---:|---|---:|---:|---:|
| 1 (7 Nov 13–18) | R1-C12 `r1_C12_codex_v6.py` | 622,921 | **602,527** | 0.967 | **8th of 61** | 1.212 | 0.8 | 0.970 |
| 2 (7 Nov 19–24) | R2-L9 `r2_L9_taker_huber.py` | 873,719 | **742,470** | 0.850 | **22nd of 59** | 0.398 | 1.0 | 0.398 |
| 3 (8 Nov 01–06) | R3-F5 `r3_F5_jump_bar.py` | 888,195 | **827,253** | 0.931 | **17th of 53** | 0.463 | 1.0 | 0.463 |
| 4 (8 Nov 07–12) | R4-W2 `r4_W2_warm10k.py` | 1,754,574 | **1,659,546** | 0.946 | **17th of 52** | 0.549 | 1.2 | 0.659 |
| Total | | | 3,831,796 | | **16th of 61** | | | **2.489** |

Round 1's upload ran on the public tape itself (the portal matched a local run to the cent). From round 2 on, each upload
ran on a separate validation tape (12,000 s) and the private tape was a third draw.

| Round | Winner | Winner's PnL | Ours / winner | 10th place | Median (positive teams) | Teams we beat |
|---|---|---:|---:|---:|---:|---:|
| 1 | Team 2 | 792,696 | 0.76 | 533,533 | 447,797 | 88% |
| 2 | Team 1 | 1,875,116 | 0.40 | 1,017,551 | 499,488 | 64% |
| 3 | Team 1 | 1,458,005 | 0.57 | 929,224 | 729,472 | 69% |
| 4 | Team 1 | 2,258,468 | 0.73 | 1,756,312 | 1,541,305 | 69% |

**Overall top 10** (same computation): 1 Team 1 8.687, 2 Team 2 6.978, 3 Team 3 6.896, 4 Team 4 5.737,
5 Team 5 5.383, 6 Team 6 5.174, 7 Team 7 4.377, 8 Team 8 3.711, 9 Team 9 3.473, 10 Team 10 3.325. Around us: 14 Team 14 2.618, 15 Team 15 2.508, **16
ThatsMyQuant 2.489**, 17 Team 17 2.193. 15th place was 0.019 points away, about 5k of round-4 PnL. 10th place was
0.84 points away, about 234k of round-4 PnL on its own. Our standing after each round: 8th, 12th, 15th, 16th.

## The final bots

All four are one line of work: an online ridge regression that forecasts the mid price 400 ms ahead from order-book
features, refits as the session runs, and (until round 4's warm start) starts from nothing on each tape. Round 1 used the forecast to make markets.
From round 2 on, where prices moved more per lot traded, it used the same forecast to take liquidity. The files are in
`python/bots/qminers/candidates/`; each file's docstring holds the notes of the bots it builds on.

### Round 1: R1-C12, an online-ridge market maker
- **What it does:** 29 causal features (quote-price centres of fresh orders, one-second aggressive-flow groups with each
  order capped at 20 lots, touch imbalance, flow), labels maturing after 400 ms, infinite memory. It quotes up to
  200 lots a side at the touch and steps one tick back when the forecast is against that side (dead zone 0.18,
  inside-spread edge 0.3). Replacement orders go out while cancels are still in flight, and an IOC order hedges
  the position back whenever it passes the 100-lot limit.
- **Lineage:** the codex session's online ridge maker (R1-C1, 554,347) → C1b (in-flight cancels plus the hedge, +17k)
  → C5 (400-ms horizon, +24k) → C9 (flow groups) → C11 (v5, 29 features) → C12 (v6). The line was built in the
  second repository, now under `codex_repo/` (C12 is `codex_repo/strategies/round1_quote_flow_622921.py`, tag
  `codex_repo/round1-622920.99`). The hand-built queue ladder (R1-F8b, 523k) was the fallback.
- **Private run:** 602,527 (0.967 of public), 20,662 fills, a 1,173 breach penalty from the hedge's brief excursions,
  |position| median 99.

### Round 2: R2-L9, a pure forecast taker with a robust fit
- **Why it changed:** round 2's tape moved about twice as often, and every round-1 maker lost money on it (C11
  −263k on the public tape). Makers with size lost on the validation tape too (E2 −41k).
- **What it does:** the same online ridge re-aimed at taking. It uses 36 features (R2-L3's 33, including liquidity and
  young-order features, plus 500-ms impact features) with a Huber-robust fit (δ 6). When the 400-ms forecast beats
  half the spread by 0.15 ticks and the spread is one tick, it sends an IOC sized within the 100-lot limit, counting
  every live order. It never rests quotes.
- **Lineage:** T1 / T2 (the ridge used to take, 486k / 490k) → L1 (liquidity features, 772k) → L3 (no quotes, 804k)
  → L8 (quotes only in calm markets, 827k). L1 and L3 came from the second repository's main (269,920 / 294,098 on
  the public tape). **L9 is Přemysl's improvement of L3**: in his research branch he took it to 296,715, then
  316,031 (Huber fit, δ 6), then 317,057 ("robust_depth": a signed 500-ms flow feature scaled by the opposing top
  depth, 36 features). That file, `codex_repo/strategies/round2/round2_local_317057.py` (his commit of 8 Nov 00:07),
  is byte-identical to `r2_L9_taker_huber.py`, uploaded at the 00:14 deadline: 873,719.
- **Private run:** 742,470 (0.85 of validation, our largest drop).

### Round 3: R3-F5, the taker plus a hidden-price filter
- **What it does:** R2-L9, plus R2-L8's one-lot quotes switched on only while the 5-s price speed is below 2.5
  ticks/s (R3-B1). On top of that, a hidden-Markov filter of the generator's latent reference price (R3-F3): a
  probability vector over the hidden price, moved by each market order's impact and updated by where new orders are
  placed. Its gap to the mid, gap·|gap| and its spread are three more ridge features (39 in all). Finally, a
  state-dependent take bar (F5): 0.25 ticks over half the spread normally, F3's 0.15 for 5 s after a 3-tick jump
  within 200 ms.
- **Evidence:** on validation the filter was worth +149,769 (F3 883,559 against B1 733,790, +20%); the jump bar
  +4,636 on F3 (a tie, kept). Online likelihood choice of the impact (F4, −44k), a 150-ms blend (F10, −70k) and
  CMA-ES constants (F6c, −20k) all lost on validation.
- **Private run:** 827,253 (0.93 of validation).

### Round 4: R4-W2, R3-F5 with a warm start
- **What it does:** R3-F5 unchanged, except the ridge does not start cold. The X'X and X'y sums F5 accumulated on
  round 4's public tape are embedded in the file, scaled to 10,000 labels (`PRIOR_MASS`), so it forecasts and takes
  from the first book. The idea came from round 3's private curves, where our first 1,000 s was the weakest of the
  top 17.
- **Evidence:** a tie with plain F5 on validation (1,754,574 against 1,752,785). Every other change that won locally
  lost on validation: MH3 (multi-horizon ridges, −15.9k), X1R3 (wide-spread takes and filter settings, −27.8k),
  W3 (flow features and depth takes, −22.2k). Each one lost in the validation tape's last, fastest third.
- **Private run:** 1,659,546 (0.946 of validation); 94,026 fills, 1,168,488 lots, end position +92 at 10,160,
  penalty 0, PnL standard error 51,873, 10 min 58 s of the 15-minute limit.

## Every upload

Taken from the dashboard. Times are Prague; the score is the public tape (round 1) or the validation tape (rounds 2–4).
The submission ID is the first 8 characters; the handovers have the full IDs.

| Round | Time | ID | Bot | Score |
|---|---|---|---|---:|
| Playground | 11:52 | cf0494bc | the final of 11 completed uploads (one by Přemysl; 7 more failed static analysis) | 283,959 (private 292,469) |
| 1 | 13:16 | 1403dba9 | R1-F3 `r1_F3_full_room.py` (all 200 lots at the touch) | 425,553 |
| 1 | 14:10 | 538fcb50 | `codex_repo/strategies/round1_depth_524k.py` (5-feature online maker) | 523,999 |
| 1 | 15:00 | fa0b258b | R1-C1 `r1_C1_codex_ridge.py` (15-feature ridge maker) | 554,347 |
| 1 | 16:20 | 10893f27 | `codex_repo/strategies/round1_size_555389.py` | 555,389 |
| 1 | 16:48 | 0d6b3d45 | R1-C1b `r1_C1b_codex_pipelined.py` | 571,237 |
| 1 | 17:09 | 4efc29ea | R1-C5 `r1_C5_long_horizon.py` | 595,442 |
| 1 | 17:31 | c7d8fbb4 | R1-C9 `r1_C9_codex_v4_flow_groups.py` | 605,753 |
| 1 | 17:38 | dc8e070c | R1-C11 `r1_C11_codex_v5_29feat.py` | 619,282 |
| 1 | 17:47 | **be7ed3eb** | **R1-C12 `r1_C12_codex_v6.py` (final)** | **622,921** |
| 2 | 19:54 | 9f4843cd | R2-E2 (learned maker, 30 lots) | −41,499 |
| 2 | 20:12 | 04625898 | R2-V2 (maker, speed-scaled exposure) | 71,864 |
| 2 | 20:28 | 7042cde4 | R2-M2 (big-order follower) | 376,082 |
| 2 | 20:40 | 9f1d18b6 | R2-M3 (M2 + stop) | 366,342 |
| 2 | 21:09 | 3565b31f | R2-T1 (forecast taker) | 485,667 |
| 2 | 21:19 | 1dfb680a | R2-RA (flow window) | 467,703 |
| 2 | 21:35 | e1827f34 | Přemysl's `round2_composite_local.py` (`codex_repo/strategies/`) | 247,165 |
| 2 | 21:43 | 2d72ef32 | R2-T2 (T1 without breaches) | 490,359 |
| 2 | 22:00 | 9cd32a00 | R2-M4 (125-ms window) | 441,088 |
| 2 | 22:10 | 8f29efb0 | R2-H1 (T1 + big-flow bias) | 567,740 |
| 2 | 22:33 | fb8478b0 | R2-L1 (T2 + liquidity features) | 771,770 |
| 2 | 22:58 | d319b090 | R2-L3 (L1 without quotes) | 804,018 |
| 2 | 23:18 | a631c405 | R2-L6 (L3 + flow bias) | 798,269 |
| 2 | 23:53 | 5c00a472 | R2-L8 (quotes below 2.5 ticks/s) | 826,778 |
| 2 | 00:14 | **bc0a2c50** | **R2-L9 `r2_L9_taker_huber.py` (final; Přemysl's)** | **873,719** |
| 3 | 01:24 | afc885d6 | R3-F1 (L9 + filter) | 862,764 |
| 3 | 01:46 | 1dbf4142 | R3-F3 (B1 + filter) | 883,559 |
| 3 | 02:57 | e4100a46 | R3-B1 (F3 without the filter) | 733,790 |
| 3 | 03:22 | **4b70c626** | **R3-F5 `r3_F5_jump_bar.py` (final)** | **888,195** |
| 3 | 04:34 | bf0acc13 | R3-F4 (filter bank) | 839,401 |
| 3 | 05:00 | 7eaab64a | R3-F10 (150-ms blend) | 818,039 |
| 3 | 05:20 | 7c58ffa4 | R3-F6c (policy-search constants) | 868,327 |
| 4 | 07:12 | 99c167e0 | R4-W1 at PRIOR_MASS 0 (= R3-F5) | 1,752,785 |
| 4 | 08:04 | ccad24f7 | R4-MH3 (multi-horizon ridges) | 1,736,913 |
| 4 | 08:34 | **ee2a564f** | **R4-W2 `r4_W2_warm10k.py` (final)** | **1,754,574** |
| 4 | 08:46 | 4631295d | R4-X1R3 (wide takes + filter settings) | 1,724,973 |
| 4 | 10:53 | 275e974f | R4-W3 (W2 + flow features + depth take) | 1,732,375 |

Private runs: round 1 eab69eda, round 2 ff5c797c, round 3 3538e497, round 4 9d366117 (the latter's detail names
ee2a564f as the evaluated submission).

## What the field's curves showed

- **Round 1:** the winner, Team 2, made 426k fills on the private tape, more than 12 times the average of the rest of the
  top 5 (we made 20.7k). Every top team's PnL grew in a straight line, and ours varied more than any of the top 5's,
  because we sat at the 100-lot limit (|position| median 99). Their edge looked like queue place and many small orders.
- **Round 2:** teams 2–21 traded like us (25-s steps correlated 0.46–0.76 with ours) but with a higher slope. Team 1
  was different: +148k in a single 25-s step at a price jump, about 8 times our exposure, apparently a bet over the
  limit on jumps. We measured that idea in round 3 and it lost on our simulator's thin post-jump book.
- **Round 3:** our first 1,000 s was the weakest of the top 17 (37k against 53–136k), the cost of the ridge's warm-up.
  Elsewhere we ran at the rate of ranks 9–16 (`data/arena/round3/leaderboard_curves.md`).
- **Round 4:** the warm start closed the warm-up gap (first 1,000 s 209k against a 222k median for ranks 2–16), but
  we trailed that median in all 12 segments, by 2–26k each and 158k in total. Team 1's +598k lead over us came from
  every segment. So the gap was a steadily better forecast or execution, not one event
  (`data/arena/round4/leaderboard_curves.md`).
- **Private against upload scores:** 0.85–0.97 each round, so the bots transferred. Small local gains did not: in
  round 4 every change worth +13k to +23k on the public tape lost 16–28k on validation, and in round 3 so did F4, F10
  and F6c. Only the structural steps held up: the filter (+150k), the taker (round 2) and the in-flight cancels
  with the hedge (round 1).

## Corrections to the round notes

The portal's "final" marks settle three places where the notes written during the rounds disagree:
- Round 1: R1-C12 was uploaded at 17:47 and marked final. `data/arena/round1/HANDOVER.md` says it "was not uploaded"
  and names C11; its private-run section (C12, 602,527) is right.
- Round 2: the final was R2-L9 (bc0a2c50, uploaded at 00:14), not R2-L8 as "Round 2 results, marked" says; the
  update at the top of round 3's handover is right.
- Round 3: the final was R3-F5 (4b70c626), not R3-F3 as "Round 3 result" and the round-3 curves table say; its
  "Private run against public" section is right.

## Where the rest is
- Each round's story, every candidate and the reasoning: `data/arena/round<N>/HANDOVER.md` and `CANDIDATES.md`.
- Every tested idea with its numbers: `IDEAS.md` (rows `R1-…` to `R4-…`).
- The server's result folders for every upload and every private run (result.json, metadata.json, the 1-s
  pnl.csv): `data/arena/round<N>/*_res/`. The private runs' full logs (the book, events and trades of each private
  tape) stay local, gitignored: `experiments.day.tape_from_logs` rebuilds a private tape from them.
- The second repository, `qminers-algo-arena` (the Codex session's, started from the clean starter), with
  Přemysl's research branch merged in: `codex_repo/`, imported on 9 Nov with its whole history (66 commits;
  each imported commit's message ends with its original hash, and its tags are `codex_repo/<tag>`). Its own
  `README.md` and `HANDOFF.md` are the way in; its `AGENTS.md` is that session's instructions, now historical.
