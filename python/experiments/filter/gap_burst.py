"""A burst over the 100-lot limit triggered by the latent gap, offline (8 Nov, round 3; IDEAS.md, "A gap-triggered
burst over the limit").

Round 2's private winner held ~8x our exposure at big jumps. Earlier triggers (forecast, book jumps, quiet trades) lost
because they fire after the jump, when the far side is thin. Here the trigger is the gap between the latent price and
the mid: the true latent of a generated tape (`--latent`, tape_gen --latent-out: the oracle) or the bot's causal filter
(latent_filter.LatentFilter with the bot's settings, FILTER_DEPTH 6 and FILTER_IMPACT 3).

Every 10 ms each (G, h) machine looks at gap = latent - mid. Idle, when |gap| first reaches G (it was below G at the
previous 10 ms), it buys (gap > 0) or sells at t + 5 ms (the starter's latency: after every tape event before t + 5 ms)
against the replayed book (tape_book.Book, not modified by our orders), taking levels up to mid + f * gap (f each of
--lim) until X lots (each of --sizes). It holds until dir * gap <= --close ticks or h s, then sells back at that
moment + 5 ms through every level of the near side. The burst's lots are counted over the limit (a base at the limit
in the jump's direction): the penalty is 10,000 a second from the entry fill to the exit fill, whatever the lots.
The book is the tape's own, so the base bot's take at the same moment (which would eat the same depth) is ignored:
the fills are an upper bound.

    uv run python -m experiments.filter.gap_burst TAPE.csv [--latent TAPE_latent.csv] [--G 3,5,8] [--hold 0.2,1,5]
        [--sizes 200,400,900] [--lim 0.5,1.0] [--filter W=30,depth=30] [--delay 0.05]
        [--per-trigger out.csv --pt-size 400 --pt-lim 1.0] [--jumps 20 --jump-cfg 5:2,7:0.5]

`--jumps J` adds a table of the mid's J-tick jumps (500 ms look-back, onsets 2 s apart) with, per (G, h) cell, the
first trigger in the jump's direction from 1 s before the onset to 0.2 s after it, at --pt-size / --pt-lim.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

from experiments.filter.latent_filter import make_filter
from experiments.tape.tape_book import Book

STEP = 0.01
LATENCY = 0.005
PENALTY = 10_000.0
BOT_FILTER = {"W": 8, "rate": 2.0, "eps": 0.01, "pi0": 0.55, "pi1": 0.39, "pi2": 0.06, "impact_scale": 3.0, "depth": 6}


def sweep(book: Book, side: int, lots: int, limit: float | None) -> tuple[int, int]:
    """Take up to `lots` from `side` (1 asks: a buy, 0 bids: a sell), prices no worse than `limit`; (lots, cash)."""
    vol = book.vol[side]
    got = cash = 0
    for p in (sorted(vol) if side == 1 else sorted(vol, reverse=True)):
        if limit is not None and ((side == 1 and p > limit) or (side == 0 and p < limit)):
            break
        q = min(vol[p], lots - got)
        got += q
        cash += q * p
        if got >= lots:
            break
    return got, cash


class Machine:
    """One (G, h): its trades, each (t_trig, dir, gap, mid, t_in, fills {(f, X): (lots, cash)}, t_out, exits)."""

    def __init__(self, G: float, h: float):
        self.G, self.h = G, h
        self.state = 0  # 0 idle, 1 entry pending, 2 holding, 3 exit pending
        self.trades = []
        self.cur = None


def run(path: Path, latent: Path | None, Gs, holds, sizes, lims, close: float, fparams: dict | None = None,
        delay: float = 0.0):
    lat = jumps = None
    if latent is not None:
        arr = np.loadtxt(latent, delimiter=",", skiprows=1)
        lat, jumps = arr[:, 1], arr[:, 3]
        cum_jump = np.concatenate(([0.0], np.cumsum(jumps)))
    filt = None if latent is not None else make_filter({**BOT_FILTER, **(fparams or {})})
    book = Book()
    machines = [Machine(G, h) for G in Gs for h in holds]
    prev_abs = 0.0
    next_g = STEP
    pending = []  # (t_fill, machine, kind)
    last_bb = last_ba = None
    n_grid = 0
    mids = []  # (t, mid) every 10 ms: the jumps' table

    def on_grid(tg: float):
        nonlocal prev_abs, n_grid
        n_grid += 1
        if last_bb is None or last_ba is None or last_bb >= last_ba:
            return
        mid = (last_bb + last_ba) / 2
        mids.append((tg, mid))
        if lat is not None:
            i = min(int(round(tg / STEP)), len(lat) - 1)
            gap = lat[i] - mid
        else:
            if filt.p is None:
                return
            gap = filt.moments()[0] + 0.5 - mid
        a = abs(gap)
        for m in machines:
            if m.state == 0:
                if a >= m.G > prev_abs:
                    d = 1 if gap > 0 else -1
                    jsum = 0.0
                    if lat is not None:
                        i = min(int(round(tg / STEP)), len(lat) - 1)
                        jsum = float(cum_jump[i + 1] - cum_jump[max(0, i - 99)])
                    m.cur = {"t": tg, "dir": d, "gap": gap, "mid": mid, "jump1s": jsum}
                    m.state = 1
                    pending.append((tg + delay + LATENCY, m, "in"))
            elif m.state == 2:
                d = m.cur["dir"]
                if d * gap <= close or tg - m.cur["t_in"] >= m.h - 1e-9:
                    m.cur["why"] = "close" if d * gap <= close else "hold"
                    m.state = 3
                    pending.append((tg + LATENCY, m, "out"))
        prev_abs = a

    def on_fill(m: Machine, kind: str):
        c = m.cur
        d = c["dir"]
        if kind == "in":
            c["t_in"] = tf
            fills = {}
            for f in lims:
                limit = c["mid"] + f * c["gap"]
                for X in sizes:
                    fills[(f, X)] = sweep(book, 1 if d > 0 else 0, X, limit)
            c["fills"] = fills
            c["mid_in"] = (book.best[0] + book.best[1]) / 2 if None not in book.best else c["mid"]
            m.state = 2
        else:
            c["t_out"] = tf
            exits = {}
            for key, (lots, cash) in c["fills"].items():
                if lots == 0:
                    exits[key] = (0, 0, 0)
                    continue
                got, back = sweep(book, 0 if d > 0 else 1, lots, None)
                short = lots - got
                if short:  # the near side ran out: value the rest at its worst level
                    worst = (min(book.vol[0]) if d > 0 else max(book.vol[1])) if book.vol[0 if d > 0 else 1] else c["mid"]
                    back += short * worst
                exits[key] = (got, back, short)
            c["exits"] = exits
            m.trades.append(c)
            m.cur = None
            m.state = 0

    with path.open() as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            t = float(t)
            # the 10-ms grid and our fills due before this event, in time order
            while True:
                tp = min(pending, key=lambda x: x[0])[0] if pending else 1e18
                if next_g <= t and next_g <= tp:
                    on_grid(next_g)
                    next_g += STEP
                    # round to the grid to avoid drift
                    next_g = round(next_g, 2)
                elif tp <= t:
                    item = min(pending, key=lambda x: x[0])
                    pending.remove(item)
                    tf = item[0]
                    on_fill(item[1], item[2])
                else:
                    break
            bb, ba = book.best
            if op == "Insert":
                sd_ = 0 if side == "B" else 1
                p_, q_ = int(price), int(vol)
                if life == "F":
                    fills = []
                    book.insert(oid, sd_, p_, q_, True, fills)
                    lots = sum(f[1] for f in fills)
                    if filt is not None and lots and filt.p is not None:
                        filt.advance(t)
                        filt.trade(1 if sd_ == 0 else -1, lots)
                else:
                    if filt is not None and bb is not None and ba is not None and bb < ba:
                        if filt.p is None:
                            filt.reset(bb)
                        filt.advance(t)
                        filt.recenter(bb)
                        if abs(p_ - (bb if sd_ == 0 else ba)) <= filt.depth:
                            filt.insert(sd_, p_, bb, ba)
                    book.insert(oid, sd_, p_, q_, False)
            else:
                book.cancel(oid)
            last_bb, last_ba = book.best
    run.mids = mids
    return machines


def jump_table(machines, mids, J: float, cfgs, key):
    """The mid's jumps (J+ ticks from its value 500 ms before, onsets 2 s apart) and, per (G, h) in cfgs, the first
    trigger in the jump's direction from 1 s before the onset to 0.2 s after it: when, its lots, gross, penalty, net."""
    t = np.array([x[0] for x in mids])
    m = np.array([x[1] for x in mids])
    lag = 50
    jumps = []
    last = -1e9
    for i in range(lag, len(t)):
        d = m[i] - m[i - lag]
        if abs(d) >= J and t[i] - last >= 2.0:
            j1 = min(len(t) - 1, i + 100)
            jumps.append((t[i], 1 if d > 0 else -1, d, m[j1] - m[i]))
            last = t[i]
    by = {(mm.G, mm.h): mm for mm in machines}
    out = []
    for tj, dj, d, after in jumps:
        row = {"t": round(tj, 2), "dir": dj, "move_500ms": round(d, 1), "then_1s": round(dj * after, 1)}
        for G, h in cfgs:
            mm = by.get((G, h))
            hit = None
            for c in mm.trades if mm else ():
                if "exits" in c and c["dir"] == dj and tj - 1.0 <= c["t"] <= tj + 0.2:
                    hit = c
                    break
            if hit is None:
                row[f"G{G:g}h{h:g}"] = "-"
                continue
            q, cash = hit["fills"][key]
            got, back, short = hit["exits"][key]
            gross = dj * (back - cash) if q else 0
            pen = PENALTY * (hit["t_out"] - hit["t_in"]) if q else 0
            row[f"G{G:g}h{h:g}"] = f"{hit['t'] - tj:+.2f}s {q}l g{gross:.0f} p{pen:.0f} n{gross - pen:.0f}"
        out.append(row)
    return out


