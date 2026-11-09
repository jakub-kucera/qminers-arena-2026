# Prompt for the generator session: the filter's model (8 Nov, 04:10)

Given to the generator session (branch `gen-v3`) after its ladder pass. The text below is what was pasted.

```text
New job for the generator session, narrower than the last: measure, on the real tapes, the three parts of the
generator that our latent-price filter models, so the filter can be rebuilt on facts instead of guesses. Round 3
closes 06:00; round 4 starts 07:00 with a new public tape. Repo: /Users/jakubkucera/Documents/qminers_arena,
your branch gen-v3. Repo rules: CLAUDE.md. Commit as Jakub with no Co-Authored-By or AI attribution; never squash,
rebase or force-push. The main session cannot read your messages: write results to
data/arena/gen/gen_v3_handoff.txt as before.

WHY
The filter is our best edge: it is worth +149,769 on round 3's validation tape (R3-F3 +883,559 against the same bot
without it, R3-B1 +733,790). On your synthetic r3b tapes the TRUE latent's gap (latent - mid) predicts the mid's
0.4-s move at corr 0.76; the filter's estimate only at 0.40. So the filter's model of the generator is wrong
somewhere, and every variant built on guesses has lost on the real tape (IDEAS.md rows "A filter of the generator's
hidden fair price" and "A better state for R3-F3's latent-price filter"):
- a calm/volatile regime mixture explained the inserts much better (log-likelihood -1.093 vs -1.204) yet LOWERED
  the gap's correlation on round3_public (0.292 vs 0.304 in the first 75%);
- leaving out your labelled ladder orders: oracle +0.003 corr; leaving out big inserts by size: worse;
- the best impact scale differs by tape: x2 on round2_public (+22k there), x3 on round3_public.

THE FILTER (python/bots/qminers/candidates/r3_F3_latent_filter_b1.py lines 121-286; offline copy
python/experiments/filter/latent_filter.py, read its docstring; Rust twin rust/arena_sim/src/strategies/ridge_maker.rs,
knobs FILTER_* listed in rust/README.md). A probability vector over the latent reference bid lb on a grid of
bid-8..bid+8 ticks. Its whole model is three guesses:
1. PLACEMENT: a new resting order (G) is placed k ticks behind the latent touch (bids at lb-k, asks at lb+1+k) with
   P(k) = 0.55 / 0.39 / 0.06 for k = 0/1/2 (round 1's offsets); a buy at or above ask-1 (a sell at or below bid+1)
   is "clamped" and counts as k <= d; inserts more than 6 ticks (FILTER_DEPTH) from the touch are ignored;
   likelihood floor 0.01 (FILTER_EPS).
2. IMPACT: each market (IOC/F) order of q lots, as filled, shifts lb by FILTER_IMPACT x table(q) ticks its way
   (table = round 1's mean 5-s mid move by size, x3), or alternatively FILTER_SQRT_C * sqrt(q) (r1 0.024, r2 0.0365).
3. DRIFT: between events lb does a symmetric random walk of one-tick steps at FILTER_RATE = 2 steps a second each way.
The bot's features: gap = E[lb] + 0.5 - mid (clipped to +-5), gap*|gap|/3, and the posterior sd.

DELIVERABLES
A. For round3_public (and round2_public and round1 for comparison), how the generator actually does each part, with
   uncertainty:
   1. Placement: the distribution of a new G order's price relative to the latent, by side, regime, size and
      ladder/non-ladder; the clamp rule; and WHAT it is placed relative to (the latent touch, the latent mid, the
      previous visible touch, something else). If the reference is not what the filter assumes, that alone may
      explain the 0.40 vs 0.76.
   2. Impact: how a market order moves the latent: form (sqrt, linear, table), coefficient per tape, filled volume
      or order size, permanent or decaying.
   3. Drift: the latent's own motion between events: step rate and size per regime, and the jump process (rate,
      size law, and how a jump shows up in placement before the mid moves).
   The latent is hidden on real tapes, so estimate by maximum likelihood / EM with the filter as the E-step, or from
   structure you can see (placement against the contemporaneous touch, the clamp, ID sequences). FIRST validate the
   estimator on r3b seeds 201-203, where data/arena/gen/r3b/seed20N_latent.csv has the true latent: it must recover
   the generator's own settings there before its real-tape numbers mean anything.
B. The test that counts: put the estimates into latent_filter.py (its --set options) and report the gap's
   correlation with the mid's 0.4-s and 1-s move on round3_public, first 75% | last 25%, against the current
   filter's 0.3043 | 0.4053 (0.4 s) and 0.2656 | 0.3398 (1 s), plus the insert log-likelihood. A model that fits
   the inserts better but predicts worse (as the regime mixture did) is not the answer: say why it happens. If the
   filter needs a structural change its knobs cannot express (a different placement reference, a decaying
   impact), describe it exactly (equations and where in _lf_insert / _lf_trade / _lf_advance it goes); the main
   session implements it in the bot and in Rust. Do not edit the candidate bots or ridge_maker.rs yourself.
C. For round 4: an estimator that reads the first N minutes of a new public tape and writes the filter's settings,
   `uv run python -m experiments.day.<your_tool> TAPE --out settings.json`, as keys the Rust ridge_maker and
   latent_filter.py accept (FILTER_PI0-2, FILTER_RATE, FILTER_IMPACT or FILTER_SQRT_C, FILTER_DEPTH, FILTER_EPS, and
   any new ones from B). Under 5 minutes on a 6,000-s tape; say how many minutes of tape each setting needs.

TIMING: B by ~05:30 if you can (an upload is still possible before 06:00 only if the gain is large); C by 06:45.
Write each result into gen_v3_handoff.txt as soon as you have it, with the commit hash.
```
