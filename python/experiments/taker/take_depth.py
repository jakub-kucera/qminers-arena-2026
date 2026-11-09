"""Day tool (R4-T1): ridge_maker settings paired with the first, as `experiments.rounds.paired_rust`, plus where the gain
sits: the paired PnL difference split by market speed (L8's decayed |mid change| rate, QS_RATE's `qs_rate`, from the
reference's RIDGE_PRED_EXTRA log) and by spread, and each run's take completion (TAKE_STATS). Rust first.

    uv run python -m experiments.taker.take_depth TAPE.csv [MORE.csv ...] --bot F5=F5: --bot E1=F5:'--set FT_RETRY=1'
        [--grid FT_DEPTH_K=1,2 --grid FT_DEPTH_E=0.25,0.5,1.0] [--threads 4] [--segment 1000] [--speed-cut 6]
        [--json OUT.json]

`--bot` and `--grid` as paired_rust (the reference needs QS_RATE for the speed column). Per tape and bot: PnL, first 75%
/ last 25% (`--holdout`), the difference, paired `--segment` segments (mean, t, won); the difference over 1-s steps by
the reference's speed terciles over those steps (the speed averaged within each step) and below / at least
`--speed-cut` ticks a second, the fastest tercile's share of the total difference, and by the step's spread (1 tick for
at least half its books, else wide); the takes (count, lots sent, the unfilled share, partial and zero fills, the next
take the same way within 100 ms after an incomplete one and how many of those at a worse price, retries, deepened
takes). Every run on a tape shares one TAKE_STATS file, so the bots' FT_DEPTH_* / FT_RETRY* values must differ.
Standard library only.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import tempfile
from pathlib import Path

from arena import qgrid, qsim_rust
from arena.botfile import parse_override
from experiments.rounds.family_rust import FAMILY, parse_bot
from experiments.rounds.paired_rust import overrides, paired, segments

E1 = ("FT_DEPTH_K", "FT_DEPTH_E", "FT_DEPTH_MODE", "FT_RETRY", "FT_RETRY_MS")
E1_DEFAULT = {"FT_DEPTH_K": 0, "FT_DEPTH_E": 0.5, "FT_DEPTH_MODE": 0, "FT_RETRY": 0, "FT_RETRY_MS": 0}


def e1_key(params: dict) -> str:
    """The TAKE_STATS line's knob prefix for these parameters (Rust's `{}` formatting of i64 and f64)."""
    out = []
    for k in E1:
        v = params.get(k, E1_DEFAULT[k])
        if k == "FT_DEPTH_E":
            v = float(v)
            text = str(int(v)) if v == int(v) else repr(v)
        else:
            text = str(int(v))
        out.append(f"{k}={text}")
    return " ".join(out)


def parse_stats(path: Path) -> dict[str, dict]:
    stats = {}
    if not path.exists():
        return stats
    for line in path.read_text().splitlines():
        head, *fields = line.split("\t")
        stats[head] = {k: int(v) for k, v in (f.split("=", 1) for f in fields)}
    return stats


def step_states(log: Path, curve: list[tuple[int, float]]) -> list[tuple[float | None, bool | None]]:
    """For each curve step [ts_i, ts_i+1): the mean speed of the pred log's books in it and whether the spread was
    1 tick at least half of them (None, None without books)."""
    edges = [ts for ts, _ in curve]
    acc = [[0.0, 0, 0] for _ in range(max(len(edges) - 1, 0))]
    i = 0
    with log.open() as f:
        for line in f:
            parts = line.split(",")
            ts = int(parts[0])
            while i < len(acc) and ts >= edges[i + 1]:
                i += 1
            if i >= len(acc):
                break
            if ts < edges[i]:
                continue
            a = acc[i]
            a[0] += float(parts[7])
            a[1] += 1
            a[2] += 1 if int(float(parts[4])) == 1 else 0
    return [(a[0] / a[1], 2 * a[2] >= a[1]) if a[1] else (None, None) for a in acc]


def tercile_cuts(values: list[float]) -> tuple[float, float]:
    v = sorted(values)
    return v[len(v) // 3], v[2 * len(v) // 3]


def split_gain(ref: list[tuple[int, float]], other: list[tuple[int, float]], states, cuts, speed_cut: float) -> dict:
    n = min(len(ref), len(other)) - 1
    out = {"slow": 0.0, "mid": 0.0, "fast": 0.0, "none": 0.0, f"<{speed_cut:g}": 0.0, f">={speed_cut:g}": 0.0,
           "spread1": 0.0, "wide": 0.0}
    for i in range(n):
        d = (other[i + 1][1] - other[i][1]) - (ref[i + 1][1] - ref[i][1])
        speed, one = states[i] if i < len(states) else (None, None)
        if speed is None:
            out["none"] += d
            continue
        out["slow" if speed < cuts[0] else "mid" if speed < cuts[1] else "fast"] += d
        out[f"<{speed_cut:g}" if speed < speed_cut else f">={speed_cut:g}"] += d
        out["spread1" if one else "wide"] += d
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tapes", nargs="+", type=Path)
    ap.add_argument("--bot", action="append", default=[], required=True, help="NAME=BASE:'--set K=V ...'; the first is the reference")
    ap.add_argument("--grid", action="append", default=[], help="K=V1,V2,... over every bot after the first")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--segment", type=int, default=1000)
    ap.add_argument("--holdout", type=float, default=0.25)
    ap.add_argument("--speed-cut", type=float, default=6.0)
    ap.add_argument("--json", type=Path, help="write every number here")
    a = ap.parse_args(argv)
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
    keys = [e1_key(bots[n]) for n in names]
    if len(set(keys)) != len(keys):
        raise SystemExit("two bots share FT_DEPTH_* / FT_RETRY values: their TAKE_STATS lines would collide")
    qsim_rust.build()
    report = {}
    width = max(len(n) for n in names) + 1
    for tape in a.tapes:
        with tempfile.TemporaryDirectory(prefix="take_depth_") as scratch:
            log, stats_path = Path(scratch) / "pred.csv", Path(scratch) / "stats.txt"
            os.environ["RIDGE_PRED_LOG"], os.environ["RIDGE_PRED_EXTRA"] = str(log), "1"
            try:
                qsim_rust.run_batch("ridge_maker", [bots[names[0]]], [tape], 1)
            finally:
                del os.environ["RIDGE_PRED_LOG"], os.environ["RIDGE_PRED_EXTRA"]
            os.environ["TAKE_STATS"] = str(stats_path)
            try:
                runs = qsim_rust.run_batch("ridge_maker", [bots[n] for n in names], [tape], a.threads)
            finally:
                del os.environ["TAKE_STATS"]
            stats = parse_stats(stats_path)
            ref = runs[0][0]
            states = step_states(log, ref["curve"])
        cuts = tercile_cuts([s for s, _ in states if s is not None])
        ref_in, ref_out = qgrid.split_at(ref["curve"], a.holdout)
        ref_seg = segments(ref["curve"], a.segment)
        print(f"== {tape}  (speed terciles cut at {cuts[0]:.2f} / {cuts[1]:.2f} ticks/s)")
        print(f"{'bot':<{width}} {'pnl':>10} {'diff':>8} {'d first':>8} {'d last':>8} {'seg mean':>8} {'t':>6} {'won':>5}"
              f" {'slow':>7} {'mid':>7} {'fast':>7} {'fast%':>6} {'<cut':>7} {'>=cut':>7} {'spr1':>7} {'wide':>7}"
              f" {'takes':>6} {'unfill':>6} {'part':>5} {'zero':>4} {'same':>5} {'worse':>5} {'retry':>5} {'deep':>5}")
        rows = {}
        for t, name in enumerate(names):
            row = runs[t][0]
            if row.get("error") or "pnl" not in row:
                print(f"{name:<{width}} error: {row.get('error')}")
                continue
            p_in, p_out = qgrid.split_at(row["curve"], a.holdout)
            mean, tstat, won, n = paired(ref_seg, segments(row["curve"], a.segment))
            g = split_gain(ref["curve"], row["curve"], states, cuts, a.speed_cut)
            st = stats.get(keys[t], {})
            unfilled = 1 - st.get("filled", 0) / max(st.get("sent", 0), 1)
            diff = row["pnl"] - ref["pnl"]
            fast_share = g["fast"] / diff if diff else float("nan")
            rows[name] = {"pnl": row["pnl"], "first": p_in, "last": p_out, "diff": diff, "d_first": p_in - ref_in,
                          "d_last": p_out - ref_out, "seg_mean": mean, "seg_t": tstat, "seg_won": won, "segments": n,
                          "split": g, "fast_share": fast_share, "stats": st, "unfilled": unfilled,
                          "params": {k: bots[name].get(k) for k in E1 if k in bots[name]}}
            seg = "" if t == 0 else f"{mean:>+8,.0f} {tstat:>+6.2f} {won:>2}/{n:<2}"
            print(f"{name:<{width}} {row['pnl']:>10,.0f} {diff:>+8,.0f} {p_in - ref_in:>+8,.0f} {p_out - ref_out:>+8,.0f}"
                  f" {seg:>21} {g['slow']:>+7,.0f} {g['mid']:>+7,.0f} {g['fast']:>+7,.0f} {fast_share:>6.0%}"
                  f" {g[f'<{a.speed_cut:g}']:>+7,.0f} {g[f'>={a.speed_cut:g}']:>+7,.0f} {g['spread1']:>+7,.0f} {g['wide']:>+7,.0f}"
                  f" {st.get('takes', 0):>6} {unfilled:>6.1%} {st.get('partial', 0):>5} {st.get('zero', 0):>4}"
                  f" {st.get('same_way_100ms', 0):>5} {st.get('worse', 0):>5} {st.get('retries', 0):>5} {st.get('deepened', 0):>5}")
        report[str(tape)] = {"cuts": cuts, "rows": rows}
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
