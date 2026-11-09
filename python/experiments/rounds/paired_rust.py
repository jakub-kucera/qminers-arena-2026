"""Day tool: named ridge_maker settings on several tapes in one `arena-sim batch` (each tape read once), every bot
paired with the first over S-second segments (the mean difference, its t and the segments won: pnl_corr's
`--segment`, without writing pnl.csv files). Rust first (data/arena/round3/HANDOVER.md).

    uv run python -m experiments.rounds.paired_rust TAPE.csv [MORE.csv ...] --bot F3=B1:'--set FILTER=1'
        --bot X=B1:'--set FILTER=1 --set FT_SZ=150' [--grid FT_EDGE=0.1,0.2] [--threads 4] [--segment 500]
        [--holdout 0.25] [--strategy ridge_maker] [--window 2935-2950 ...]

`--bot NAME=BASE:'--set K=V ...'` as `experiments.rounds.family_rust` (BASE one of its FAMILY or empty); the first bot is
the reference. `--grid K=V1,V2` (repeatable) expands every bot after the first into the grid's cells. Prints, per tape,
each bot's PnL, first 75% / last 25% (`--holdout`), the difference with the reference and the paired segments; then the
differences, bots by tapes. `--window S-E` (seconds, repeatable) adds each bot's PnL change over that window of every
tape (the reference's, then the others' differences). Standard library only.
"""

from __future__ import annotations

import argparse
import itertools
import math
import shlex
import sys
from pathlib import Path

from arena import qgrid, qsim_rust
from arena.botfile import parse_override
from experiments.rounds.family_rust import FAMILY, parse_bot


def overrides(sets: str) -> dict:
    """A `--set K=V ...` line as the dict qsim_rust passes (the last of a repeated key wins)."""
    words = shlex.split(sets)
    out = {}
    for i, word in enumerate(words):
        if word == "--set":
            key, value = parse_override(words[i + 1])
            out[key] = value
        elif not (i > 0 and words[i - 1] == "--set"):
            raise SystemExit(f"only --set K=V in a bot's line, not {word!r}")
    return out


def segments(curve: list[tuple[int, float]], seconds: int) -> list[float]:
    """The PnL change over each `seconds` segment of a 1-s curve."""
    values = [pnl for _, pnl in curve]
    marks = values[::seconds]
    return [b - a for a, b in zip(marks, marks[1:])]


def window_pnl(curve: list[tuple[int, float]], start: float, end: float) -> float:
    """The PnL change from `start` to `end` seconds on a [(ts_us, pnl), ...] curve (the last point at or before each)."""
    def at(sec: float) -> float:
        value = 0.0
        for ts, pnl in curve:
            if ts > sec * 1_000_000:
                break
            value = pnl
        return value
    return at(end) - at(start)


def paired(ref: list[float], other: list[float]) -> tuple[float, float, int, int]:
    n = min(len(ref), len(other))
    d = [other[i] - ref[i] for i in range(n)]
    if n < 2:
        return float("nan"), float("nan"), 0, n
    mean = sum(d) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1))
    return mean, (mean / (sd / math.sqrt(n)) if sd > 0 else float("nan")), sum(1 for x in d if x > 0), n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tapes", nargs="+", type=Path)
    ap.add_argument("--bot", action="append", default=[], required=True, help="NAME=BASE:'--set K=V ...'; the first is the reference")
    ap.add_argument("--grid", action="append", default=[], help="K=V1,V2,... over every bot after the first")
    ap.add_argument("--strategy", default="ridge_maker")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--segment", type=int, default=500)
    ap.add_argument("--holdout", type=float, default=0.25)
    ap.add_argument("--window", action="append", default=[], help="S-E seconds: each bot's PnL over it (repeatable)")
    a = ap.parse_args(argv)
    for tape in a.tapes:
        if not tape.exists():
            raise SystemExit(f"no such tape: {tape}")
    bots: dict[str, dict] = {}
    for i, spec in enumerate(a.bot):
        name, sets = parse_bot(spec, dict(FAMILY))
        base = overrides(sets)
        if i == 0 or not a.grid:
            bots[name] = base
            continue
        axes = [(k, v.split(",")) for k, v in (g.split("=", 1) for g in a.grid)]
        for combo in itertools.product(*(vals for _, vals in axes)):
            cell = dict(base)
            for (k, _), v in zip(axes, combo):
                cell.update(dict([parse_override(f"{k}={v}")]))
            bots[name + "[" + ",".join(f"{k}={v}" for (k, _), v in zip(axes, combo)) + "]"] = cell
    names = list(bots)
    windows = [tuple(float(x) for x in w.split("-", 1)) for w in a.window]
    qsim_rust.build()
    runs = qsim_rust.run_batch(a.strategy, [bots[n] for n in names], a.tapes, a.threads)
    width = max(len(n) for n in names) + 1
    diffs: dict[tuple[str, Path], str] = {}
    for f, tape in enumerate(a.tapes):
        print(f"== {tape}")
        print(f"{'bot':<{width}} {'pnl':>10} {'first':>10} {'last':>9} {'diff':>9} {'d first':>9} {'d last':>8}"
              f" {'breach':>7} {'fills':>7}  paired {a.segment}-s segments")
        ref = runs[0][f]
        ref_in, ref_out = qgrid.split_at(ref.get("curve", []), a.holdout) if "curve" in ref else (0.0, 0.0)
        ref_seg = segments(ref.get("curve", []), a.segment)
        for t, name in enumerate(names):
            row = runs[t][f]
            if row.get("error") or "pnl" not in row:
                print(f"{name:<{width}} error: {row.get('error')}")
                diffs[(name, tape)] = "error"
                continue
            p_in, p_out = qgrid.split_at(row["curve"], a.holdout)
            mean, tstat, won, n = paired(ref_seg, segments(row["curve"], a.segment))
            pair = "" if t == 0 else f"  mean {mean:+,.0f} t {tstat:+.2f} won {won}/{n}"
            if windows:
                own = [window_pnl(row["curve"], s, e) for s, e in windows]
                base = [0.0] * len(windows) if t == 0 else [window_pnl(ref["curve"], s, e) for s, e in windows]
                pair += "  windows " + " ".join(f"{s:g}-{e:g} {o - b:+,.0f}" for (s, e), o, b in zip(windows, own, base))
            print(f"{name:<{width}} {row['pnl']:>10,.0f} {p_in:>10,.0f} {p_out:>9,.0f} {row['pnl'] - ref['pnl']:>+9,.0f}"
                  f" {p_in - ref_in:>+9,.0f} {p_out - ref_out:>+8,.0f} {row['breach_penalty']:>7,.0f} {row['fills']:>7}{pair}")
            diffs[(name, tape)] = f"{row['pnl'] - ref['pnl']:+,.0f}" if t else f"{row['pnl']:,.0f}"
    if len(a.tapes) > 1:
        heads = [t.stem[:12] for t in a.tapes]
        print(f"== the reference's pnl, then each bot's difference; bots by tapes")
        print(f"{'bot':<{width}} " + " ".join(f"{h:>12}" for h in heads))
        for name in names:
            print(f"{name:<{width}} " + " ".join(f"{diffs[(name, t)]:>12}" for t in a.tapes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
