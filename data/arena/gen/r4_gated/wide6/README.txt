Experimental round-4 stress model: wide6, source e4de870 on gen-v3.
Calibration seed501; fresh checks511-513. Each tape6000s with true latent and generation provenance.
NOT a qualified strategy-selection or pretraining target: fresh F3 PnL15.64% high; quote gains far too small and change sign across seeds; small-F markouts too weak.
See docs/GENERATOR_ROUND4.json for exact settings and all evidence; docs/GENERATOR_PLAN.md and data/arena/gen/gen_v3_handoff.txt for interpretation.
Reproduce from the main checkout after merging gen-v3:
uv run python -m experiments.day.gen_round_fit data/arena/round4/round4_public.csv --params data/arena/gen/r4_params.json --dir data/arena/gen/r4_gated --cases docs/GENERATOR_ROUND4.json --select wide6 --seeds 511-513 --score --latent --family data/arena/round4/family_rust.txt --binary rust/target/release/arena-sim --out data/arena/gen/r4_gated/fresh_wide6.json
Use a new output directory if generator-source provenance differs; do not bypass verification. Use new seed numbers for more stress draws; omit --score to skip the six-bot replay.
