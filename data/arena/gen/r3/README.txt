Synthetic tapes from experiments.day.tape_gen v2 (8 Nov), one per seed: seed<N>.csv, 12000 s each, the starter's CSV format.
The model: /Users/jakubkucera/Documents/qminers_arena/data/arena/gen/r3_params.json (tape_gen --fit of the round's public tape) with the latent options 'r3_public_stats':
{"impact_sqrt": 0.0528, "f_limit_latent": 1, "jx_rate_off": 0.0046, "jx_dwell_off": 597.9, "jx_dwell_on": 142.9, "jx_median": 6.66, "jx_logsd": 0.79, "jx_warn_s": 2.47, "jx_warn_k": 1.15, "jx_lead_s": 0.5, "jx_lead_min": 500, "jx_rate_on": 0.4, "jx_lead_extra": 2.0, "stale_s": 0.216, "impact_delay": -0.22, "impact_tau": 6.8}
Made by:
  uv run python -m experiments.day.gen_calibrate write --params /Users/jakubkucera/Documents/qminers_arena/data/arena/gen/r3_params.json --opts r3_public_stats --seeds 101-130 --seconds 12000 --dir /Users/jakubkucera/Documents/qminers_arena/data/arena/gen/r3 --latent-seeds 101-103
seed<N>_latent.csv (for the --latent-seeds): the true latent mid every 10 ms (time, latent, the jump chain's state 0 calm / 1 volatile, the latent's own jumps in ticks since the previous row); the same draw as seed<N>.csv (tape_gen --latent-out).
The calibration: IDEAS.md, "Calibrating the generator to round 2's validation scoreboard"; gen_calibrate.PRESETS.
params.json here is the fitted model with those options merged in (tape_gen --params params.json --seed N --seconds S --out X.csv draws one more).
