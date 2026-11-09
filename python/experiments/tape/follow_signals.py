"""Does following the tape pay on a qminers tape? A price-time replay of the tape alone (`tape_book`, no bot) gives the
touch at every event that moves it or trades; on it, with no queue and our orders taking at the touch 5 ms after the
signal (the first event at or after it), held at N lots and marked at the mid:
- the mid's move after an aggressive order by its size (ticks its way, from the mid just after it);
- the big-order follower (R2-M2): N lots the way of the last aggressive order of K+ lots, alone and with R2-M2's
  self-gate (trade only while a one-lot shadow is up more than 10 ticks since the start);
- time-series momentum (R2-M1): N lots the way the mid has moved over the last L s, once it has moved X ticks, held
  until X the other way;
- a shuffle test of the momentum: the same rule on the 1-s grid against the tape's 1-s moves shuffled in blocks of 1
  and 30 s (PnL z against 100 shuffles).
Each PnL split into the first 75% / last 25% of the time and into six segments. The simulator's numbers are within
~10-15% of these (R2-M2 at K 500: 104k here, 117k in the simulator; R2-M1 at 90 s / 8 ticks: 50k against 47k).

    uv run python -m experiments.tape.follow_signals data/arena/round2/round2_public.csv [--n 100] [--no-shuffle]
"""

from __future__ import annotations

import argparse

import numpy as np

from experiments.tape.tape_book import Book


def replay(path: str) -> dict:
    book = Book()
    rows = []
    last = (None, None)
    with open(path) as fh:
        next(fh)
        for line in fh:
            t, op, oid, side, vol, price, life = line.rstrip("\n").split(",")
            traded = 0
            if op == "Insert":
                sd = 0 if side == "B" else 1
                traded = book.insert(oid, sd, int(price), int(vol), life == "F")
                if sd == 1:
                    traded = -traded
            else:
                book.cancel(oid)
            bb, ba = book.best
            if bb is None or ba is None:
                continue
            if traded or (bb, ba) != last:
                rows.append((float(t), bb, ba, traded))
                last = (bb, ba)
    a = np.array(rows, dtype=float)
    return {"t": a[:, 0], "bid": a[:, 1], "ask": a[:, 2], "flow": a[:, 3]}


class Tape:
    def __init__(self, d: dict) -> None:
        self.t, self.bid, self.ask, self.flow = d["t"], d["bid"], d["ask"], d["flow"]
        self.mid = (self.bid + self.ask) / 2
        t = self.t
        self.n = len(t)
        self.lag = np.minimum(np.searchsorted(t, t + 0.005), self.n - 1)
        self.segs = [np.searchsorted(t, t[0] + k * (t[-1] - t[0]) / 6) for k in range(1, 6)]
        self.icut = np.searchsorted(t, t[0] + 0.75 * (t[-1] - t[0]))

    def ffill(self, s: np.ndarray) -> np.ndarray:
        idx = np.where(~np.isnan(s), np.arange(self.n), 0)
        np.maximum.accumulate(idx, out=idx)
        out = s[idx]
        out[np.isnan(out)] = 0
        return out

    def pnl_path(self, target: np.ndarray) -> tuple[np.ndarray, float]:
        dp = np.diff(np.concatenate([[0.0], target]))
        px = np.where(dp > 0, self.ask[self.lag], self.bid[self.lag])
        cash = -np.cumsum(dp * px)
        return cash + target * self.mid[self.lag], float(np.abs(dp).sum())

    def report(self, name: str, target: np.ndarray) -> None:
        pnl, lots = self.pnl_path(np.round(target))
        pts = [0.0] + [pnl[s] for s in self.segs] + [pnl[-1]]
        seg = np.diff(pts)
        print(f"  {name:34} pnl {pnl[-1]:10,.0f}  in {pnl[self.icut]:10,.0f}  out {pnl[-1] - pnl[self.icut]:9,.0f}  "
              f"lots {lots:9,.0f}  segments + {(seg > 0).sum()}/6: " + " ".join(f"{s:,.0f}" for s in seg))

    def big(self, k: float) -> np.ndarray:
        f = self.flow
        return self.ffill(np.where(f >= k, 1.0, np.where(f <= -k, -1.0, np.nan)))

    def back(self, seconds: float) -> np.ndarray:
        j = np.maximum(np.searchsorted(self.t, self.t - seconds, side="right") - 1, 0)
        r = self.mid - self.mid[j]
        r[self.t - self.t[0] < seconds] = 0
        return r

    def band(self, r: np.ndarray, x: float) -> np.ndarray:
        return self.ffill(np.where(r >= x, 1.0, np.where(r <= -x, -1.0, np.nan)))


