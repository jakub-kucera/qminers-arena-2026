# Kickoff prompts

Paste one of these into a fresh agent session, started in the repository's root, at the start of a round. Fill in the `<angle brackets>` and delete any line that doesn't apply. Unzip the round's download into `data/arena/round<N>/` first (`data/` is gitignored), and save the Technical Rules or assignment text there as well, as `rules.md` or the PDF as given. Download the data as soon as the round opens: the link is only on the current round's card. Fill the deadline and the limits in from the dashboard ("Submissions used x / y", the file-size cap), not from the schedule: the submission deadline can come before the round's end.

The agent reads `CLAUDE.md` by itself, so the prompt only says what `CLAUDE.md` can't: which round this is, what the agent has, when it must be done, and what it must not do alone. Each person on the team pastes it with their own track.

## Round 1

```text
This is the Qminers Algo Trade Arena, round 1 of 4, for real. Submissions close at <HH:MM> (the dashboard's deadline; the round itself ends at <HH:MM>). Run `date` now and keep track of the time yourself.

What you have:
- The round's public data: data/arena/round1/
- The organisers' assignment / Technical Rules: data/arena/round1/<rules file>  (or pasted below)
- Anything else they gave (example bot, API docs): <paths, or "nothing">
- The dashboard's limits: <y> public submissions this round, files up to <size>.

Your track: <all of it | Checklist | Probes | Data>, as in ON_THE_DAY.md, "Splitting the first hour". Teammates have the others: <who has what>.

Read first, in this order: the rules file in full; RUNBOOK.md (one page, the day's index: each line names the ON_THE_DAY.md section behind it); then only the ON_THE_DAY.md sections RUNBOOK names for your step, as each comes up (the whole file is about 36k tokens: don't read it in full; its "First hour" is step 1's list and "The format swap, step by step" the checklist for steps 2 and 3); ARCHITECTURE.md's paragraph "**Formats are plug-ins**" before the plug-in; references/wiki/concepts/reading-the-data-on-day-one.md before choosing any product's settings; and IDEAS.md's index (its first 150 lines: every row by line) to find the rows that fit. Everything in this repo was built on IMC Prosperity as a stand-in. Treat every Prosperity result (IDEAS.md, the template's PARAMS) as a prior to re-test on this data, never as a fact about this market: IDEAS.md's header says which of them failed on ABIDES, an agent market we didn't write, where the template's quotes lost and a linear fair paid.

Work in this order, and tell me when each step is done:
1. Rules and API. Answer every item of ON_THE_DAY.md's "First hour" that the rules settle, under the item and with its source. List what they leave open, and anything in them that contradicts how the repo assumes the market works (matching, limits, scoring, the bot's interface, the runtime limits, what is allowed). If the round has a single product, say so: then its whole score rides on that market, and it gets every probe and the whole of diagnose's reading. Put the list at the top of data/arena/round1/HANDOVER.md (a copy of docs/HANDOVER_TEMPLATE.md; committed, so the team shares it) and show it to me; while I read it, go on with step 2, but write no bot code until I've answered.
2. The format plug-in: fill in python/arena/formats/qminers.py (already registered as --format qminers, a skeleton marked TODO(day)), following ON_THE_DAY.md's "The format swap, step by step", then on the data: arena.diagnose --suggest and experiments.day.structure. Once step 3's bot runs, experiments.day.premise (per product: Prosperity-like, mixed or agent-like, and the grids to run; it takes the bot, and runs on the Python engine until its Rust twin exists). Show me premise's table before any tuning: if a product is agent-like (two or three of its signs), don't trust a Prosperity prior for it until a grid on this data backs it; a mixed product (one sign) keeps the priors, and its pick is checked against a bot that sends nothing.
3. Our bot: python/bots/qminers/template.py, prepared (PARAMS empty, its seven ADAPTER functions raising until written; the drill's bodies beside them): rewrite only its imports, PARAMS and ADAPTER, as python/bots/drill/template.py was. Every product in the data gets a PARAMS entry, starting from diagnose --suggest's (on a large-tick book that pays, make_edge 0.5; where no side pays, make_size 0).
4. arena.validate on it, under the fill mode and mark the rules state (or both fill modes they make plausible, if they leave it open), with --time-limit-ms at their limit and --max-size at the dashboard's cap (over the cap: arena.compact, then validate the copy). By <T+2h, HH:MM> I want a validated bot I can upload. That comes before any tuning.
   Once its evaluation completes: save the submission's metrics (the page's API response) as JSON and its results ZIP, and run experiments.day.calibrate on the same file and data (--portal, --results, the ZIP's names mapped first as the swap's step 11 says; --vary fee=... if the rules leave it open; delay 0 and 1 are tried anyway). If it prints RESTING and ENGINE (its worst figure within 5%), put them into the plug-in, so every backtest and grid after that uses it, and tell me which settings it couldn't tell apart. If it refuses, don't paste anything: tell me the cause it names (a scale to re-run with, or our wrapper doing something their exchange doesn't) and keep the plug-in's settings with the grid's --modes widened (ON_THE_DAY.md, "How is PnL scored?"). Also note how long the evaluation took: call it E.
5. Then improve it, in the improvement loop once I start it (KICKOFF_PROMPT.md, "The improvement loop": one pre-registered experiment an iteration, a board of candidates that differ in kind, each checked by a fresh verifier). Its queue starts from these: the grid's pick under --modes all,worse until the rules or the playground settle the fill mode, then --modes <that>,worse,none --gate first --holdout last (ON_THE_DAY.md, "Which modes gate the grid's pick?": re-decide it if the official rules fit another option better), arena.stress, the stop losses (converted to each product's ticks), and for each product the settings its diagnose notes point to in the day-one table (e.g. "mid and wall mid both noisy": grid smoothing against fair mid and weighted_mid) and the IDEAS.md rows that fit it. On an agent-like product, the benchmark is a bot that sends nothing, and the grids are premise's: the linear fair (lin_rho3, lin_momentum) where its forecast fires, and the move gate (gate_move). If the trades carry no names, experiments.day.informed may find an informed size class for copy_sizes. Each change must beat the bot before it on held-out days, not only in-sample. If the rules make the total a weighted sum of raw PnL, round 1 runs for expected PnL instead (ON_THE_DAY.md, "How is PnL scored?"): ask me first.
6. At <30 min before the deadline, HH:MM>, or earlier if 2E is longer than 30 minutes: stop changing strategy. Run validate on the final candidate and give me the file to upload.

Rules for you:
- A variant that games the exchange or other teams rather than trading (spoofing, moving the mark, an exchange bug) may be built and tested, but its file sets GRAY_AREA = "<what it does>" at module level, so arena.validate fails it, and you tell me each time one exists, what it gains and that it is not for upload (ON_THE_DAY.md, "Gray-area variants").
- I upload. Never upload, and never spend a submission. Before each upload, tell me what the bot is, its local result, and the PnL and metrics it should show, so that the portal's figures can be checked against it (ON_THE_DAY.md, "Spend the round's submissions by a rule written before the first score").
- How uploads work, from the site's code (ON_THE_DAY.md, "Known so far"): one evaluation at a time, so each upload blocks the next until it has run; a new upload becomes final only once it completes (the round's first one at once); a failed one leaves the final as it was and shows a note, probably the error, which you read before we spend another; an exploratory upload that completes replaces the final, so afterwards I mark the chosen one final again. Plan the last upload to start at least 2E before the deadline.
- The bot must be one self-contained .py file: standard library only (unless the rules allow more), deterministic, with its state kept the way the rules say the engine keeps it.
- Ask me before doing anything the rules may forbid, any web search beyond the organisers' own pages, ON_THE_DAY.md's "Is the data a real series in disguise?" search (it needs my approval and a budget), or a run expected to take over 10 minutes.
- --engine rust only works for bots with a Rust twin. The Arena's template gets one by config, with no Rust code, if its ADAPTER follows the drill's conventions: a row in rust/twins.json and `experiments.rust_bench --twin` (ON_THE_DAY.md, "The format swap, step by step", step 10). Do it once grids are what is slowing us down; if the check shows differences, grid in Python and tell me.
- Write what you learn where CLAUDE.md says (ON_THE_DAY.md, IDEAS.md, TODO.md), and commit each step that works. Nothing stays only in the chat.
- Every hour, or when you are blocked, give me five lines: done, in progress, the bot's current local PnL, what you need from me, and the next step.
```

