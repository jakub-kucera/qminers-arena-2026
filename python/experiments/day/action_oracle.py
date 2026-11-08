"""Day tool (R4-A1): a restricted-action oracle against F5's own continuation, by exact branches in Rust.

At a sampled decision t of F5 on a tape, one forced action replaces F5's (ridge_maker's FA_T / FA_ACT), then F5's
policy runs unchanged to the tape's end. The tape is deterministic, so A(t, a) = PnL(branch) - PnL(F5) is exact,
every later fill and decision included. Actions: WAIT (1: F5's take skipped, its 50-ms cooldown started), TAKE_NOW
(2: the forecast's way at the touch though under the bar), REDUCE (3: an IOC to flat, never past, in place of the
decision), COMPLETE (4: a partly filled take's rest at the next book).

    uv run python -m experiments.day.action_oracle log TAPE.csv --out DIR             # F5 with FA_LOG: DIR/fa_log.csv
    uv run python -m experiments.day.action_oracle sample DIR [--seed 4] [--n wait=260,flip=110,take=170,reduce=110,complete=130] [--append]
    uv run python -m experiments.day.action_oracle run TAPE.csv DIR [--threads 6] [--chunk 60]   # appends DIR/branches.csv
    uv run python -m experiments.day.action_oracle report DIR

`sample` draws the decisions per class spread over the whole tape (equal strata of time): `wait` F5's takes (WAIT),
`flip` F5's takes that reverse the position (REDUCE, i.e. stop at flat), `take` near-bar decisions without a take
with room the forecast's way (TAKE_NOW), `reduce` near-bar decisions without a take while holding (REDUCE), `complete`
partly filled takes (COMPLETE). `report` gives, per class, the mean of A, its t, the share positive and the positive
part's sum, then by 1,000-s block, speed tercile (QS_RATE's rate), spread, |position| and forecast margin, and the
differences at t+5 / 30 / 300 s from the 1-s curve. Standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import os
import random
import sys
from pathlib import Path

from arena import qsim_rust
from experiments.day.family_rust import F5
from experiments.day.paired_rust import overrides

ACT = {"wait": 1, "flip": 3, "take": 2, "reduce": 3, "complete": 4}
LOG_COLS = ("kind", "t", "mid", "spread", "signal", "need_up", "need_dn", "sign", "qty", "inv", "res_b", "res_s",
            "qs", "jump", "flip_age", "gap", "sd")
HORIZONS = (5, 30, 300)


def base_params(extra: str = "") -> dict:
    return overrides(F5 + (" " + extra if extra else ""))


def cmd_log(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["FA_LOG"] = str(out / "fa_log.csv")
    qsim_rust.build()
    [[row]] = qsim_rust.run_batch("ridge_maker", [base_params()], [Path(args.tape)], threads=1)
    del os.environ["FA_LOG"]
    if row.get("error"):
        raise SystemExit(row["error"])
    (out / "base.json").write_text(json.dumps({"pnl": row["pnl"], "curve": row["curve"]}))
    print(f"F5 {row['pnl']:.2f} ({row['seconds']:.1f} s); log {out / 'fa_log.csv'}")


def read_log(path: Path) -> tuple[list[dict], list[dict]]:
    decisions, partials = [], []
    with open(path) as f:
        for line in f:
            v = line.rstrip("\n").split(",")
            if v[0] == "3":
                partials.append({"kind": 3, "t": int(v[1]), "sign": int(v[2]), "req": int(v[3]), "filled": int(v[4]), "inv": int(v[5])})
                continue
            d = dict(zip(LOG_COLS, v))
            for k in ("kind", "t", "spread", "sign", "qty", "inv", "res_b", "res_s", "jump", "flip_age"):
                d[k] = int(d[k])
            for k in ("mid", "signal", "need_up", "need_dn", "qs", "gap", "sd"):
                d[k] = float(d[k])
            decisions.append(d)
    return decisions, partials


def stratified(rows: list[dict], n: int, t0: int, t1: int, rng: random.Random) -> list[dict]:
    """n rows, one from each of n equal time strata (a stratum without rows gives its draw to a random other)."""
    if n <= 0 or not rows:
        return []
    width = (t1 - t0) / n
    buckets: dict[int, list[dict]] = {}
    for r in rows:
        buckets.setdefault(min(n - 1, int((r["t"] - t0) / width)), []).append(r)
    picked = [rng.choice(b) for b in buckets.values()]
    rest = [r for r in rows if r not in picked] if len(picked) < n else []
    picked += rng.sample(rest, min(len(rest), n - len(picked)))
    return sorted(picked, key=lambda r: r["t"])


def cmd_sample(args) -> None:
    d = Path(args.dir)
    decisions, partials = read_log(d / "fa_log.csv")
    base = json.loads((d / "base.json").read_text())
    t0, t1 = base["curve"][0][0], base["curve"][-1][0]
    t_hi = t1 - 300_000_000 * 0  # every decision is eligible; the 300-s horizon is cut at the tape's end
    want = dict(kv.split("=") for kv in args.n.split(","))
    rng = random.Random(args.seed)
    takes = [r for r in decisions if r["kind"] == 1 and r["t"] < t_hi]
    pools = {
        "wait": takes,
        "flip": [r for r in takes if r["sign"] * r["inv"] < 0],
        "take": [r for r in decisions if r["kind"] == 0 and r["t"] < t_hi and room(r) > 0],
        "reduce": [r for r in decisions if r["kind"] == 0 and r["t"] < t_hi and r["inv"] != 0],
        "complete": [dict(p) for p in partials if p["t"] < t_hi],
    }
    old = []
    if args.append and (d / "tasks.jsonl").exists():
        old = [json.loads(l) for l in (d / "tasks.jsonl").read_text().splitlines() if l.strip()]
    seen = {(t["cls"], t["t"]) for t in old}
    tasks = []
    for cls, pool in pools.items():
        pool = [r for r in pool if (cls, r["t"]) not in seen]
        for r in stratified(pool, int(want.get(cls, 0)), t0, t1, rng):
            tasks.append({"cls": cls, "act": ACT[cls], **r})
    with open(d / "tasks.jsonl", "a" if old else "w") as f:
        for i, t in enumerate(tasks, start=len(old)):
            f.write(json.dumps({"id": i, **t}) + "\n")
    print(" ".join(f"{c} {len(p)} -> {sum(1 for t in tasks if t['cls'] == c)}" for c, p in pools.items()), f"= {len(tasks)} tasks")


def room(r: dict) -> int:
    """F5's take quantity the forecast's way at a no-take decision (EXPOSURE 100, FT_ROOM_LIVE, FT_SZ 200)."""
    s = 1 if r["signal"] > 0 else -1
    pos = s * r["inv"]
    reserved = r["res_b"] if s > 0 else r["res_s"]
    return min(200, 100 - pos - reserved)


def at(curve: list, t_us: int) -> float:
    """The curve's PnL at the last 1-s sample at or before t_us (the bisection over sample times)."""
    lo, hi = 0, len(curve) - 1
    if t_us < curve[0][0]:
        return curve[0][1]
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if curve[mid][0] <= t_us:
            lo = mid
        else:
            hi = mid - 1
    return curve[lo][1]


