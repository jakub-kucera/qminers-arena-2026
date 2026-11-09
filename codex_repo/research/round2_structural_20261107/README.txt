Round-2 structural development study

Goal: find a net-PnL solution reaching at least 100,000 on the new public tape,
with chronological validation and unchanged native scoring. No achievement yet.
First 60% is development; later public segments remain reserved.
Six frozen hypotheses compare robust labels, small-order replenishment, and
selective longer-horizon IOC trading. All use strict 100-lot reservations.
Smaller child orders retain the inherited eight-live-orders-per-side bound;
measure actual exposure and volume, not fill count alone.
User-reported Team 2 fill evidence is in docs/ROUND2_STRUCTURAL_IDEAS.md.
Baseline results reproduced the six upstream controls exactly.
Run: python -m scripts.round2_structural_batch
Working results: logs/round2_structural_batch/results.json
Sources and protocol were frozen before candidate outcomes were inspected.