## Rounds 2 to 4

```text
This is the Qminers Algo Trade Arena, round <N> of 4 (weight <20|30|40>%, if the rules confirm the weights). Submissions close at <HH:MM> (the dashboard's deadline; the round itself ends at <HH:MM>). Run `date` now and keep track of the time yourself.

What you have:
- This round's public data: data/arena/round<N>/; earlier rounds' data: data/arena/round<1..N-1>/
- This round's rules or announcement: <path, or pasted below>
- The dashboard's limits: <y> public submissions this round, files up to <size>. Last round's evaluation took <E> minutes.
- Our final bot from round <N-1>: python/bots/<file>.py. Its portal score: <score>, our local prediction was <number>. Leaderboard: <our place, the top scores, anything visible about other teams>. Its private run: <PnL> against its public run's <PnL>; the leaderboard curves' verdict (experiments.day.leaderboard_curves --read): <verdict>. The handover note: data/arena/round<N-1>/HANDOVER.md.
- What we learned last round: ON_THE_DAY.md (the answers written in), IDEAS.md's Arena rows, and git log since the round started.

Your track: <...>. Teammates have <...>.

Work in this order:
1. What changed. Compare this round's rules, products, limits and data with round <N-1>'s: new products, removed ones, changed limits, fees, matching, scoring, news or other new inputs. Go through references/wiki/concepts/harder-rounds.md and say which mechanisms this round shows. Show me this list; while I read it, go on with step 2, but change no bot code until I've answered.
2. Does last round's bot still run? Run validate on the new data (with --max-size at this round's cap), and backtest it on the new days with last round's --mark and --limit-penalty. Fit those two again from this round's first upload's metrics: scoring can change between rounds. That is the baseline, and an upload candidate as soon as it passes. Run experiments.day.premise on the new days too: a harder round may turn a Prosperity-like product agent-like.
3. Changes, in this order: the format plug-in and ADAPTER for anything new in the API; then PARAMS for the new products; then the old products' settings, gridded again on this round's data rather than kept from last round (diagnose both). The rounds get harder by design, so last round's choices (strategy, modes, settings, fill model) are a baseline to beat, not a default: by <T+1h, HH:MM>, put at least one alternative against last round's approach, the one this round's diagnose notes point to, and say which of last round's choices you kept without testing. Check that a day isn't repeated from an earlier round before treating it as held out (the grid's repeated-day check).
4. By <T+2h, HH:MM>: a validated bot at least as good as the baseline on this round's data. After its upload, the improvement loop (KICKOFF_PROMPT.md, "The improvement loop"), with this round's CANDIDATES.md; step 3's alternatives go on its board.
   Round 4 only: before choosing how much risk to keep, run experiments.day.standings on rounds 1-3's leaderboards, with and without --growth-from (the round's scale from a proxy field on round 3's data and this round's; it helps under one scoring only until the rules give it), and each candidate's own backtests as --ours (ON_THE_DAY.md, "How is PnL scored?").
5. At <30 min before the deadline, or 2E if longer, HH:MM>: stop changing strategy, run validate, and give me the file.

The rules from round 1 still hold: I upload; one self-contained, deterministic file under the size cap; one evaluation at a time, so the last upload starts at least 2E before the deadline; ask before anything the rules may forbid, any outside data search, or a long run; write what you learn into the repo and commit each step; a five-line status every hour. This round is worth <weight>%, so <"protect what we have: prefer the grid's worst day over its best PnL" | "we need to catch up: say what it would take">.
```

