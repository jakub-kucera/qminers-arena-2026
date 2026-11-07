# Round 1 handover (7 Nov, 13:00-18:00; submissions close 18:00, freeze 17:30, last upload by 17:35)

The template (`docs/HANDOVER_TEMPLATE.md`): copy it to `data/arena/round<N>/HANDOVER.md` at the start of round N,
fill it in during the round and finish it by deadline − 0:10; the template itself stays as it is. Committed and pushed so the other laptop has it (ON_THE_DAY.md, "Handover note"); the private
run's results and `leaderboard.json` go in this folder too.

## Uploaded
<!-- each upload: file, time, why; local PnL under all / worse / --resting; the metrics expected (arena.backtest --metrics) -->
- 13:16, `python/bots/qminers/candidates/r1_F3_full_room.py` (A0: F3 with SESSION_S 1e9), round_start's best on round1.csv. Expected on the public data: pnl 425,553.00, fills 30,452, traded volume 2,645,992, end position +100, cash -577,347.00, mark price 10,029.00, breach 0, pnl_se 11,263.42, |inv| q50/68/95/99.7 98/100/100/100; exchange-simulator 26 s here.
- Next: `python/bots/qminers/candidates/r1_F5_shrink_react.py` (R1-F5). Expected on the public data: pnl 455,822.00, fills 37,847, traded volume 2,481,742, end position +100, cash -547,078.00, mark price 10,029.00, breach 0, pnl_se 11,038.79, |inv| q50/68/95/99.7 95/100/100/100.

## Portal against local
<!-- the portal's figures against our backtest of the same file on the same days; the ratio (T); which fill mode and mark fit -->
Before the round (the playground, 7 Nov): the portal's results folder is byte-identical to a local `exchange-simulator` run of the same file on the same data (A0: -7,598, 394 fills; the trend follower +1,878), so `T` = 0 on the public data; only the private data differs (ON_THE_DAY.md, "From the playground"). Check it again on round 1's first upload.
- Round 1's first upload (R1-F3, 13:16): the portal identical to the local run (+425,553.00, 30,452 fills, 2,645,992 lots, end +100, pnl_se 11,263.42); "Simulation time" 1 min 2.8 s for 4.4M rows, so E is about 1-2 minutes with the queue. T = 0 again.
- Its review (`uv run python -m experiments.day.run_review data/arena/round1/r1_F3_full_room_res`, the results folder ignored): maker fills +0.42 ticks inside the mid at the fill, then the mid 0.26 ticks AGAINST them at 1 / 5 / 30 s (sample_v2: +0.06 our way): adverse selection eats ~60% of the edge here; PnL steady by quarter (96k / 202k / 315k / 426k), max drawdown 899; 54,646 orders, 28,162 cancels (193 too late).

## Private run against public
<!-- the private (hidden) run's PnL against the public one, per product -->

## Fill model and mark
<!-- the engine settings that matched the portal: --resting/--queue, --match-trades, --mark, --limit-penalty, --fee -->
Their simulator is the engine (`uv run exchange-simulator`; `arena.qgrid` and `arena.qsim_rust` run it, the Rust port byte-identical): no fill model to choose. Latency 5 ms, limit 100 (10,000/s above), markout against the market's resting orders.

## Units map
<!-- exchange unit → engine unit (1 / PRICE_SCALE) → each product's tick; their timestamps → 0..999,900; where each limit comes from -->
One instrument; prices in ticks, sizes in lots, Time in seconds. The template's clock maps (Time - first Time) / SESSION_US onto 0..999,900: set SESSION_US (template) and SESSION_S (families) from the round's file (round_start prints its length).

## Rule answers
<!-- which ON_THE_DAY.md items the rules or probes answered (written under each item, with the source), and the ones still open -->
Answered before the round: ON_THE_DAY.md, "Known so far", the 7 Nov blocks (site, starter repository, slides, playground). Open: the round's submission deadline (the dashboard's), whether the private hour looks like the public one.

## Re-tests
<!-- which of last round's choices were tested again this round, which were kept untested ("Choose the approach again each round") -->

## Leaderboard
<!-- leaderboard.json saved here; experiments.day.leaderboard_curves --read verdict; our standing -->

## Next round
<!-- round N+1's first candidate, and its first three actions -->