def cmd_run(args) -> None:
    d = Path(args.dir)
    tasks = [json.loads(l) for l in (d / "tasks.jsonl").read_text().splitlines() if l.strip()]
    base = json.loads((d / "base.json").read_text())
    out = d / "branches.csv"
    done = set()
    if out.exists():
        with open(out) as f:
            done = {int(r["id"]) for r in csv.DictReader(f)}
    todo = [t for t in tasks if t["id"] not in done]
    random.Random(0).shuffle(todo)  # every chunk mixes the classes and the tape's time
    if args.limit:
        todo = todo[: args.limit]
    qsim_rust.build()
    fields = ["id", "cls", "act", "t", "A", *[f"A{h}" for h in HORIZONS], "pnl"]
    new = not out.exists()
    with open(out, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(fields)
        for i in range(0, len(todo), args.chunk):
            chunk = todo[i: i + args.chunk]
            params = [{**base_params(), "FA_T": t["t"], "FA_ACT": t["act"]} for t in chunk]
            rows = qsim_rust.run_batch("ridge_maker", params, [Path(args.tape)], threads=args.threads)
            for t, [row] in zip(chunk, rows):
                if row.get("error"):
                    print(f"task {t['id']}: {row['error']}", file=sys.stderr)
                    continue
                c = row["curve"]
                hs = [(at(c, t["t"] + h * 1_000_000) - at(c, t["t"])) - (at(base["curve"], t["t"] + h * 1_000_000) - at(base["curve"], t["t"])) for h in HORIZONS]
                w.writerow([t["id"], t["cls"], t["act"], t["t"], f"{row['pnl'] - base['pnl']:.2f}", *[f"{x:.2f}" for x in hs], f"{row['pnl']:.2f}"])
            f.flush()
            print(f"{i + len(chunk)} / {len(todo)} done", flush=True)


def stats(xs: list[float]) -> str:
    n = len(xs)
    if n == 0:
        return "n 0"
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    t = m / (sd / math.sqrt(n)) if sd > 0 else float("nan")
    pos = sum(1 for x in xs if x > 0)
    zero = sum(1 for x in xs if x == 0)
    return (f"n {n:4d}  mean {m:9.1f}  t {t:6.2f}  pos {pos / n:5.1%}  zero {zero / n:5.1%}  "
            f"sum+ {sum(x for x in xs if x > 0):10.0f}  sum- {sum(x for x in xs if x < 0):10.0f}  median {sorted(xs)[n // 2]:8.1f}")


def cmd_report(args) -> None:
    d = Path(args.dir)
    tasks = {t["id"]: t for t in (json.loads(l) for l in (d / "tasks.jsonl").read_text().splitlines() if l.strip())}
    base = json.loads((d / "base.json").read_text())
    t0 = base["curve"][0][0]
    decisions, partials = read_log(d / "fa_log.csv")
    qs_all = sorted(r["qs"] for r in decisions)
    q1, q2 = qs_all[len(qs_all) // 3], qs_all[2 * len(qs_all) // 3]
    take_rows = [r for r in decisions if r["kind"] == 1]
    take_times = [r["t"] for r in take_rows]
    rows = []
    with open(d / "branches.csv") as f:
        for r in csv.DictReader(f):
            t = dict(tasks[int(r["id"])])
            if t["cls"] == "complete":  # the state at the take it completes: the last take at or before its cancel
                k = bisect.bisect_right(take_times, t["t"]) - 1
                while k >= 0 and take_rows[k]["sign"] != t["sign"]:
                    k -= 1
                if k >= 0:
                    t.update({key: take_rows[k][key] for key in ("spread", "signal", "need_up", "need_dn", "qs", "jump", "flip_age", "gap", "sd")})
            rows.append({**t, "A": float(r["A"]), **{f"A{h}": float(r[f"A{h}"]) for h in HORIZONS}})
    print(f"F5 {base['pnl']:.2f}; {len(rows)} branches; speed terciles at QS_RATE {q1:.2f} / {q2:.2f} (over logged decisions)")

    def margin(r: dict) -> float:
        if "signal" not in r:
            return float("nan")
        s = 1 if r["signal"] > 0 else -1
        need = r["need_up"] if s > 0 else r["need_dn"]
        return abs(r["signal"]) - need

    keys = {
        "block": lambda r: f"{int((r['t'] - t0) / 1e9)}",
        "speed": lambda r: "na" if "qs" not in r else "slow" if r["qs"] < q1 else ("mid" if r["qs"] < q2 else "fast"),
        "spread": lambda r: str(min(r.get("spread", 1), 3)),
        "pos": lambda r: (lambda a: "0" if a == 0 else ("1-50" if a <= 50 else ("51-99" if a < 100 else "100+")))(abs(r["inv"])),
        "margin": lambda r: (lambda m: "na" if m != m else ("<-0.2" if m < -0.2 else ("-0.2..0" if m < 0 else ("0..0.25" if m < 0.25 else ("0.25..0.75" if m < 0.75 else ">=0.75")))))(margin(r)),
        "withpos": lambda r: "na" if "signal" not in r or r["inv"] == 0 else ("with" if r["signal"] * r["inv"] > 0 else "against"),
        "jump": lambda r: "na" if "jump" not in r else ("jump" if r["jump"] != 0 else "none"),
        "flipage": lambda r: "na" if "flip_age" not in r else ("<0.5s" if r["flip_age"] < 500_000 else ("0.5-2s" if r["flip_age"] < 2_000_000 else ">2s")),
    }
    if args.compact:
        takes = [r for r in decisions if r["kind"] == 1]
        near = [r for r in decisions if r["kind"] == 0]
        pools = {"wait": len(takes), "flip": sum(1 for r in takes if r["sign"] * r["inv"] < 0),
                 "take": sum(1 for r in near if room(r) > 0), "reduce": sum(1 for r in near if r["inv"] != 0),
                 "complete": len(partials)}
        def line(label: str, sub: list[dict], pool: int | None) -> str:
            xs = [r["A300"] for r in sub]
            n = len(xs)
            m = sum(xs) / n
            sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
            t = m / (sd / math.sqrt(n)) if sd > 0 else float("nan")
            sp = sum(x for x in xs if x > 0)
            head = f"| {label} | {n} | {m:+.1f} | {t:+.2f} | {sum(1 for x in xs if x > 0) / n:.0%} / {sum(1 for x in xs if x < 0) / n:.0%} | {sp:,.0f} |"
            head += f" {sp * pool / n:,.0f} |" if pool else " |"
            return head + f" {sum(r['A'] for r in sub) / n:+.1f} |"
        print("| group | n | mean A300 | t | share + / - | sum of A300+ | scaled to the pool | mean A (end) |")
        print("|---|---|---|---|---|---|---|---|")
        for cls in ACT:
            sub = [r for r in rows if r["cls"] == cls]
            if not sub:
                continue
            print(line(f"**{cls}**", sub, pools.get(cls)))
            for name in args.compact.split(","):
                groups: dict[str, list[dict]] = {}
                for r in sub:
                    groups.setdefault(keys[name](r), []).append(r)
                for g in sorted(groups):
                    print(line(f"{cls} {name} {g}", groups[g], None))
        return
    for cls in ACT:
        sub = [r for r in rows if r["cls"] == cls]
        if not sub:
            continue
        print(f"\n== {cls} (FA_ACT {ACT[cls]}) ==")
        print(f"  all         {stats([r['A'] for r in sub])}")
        for h in HORIZONS:
            print(f"  at +{h:3d} s    {stats([r[f'A{h}'] for r in sub])}")
        for name, key in keys.items():
            groups: dict[str, list[dict]] = {}
            for r in sub:
                groups.setdefault(key(r), []).append(r)
            print(f"  by {name} (A to the end; then A at +300 s):")
            for g in sorted(groups):
                print(f"    {g:>10}  {stats([r['A'] for r in groups[g]])}")
                print(f"    {'':>10}  {stats([r['A300'] for r in groups[g]])}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("log")
    p.add_argument("tape")
    p.add_argument("--out", required=True)
    p = sub.add_parser("sample")
    p.add_argument("dir")
    p.add_argument("--seed", type=int, default=4)
    p.add_argument("--n", default="wait=260,flip=110,take=170,reduce=110,complete=130")
    p.add_argument("--append", action="store_true", help="add to DIR/tasks.jsonl (new ids, decisions not drawn before)")
    p = sub.add_parser("run")
    p.add_argument("tape")
    p.add_argument("dir")
    p.add_argument("--threads", type=int, default=6)
    p.add_argument("--chunk", type=int, default=60)
    p.add_argument("--limit", type=int, default=0)
    p = sub.add_parser("report")
    p.add_argument("dir")
    p.add_argument("--compact", default="", help="a Markdown table by these keys (block,speed,spread,|pos|,margin,...)")
    args = ap.parse_args(argv)
    {"log": cmd_log, "sample": cmd_sample, "run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
