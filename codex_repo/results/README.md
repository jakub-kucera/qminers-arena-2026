# Result manifests

`round2_submission.json` and immutable `round2_144580.json` identify the first
verified full-public checkpoint: 144,580.19 net, with exact organizer CLI match.
`round2_selection_v1.json` records six-candidate chronological selection;
`round2_volatility_attribution.json` checks actual exposure versus volatility.
There is no server/private result yet. All public segments are now consumed.

`round2_alternative_mechanisms.json` records24 later development cases with risk
sizing fixed or a separate fixed-size IOC policy. The queue-wait prototype's
full-public143,252.19 did not improve the checkpoint. `round2_pretrained_specs.json`
freezes four pretrained nonlinear-alpha candidates; first60% is fitting data,
so their full-public scores must not be mistaken for held-out results.

`round2_development_progress.json` records later first-60% tuning studies;
`round2_development_31840.json` preserves a positive inventory-policy checkpoint.
Neither is a selected submission or a later-public/server result.
`round2_transfer_attribution.json` is an exact native-verified decomposition
of the original transfer loss, with descriptive future fill markouts.

[round2_initial_investigation.json](round2_initial_investigation.json) is the
current public-data intake comparison and first-60% test evidence. It records
the new data hash, volatility/signal changes, all six reference results, four
controlled diagnostics, and the provisional deadline. It contains no server
validation or organizer private score.

`round1_reported_leaderboard.json` records the user's reported 602,526.53,
rank 8/61, with no source/dataset attribution. It must not be silently attached
to the 624,076 local replay. `round2_competition_protocol.json` records the
three-dataset announcement. `round2_server_results.json` is the separate server
feedback ledger; it is currently empty. Local public checks are not private scores.
`round1_reported_chart_analysis.json` records the later user-supplied curve
summary and qualified exposure proxies. Its scope is round 1; raw curves and
the user's private log have not been supplied here.

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
- [round2_preparation_checks.json](round2_preparation_checks.json) records the
  preparation checks, 66-test suite, 18 historical replays, exact native matches
  and preservation of the frozen round-1 source.

Raw replay curves, source snapshots and per-run logs live under `logs/` and
are ignored by Git. Compact provenance and promoted source files are tracked.
The actual next-round workflow writes its state under `logs/round2`; copy its
verified final report and frozen source to tracked round-2 paths when that
round has been evaluated. The first such checkpoint is now `round2_submission.json`, with a matching
standalone source and immutable `round2_144580.json` evidence.
