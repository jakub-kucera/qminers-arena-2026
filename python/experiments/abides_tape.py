"""A tape in the Qminers starter's CSV format from ABIDES's RMSC04: an agent market that isn't the starter's sample.

usage (from the repo root; needs references/abides-jpmc and data/abides/env, `experiments.abides_days setup`):
  uv run python -m experiments.abides_tape --seed 1                       # 10:00-11:00 -> data/arena/abides/abides_seed1.csv
  uv run python -m experiments.abides_tape --seed 2 --start 12:00:00 --end 13:00:00
  cd references/qminers-algo-arena && uv run exchange-simulator --strategy strategies/trend_follower.py --backtest ../../data/arena/abides/abides_seed1.csv --log-dir X --no-logs

The starter's tape (STARTER.md, "How the exchange works") is every order event in time order:
`Time,Operation,OrderId,Side,Volume,Price,Lifespan`, Time in seconds from the start, an Insert matching
as a taker first and then resting (G) or dying (F). ABIDES's order book keeps a history of what it did
(order_book.py: LIMIT when an order rests, EXEC per match, CANCEL, CANCEL_PARTIAL, MODIFY, REPLACE),
not of the orders it received, so each order is rebuilt from it:

  - an order that rested with nothing filled: Insert G at its price and size;
  - an incoming order whose matches (the EXECs sharing its id) are followed by its LIMIT: Insert G at
    the LIMIT's price, the matched lots plus the rest;
  - an incoming order fully filled (a market order, or a limit that crossed for its whole size):
    Insert F at the worst price it filled at, the matched lots: against the same book it fills exactly
    as in ABIDES (an order that found nothing to match left no trace and is missing);
  - REPLACE: Cancel the old order, Insert G the new one (its matches follow in the history);
  - CANCEL_PARTIAL and MODIFY (a size change in place, keeping the order's priority): Cancel and
    Insert G the new size at the same price under a new id, which loses the priority (counted).

The book resting at the window's start is inserted first (G, in ABIDES's order of arrival, a
microsecond apart from Time 0), so the replayed book is ABIDES's at every event; `book_check` counts
the seconds whose rebuilt best bid and ask differ from ABIDES's own book log (0 means the stream is
exact). Prices are ABIDES's cents, a tick each (RMSC04's fundamental starts at 100,000); times are
kept to the microsecond, bumped by 1 µs where two events would share one. RMSC04 runs to `--end`
plus `--tail` (5 min) so the agents' closing behaviour stays out of the window.

Writes TAPE.csv, TAPE.book.csv (ABIDES's best bid and ask at the end of each second, for comparing
with a replay) and TAPE.json (the counts). The ABIDES half runs under ABIDES's Python
(`--inside`), the conversion (`to_tape`) is standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / "data" / "abides" / "env"
ABIDES = ROOT / "references" / "abides-jpmc"
EXPORT = Path(__file__).resolve().parent / "abides_export"  # its pomegranate.py stands in for the one class RMSC04 uses
OUT = ROOT / "data" / "arena" / "abides"
HEADER = ["Time", "Operation", "OrderId", "Side", "Volume", "Price", "Lifespan"]
FIRST_ID = 1_000_001


def to_tape(history: list[dict], start_ns: int, end_ns: int) -> tuple[list[list], dict, list[tuple]]:
    """ABIDES's book history -> the tape's rows, the counts, and (time_ns, best bid, best ask) after each event."""
    resting: dict[int, list] = {}  # ABIDES id -> [tape id, side "B"/"A", price, lots, arrival]
    rows: list[list] = []
    touches: list[tuple] = []
    counts = dict(inserts_g=0, inserts_f=0, cancels=0, replaces=0, resized=0, execs=0, snapshot=0, unknown=0)
    state = {"next": FIRST_ID, "last_us": -1, "arrival": 0, "open": False}

    def new_id() -> int:
        state["next"] += 1
        return state["next"] - 1

    def stamp(t_ns: int) -> str:
        us = max((t_ns - start_ns) // 1000, state["last_us"] + 1)
        state["last_us"] = us
        return f"{us / 1e6:.6f}"

    def emit(t_ns, row):
        if state["open"]:
            rows.append([stamp(t_ns), *row])

    def insert(t_ns, oid, side, price, lots, lifespan):
        if lifespan == "G":
            counts["inserts_g"] += state["open"]
        else:
            counts["inserts_f"] += state["open"]
        tape_id = new_id()
        emit(t_ns, ["Insert", tape_id, side, lots, price, lifespan])
        return tape_id

    def rest(oid, tape_id, side, price, lots):
        state["arrival"] += 1
        resting[oid] = [tape_id, side, price, lots, state["arrival"]]

    def cancel(t_ns, oid):
        order = resting.pop(oid, None)
        if order is None:
            counts["unknown"] += 1
            return None
        emit(t_ns, ["Cancel", order[0], "", "", "", ""])
        counts["cancels"] += state["open"]
        return order

    def touch(t_ns):
        if not state["open"]:
            return
        bid = max((o[2] for o in resting.values() if o[1] == "B"), default=None)
        ask = min((o[2] for o in resting.values() if o[1] == "A"), default=None)
        touches.append((t_ns, bid, ask))

    absorbed = None  # a REPLACE's new order: its matches follow and were inserted with it
    i, n = 0, len(history)
    while i < n:
        event = history[i]
        t = int(event["time"])
        if t >= end_ns:
            break
        if not state["open"] and t >= start_ns:
            state["open"] = True
            for oid, order in sorted(resting.items(), key=lambda kv: kv[1][4]):  # the book at the start, oldest first
                order[0] = new_id()
                emit(start_ns, ["Insert", order[0], order[1], order[3], order[2], "G"])
                counts["snapshot"] += 1
            touch(start_ns)
        kind = event["type"]
        if kind == "EXEC":
            incoming, matched, worst, side = event["oppos_order_id"], 0, None, "B" if event["side"] == "SELL" else "A"
            while i < n and history[i]["type"] == "EXEC" and history[i]["oppos_order_id"] == incoming:
                passive = resting.get(history[i]["order_id"])
                lots = int(history[i]["quantity"])
                if passive is None:
                    counts["unknown"] += 1
                else:
                    passive[3] -= lots
                    worst = passive[2] if worst is None else (max(worst, passive[2]) if side == "B" else min(worst, passive[2]))
                    if passive[3] <= 0:
                        del resting[history[i]["order_id"]]
                matched += lots
                counts["execs"] += state["open"]
                i += 1
            if incoming == absorbed:
                resting[incoming][3] -= matched
                if resting[incoming][3] <= 0:
                    del resting[incoming]
                absorbed = None
            elif i < n and history[i]["type"] == "LIMIT" and history[i]["order_id"] == incoming:
                rest_event = history[i]
                tape_id = insert(t, incoming, side, int(rest_event["price"]), matched + int(rest_event["quantity"]), "G")
                rest(incoming, tape_id, side, int(rest_event["price"]), int(rest_event["quantity"]))
                i += 1
            elif worst is not None:
                insert(t, incoming, side, worst, matched, "F")
            touch(t)
            continue
        if kind == "LIMIT":
            side = "B" if event["side"] in ("BID", "BUY") else "A"
            tape_id = insert(t, event["order_id"], side, int(event["price"]), int(event["quantity"]), "G")
            rest(event["order_id"], tape_id, side, int(event["price"]), int(event["quantity"]))
        elif kind == "CANCEL":
            cancel(t, event["order_id"])
        elif kind == "REPLACE":
            old = cancel(t, event["old_order_id"])
            if old is not None:
                counts["replaces"] += state["open"]
                tape_id = insert(t, event["new_order_id"], old[1], int(event["price"]), int(event["quantity"]), "G")
                rest(event["new_order_id"], tape_id, old[1], int(event["price"]), int(event["quantity"]))
                absorbed = event["new_order_id"]
        elif kind in ("CANCEL_PARTIAL", "MODIFY"):
            oid = event["order_id"]
            old = resting.get(oid)
            if old is None:
                counts["unknown"] += 1
            else:
                lots = old[3] - int(event["quantity"]) if kind == "CANCEL_PARTIAL" else int(event["new_quantity"])
                cancel(t, oid)
                counts["resized"] += state["open"]
                if lots > 0:
                    tape_id = insert(t, oid, old[1], old[2], lots, "G")
                    resting[oid] = [tape_id, old[1], old[2], lots, old[4]]
        touch(t)
        i += 1
    return rows, counts, touches


def book_check(touches: list[tuple], book_log: list[tuple], start_ns: int, seconds: int) -> dict:
    """The rebuilt best bid and ask against ABIDES's book log at the end of each second of the window."""
    t_rebuilt, t_log = [t for t, _, _ in touches], [t for t, _, _ in book_log]
    differ, spreads = 0, []
    for s in range(seconds):
        at = start_ns + (s + 1) * 1_000_000_000
        j, k = bisect.bisect_right(t_rebuilt, at) - 1, bisect.bisect_right(t_log, at) - 1
        mine = touches[j][1:] if j >= 0 else (None, None)
        theirs = book_log[k][1:] if k >= 0 else (None, None)
        differ += mine != theirs
        if theirs[0] is not None and theirs[1] is not None:
            spreads.append(theirs[1] - theirs[0])
    spreads.sort()
    return {"seconds_differing": differ, "spread_median": spreads[len(spreads) // 2] if spreads else None,
            "spread_mean": round(sum(spreads) / len(spreads), 2) if spreads else None}


def inside(args) -> None:
    """Runs RMSC04 under ABIDES's Python and writes the tape, the book path and the counts."""
    import numpy as np
    import pandas as pd
    from abides_core import abides
    from abides_core.utils import str_to_ns
    from abides_markets.configs import rmsc04

    start_ns_day, end_ns_day = str_to_ns(args.start), str_to_ns(args.end)
    run_end = pd.Timedelta(end_ns_day + args.tail * 1_000_000_000)
    run_end = f"{run_end.components.hours:02d}:{run_end.components.minutes:02d}:{run_end.components.seconds:02d}"
    config = rmsc04.build_config(seed=args.seed, end_time=run_end, stdout_log_level="WARNING", log_orders=False,
                                 **json.loads(args.options))
    end_state = abides.run(config, kernel_random_state=np.random.RandomState(seed=args.seed))
    book = end_state["agents"][0].order_books["ABM"]
    date = int(pd.to_datetime(json.loads(args.options).get("date", "20210205")).to_datetime64())
    start_ns, end_ns = date + start_ns_day, date + end_ns_day
    seconds = (end_ns - start_ns) // 1_000_000_000

    rows, counts, touches = to_tape(book.history, start_ns, end_ns)
    book_log = [(int(r["QuoteTime"]), int(r["bids"][0][0]) if len(r["bids"]) else None,
                 int(r["asks"][0][0]) if len(r["asks"]) else None) for r in book.book_log2]
    check = book_check(touches, book_log, start_ns, seconds)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(HEADER)
        writer.writerows(rows)
    t_log = [t for t, _, _ in book_log]
    with out.with_suffix(".book.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["second", "bid", "ask"])
        for s in range(seconds):
            k = bisect.bisect_right(t_log, start_ns + (s + 1) * 1_000_000_000) - 1
            writer.writerow([s + 1, *(("" if v is None else v) for v in (book_log[k][1:] if k >= 0 else (None, None)))])
    meta = {"seed": args.seed, "start": args.start, "end": args.end, "options": json.loads(args.options), "rows": len(rows),
            "span_s": float(rows[-1][0]) if rows else 0.0, "trades_per_s": round(counts["execs"] / seconds, 3),
            **counts, **check}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1) + "\n")
    print(json.dumps(meta))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m experiments.abides_tape")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--start", default="10:00:00", help="the window's start (RMSC04 opens at 09:30)")
    parser.add_argument("--end", default="11:00:00", help="the window's end")
    parser.add_argument("--tail", type=int, default=300, help="seconds RMSC04 runs past the window")
    parser.add_argument("--options", default="{}", help="RMSC04's build_config arguments, a JSON object")
    parser.add_argument("--out", type=Path, help="the tape (default data/arena/abides/abides_seed<S>.csv)")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inside:
        inside(args)
        return
    python = ENV / "bin" / "python"
    if not python.exists() or not (ABIDES / "abides-markets").exists():
        sys.exit("needs references/abides-jpmc and data/abides/env: references/clone.sh, then "
                 "uv run python -m experiments.abides_days setup")
    out = (args.out or OUT / f"abides_seed{args.seed}.csv").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ABIDES / "abides-core"), str(ABIDES / "abides-markets"), str(EXPORT)])}
    subprocess.run([str(python), str(Path(__file__).resolve()), "--inside", "--seed", str(args.seed), "--start", args.start,
                    "--end", args.end, "--tail", str(args.tail), "--options", args.options, "--out", str(out)],
                   check=True, env=env, cwd=out.parent)


if __name__ == "__main__":
    main()
