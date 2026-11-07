# Runbook

**Start here.** This page is the day's index: each line names the `ON_THE_DAY.md` section behind it in
brackets; read only those, when the line comes up. Before the plug-in: `ARCHITECTURE.md`'s paragraph "**Formats are plug-ins**".
Before any product's PARAMS: `references/wiki/concepts/reading-the-data-on-day-one.md`. `KICKOFF_PROMPT.md` is
the prompt that starts an agent session (it points back here). `D` is `data/arena/round<N>/`,
`DAYS` its day specs (`all`), and `BOT` is `python/bots/qminers/template.py` (prepared, `--format qminers` registered).

## Before the doors open (Sat 08:00)
- `git pull && uv sync && uv run pytest` on every laptop; `references/` was cloned at home.
- `python3 references/check_arena_site.py`: a change goes into "Known so far"; offline, the snapshot stands.
- Names for A (driver, recorder) and B (data, research) ["The day: timeline and roles"].
- Every laptop on Europe/Prague time, logged in to the portal by the playground: e-mailed links are single-use
  ["Known so far"].

## Opening and workshop (09:00–10:30)
1. One person reads the Technical Rules in full and writes each answer into "First hour", with its source;
   what they leave open, ask at the workshop ["Questions for the organisers"].
2. Settle first: the entry point, the data format, whether orders rest, the limits, the Python version and
   allowed imports, the time limit, the submission cap, whether scores come back, how rounds combine ["First hour"].
3. If they hand out a module or SDK file, it goes into the plug-in unchanged, never retyped ["The format swap, step by step", step 4].
4. By 10:30, a fallback bot or not: an agent writes one only if the cap leaves an extra round-1 upload and the
   ADAPTER may not be validated by 13:00 ["Spend the round's submissions", "A fallback first?"].

## Playground (10:30–12:00): three tracks at once, B's loader first ["Splitting the first hour"]
- **Probes (A):** rewrite `python/bots/qminers/probe.py`'s ADAPTER, `PRODUCT` and `LIMIT`. Once B's loader runs, check it:
  `uv run python -m arena.backtest python/bots/qminers/probe.py all --format qminers --data D --print --no-strict`; then run it in
  the playground and read the `PROBE` lines ["Probes"]. If their rules forbid dynamic imports or sleeps, or uploads are scarce,
  delete its RISKY PROBES block first.
