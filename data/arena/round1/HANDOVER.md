# Round 1 handover (7 Nov, 13:00-18:00)

The template (`docs/HANDOVER_TEMPLATE.md`): copy it to `data/arena/round<N>/HANDOVER.md` at the start of round N,
fill it in during the round and finish it by deadline − 0:10; the template itself stays as it is. Committed and pushed so the other laptop has it (ON_THE_DAY.md, "Handover note"); the private
run's results and `leaderboard.json` go in this folder too.

## Uploaded
<!-- each upload: file, time, why; local PnL under all / worse / --resting; the metrics expected (arena.backtest --metrics) -->

## Portal against local
<!-- the portal's figures against our backtest of the same file on the same days; the ratio (T); which fill mode and mark fit -->
Before the round (the playground, 7 Nov): the portal's results folder is byte-identical to a local `exchange-simulator` run of the same file on the same data (A0: -7,598, 394 fills; the trend follower +1,878), so `T` = 0 on the public data; only the private data differs (ON_THE_DAY.md, "From the playground"). Check it again on round 1's first upload.

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