## The improvement loop

From the first completed upload (about T+2:00) to the freeze, the session works in iterations: one experiment each, measured the same way, checked by a verifier that didn't build it, and recorded in a state file. The point is not the highest local PnL but a small board of verified candidates that differ in kind, each with its pluses and minuses measured, and a final choice made by a rule written before the scores came in.

- **Start it:** in the same session, after the round prompt's validated bot is uploaded and calibrated, ask the agent to copy `docs/CANDIDATES_TEMPLATE.md` to `data/arena/round<N>/CANDIDATES.md` and fill in its "Round" from `HANDOVER.md`. Check the "Round" section yourself, especially the held-out days and the final rule. Then type the line below. `/loop` without an interval paces itself: each firing is one iteration, and long runs wake it when they finish.
- **Without `/loop`:** paste the loop block once and add "Repeat the iteration until the freeze."
- **The verifier** is a fresh subagent that the loop starts itself, with the brief below. A teammate's session on the other laptop can take the brief instead.

```text
/loop Round <N>'s improvement loop: do one iteration as KICKOFF_PROMPT.md's "The improvement loop" says, from data/arena/round<N>/CANDIDATES.md.
```

The loop's instructions, read at every iteration:

```text
One iteration of the improvement loop. Your goal is a board of verified candidates that differ in kind, each with measured pluses and minuses, and a final choice by the rule in CANDIDATES.md's "Round", not the highest local PnL.

1. Orient. Run `date`. Read data/arena/round<N>/CANDIDATES.md in full, and HANDOVER.md's "Portal against local" and "Fill model and mark". Past the freeze: go to step 8. If the last iteration's run has finished, record it (steps 5 to 7) before starting another.

2. Choose one experiment: the top of "Queue". Keep the queue filled from, in this order: what the first upload's calibration and the portal's figures showed; each product's diagnose notes against the day-one table (references/wiki/concepts/reading-the-data-on-day-one.md); premise's grids for agent-like and mixed products; the IDEAS.md rows that fit (its index, the first 150 lines; each row says what to re-test on the day); the ON_THE_DAY.md items the probes have answered. The board must hold candidates that differ in kind, not six neighbours of one setting. By the middle of the loop it has:
   - A0, the baseline: the first upload, as uploaded;
   - a robust candidate: the grid's `pick` under the gate (it holds under the fill models still possible, at a lower PnL);
   - an expected-PnL candidate: the best pnl cell that beats A0 under every gate mode (more variance; the right one when raw PnL is summed: ON_THE_DAY.md, "How is PnL scored?");
   - a structural alternative: another fair, signal or treatment the notes point to (the linear fair or gate_move on an agent-like product, a level or jump bet, a basket's spread), or on an agent-like product a bot that sends nothing for it;
   - a defensive candidate: a good one with smaller quotes (make_size), stop losses at about 3x its plain drawdown, and flatten_from if the close is valued badly.
   Never more than six live candidates: each one is a trial the final comparison pays for. Drop the weakest, with the reason, into "Dropped" before adding a seventh.

3. Pre-register, before running anything: write into the queue item the mechanism (why it should work in this market, in one line, from a pattern in this data, not "the grid may find something"), the exact command, the training days, and the rule that keeps it. The default rule: it beats its parent on the held-out data under every gate mode, by more than T if it would replace an upload, and arena.stress's worst perturbation is not more than 10% worse than its parent's. A rule written after the result doesn't count.

4. Run it, choosing on training days only:
   - settings: arena.grid with the gate in "Round" and the scenarios still possible, at the steps in ON_THE_DAY.md's "Which modes gate the grid's pick?". Take the summary's `pick`, not the best cell. If the axis-end note fires, widen that axis once; the `finer around` line is one second pass at most;
   - a pattern bet (a level, jumps, a trend, a signal): also --permute 19 on its grid, and keep it only if p for the lift is at most 0.1;
   - past 100k cells: --search tpe --budget 1000. A run expected to take over 10 minutes: ask me in the status line first, and take the next queue item meanwhile;
   - a product the template doesn't fit: a new STRATEGY function behind a setting that defaults off, never a change to the ADAPTER.
   Each candidate is its own file, python/bots/qminers/candidates/r<N>_<id>_<name>.py: the template with only PARAMS (or a gated STRATEGY addition) changed, and a comment at its top naming its parent, what changed, and the commands that chose it.

5. Measure it, the same way as every other candidate, and fill its board row; each number comes from a command written into "Trials":
   - `uv run python -m arena.compare <A0's file> DAYS --format qminers --data D --bot <every live candidate> --modes <the gate's modes> [the scenarios]`: PnL per mode, the worst day, each day held out, and PBO, the DSR, SPA and StepM's pick over the whole board (the board is the selection, so re-run it with every candidate, not just the new one);
   - `uv run python -m arena.stress <file> DAYS --format qminers --data D`: the worst perturbation;
   - `uv run python -m arena.backtest <file> DAYS --format qminers --data D --metrics` under the calibrated settings: the max drawdown, the |position| quantiles, and the figures the portal will show;
   - `uv run python -m arena.validate <file> DAYS --format qminers --data D --time-limit-ms <theirs> --max-size <cap>`.
   Write the pluses and minuses as measured facts ("+8% held out under worse; -30% under the trend perturbation"), and what it relies on (a fill mode, a pattern, the mark, the limit).

6. Verify it independently. A candidate counts as verified only on a fresh verifier's PASS, never on your own reading. Commit, then start one subagent (the Agent tool, a fresh general-purpose agent) with KICKOFF_PROMPT.md's "Verifier brief", the candidate's file path, its board row and its "Trials" lines, and nothing else from this conversation. Paste its report verbatim into "Verifier verdicts", and PASS or FAIL into the row. A FAIL is fixed in a new file and verified again, or the candidate is dropped.

7. Close the iteration. Run `git status` first, so a teammate's changes aren't swept in, then commit CANDIDATES.md and the candidate files in one commit. Give me five lines: done; in progress; the best verified candidate and its held-out PnL; what you need from me; next. If the spending rule says an upload is due (ON_THE_DAY.md, "Spend the round's submissions by a rule written before the first score"), name the candidate and the figures it should show: I upload. If the last two iterations kept nothing, stop searching, and spend the next ones on the board's robustness (stress, the scenarios still possible, smaller sizes).

8. At the freeze: no new experiments. Re-run step 5's compare over the verified candidates and choose by "Round"'s final rule; if it needs me (round 1 under a raw-PnL total), ask. Validate the choice, give me its file and the figures it should show, write HANDOVER.md's "Next round", and stop the loop.

The round prompt's rules still hold: I upload; ask before anything the rules may forbid, any outside data, or a run over 10 minutes; one self-contained deterministic file; gray-area variants marked. Never choose with the held-out days, and never tune to a portal score: a portal score decides only through the spending rule. Never edit A0's file or a verified candidate; make a new one.
```

