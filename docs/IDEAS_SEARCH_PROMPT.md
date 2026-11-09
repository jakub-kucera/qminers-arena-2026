# Prompt for an extra research session: new ideas for round 4 (8 Nov, 05:40)

Given to a separate LLM session alongside the main session's three research agents. The text below is what was pasted.

```text
You are a research session for the Qminers Algo Trade Arena, a live 24-hour hackathon. Round 4, the last, runs
07:00-12:00 on 8 Nov 2026 with a new tape; it is ~05:40 now. Repo: /Users/jakubkucera/Documents/qminers_arena.
Another session (the "main session") runs the bots and uploads. Your job: find NEW ideas that could beat our best bot,
test them fast, and hand back only what survives. Work in your own worktree and branch:
`git worktree add .claude/worktrees/ideas-search -b ideas-search main`, then work there.
Repo rules: CLAUDE.md (read it first: "Rust first", where results are filed). Commit as Jakub with NO Co-Authored-By
or any AI attribution; never squash, rebase or force-push. The main session may not be able to read your messages:
write findings to data/arena/research/ideas_handoff.txt (create it), each with its time and commit hash.

THE GAME (third_party/qminers-starter/README.md, ON_THE_DAY.md "Known so far")
One product, an order book replayed from a tape (the organisers' simulator in simulator/; our byte-identical Rust port
in rust/arena_sim). 5 ms order latency, FIFO matching, a position limit of 100 lots with a 10,000/s penalty above it
(a continuous integral), orders refused past 1,000. The position is marked at the end by walking the book. A bot is one
Python file (numpy/pandas/scipy/sklearn allowed), at most 15 minutes of server time. The tapes come from the organisers'
generator: a hidden latent price moved by sqrt-impact of market orders, calm and volatile regimes, jumps, resting orders
placed around the latent (docs/GENERATOR_PLAN.md).

OUR BEST BOT: R3-F5 (python/bots/qminers/candidates/round3/r3_F5_jump_bar.py), +888,195 on round 3's validation tape.
- An online ridge (39 features, Huber-weighted, infinite memory) forecasts the 400-ms mid move.
- Three of the features come from a hidden-Markov filter of the latent price (worth +150k on the server).
- A take is an IOC at the far touch for the room under the limit (flips are 200 lots). It fires when
  (forecast - skew) >= 0.25 + half the spread, or 0.15 for 5 s after a 3-tick jump, and only at a 1-tick spread.
- One-lot quotes run in slow markets.
- Its Rust twin is ridge_maker: `uv run python -c "import sys; sys.path.insert(0,'python'); from
  experiments.rounds.family_rust import F5; print(F5)"` prints the --set line (515,670 on data/arena/round3/round3_public.csv).
- Grid any knob in ~12 s a run: `uv run python -m arena.qsim_rust ridge_maker TAPE <F5 line> --grid K=a,b --holdout 0.25
  --threads 4`, or several tapes and bots at once with `uv run python -m experiments.rounds.family_rust TAPES...
  --bot NAME=F5:'--set ...' --jobs 4`.

WHERE F5'S MONEY GOES (round3_public, against the mid; IDEAS.md row "R3-F5's PnL against the mid")
- Position moves earn +746.6k.
- Takes pay -252.9k of spread on 500k lots.
- Reversals within 0.5 s cost -38k.
- 82% of PnL comes from 3 s before a jump to 10 s after.
- The losses are jumps against a full position.
- Every take bin earns.
- The 400-ms forecast is near saturation for the current inputs.

LESSONS (read IDEAS.md's index, the first 150 lines, and round 3's "Dropped here" in data/arena/round3/HANDOVER.md)
- Small local gains did NOT transfer. On round3_public, +3k to +20k became -20k to -70k on the server: a 250-ms
  horizon, a 150-ms ridge blend, the policy search's settings, a likelihood-chosen filter impact.
