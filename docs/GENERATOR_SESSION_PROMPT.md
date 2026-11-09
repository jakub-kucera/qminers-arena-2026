# The generator session's prompt (written 8 Nov, 02:20, during round 3)

The prompt the user pastes into a separate Claude Code session dedicated to reverse-engineering the Arena's tape
generator. The plan behind it is `docs/GENERATOR_PLAN.md`; the main round session keeps running round 3 meanwhile.

```text
You are a dedicated session for one job: reverse-engineer the tape generator of the Qminers Algo Trade Arena, a
24-hour hackathon running now. Round 3 runs 01:00-06:00 on 8 Nov 2026, round 4 runs 07:00-12:00. The repo is
/Users/jakubkucera/Documents/qminers_arena. Another Claude session (the "main session") runs the round's bots and
uploads; you own the generator. Work fast, commit often, report what you find to the main session.

GOAL
Recover the generator's model and its settings as exactly as the data allows: the model class, every component's
distribution, and the parameter values of each tape we have seen. The working assumption: the organisers wrote one
generator with a modest set of settable parameters (maybe round numbers), changed per round or per tape. If we
know the model and can estimate a new tape's parameters within minutes, we can generate as many look-alike tapes as
we want, choose bots on them, and pre-train on them. Every finding must be checked against real data, never only
against our own generator.

READ FIRST (in this order, skim the rest)
- CLAUDE.md (repo rules), then docs/GENERATOR_PLAN.md in full (Phase 1 findings, Phase 2, the risks).
- IDEAS.md rows (find them with grep): "The tape generator's structure", "Calibrating the generator to round 2's
  validation scoreboard", "A filter of the generator's hidden fair price", "Round 3's first look", "Burst sizing on
  R2-L9", "Round 3's tape: where money can be made".
- The tools' docstrings: python/experiments/tape/tape_book.py (the price-time book replay), tape_gen.py (generator v2
  and its options), gen_identify.py (Phase 1's measurements), gen_calibrate.py (presets r2_validation and
  r3_public_stats; draw / score / rank / fitstats / jumpflow / search / stats), latent_filter.py (the HMM filter of
  the latent price, with --latent for the true path), tape_character.py, tape_from_logs.py, family_rust.py, and
  python/arena/qsim_rust.py (the Rust simulator: about 10 s a tape a bot).
- third_party/qminers-starter/README.md: the tape format, the simulator's rules, the bot API.

THE DATA (absolute paths; data/ is gitignored and lives in the main checkout)
Real tapes (order by order: Time, Operation, OrderId, Side, Volume, Price, Lifespan G/F):
- data/arena/round1/round1.csv: round 1 public, 12,000 s, the calm regime.
- data/arena/round1/private_reconstructed.csv: round 1's private tape rebuilt from the private run's full logs
  (data/arena/round1/r1_C12_v6_private_res/ has book_deltas.csv, events.csv, trades.csv, pnl.csv: the private
  tape's book itself, as our bot saw it).
- data/arena/round2/round2_public.csv (6,000 s) and round2_public_mirror.csv.
- data/arena/round3/round3_public.csv (6,000 s).
- data/sample.csv and data/arena/playground/sample_v2.csv: the organisers' sample tapes. Use them for STRUCTURE only
  (other draws of the same code?); never to choose bots.
Server results on the hidden tapes (each a deterministic bot on one hidden tape; result.json, a 1-s pnl.csv,
metadata.json):
- Round 2 validation (12,000 s): every data/arena/round2/*_res/ folder, and the 14-bot scoreboard in
  data/arena/round2/CANDIDATES.md and HANDOVER.md, "Round 2 results, marked" (E2 -41k ... L9 +873,719). The bots
  are in python/bots/qminers/candidates/ (r2_*.py); the Rust twins and their --set lines are in rust/README.md and
  python/experiments/rounds/family_rust.py.
- Round 3 validation (12,000 s): data/arena/round3/r3_F1_latent_filter_res/ (+862,764) and
  r3_F3_latent_filter_b1_res/ (+883,559); more arrive as the user uploads (data/arena/round3/CANDIDATES.md,
  "Uploads").
- Round 1 and round 2 private (12,000 s): data/arena/round*/leaderboard.json (every team's private PnL), our private
  results in the round folders and HANDOVER.md files.
Our synthetic draws: data/arena/gen/r3b/ (20 draws with r3_public_after, the better fit: Spearman 0.60 on the six
r3 public scores, the filter's gain realistic, pure takers still ~7% too high; seed201-203 also have *_latent.csv,
the true latent path), data/arena/gen/r3/ (30 older draws with r3_public_stats, Spearman 0.31),
data/arena/gen/r2_params.json and r3_params.json. r3_public_after's structure: informed IOCs after each jump, jumps
of median 3 plus 4 ticks/sqrt(s) diffusion in the volatile state; it still needs about 3-4 informed 500+ lot IOCs a
jump against the tape's ~0.75, so its big-order move curve is 2x too strong.

WHAT IS KNOWN (Phase 1 and 2; verify, don't trust)
- A latent price; every aggressive (F) order moves it by c*sqrt(traded lots), deterministic and permanent; c 0.024
  (r1), about 0.03 calm / 0.05 volatile on r2 and r3.
- F orders are priced at the latent +-1 tick (not the touch), side a coin flip, sizes heavy-tailed (median 60, p99
  ~1,540, Hill 1.7, 1,831 distinct values); counts Poisson in the calm state, bursty in the volatile one.
- Limit (G) inserts land k ticks behind the latent touch (k 0/1/2: 55/39/6% on r1, wider in the volatile state),
  side a coin flip, ~180-196/s; lifetimes median 0.31-0.35 s; stale orders cancel faster (hazard 1.5-2.4x).
- Two hidden regimes (r1 calm only; r2 53%, r3 68% volatile). The volatile one has exogenous permanent jumps
  (3+ ticks: 313 on r2, 389 on r3 per 6,000 s), sign 50/50, clustered; the book widens about 2 s before a jump.
- The "informed IOCs before jumps" are an artefact: timed by the latent, they come after it moves.
OPEN DISCREPANCIES (the generator v2 gets these wrong; each is a clue)
- A jump-aware filter tracks the generator's latent much better (corr 0.40 -> 0.53 with the 0.4-s mid move) but
  gains nothing on the real r3 tape: the real volatile-state latent is not the generator's compound-Poisson jumps.
- The latent filter adds +13-16% PnL on the real r3 tape but only +6-7% on r3 draws.
- r3_public_stats overrates pure takers (L9, B1) against the L8 family; the r2 preset's PnL level is 0.75x the
  server's; E2's sign; mid changes 4.1-4.3/s against 4.85; about half the real jump count; too much 5-s move after
  big orders.

HOW TO WORK
1. Inventory and invariants (first 30 min). For each real tape and the samples, tabulate the raw fields:
   - OrderId: sequential? gaps? interleaving by order type? Do ID ranges or parity reveal the number of agents or
     processes?
   - Time: resolution, quantization, ties; inter-arrival laws per stream (exponential? thinned?).
   - Lifespan codes. Volume: G size law (discrete table? lognormal? Pareto with xmin?) and F size law. Price
     offsets.
   - Cancels: is each cancel scheduled at insert (lifetime independent of everything) or event-driven?
   - Are there exact repeats or round-number parameters across tapes?
   Any deterministic structure is gold.
2. Component by component, maximum likelihood where possible. For every stream, fit candidate laws and compare by
   likelihood/AIC on each tape; tabulate the parameters per tape with confidence intervals, and look for which ones
   are equal across tapes (fixed in the code) and which move (the settings).
3. The latent process in the volatile state. Test alternatives to compound-Poisson jumps: diffusion with stochastic
   volatility, Hawkes-driven F flow, a jump size law with many small jumps, a mean-reverting component, regime
   switching on a schedule vs Markov. Judge them by real-tape statistics (the return distribution by horizon
   0.1-300 s, variance ratios, the jump/diffusion split, the filter-correlation test above).
4. Reconstruct the hidden validation tapes from our uploads. Each bot is deterministic. A pure taker holds |position|
   100 most of the time (the |position| q50 is 100), so its 1-s PnL step is about inventory x mid change.
   - With several uploads on the same tape (round 2 has 14 on its validation tape, round 3 has two so far), solve
     for that tape's 1-s mid path: its volatility by segment, jumps, regime timeline and end price (the mark price
     is in result.json).
   - First prove the method locally: run a bot on a public tape (`uv run exchange-simulator --strategy BOT
     --backtest TAPE --log-dir DIR`), reconstruct the mid from its pnl.csv alone, compare with the truth.
   - Then fit the generator's parameters to the reconstructed validation paths. That's the closest data we have to
     the private tape.
5. Simulation-based inference for whatever has no likelihood. Use the method of simulated moments, ABC, or a
   random/Bayesian search with gen_calibrate, over a rich vector of statistics: the spread mix, mid changes/s, return
   sd and kurtosis by horizon, the impact curve, the jump counts, insert offsets by regime, lifetimes, F burstiness.
   Plus the bot scoreboards: the 14 round-2 validation scores, round 3's uploads and round 3's six public scores,
   matched in order AND level AND per-1,000-s PnL path.
6. Generator v3. Make every component a named, settable parameter of tape_gen (keep v2's options working and
   byte-identical). Commit a parameter table for every tape we have (r1 public, r1 private, r2 public, r2
   validation, r3 public, r3 validation) and presets named after them.
7. The round-4 playbook, the deliverable that matters most after round 3:
   - a single command that, given a new public tape, estimates every parameter in under 10 minutes and writes N
     synthetic tapes plus a one-page report (regime shares, jump law, impact, how it differs from earlier rounds);
   - an online version of the regime/parameter estimate a bot could use in its first minutes.

PRIORITIES AND TIMES
- by 03:30: steps 1-2 and the step-4 method proven locally. Send the main session an interim.
- by 05:00: a round-3 preset better than r3_public_stats. It must rank R2-L8 / R2-L3 / R2-L9 / R3-B1 / L8+FILTER /
  B1+FILTER like the real r3 public tape (427,819 / 425,321 / 424,730 / 433,922 / 484,057 / 505,212) and the r3
  uploads like validation. Write 20 draws to data/arena/gen/r3c/, with a README of the exact command.
- by 06:45: the round-4 playbook (step 7), tested on r2 and r3 as if each were new.
- at 07:00 (round 4 opens): run the playbook on round 4's public tape the moment the user provides it.

RULES (binding)
- Git: work in your own worktree and branch, never in the main checkout:
  `git -C /Users/jakubkucera/Documents/qminers_arena worktree add .claude/worktrees/gen-v3 -b gen-v3` (then work
  there; data paths stay absolute into the main checkout).
  - Commit as the repo's git user (Jakub), with NO Co-Authored-By or any Claude attribution in messages. Commit at
    least every 30 minutes, failed experiments too, with a note. Never squash, rebase or force-push: the organisers
    read the history.
  - The main session merges your branch; tell it the hash.
  - The main session's calibration agent makes one last commit to tape_gen.py / gen_calibrate.py on branch
    worktree-agent-aa9de7b287c6d051d; `git merge main` before editing those files, then they are yours.
- Docs: each finding gets an IDEAS.md row (date, data, command, numbers; failures marked `dropped here`), then
  `uv run python -m experiments.ideas_index`. Each new script gets a python/experiments/README.md row; the
  generator's state goes in docs/GENERATOR_PLAN.md. Run `uv run pytest python/tests/test_docs.py -q` before each
  commit.
- Code: standard library plus numpy (scipy if needed) in python/experiments/day/; results must reproduce from the
  repo (no scratchpad paths in IDEAS commands). Don't edit bots in python/bots/qminers/candidates/, the round
  folders' CANDIDATES.md / HANDOVER.md (append-only), or rust/arena_sim/src/strategies/ridge_maker.rs (the main
  session's). Use the Rust simulator to run bots (arena.qsim_rust, family_rust): about 10 s a tape.
- CPU: 14 cores shared with the main session and its agents. Use at most 5 processes or threads in total, including
  any subagents you start (at most 2 subagents). Check `uptime` before starting a batch; back off above load 20.
- NEVER open ~/Documents/qminers_mock_round_2/ (neither private/ nor public/). The Arena site: no API calls, no
  guessed URLs; only what the user shows you. The user uploads; you never upload. The references/ clones are
  read-only.
- Report to the main session with SendMessage to "restructure-repo-docs-for-day": an interim at 03:30, a message
  whenever a preset or tapes are ready (with the paths), and a final report. Be honest about what does not fit.
```