### Verifier brief

```text
You are verifying one candidate bot for a trading competition. You didn't build it: your job is to find reasons it should not be uploaded. Work in the repository's root; CLAUDE.md describes the tools. You have the candidate's file, its row on the candidate board (data/arena/round<N>/CANDIDATES.md) and the "Trials" lines that produced its numbers. Edit no file. Report one line per check, then a verdict:
1. Reproduce: the file is committed unchanged (`git status`); re-run the row's arena.compare and arena.validate commands and check its numbers within 1%. arena.validate also replays a day again for determinism, other hash seeds and a reload every tick: it must PASS.
2. What changed: diff the file against its parent (named in its top comment). Every difference is one the row declares; no GRAY_AREA, no file, network or clock access, no unseeded randomness.
3. No leak: its settings were chosen on training days only (the Trials commands set --holdout, or leave the held-out days out), no held-out day repeats a training day (experiments.day.structure's repeats), and no number in its PARAMS comes from the held-out days.
4. Robustness: it beats its parent on the held-out data under every gate mode, and arena.stress's worst perturbation is not more than 10% worse than its parent's (or the row says why that is accepted). For a pattern bet, its Trials line shows --permute's p for the lift at most 0.1.
5. The claim: the row's pluses and minuses match what the numbers show; name any that overstate.
Last line: PASS, or FAIL and the one thing to fix first.
```

