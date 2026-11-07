"""Does the best-level imbalance predict the price on Prosperity data? Gould & Bonart's test, per product and day.

usage (from the repo root): uv run python -m experiments.day.imbalance
       uv run python -m experiments.day.imbalance --data DIR --days 1 2 [--format F --products A,B]

The imbalance is `ρ = (Vᵇ − Vᵃ)/(Vᵇ + Vᵃ)` at the best bid and ask
(references/wiki/concepts/book-imbalance-and-micro-price.md). For each product of the
market-making rounds (DATASETS), three tests:

1. Gould & Bonart: at each tick where the mid changes, `y` = up, against `ρ` one tick before.
   A logistic regression `P(up) = 1/(1 + e^-(x0 + x1 ρ))`, fitted leaving one day out. Reports
   the ROC area and the drop in squared error against a coin flip (0.25), out of sample, the
   sign of `x1` fitted on each day alone, and the same split by spread (in ticks).
2. Fair value: how well each candidate at tick t predicts the wall mid (the market maker's
   price, which the template trades back at) and the mid (Prosperity's mark) H ticks later.
   Root mean squared error, pooled over the days. Candidates: mid, wall_mid, sized_mid (15),
   the weighted mid `W = I·Pᵃ + (1 − I)·Pᵇ` with `I = Vᵇ/(Vᵇ + Vᵃ)`, and `wall_mid + b·ρ`
   with `b` fitted by least squares leaving one day out (the linear micro-price), the same with ρ
   over the best DEPTH levels (`wall_mid + b·ρ3`, added 2026-10-26 after section 4), and
   `wall_mid + G(ρ, spread)`, Stoikov's form: the mean move in each of 5 ρ buckets × the spread
   buckets, also leaving one day out (the micro-price's table at horizon H, without his
   symmetrising or Markov-chain step, so it can only fit better in sample).
3. The fitted `b` per day, in ticks per unit of ρ, at each horizon: a stable sign and size is
   what a `PARAMS` entry would need.
4. Order flow (Cont et al.'s OFI, decomposed as Sitaru et al. do) and how far ahead each signal
   reads: between consecutive snapshots, the best levels' **adds** (a bid queue growing or a new
   higher bid, less the same at the ask) and **removals** (an ask queue shrinking or the best ask
   gone up, less the same at the bid), their sum the OFI, and the tick's **trades** (signed market
   volume, classified against its own book as arena.diagnose does), next to ρ and the depth
   imbalance over the best 3 levels (ρ3). Each at tick t against the wall mid's and the mid's change
   from t to t + h, for h in FLOW_HORIZONS: the correlation averaged over the days, whether every
   day has its sign, and the move one standard deviation of the signal predicts, in ticks. Prosperity's
   trades don't line up with the book's changes (the generator redraws the book each tick), so
   removals can't be split into cancels and trades as on an order-by-order feed.
Results go into IDEAS.md ("The micro-price or weighted mid as fair value", "Book imbalance",
"Order flow decomposed, and how far ahead it reads").

With --data (the day's download) every product there (or --products) is studied on those days;
prices stay in the data's unit, and the spread is in each product's ticks (Day.info).
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections import defaultdict

from arena.cli import add_dataset_arguments, dataset_from
from arena.formats import FORMATS

DATASETS = [  # (data alias, round, products): the rounds whose products the template makes markets in
    ("p2", "1", ["AMETHYSTS", "STARFRUIT"]),
    ("p3", "1", ["RAINFOREST_RESIN", "KELP", "SQUID_INK"]),
    ("p3", "5", ["RAINFOREST_RESIN", "KELP", "SQUID_INK"]),
    ("p4", "1", ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]),
    ("p4", "2", ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]),
]
HORIZONS = (1, 10, 50)
FLOW_HORIZONS = (1, 5, 20, 100)
FLOW_SIGNALS = ("rho", "rho3", "adds", "removals", "ofi", "trades")
DEPTH = 3  # levels in rho3
WALL_SIZE = 15
RHO_BUCKETS = 5
TABLE = "wall_mid + G(ρ, spread)"


def imbalance(book) -> float:
    vb, va = book.bids[0][1], book.asks[0][1]
    return (vb - va) / (vb + va)


def sized_mid(book) -> float:
    bid = next((p for p, v in book.bids if v >= WALL_SIZE), book.bids[0][0])
    ask = next((p for p, v in book.asks if v >= WALL_SIZE), book.asks[0][0])
    return (bid + ask) / 2


def depth_imbalance(book) -> float:
    """ρ over the best DEPTH levels of each side."""
    vb, va = sum(v for _, v in book.bids[:DEPTH]), sum(v for _, v in book.asks[:DEPTH])
    return (vb - va) / (vb + va)


def weighted_mid(book) -> float:
    i = book.bids[0][1] / (book.bids[0][1] + book.asks[0][1])
    return i * book.asks[0][0] + (1 - i) * book.bids[0][0]


def series(day, product) -> list[dict]:
    """Per tick with both sides present: ρ, spread (in ticks) and the candidate prices."""
    info = day.info.get(product, {})
    unit = round(info["tick"] / info["unit"]) if "tick" in info and "unit" in info else 1  # the tick in the data's unit
    out = []
    for tick in day.ticks:
        book = tick.books.get(product)
        if book is None or not book.bids or not book.asks:
            out.append(None)
            continue
        out.append({
            "rho": imbalance(book), "rho3": depth_imbalance(book), "spread": (book.asks[0][0] - book.bids[0][0]) / unit,
            "mid": book.mid, "wall_mid": book.wall_mid, "sized_mid": sized_mid(book), "weighted": weighted_mid(book),
        })
    return out


def flows(day, product) -> list[dict | None]:
    """Per tick with both sides present (and the tick before it): section 4's signals, and the wall mid
    and the mid in the product's ticks."""
    info = day.info.get(product, {})
    unit = round(info["tick"] / info["unit"]) if "tick" in info and "unit" in info else 1
    out, prev = [], None
    for tick in day.ticks:
        book = tick.books.get(product)
        if book is None or not book.bids or not book.asks:
            out.append(None)
            prev = None
            continue
        (pb, qb), (pa, qa) = book.bids[0], book.asks[0]
        row = None
        if prev is not None:
            (ppb, pqb), (ppa, pqa) = prev.bids[0], prev.asks[0]
            add_b, rem_b = (qb, 0) if pb > ppb else (0, pqb) if pb < ppb else (max(qb - pqb, 0), max(pqb - qb, 0))
            add_a, rem_a = (qa, 0) if pa < ppa else (0, pqa) if pa > ppa else (max(qa - pqa, 0), max(pqa - qa, 0))
            signed = sum(t.quantity * (1 if t.price >= pa else -1) for t in tick.trades.get(product, []) if t.price >= pa or t.price <= pb)
            row = {"rho": imbalance(book), "rho3": depth_imbalance(book), "adds": add_b - add_a, "removals": rem_a - rem_b,
                   "ofi": add_b - add_a + rem_a - rem_b, "trades": signed, "spread": (pa - pb) / unit,
                   "wall_mid": book.wall_mid / unit if book.wall_mid is not None else None, "mid": book.mid / unit}
        out.append(row)
        prev = book
    return out


