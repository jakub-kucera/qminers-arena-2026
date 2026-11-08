Synthetic tapes from experiments.day.tape_gen v2 (8 Nov), one per seed: seed<N>.csv, 12000 s each, the starter's CSV format.
The model: /Users/jakubkucera/Documents/qminers_arena/data/arena/gen/r3_params.json (tape_gen --fit of the round's public tape) with the latent options 'r3_public_after':
{"impact_sqrt": 0.047, "f_limit_latent": 1, "jx_rate_off": 0.0046, "jx_dwell_off": 600, "jx_dwell_on": 119.2, "jx_logsd": 0.85, "jx_warn_s": 2.47, "jx_rate_on": 0.3911, "jx_lead_min": 500, "jx_after_extra": 15.5, "jx_after_s": 0.2, "stale_s": 0.1907, "impact_delay": -0.2623, "impact_tau": 6.8, "jx_median": 3.0, "jx_warn_k": 1.0, "jx_on_k": 0.4, "jx_warn_sd": 0.8, "jx_false_rate": 0.05, "jx_diff_sd": 4.0}
Made by:
  uv run python -m experiments.day.gen_calibrate write --params /Users/jakubkucera/Documents/qminers_arena/data/arena/gen/r3_params.json --opts r3_public_after --seeds 201-220 --seconds 12000 --dir /Users/jakubkucera/Documents/qminers_arena/data/arena/gen/r3b --latent-seeds 201-203
seed<N>_latent.csv (for the --latent-seeds): the true latent mid every 10 ms (time, latent, the jump chain's state 0 calm / 1 volatile, the latent's own jumps in ticks since the previous row); the same draw as seed<N>.csv (tape_gen --latent-out).
The calibration: IDEAS.md, "Calibrating the generator to round 2's validation scoreboard"; gen_calibrate.PRESETS.
params.json here is the fitted model with those options merged in (tape_gen --params params.json --seed N --seconds S --out X.csv draws one more).
