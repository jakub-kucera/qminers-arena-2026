# Result manifests

- [round1_submission.json](round1_submission.json) identifies the frozen current
  round-1 source, exact native result, hashes and verification.
- [round1_624076.json](round1_624076.json) preserves its named archive evidence.
- [round1_claude_research.json](round1_claude_research.json) summarizes the 77 full
  and 121 screening comparisons after the supplied 595K model. These are
  sample-tuned results on already consumed data.
- Earlier `round1_*.json` files preserve earlier checkpoints and provenance.
- `round2_historical_characterization.json`, produced by the preparation tool,
  compares the predeclared candidates on historical tapes. It is not a round-2
  result or selection. The report records source, dataset and engine hashes.

Raw replay curves, source snapshots and per-run logs live under `logs/` and
are ignored by Git. Compact provenance and promoted source files are tracked.
The actual next-round workflow writes its state under `logs/round2`; copy its
verified final report and frozen source to tracked round-2 paths when that
round has been evaluated. No such round-2 submission has been selected yet.
