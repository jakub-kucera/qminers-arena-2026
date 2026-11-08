"""Day tool: the forecast-taker family in the Rust ridge_maker, every bot on every tape, one table (Rust first:
data/arena/round3/HANDOVER.md, "Rule for round 3: Rust first").

Each bot is a `--set` line of `arena.qsim_rust ridge_maker` that reproduces its Python file to the unit (rust/README.md,
"Round 2's forecast takers": R2-T2, R2-L1, R2-L3, R2-L8, R2-L9; R3-B1 is R2-L9 with R2-L8's quote switch; R3-F3, R3-F4 and
R3-F5 are B1 with the latent-price filter, its impact bank and the jump-dependent take bar). The runs go in
parallel, one thread each, so `--jobs` is the cores they take. `--bot NAME=BASE:'--set K=V ...'` adds a bot (BASE one of
the family, or empty).

    uv run python -m experiments.day.family_rust data/arena/round3/round3_public.csv [MORE.csv ...] [--bots L8,L9]
        [--bot L3_pl100=L3:'--set POSITION_LIMIT=100'] [--jobs 6] [--holdout 0.25]

Prints, per tape, each bot's PnL, its first 75% and last 25% (`--holdout`), max drawdown, breach penalty and fills;
then the PnL table, bots by tapes. Standard library only.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

T2 = ("--set POSITION_LIMIT=1000 --set EXPOSURE=100 --set HEDGE=1 --set MODEL_MEMORY_US=100000000000 --set HORIZON_US=400000"
      " --set DEAD_ZONE=0.18 --set QUOTEFEAT=1 --set FLOWGRP=2 --set FLOWGRP_CAP=20 --set FLOWGRP_US=1000000 --set FT_EDGE=0.15"
      " --set FT_SZ=200 --set FT_GAP_MS=50 --set QUOTE_SIZE=1 --set KEEP_LOTS=20 --set KEEP_TH=0.3 --set FT_MAXSPREAD=1"
      " --set FT_ROOM_LIVE=1")
L1 = T2 + " --set LIQ=1"
L3 = L1 + " --set QUOTE_SIZE=0"
L8 = L1 + " --set QS_RATE=2.5"
L9 = L3 + " --set POSITION_LIMIT=100 --set IMPACT_US=500000 --set HUBER=6.0 --set RIDGE_MIN=30 --set RIDGE_FRAC=0.003"
B1 = L9 + " --set QUOTE_SIZE=1 --set QS_RATE=2.5"
F3 = B1 + " --set FILTER=1"  # R3-F3, round 3's first final: B1 plus the latent-price filter (505,212 on round3_public)
F4 = F3 + " --set FILTER_IMP2=2.0"  # R3-F4: a second filter at impact x2, the better-fitting copy's features (512,175)
F5 = F3 + " --set FT_EDGE=0.25 --set FT_JUMP=3 --set FT_JUMP_HOLD_MS=5000 --set FT_JUMP_EDGE=0.15"  # R3-F5 (515,670)
FAMILY = {"T2": T2, "L1": L1, "L3": L3, "L8": L8, "L9": L9, "B1": B1, "F3": F3, "F4": F4, "F5": F5}
FIELDS = ("pnl", "in", "out", "nbhd", "max_dd", "breach", "fills")


def run(tape: str, sets: str, holdout: float) -> dict:
    """One `arena.qsim_rust` run: the numbers of its `base` row, or the error's last line."""
    cmd = [sys.executable, "-m", "arena.qsim_rust", "ridge_maker", tape, "--threads", "1", "--holdout", str(holdout),
           *shlex.split(sets)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if line.startswith("base "):
            return dict(zip(FIELDS, line.split()[1:1 + len(FIELDS)]))
    tail = (out.stderr or out.stdout).strip().splitlines()
    return {"error": tail[-1] if tail else f"exit {out.returncode}"}


def parse_bot(spec: str, bots: dict) -> tuple[str, str]:
    name, _, rest = spec.partition("=")
    base, _, sets = rest.partition(":")
    if base and base not in bots:
        raise SystemExit(f"--bot {spec}: unknown base {base!r} (one of {', '.join(bots)})")
    return name, (bots[base] + " " if base else "") + sets


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tapes", nargs="+")
    ap.add_argument("--bots", default=",".join(FAMILY), help="which of the family, comma-separated")
    ap.add_argument("--bot", action="append", default=[], help="NAME=BASE:'--set K=V ...', an extra bot")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--holdout", type=float, default=0.25)
    a = ap.parse_args(argv)
    bots = {name: FAMILY[name] for name in a.bots.split(",") if name}
    for spec in a.bot:
        name, sets = parse_bot(spec, {**FAMILY, **bots})
        bots[name] = sets
    for tape in a.tapes:
        if not Path(tape).exists():
            raise SystemExit(f"no such tape: {tape}")
    jobs = [(tape, name) for tape in a.tapes for name in bots]
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        results = dict(zip(jobs, pool.map(lambda j: run(j[0], bots[j[1]], a.holdout), jobs)))
    width = max(len(n) for n in bots) + 1
    for tape in a.tapes:
        print(f"== {tape}")
        print(f"{'bot':<{width}} {'pnl':>11} {'first':>11} {'last':>10} {'max dd':>8} {'breach':>8} {'fills':>8}")
        for name in bots:
            r = results[(tape, name)]
            if "error" in r:
                print(f"{name:<{width}} error: {r['error']}")
                continue
            print(f"{name:<{width}} {r['pnl']:>11} {r['in']:>11} {r['out']:>10} {r['max_dd']:>8} {r['breach']:>8} {r['fills']:>8}")
    if len(a.tapes) > 1:
        names = [Path(t).stem[:14] for t in a.tapes]
        print("== pnl, bots by tapes")
        print(f"{'bot':<{width}} " + " ".join(f"{n:>14}" for n in names))
        for name in bots:
            print(f"{name:<{width}} " + " ".join(f"{results[(t, name)].get('pnl', 'error'):>14}" for t in a.tapes))


if __name__ == "__main__":
    main()