def summarise(machines, sizes, lims, tape_s: float):
    rows = []
    for m in machines:
        for f in lims:
            for X in sizes:
                n = n_lots = lots = 0
                gross = pen = 0.0
                n_close = 0
                for c in m.trades:
                    if "exits" not in c:
                        continue
                    n += 1
                    q, cash = c["fills"][(f, X)]
                    if q == 0:
                        continue
                    n_lots += 1
                    lots += q
                    got, back, short = c["exits"][(f, X)]
                    gross += c["dir"] * (back - cash)
                    pen += PENALTY * (c["t_out"] - c["t_in"])
                    n_close += c["why"] == "close"
                rows.append({"G": m.G, "h": m.h, "lim": f, "X": X, "triggers": n, "with_lots": n_lots,
                             "lots": lots, "lots_per": round(lots / n_lots, 1) if n_lots else 0,
                             "gross": round(gross), "penalty": round(pen), "net": round(gross - pen),
                             "tick_per_lot": round(gross / lots, 2) if lots else 0.0, "closed": n_close})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tape", type=Path)
    ap.add_argument("--latent", type=Path)
    ap.add_argument("--G", default="3,5,8,12,20")
    ap.add_argument("--hold", default="0.2,0.5,1,2,5")
    ap.add_argument("--sizes", default="200,400,900")
    ap.add_argument("--lim", default="0.5,1.0")
    ap.add_argument("--close", type=float, default=1.0)
    ap.add_argument("--filter", default="", help="the causal filter's settings over the bot's, K=V,... (e.g. W=30,depth=30)")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds added before the entry order (a slower trigger)")
    ap.add_argument("--out", type=Path, help="the summary as CSV")
    ap.add_argument("--per-trigger", type=Path, help="every trigger of every (G, h) at --pt-size / --pt-lim as CSV")
    ap.add_argument("--pt-size", type=int, default=400)
    ap.add_argument("--pt-lim", type=float, default=1.0)
    ap.add_argument("--jumps", type=float, default=0, help="J > 0: the per-jump table for the mid's J-tick jumps")
    ap.add_argument("--jump-cfg", default="5:2", help="the (G, h) cells of the per-jump table, G:h,...")
    args = ap.parse_args(argv)
    Gs = [float(x) for x in args.G.split(",")]
    holds = [float(x) for x in args.hold.split(",")]
    sizes = [int(x) for x in args.sizes.split(",")]
    lims = [float(x) for x in args.lim.split(",")]
    fparams = {k: float(v) for k, v in (kv.split("=") for kv in args.filter.split(",") if kv)}
    machines = run(args.tape, args.latent, Gs, holds, sizes, lims, args.close, fparams, args.delay)
    rows = summarise(machines, sizes, lims, 0.0)
    w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    if args.out:
        with args.out.open("w", newline="") as fh:
            w2 = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w2.writeheader()
            w2.writerows(rows)
    if args.per_trigger:
        key = (args.pt_lim, args.pt_size)
        with args.per_trigger.open("w", newline="") as fh:
            w3 = csv.writer(fh)
            w3.writerow(["G", "h", "t", "dir", "gap", "mid", "jump1s", "mid_in", "lots", "avg_in", "t_out", "why",
                         "avg_out", "short", "gross", "penalty", "net"])
            for m in machines:
                for c in m.trades:
                    if "exits" not in c:
                        continue
                    q, cash = c["fills"][key]
                    got, back, short = c["exits"][key]
                    gross = c["dir"] * (back - cash) if q else 0
                    pen = PENALTY * (c["t_out"] - c["t_in"]) if q else 0.0
                    w3.writerow([m.G, m.h, round(c["t"], 2), c["dir"], round(c["gap"], 2), c["mid"], round(c["jump1s"], 1),
                                 c["mid_in"], q, round(cash / q, 2) if q else "", round(c["t_out"], 3), c["why"],
                                 round(back / q, 2) if q else "", short, round(gross), round(pen), round(gross - pen)])
    if args.jumps > 0:
        cfgs = [tuple(float(x) for x in c.split(":")) for c in args.jump_cfg.split(",")]
        table = jump_table(machines, run.mids, args.jumps, cfgs, (args.pt_lim, args.pt_size))
        print(f"\njumps of {args.jumps:g}+ ticks in 500 ms: {len(table)}; per cell: trigger time vs onset, lots, gross, penalty, net")
        for r in table:
            print("  ".join(str(v) for v in r.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
