# The day's playbook, as it was used

These files ran the event. They were written before the Arena, rewritten during its first hour for the real API, and
used by the team and its agent sessions through the four rounds. They are kept here unchanged, so their paths and
links point at the repository as it was on 7-8 Nov (the combined repository, whose Prosperity-era half is now the
prep repository).

| File | What it was for |
|---|---|
| [`RUNBOOK.md`](RUNBOOK.md) | One page for the day: what to run at each checkpoint of a round, each line naming the `ON_THE_DAY.md` section behind it |
| [`ON_THE_DAY.md`](ON_THE_DAY.md) | Every question about the real Arena with its assumption, what changes if the answer differs, and the answers as they came ("Known so far") |
| [`KICKOFF_PROMPT.md`](KICKOFF_PROMPT.md) | The prompts pasted into a fresh agent session at the start of each round, and the improvement loop |
| [`CLAUDE.md`](CLAUDE.md) | What every agent session read first: the Arena path, the commands, the rules that kept the parts consistent |

Each round's own record (what was uploaded, what each upload scored, what we learned, what the next round should try)
is in `data/arena/round<N>/HANDOVER.md` and `CANDIDATES.md`, written during the round from
[`../HANDOVER_TEMPLATE.md`](../HANDOVER_TEMPLATE.md).