def flow_study(days: list, product: str) -> dict:
    """Section 4: per signal, target and horizon, the correlation per day and pooled, and the move one sd predicts."""
    rows = [flows(day, product) for day in days]
    out = {"half": statistics.median([r["spread"] for day in rows for r in day if r]) / 2 if any(r for day in rows for r in day) else None}
    for target in ("wall_mid", "mid"):
        for h in FLOW_HORIZONS:
            for signal in FLOW_SIGNALS:
                per_day, xs, ys = [], [], []
                for day in rows:
                    pairs = [(r[signal], day[k + h][target] - r[target]) for k, r in enumerate(day[:-h])
                             if r and day[k + h] and r[target] is not None and day[k + h][target] is not None]
                    x, y = [p[0] for p in pairs], [p[1] for p in pairs]
                    try:
                        per_day.append(statistics.correlation(x, y))
                    except statistics.StatisticsError:
                        per_day.append(None)
                    xs += x
                    ys += y
                known = [c for c in per_day if c is not None]
                mean = statistics.fmean(known) if known else None
                steady = bool(known) and len(known) == len(per_day) and (all(c > 0 for c in known) or all(c < 0 for c in known))
                move = mean * statistics.pstdev(ys) if mean is not None and len(ys) > 1 else None
                out[(target, h, signal)] = {"corr": mean, "days": per_day, "steady": steady, "move": move}
    return out


def logistic(xs: list[float], ys: list[int], steps: int = 25) -> tuple[float, float]:
    """Fit P(y=1) = 1/(1 + e^-(a + b x)) by Newton's method."""
    a = b = 0.0
    for _ in range(steps):
        ga = gb = haa = hab = hbb = 0.0
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(a + b * x)))
            w = p * (1 - p)
            ga += y - p
            gb += (y - p) * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        if det <= 1e-12:
            break
        a += (hbb * ga - hab * gb) / det
        b += (haa * gb - hab * ga) / det
    return a, b