- **Data (B):** fill in `python/arena/formats/qminers.py` (registered) by the 13-step checklist ["The format swap, step by
  step"]; then run `uv run python -m arena.diagnose DAYS --format qminers --data D --profile --suggest` ["What kind of market is
  each product?"].
- **Bot (A):** in the prepared `python/bots/qminers/template.py`, rewrite only the imports, PARAMS and ADAPTER (the checklist's step 5). Then
  `uv run python -m arena.validate BOT DAYS --format qminers --data D --time-limit-ms <theirs> --max-size <the dashboard's> [--allow numpy]`.
  Over the cap: `uv run python -m arena.compact BOT <copy>.py`, then validate and upload the copy ["How do submissions work?"].

## Lunch (12:00–13:00)
- After the first upload: its metrics (JSON) and results ZIP into `uv run python -m experiments.day.calibrate --data D
  --days DAYS --format qminers --bot <that file> --portal metrics.json --results <zip>` (its names mapped, swap step 11);
  the `RESTING` and `ENGINE` it prints go into the plug-in; if it refuses (no fit within 5%), keep them and widen `--modes` ["Which backtest settings match the playground?", "How is PnL scored?"].
- Write round 1's candidates in order, with each one's local result ["Spend the round's submissions"].

## Each round (T = its start; rounds at 13:00, 19:00, 01:00, 07:00)
| When | Do |
|---|---|
| T+0:00 | Reload the dashboard; download the data (its link goes with the round) and the rules; note the submission deadline (it may come before the end). Write what changed into "Rule changes" and "Products". |
| T+0:15 | `arena.diagnose --suggest` and `experiments.day.structure` (repeats, sums, grids) on the new days; backtest last round's bot on them in each mode; `arena.validate` it: the first candidate. `uv run python -m experiments.day.premise --data D --days DAYS --format qminers --bot BOT` (`--engine rust` once the twin exists; round 1 before any prior; later, whether a product changed kind): per product Prosperity-like or agent-like, and the grids to run ["What kind of market is each product?"]. |
| T+0:30 | New products into PARAMS, by `references/wiki/concepts/reading-the-data-on-day-one.md`. Rounds 2–4: by T+1:00, one alternative to last round's approach against it, and every setting gridded again; last round's choices are priors, not defaults ["Choose the approach again each round"]. Options, baskets, named traders or jumps: the experiment for each (`python/experiments/README.md`). |
| T+1:00 | `uv run python -m arena.grid BOT DAYS --format qminers --data D --grid PARAMS.<P>.make_edge=0.5,1,1.5,2 --modes <closest>,worse [--screen 0.25]` while the fill mode is uncertain; once the rules or the playground's fills pin it, `--modes <that>,worse,none --gate first --holdout last` (`--holdout 25%` for one day of data); past ~100k cells, `--search tpe --budget 1000`. Change a setting only to the summary's `pick` (the last printed, with `--holdout`; round 1 under a raw-PnL total: the best `pnl` cell beating the bot as is ["How is PnL scored?"]) ["Evaluation data", "Which modes gate the grid's pick"]. Fill model unsure: add a `--scenario` for each one left possible ["Which backtest settings match the playground?"]. |
| T+1:30 | `uv run python -m arena.stress BOT DAYS --format qminers --data D`; set each `stop_loss` to about 3× its plain drawdown ["Stress the bot"]. If the market is shared: `--vs` copies, the round's zoo through `arena.compare`, and the rivals ["Is the market shared"]. |
| T+2:00 | A validated bot at least as good as the last one, uploaded; its portal score against our backtest is the engine's error `T`. Then `KICKOFF_PROMPT.md`'s improvement loop. |
| deadline − 0:30 | (T+4:30; earlier if 2× the first evaluation's time is longer.) Stop changing strategy. Validate the final candidate and upload it. |
| deadline − 0:10 | Check which submission is marked final. Write the handover note (`data/arena/round<N>/HANDOVER.md`, copied from `docs/HANDOVER_TEMPLATE.md`), then commit and push it. |
| After | After the private run: our PRIVATE entry's results against the public run of the same file; save the leaderboard's data to `data/arena/round<N>/leaderboard.json` and run `uv run python -m experiments.day.leaderboard_curves --read data/arena/round<N>/leaderboard.json --team <ours>`. Both into the handover note ["The day: timeline and roles", "Is the market shared"]. |

## Rules that hold all day
- Never upload code `arena.validate` hasn't passed, and never spend a submission on untested code. A `GRAY_AREA`
  bot fails it on purpose: never uploaded without an organiser's yes ["Gray-area variants"].
- A round's first upload is a bot that has already run in the playground (round 1) or the last round's final bot:
  `arena.validate` checks only against our copy of their API ["How do submissions work?"].
- Never choose between two variants by portal score when within `T`.
- One evaluation at a time, and an upload that completes becomes final: time the first evaluation, and mark the
  chosen one final again after any exploratory upload ["How do submissions work?"].
- Naps only in rounds 2 and 3, in a round that looks like the last, T+0:30 to T+4:00, off site (tell an
  organiser); while A sleeps, B uploads only from the written list ["The day: timeline and roles"].
- Before round 4: decide in writing how much risk to keep, and any relative hedge, from
  `uv run python -m experiments.day.standings --rounds data/arena/round{1,2,3}/leaderboard.json --team <ours> --ours <round 4's grid CSV> --growth-from data/arena/round3:<days> data/arena/round4:<days> --proxy-bots <the round's zoo> --format qminers`
  (our rank under each way the rounds may combine; the 10/20/30/40% are unconfirmed); if rounds 2–3's private runs
  strayed from our backtests, a bot that sends nothing is on the list ["How is PnL scored?"].