- Only structural gains transferred: the filter's new information, +150k.
- Offline R^2 gains did not become PnL three times: a pretrained MLP, the gap's extra weight, the blend.
- The synthetic tapes data/arena/gen/r3b/seed201-220.csv (12,000 s, the generator calibrated to round 3) called the
  server's direction in 3 of 4 tests.
- So every idea is judged on: round3_public in both halves; data/arena/round2/round2_public.csv;
  data/arena/round1/round1.csv (a calm tape); and at least 5 r3b seeds. It must be positive on round3_public and on
  the seeds' sum, with a gain of +3% or more, and must not trade far more lots than F5 (overtrading pays the spread).
- Already tried and lost or tied (do not repeat):
  - filter variants: regime mixture, ladder or big-order exclusion, a filter bank, impact x2, a placement mixture;
  - take sizing and timing: flip-to-flat, flip margins, early and wide-spread exits, the take gap;
  - over-limit bursts, including one triggered by the filter gap;
  - passive pre-entry; quote pulls;
  - a pretrained MLP or HGB; shorter or blended horizons; event-time labels; feature standardisation;
  - extra 100-ms / 1-s ridges as features; the bid/ask side ridges.
- Running right now in the main session (do not duplicate): a mixture-of-experts ridge per regime; a profit-gate
  model (predicts net-of-spread take PnL); an adaptive ensemble choosing among forecasters by paper PnL.

WHERE TO LOOK (ideas the record has not covered; pick by expected size, test the cheapest first)
1. New INFORMATION for the forecast, as the filter was. Candidates:
   - cancellation patterns (who cancels, at what distance, how fast after a trade);
   - order lifetimes and the order-id sequence (every insert increments one shared id);
   - round 3's ladder population as a feature rather than a filter exclusion;
   - queue depletion rates at the touch;
   - the IOC size distribution's tail;
   - the time since the last jump;
   - the depth profile beyond the touch.
   First measure: does it predict the 0.4-s / 1-s move beyond F5's forecast? Use the Rust prediction log
   (RIDGE_PRED_LOG / RIDGE_PRED_EXTRA, rust/README.md) and a held-out partial R^2. Then add it as a feature behind a
   knob and backtest.
2. JUMPS: 82% of PnL is near jumps and the losses are jumps against our position. Can a jump's DIRECTION be read
   earlier, from where new orders land, the latent filter's posterior, the first market orders after a jump, or the
   ladder population? The round-2 winner (Team 1) made 8x our PnL at single jumps (data/arena/round2/HANDOVER.md
   lines 182-190); that is still unexplained.
3. What the top teams do: in round 2 places 2-21 had our curve's shape with a higher slope (a better forecast, the
   same family). After 06:00, round 3's private leaderboard and curves may be published (data/arena/round3/; the
   tool experiments.rounds.leaderboard_curves). Read them for clues.
4. Anything else structural you find in the tapes (tape_book.py replays the book) or in the organisers' simulator rules
   that we have not exploited.

DELIVERABLES
- By 06:45: the first handoff entry. Each idea with its measurement, its Rust grid numbers on all the tapes above
  against F5, and a verdict (keep / drop). Every result also goes in an IDEAS.md row (date, data, command, numbers),
  with the index rebuilt (`uv run python -m experiments.ideas_index`) and `uv run pytest python/tests/test_docs.py`
  passing.
- From 07:00: round 4's tape will be at data/arena/round4/round4_public.csv. Re-run any surviving idea on it against F5
  (step 2 of data/arena/round4/HANDOVER.md gives F5's grid) and add the numbers to the handoff.
- New Rust knobs must be off by default, with F5 still 515670.00 byte for byte (run `uv run pytest
  python/tests/test_arena_rust.py`). Do not edit the candidate bots in python/bots/qminers/candidates/; if an idea
  passes, describe the Python change it needs and the main session writes the file.

RESOURCES: the machine has 14 cores shared with the main session's three agents. Use at most 4 processes at once and
check `uptime` before each batch (back off above a load average of 20). Keep large logs out of the repo.
```