def auc(scores: list[float], ys: list[int]) -> float:
    """ROC area by ranks, ties counted half."""
    pairs = sorted(zip(scores, ys))
    pos = sum(ys)
    neg = len(ys) - pos
    if not pos or not neg:
        return float("nan")
    rank_sum, k = 0.0, 0
    while k < len(pairs):
        j = k
        while j < len(pairs) and pairs[j][0] == pairs[k][0]:
            j += 1
        mean_rank = (k + 1 + j) / 2
        rank_sum += mean_rank * sum(y for _, y in pairs[k:j])
        k = j
    return (rank_sum - pos * (pos + 1) / 2) / (pos * neg)


def moves(rows: list[dict | None]) -> list[tuple[float, int, float]]:
    """(ρ before, up?, spread before) at each tick where the mid changes."""
    out = []
    for prev, cur in zip(rows, rows[1:]):
        if prev and cur and cur["mid"] != prev["mid"]:
            out.append((prev["rho"], int(cur["mid"] > prev["mid"]), prev["spread"]))
    return out


def ols_slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope through the origin (the move is centred on the current price)."""
    den = sum(x * x for x in xs)
    return sum(x * y for x, y in zip(xs, ys)) / den if den else 0.0


def ahead(rows: list[dict | None], h: int, target: str) -> list[tuple[dict, float]]:
    return [(r, rows[k + h][target]) for k, r in enumerate(rows[:-h]) if r and rows[k + h]]


def rho_bucket(rho: float) -> int:
    return min(int((rho + 1) / 2 * RHO_BUCKETS), RHO_BUCKETS - 1)


def spread_bucket(s: float) -> str:
    return "1-2" if s <= 2 else "3-5" if s <= 5 else "6-9" if s <= 9 else "10+"


def study(days: list, product: str) -> dict:
    rows = [series(day, product) for day in days]
    out: dict = {"days": [d.name for d in days]}

    # 1. Gould & Bonart, leave one day out.
    per_day = [moves(r) for r in rows]
    out["slopes"] = [logistic([x for x, _, _ in m], [y for _, y, _ in m])[1] for m in per_day]
    scores, ys, spreads = [], [], []
    for k, test in enumerate(per_day):
        train = [m for j, d in enumerate(per_day) if j != k for m in d]
        a, b = logistic([x for x, _, _ in train], [y for _, y, _ in train])
        for x, y, s in test:
            scores.append(1 / (1 + math.exp(-(a + b * x))))
            ys.append(y)
            spreads.append(s)
    out["n"] = len(ys)
    out["auc"] = auc(scores, ys)
    out["brier"] = 1 - sum((p - y) ** 2 for p, y in zip(scores, ys)) / len(ys) / 0.25 if ys else float("nan")
    by_spread = defaultdict(lambda: ([], []))
    for p, y, s in zip(scores, ys, spreads):
        by_spread[spread_bucket(s)][0].append(p)
        by_spread[spread_bucket(s)][1].append(y)
    out["by_spread"] = {k: (len(v[1]), auc(*v)) for k, v in by_spread.items()}

    # 2-3. Candidates as predictors of the wall mid and the mid H ticks later.
    out["rmse"], out["b"] = {}, {}
    for target in ("wall_mid", "mid"):
        for h in HORIZONS:
            pairs = [ahead(r, h, target) for r in rows]
            moves_by_day = [([r["rho"] for r, _ in p], [f - r["wall_mid"] for r, f in p]) for p in pairs]
            depth_by_day = [([r["rho3"] for r, _ in p], m[1]) for p, m in zip(pairs, moves_by_day)]
            out["b"][(target, h)] = [ols_slope(*m) for m in moves_by_day]
            err = defaultdict(float)
            count = 0
            for k, p in enumerate(pairs):
                xs = [x for j, m in enumerate(moves_by_day) if j != k for x in m[0]]
                dy = [y for j, m in enumerate(moves_by_day) if j != k for y in m[1]]
                b = ols_slope(xs, dy)
                b3 = ols_slope([x for j, m in enumerate(depth_by_day) if j != k for x in m[0]], dy)
                sums = defaultdict(lambda: [0.0, 0])
                for j, q in enumerate(pairs):
                    if j != k:
                        for r, future in q:
                            cell = sums[(rho_bucket(r["rho"]), spread_bucket(r["spread"]))]
                            cell[0] += future - r["wall_mid"]
                            cell[1] += 1
                table = {key: total / n for key, (total, n) in sums.items()}
                for r, future in p:
                    g = table.get((rho_bucket(r["rho"]), spread_bucket(r["spread"])), 0.0)
                    err[TABLE] += (r["wall_mid"] + g - future) ** 2
                    for name in ("mid", "wall_mid", "sized_mid", "weighted"):
                        err[name] += (r[name] - future) ** 2
                    err["wall_mid + b·ρ"] += (r["wall_mid"] + b * r["rho"] - future) ** 2
                    err["wall_mid + b·ρ3"] += (r["wall_mid"] + b3 * r["rho3"] - future) ** 2
                count += len(p)
            out["rmse"][(target, h)] = {name: math.sqrt(e / count) for name, e in err.items()}
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m experiments.day.imbalance")
    add_dataset_arguments(parser, bot=False)
    args = parser.parse_args(argv)
    try:
        dataset = dataset_from(args)
    except ValueError as error:
        parser.error(str(error))
    datasets = [(alias, f"r{rnd}", "prosperity", [rnd], products) for alias, rnd, products in DATASETS]
    if dataset:
        datasets = [(dataset.name, "", dataset.format, list(dataset.days), list(dataset.products))]
    results, flow_results = {}, {}
    for data, label, format_name, specs, products in datasets:
        fmt = FORMATS[format_name]
        days = fmt.load_days(fmt.resolve_data_dir(dataset.data if dataset else data), specs)
        for product in products:
            results[(data, label, product)] = study(days, product)
            flow_results[(data, label, product)] = flow_study(days, product)

    print("1. Gould & Bonart: the direction of the next mid change from ρ one tick before, leaving one day out.\n")
    print("| Data | Product | Mid changes | ROC area | Squared error vs a coin flip | x1 per day | ROC area by spread (ticks: n, area) |")
    print("|---|---|---|---|---|---|---|")
    for (alias, rnd, product), o in results.items():
        slopes = ", ".join(f"{s:+.2f}" for s in o["slopes"])
        spreads = "; ".join(f"{k}: {n:,}, {a:.2f}" for k, (n, a) in sorted(o["by_spread"].items()))
        print(f"| {(alias + " " + rnd).strip()} | {product} | {o['n']:,} | {o['auc']:.3f} | {o['brier'] * 100:+.1f}% | {slopes} | {spreads} |")

    for target in ("wall_mid", "mid"):
        print(f"\n2. Root mean squared error of each candidate against the {target} H ticks later (pooled over the days; "
              "b fitted leaving one day out).\n")
        names = ["mid", "wall_mid", "sized_mid", "weighted", "wall_mid + b·ρ", "wall_mid + b·ρ3", TABLE]
        print("| Data | Product | H | " + " | ".join(names) + " |")
        print("|---|---|---|" + "---|" * len(names))
        for (alias, rnd, product), o in results.items():
            for h in HORIZONS:
                r = o["rmse"][(target, h)]
                best = min(r.values())
                cells = [f"**{r[n]:.3f}**" if r[n] == best else f"{r[n]:.3f}" for n in names]
                print(f"| {(alias + " " + rnd).strip()} | {product} | {h} | " + " | ".join(cells) + " |")

    print("\n3. The fitted b (ticks of wall-mid move per unit of ρ) on each day alone, target the wall mid.\n")
    print("| Data | Product | " + " | ".join(f"H={h}" for h in HORIZONS) + " |")
    print("|---|---|" + "---|" * len(HORIZONS))
    for (alias, rnd, product), o in results.items():
        cells = [", ".join(f"{b:+.2f}" for b in o["b"][("wall_mid", h)]) for h in HORIZONS]
        print(f"| {(alias + " " + rnd).strip()} | {product} | " + " | ".join(cells) + " |")

    print("\n4. Order flow and how far ahead each signal reads: the correlation of the signal at t with the change from t to "
          "t + h, averaged over the days, wall mid / mid (* = the same sign on every day). Last column: the wall mid's move "
          f"one sd of the signal predicts at h = {FLOW_HORIZONS[1]}, in ticks, against the half-spread.\n")
    print("| Data | Product | Signal | " + " | ".join(f"h={h}" for h in FLOW_HORIZONS) + f" | move at {FLOW_HORIZONS[1]} / half-spread |")
    print("|---|---|---|" + "---|" * (len(FLOW_HORIZONS) + 1))
    for (alias, rnd, product), o in flow_results.items():
        for signal in FLOW_SIGNALS:
            cells = []
            for h in FLOW_HORIZONS:
                pair = [o[(target, h, signal)] for target in ("wall_mid", "mid")]
                cells.append(" / ".join("-" if r["corr"] is None else f"{r['corr']:+.2f}{'*' if r['steady'] else ''}" for r in pair))
            move = o[("wall_mid", FLOW_HORIZONS[1], signal)]["move"]
            tail = "-" if move is None or not o["half"] else f"{move:+.3f} / {o['half']:g}"
            print(f"| {(alias + " " + rnd).strip()} | {product} | {signal} | " + " | ".join(cells) + f" | {tail} |")


if __name__ == "__main__":
    main()
