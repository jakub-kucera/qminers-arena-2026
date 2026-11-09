# Runbook

**Start here.** This page is the day's index: each line names the `ON_THE_DAY.md` section behind it in
brackets; read only those, when the line comes up. The market's rules: `STARTER.md` (their README) and
"Known so far" (the 7 Nov blocks). `KICKOFF_PROMPT.md` is the prompt that starts an agent session (it points back
here). `D` is `data/arena/round<N>/`, `F` its tape (`D/<file>.csv`), and `BOT` is `python/bots/qminers/template.py`
(`ArenaBot`, written; it runs on their `exchange-simulator`). Our engine's tools run on Prosperity data only: priors.

## Before the doors open (Sat 08:00)
- `git pull && uv sync && uv run pytest` on every laptop; `references/` was cloned at home.
- `python3 references/check_arena_site.py`: a change goes into "Known so far"; offline, the snapshot stands.
- Names for A (driver, recorder) and B (data, research) ["The day: timeline and roles"].
- Every laptop on Europe/Prague time, logged in to the portal by the playground: e-mailed links are single-use
  ["Known so far"].

## Opening and workshop (09:00–10:30)
1. One person reads the Technical Rules in full and writes each answer into "First hour", with its source;
   what they leave open, ask at the workshop ["Questions for the organisers"].
2. Most of "First hour" is answered by `STARTER.md` (7 Nov answers under each item). Still open: the
   submission deadline, the data files' names, whether the private data is like the public ["First hour"].
3. If they hand out new code, it goes in unchanged, never retyped ["The format swap, step by step"].
4. By 10:30, a fallback bot or not: the playground candidate `python/bots/qminers/candidates/r0_A0_mm.py`
   is one already ["Spend the round's submissions", "A fallback first?"].

## Playground (10:30–12:00): three tracks at once ["Splitting the first hour"]
- **Probes (A, optional):** their simulator runs locally and answers most of what the probes asked ["Probes"].
- **Data (B):** no loader to fill in. Unzip (`uv run python -m gzip -d D/<file>.csv.gz`), then
  `uv run exchange-simulator --strategy BOT --backtest F --log-dir logs/<run>` and
  `uv run backtest-explorer --log-dir logs/<run>` on that full-logs run: spread, depth, trade rate, trend.
- **Bot (A):** set `PARAMS['ASSET']` (empty sends nothing; e.g. `--set 'PARAMS.ASSET={"fair": "mid"}'`). Check:
  `uv run python -m arena.validate BOT all --format qminers --max-size 1MiB` (source checks only, no --data; exit 0
  on a clean file) and a full `exchange-simulator ... --no-logs`
  run well under 15 min, flat at the end, no `breach_penalty`. Cap 1 MiB ["The format swap, step by step"].

## Lunch (12:00–13:00)
- After the first upload: compare the portal's figures with `logs/<run>/result.json` of the same file on the same
  data; a gap is the engine's error `T` ["How is PnL scored?"].
- Write round 1's candidates in order, with each one's local result ["Spend the round's submissions"].

## Each round (T = its start; rounds at 13:00, 19:00, 01:00, 07:00)
| When | Do |
|---|---|
| T+0:00 | Reload the dashboard; download the data (its link goes with the round) and the rules; note the submission deadline (it may come before the end). Write what changed into "Rule changes" and "Products". Unzip the tape. |
| T+0:15 | `uv run python -m experiments.rounds.round_start F --out results/r<N>` (profile, markouts, every candidate ranked, next grids); last round's bot (round 1: A0) on the new tape: `uv run exchange-simulator --strategy BOT --backtest F --log-dir logs/<run> --no-logs`, then a full-logs run into `backtest-explorer`; source-check it with `arena.validate`: the first candidate. |
| T+0:30 | Rounds 2–4: by T+1:00, one alternative to last round's approach against it, and every setting gridded again; last round's choices are priors, not defaults ["Choose the approach again each round"]. |
| T+1:00 | `uv run python -m arena.qgrid BOT F --grid PARAMS.ASSET.make_edge=1,2,3 --set 'PARAMS.ASSET={...}' --holdout 0.25 [--out <csv>]` (README.md, "Grid on the Arena's simulator"): take a cell good held out and in its neighbourhood, not the best cell ["Evaluation data"]. |
| T+1:30 | Size `stop_loss` and `flatten_from` on the PnL path (`logs/<run>/pnl.csv`, qgrid's max drawdown) ["Stress the bot"]. |
| T+2:00 | A checked bot at least as good as the last one, uploaded; its portal score against `result.json` is the engine's error `T`. Then `KICKOFF_PROMPT.md`'s improvement loop (qgrid with `--holdout`, exchange-simulator, validate's source check). |
| deadline − 0:30 | (T+4:30; earlier if 2× the first evaluation's time is longer.) Stop changing strategy. Check the final candidate and upload it; copy it into the root `strategies/` folder and commit. |
| deadline − 0:10 | Check which submission is marked final. Write the handover note (`data/arena/round<N>/HANDOVER.md`, copied from `docs/HANDOVER_TEMPLATE.md`), then commit and push it. |
| After | After the private run: our PRIVATE entry's results against the public run of the same file; save the leaderboard's data to `data/arena/round<N>/leaderboard.json` and run `uv run python -m experiments.rounds.leaderboard_curves --read data/arena/round<N>/leaderboard.json --team <ours>`. Both into the handover note ["The day: timeline and roles", "Is the market shared"]. |

## Rules that hold all day
- Never upload code whose source check and full `exchange-simulator` run haven't passed, and never spend a
  submission on untested code. A `GRAY_AREA` bot fails validate on purpose: never uploaded without an organiser's
  yes ["Gray-area variants"].
- A round's first upload is a bot that has already run in the playground (round 1) or the last round's final bot
  ["How do submissions work?"].
- Never choose between two variants by portal score when within `T`.
- Commit every 30 min at least, failed experiments too; no squash, rebase or force-push: they read it ["Known so far"].
- One evaluation at a time, and an upload that completes becomes final: time the first evaluation, and mark the
  chosen one final again after any exploratory upload ["How do submissions work?"].
- Naps only in rounds 2 and 3, in a round that looks like the last, T+0:30 to T+4:00, off site (tell an
  organiser); while A sleeps, B uploads only from the written list ["The day: timeline and roles"].
- Before round 4: decide in writing how much risk to keep (the score: 0.8·z1 + z2 + z3 + 1.2·z4, a loss scored
  as 0); if rounds 2–3's private runs strayed from our backtests, a bot that sends nothing is on the list
  ["How is PnL scored?"].