## Without the repository

For a second, independent attempt: an agent that sees only what the organisers hand out, so it isn't steered (or swamped) by this repo's Prosperity tooling. It is also a check on our own bot: if the clean-room bot beats it, find out why before uploading ours.

- **Start it outside the repo.** Make an empty folder (e.g. `~/arena-clean/round<N>/`), copy in the round's data, the rules and any example bot, and start the agent session there. A session started inside this repo reads `CLAUDE.md` and is no longer clean.
- **No memory or custom instructions** that mention this repo or Prosperity: a fresh account or project, or memory off.
- **The "Priors" block is optional.** It is what our Prosperity prep found, in a few lines and with no code. Keep it for a stronger attempt; delete it for a fully clean-room one.

```text
You are helping our team in a 24-hour algorithmic trading hackathon (the Qminers Algo Trade Arena). It has four rounds of 5 hours; at the end of each, a team uploads one Python bot file, which the organisers run on a simulated limit-order-book exchange. This is round <N> of 4, worth <10|20|30|40>% of the total if the rules confirm the weights. Submissions close at <HH:MM>; run `date` now and keep track of the time yourself.

Everything you have is in this folder:
- the organisers' assignment and Technical Rules: <file, or pasted below>
- the round's public data: <folder>
- <an example bot / API docs / nothing else>
- the portal's limits: <y> uploads this round, files up to <size>
Use nothing else: no web search, no other folders, unless I say so.

The deliverable is one self-contained .py file that follows the rules' bot interface exactly: standard library only unless the rules allow more, deterministic (seed any randomness, never read the clock), keeping state between calls only in the way the rules say the exchange keeps it, and inside every runtime limit.

Work in this order, and tell me when each step is done:
1. Read the rules in full. Write rules_summary.md: the bot's interface (what it is called with, what it returns, how often), order types and how they match and expire, position limits and what happens on a breach, fees, scoring (what open positions are marked to, whether they are liquidated at the end), runtime and memory limits, allowed libraries, and the submission rules. List what the rules leave open or ambiguous. If there is only one product, say so: the whole score rides on it. If the rules name another round than this prompt, theirs is right. Show me this; while I read it, go on with step 2, but write no bot code until I've answered.
2. Look at the data. Per product: price units and tick size, the spread and the book's depth, how the mid behaves (does it return to a level, trend, or jump, and do jumps reverse), how often market trades print and at which prices, whether products are related (baskets, options, a common factor), and whether trades name counterparties. Check whether any day repeats another. Write it into data_notes.md with the numbers.
3. A local backtester (backtest.py) that replays the data through the bot's exact interface, enforcing the limits and the breach rule as the rules state them. Implement the fill rule the rules state as the default. Make every matching rule they leave open a switch, with the expected portal figure under each: the passive-fill rule (optimistic: a trade at our price fills us; conservative: only a trade through our price, or a book that crosses us), and whether volume we take stays gone on later snapshots (in a dry run that one moved the score by a quarter). Report PnL per product and day, positions, fills, errors and the slowest call, and the figures the rules say the portal shows on each submission (if they don't say: filled orders, traded volume, end position, cash, the price the end position is valued at, any position-limit penalty). If the rules don't state the price the end position is valued at, make it a switch too (the mid, the touch: best bid for a long position and best ask for a short, or the last trade) until the first upload's figures show which one the portal uses. Test it on a few hand-made ticks before trusting it.
4. A simple, robust first bot: per product, a fair value that ignores small orders near the touch (e.g. the mid of the largest levels), take anything mispriced against it, quote passively around it, and push inventory back toward zero near the limit. Never send orders that could breach a limit. Catch exceptions per product so one product's error can't stop the others.
5. Validate it: every day runs with no errors, no breaches, deterministic across two runs, within the time limit, in the rules' fill rule and its switched alternatives, and the file is under the size cap. Run it on the Python version the rules name if this machine has it (`python3 --version`; else keep the bot to features that version has). By <T+2h, HH:MM> give me a file I can upload. That comes before any tuning.
6. Then improve, one change at a time. Tune on some days and check on days the tuning didn't see; prefer a setting whose neighbours also do well over the single best; distrust a gain that disappears under a switched alternative. Keep a log (changes.md): each change, its PnL per day under each, kept or dropped. When an hour of changes has added under 1%, stop tuning and spend the time on robustness: the bot on perturbed days (a trend, a shift, doubled volatility), and what it loses if a pattern it relies on stops.
7. At <30 min before the deadline, HH:MM>: stop changing strategy, re-run the validation, and give me the final file. Uploads are evaluated one at a time, each blocking the next, so I will tell you how long the first one took; leave at least twice that before the deadline.

Rules for you:
- I upload. Never upload or spend a submission. Plan the uploads: the first as soon as a bot validates (it checks the backtester), the last kept for the final candidate or a fix. Before each upload, tell me what the bot is and the PnL and figures you expect from the backtester, so that the portal's figures check the backtester. When an upload fails, I will paste you its error note.
- Ask before anything the rules may forbid, and before any run expected to take over 10 minutes.
- Every hour, or when you are blocked: five lines: done, in progress, the bot's current local PnL (both fill modes), what you need from me, the next step.

Priors from practice on similar exchanges (IMC Prosperity), to test on this data, not to trust:
- A backtest that fills passive orders on any trade at their price overstates passive profit, often by a third or more; whatever beats the market under the optimistic rule may lose under the conservative one.
- The mid of the largest book levels (the market maker's "wall") is a far quieter fair value than the plain mid, unless another team's large orders can become the largest level; then use the mid of levels above a size threshold.
- Quoting one tick inside the best price around a good fair value, plus taking clear mispricings, was the core of most profit; inventory skew cost money when holding inventory had no penalty.
- Products that return to a known level pay most when held at the full limit against moves away from it; products that jump and mostly snap back pay for holding against each jump, once the day shows jumps do reverse.
- Days are often reused across rounds; a repeated day is not a held-out test.
- If open positions are liquidated badly at the end, flatten in the last few percent of the day.
- All of the above held on IMC's generator, not on an agent market where some traders know where the price is going and others chase trends. Tell the two apart before trusting them: replay a day with its ticks shuffled into random order; if the bot makes far more on the shuffled day, the order of events (informed flow, momentum) is costing it, and its passive fills will lose. There, quoting lost in every setting tried, a bot that sent nothing beat it, and what paid was a fair value leaning on the recent trend and the book's depth imbalance, or not quoting into a move that had just happened.
- A loss stop per product (about 3 times its normal worst drawdown) limits the damage when a market behaves unlike its data. Build it from position and price, not from a tally of fills: an exchange that discards a failed call's state loses that call's fills from the tally, and the stop then fires on nothing. Where another guard already stands the product down (a gate on whether its pattern still holds), a stop can cost more than it saves.
```

For rounds 2–4, add this to the prompt above, after the list of files:

```text
This is not the first round. Also in this folder: our final bot from round <N-1> (<file>), its portal score (<score>) against what our backtester predicted (<number>), the leaderboard (<what it shows>), and last round's notes (rules_summary.md, data_notes.md, changes.md). Start with step 1 as a diff: what changed in the rules, products, limits and data since last round, and stop to show me. Then run last round's bot on the new data as the baseline and first upload candidate. The rounds get harder by design, so treat its choices as priors: test them again on this round's data, and try at least one other approach, rather than keeping what worked last round.
```