def grid_band(path: np.ndarray, lookback: int, x: float, n: int, half: float) -> float:
    r = np.zeros(len(path))
    r[lookback:] = path[lookback:] - path[:-lookback]
    s = np.where(r >= x, 1.0, np.where(r <= -x, -1.0, np.nan))
    idx = np.where(~np.isnan(s), np.arange(len(s)), 0)
    np.maximum.accumulate(idx, out=idx)
    s = s[idx]
    s[np.isnan(s)] = 0
    pos = s * n
    dp = np.diff(np.concatenate([[0.0], pos]))
    return float((pos[:-1] * np.diff(path)).sum() - np.abs(dp).sum() * half)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tape")
    parser.add_argument("--n", type=int, default=100, help="lots held")
    parser.add_argument("--no-shuffle", action="store_true")
    args = parser.parse_args()
    tape = Tape(replay(args.tape))
    t, mid, flow, n = tape.t, tape.mid, tape.flow, args.n
    print(f"{args.tape}: {t[-1] - t[0]:,.0f} s, {tape.n:,} touch events, mean spread at them {np.mean(tape.ask - tape.bid):.2f}")

    print("mid move after an aggressive order, by its lots (ticks its way; first 75% / last 25% at 5 s)")
    fwd = {h: mid[np.minimum(np.searchsorted(t, t + h), tape.n - 1)] - mid for h in (1, 5, 30)}
    cut = t[0] + 0.75 * (t[-1] - t[0])
    edges = [1, 58, 200, 333, 500, 800, 1500, 10**9]
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (np.abs(flow) >= lo) & (np.abs(flow) < hi)
        s = np.sign(flow)
        a, b = m & (t < cut), m & (t >= cut)
        print(f"  [{lo:>5}, {hi if hi < 10**9 else 'inf':>5})  n {m.sum():6,}  1 s {(s * fwd[1])[m].mean():+.2f}  "
              f"5 s {(s * fwd[5])[m].mean():+.2f}  30 s {(s * fwd[30])[m].mean():+.2f}   "
              f"5 s {(s * fwd[5])[a].mean():+.2f} / {(s * fwd[5])[b].mean():+.2f}")

    print(f"big-order follower (R2-M2), {n} lots")
    for k in (333, 500, 800):
        s = tape.big(k)
        tape.report(f"K {k}", n * s)
        shadow, _ = tape.pnl_path(s)
        tape.report(f"K {k}, self-gated", n * s * (shadow > 10))

    print(f"time-series momentum (R2-M1), {n} lots")
    for lookback in (60, 120):
        r = tape.back(lookback)
        for x in (8, 12, 16):
            tape.report(f"L {lookback} s, X {x}", n * tape.band(r, x))

    if not args.no_shuffle:
        grid = np.arange(t[0], t[-1], 1.0)
        idx = np.searchsorted(t, grid, side="right") - 1
        path = mid[idx]
        half = float(np.mean((tape.ask - tape.bid)[idx])) / 2
        inc = np.diff(path)
        rng = np.random.default_rng(1)
        print("momentum against shuffled 1-s moves (1-s grid, cost half the mean spread a lot)")
        for lookback, x in ((60, 8), (120, 12)):
            real = grid_band(path, lookback, x, n, half)
            line = f"  L {lookback} s, X {x}: real {real:,.0f}"
            for block in (1, 30):
                nb = len(inc) // block
                sims = []
                for _ in range(100):
                    p = inc[: nb * block].reshape(nb, block)[rng.permutation(nb)].ravel()
                    sims.append(grid_band(np.concatenate([[path[0]], path[0] + np.cumsum(p)]), lookback, x, n, half))
                sims = np.array(sims)
                line += f";  blocks {block} s: mean {sims.mean():,.0f} sd {sims.std():,.0f} z {(real - sims.mean()) / sims.std():+.2f}"
            print(line)


if __name__ == "__main__":
    main()
