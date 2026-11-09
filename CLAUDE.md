# CLAUDE.md

Team ThatsMyQuant's record of the Qminers Algo Trade Arena (7-8 Nov 2026): four rounds, a Python bot submitted each
round, scored on a private tape. The event is over; this repository is the record, not live development.

- `README.md` is the front page; `RESULTS.md` the standings, each round's final bot and every upload;
  `docs/postmortem.md` what the market turned out to be; `docs/decisions.md` Jakub's calls during the event, from his
  prompts.
- Bots: `python/bots/qminers/candidates/round<N>/` (indexed in its README, the finals in bold); the engine and tools:
  `python/arena/` and `python/experiments/<theme>/` (rounds, tape, generator, filter, maker, taker, audits;
  `docs/tools.md` says how to run them); the Rust port of the Arena's simulator: `rust/arena_sim/`; the organisers'
  starter: `third_party/qminers-starter/`.
- Each round: `data/arena/round<N>/` (`HANDOVER.md`, `CANDIDATES.md`, the server's result folders, the leaderboard);
  every tested idea: `IDEAS.md`; the day's playbook as used: `docs/day/`; the Codex session's repository and
  Přemysl's research branch: `codex_repo/`.
- Other teams appear as "Team N", N their place in the overall standings.

```sh
uv sync && uv run pytest                     # Python 3.13; the round tools' tests
cargo build --release -p arena_sim --manifest-path rust/Cargo.toml
```

Keep history as it is (no rebase or squash); a document's numbers change only with the command that produced them.
