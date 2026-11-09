Qminers sample-v2 local research
7 November 2026

Open ../Qminers-local-testing.html from the repository's parent outputs folder.
The report covers 21 exploratory full-tape experiments and 5 deterministic
engine probes. All simulator source files remain unchanged. No portal upload,
remote push, sharing change or organizer communication was performed.

Data: data/sample_v2.csv, copied unchanged from the user's Downloads file.
SHA256 dd4e00e281abe50c9a19e16c147ccbc0b5b69835fee567f00136402ef1e01d08
Official simulator commit: 3f5bea730d5f341c6988b1fe2722998b66270ea0
Team reference commit: 6ca459e966bb1f9e767258ef5ae0ef0bce979c3f

The scripts run from the repository root with .venv/Scripts/python.exe.
run_study.py: official-engine replays, lifecycle counters, bounded data collection.
analyze_features.py: first-half-only Ridge fits, purged chronological metrics.
prepare_stress.py: fixed latency, size and cross-tape cases.
prepare_followup.py: matched-size comparisons and IOC threshold probe.
test_engine_probes.py: five deterministic integration tests.
export_candidates.py: single-file exports and conservative local source checks.
benchmark_export.py: unwrapped strategy replay and Windows process resources.
build_report.py: interactive HTML, plain text, comparison table and manifest.

Reference strategies are frozen local snapshots from the authorized team repo,
not a newly published repository. Results include every attempted strategy case,
including no-trade and losing variants. The first draft of the probe tests used
uppercase strings instead of the enum's lowercase serialized values; assertions
were corrected and all five tests then passed. The simulator was not changed.

Quarter statistics carry book state and inventory continuously. They are
diagnostics, not separate fresh starts. F2 was already tuned on the full v2 tape.
Ridge training uses only the first half; its full PnL includes that training half.
The third quarter is validation and the last is a reused diagnostic tail. No
private competition data was available. Final testing needs a new untouched tape.

Source-check success is local only. It is not proof of remote sandbox acceptance.
The official CLI writes minimal logs with --no-logs; remove that flag to produce
the full explorer logs, which can be large on a two-million-event dataset.
