"""Does anything predict the price? An extra feed against the wall mid, then a linear forecast from the book and the flow.

usage (from the repo root): uv run python -m experiments.day.predict [--part 1|2]
       uv run python -m experiments.day.predict --data DIR --days 1 2 [--format F --products A,B] [--part 1|2]

1. **A feed beyond the book** (an audit's idea 5; references/wiki: a fair term, not a forecast).
   Prosperity keeps one: P3 round 4's observations file (the foreign bid and ask, transport fees,
   tariffs, sugar price and sunlight index, for MAGNIFICENT_MACARONS), which arena.formats.prosperity
   doesn't load (the bot's state gets an empty Observation), so it is read here from the data folder:
   every `<kind>_round_R_day_D.csv` beside the prices and trades (a file with a `product` column
   applies to that product, one without to every --products). For each numeric column that moves
   within a day, against the product's wall mid:
     - its one-tick change against the wall mid's change at the same tick, and against the wall mid's
       move 1, 5, 20 and 100 ticks ahead (a lead), the mean correlation over the days and whether
       every day has its sign (*);
     - a leave-one-day-out fit of the wall mid's change over h ticks on the feed's change over the
       same h (through 0; non-overlapping windows): b, and its out-of-sample R². That is the fair
       term `fair += b × (feed − its level when the fair was last set)`, same tick, not a forecast;
     - an event study: around the feed's largest one-tick changes (above EVENT_QUANTILE of its
       non-zero changes), the wall mid's mean move in the change's direction from the tick before,
       at offsets −20 to +100 ticks: how much of it comes before, at, and after the change.
   On ABIDES's days the one extra file is the fundamental, the answer key no bot sees: it is read
   as a feed all the same, as an upper bound on what a feed could do.
2. **A linear forecast** (edge_ideas item 6): leave one day out, a ridge regression of the wall
   mid's move 1, 5, 20 and 100 ticks ahead (in ticks) on ρ and ρ3 (python/experiments/day/imbalance.py's
   imbalance and depth_imbalance), its flows (adds, removals, OFI, and the signed trades of the tick
   before: a tick's trades print after its snapshot, and a bot sees them a tick later), the wall mid's
   momentum over 1, 5, 20 and 100 ticks, the time of day, and every other product's 5-tick return.
   Features standardised on the training days, penalty RIDGE × the training rows. Per held-out day
   and pooled: the out-of-sample R², the move one sd of the forecast predicts (the slope of the move
   on the forecast × the forecast's sd) against the half-spread, and Sitaru et al.'s rule
   (references/wiki/sources/decomposed-ofi.md): trade only when the forecast beats half the spread
   at that tick; the mean move in the forecast's direction less that half-spread on those ticks,
   per day, and the share of ticks it trades. The trigger for a `linear` fair in the template is a
   move per sd above the half-spread with R² > 0 on every held-out day (IDEAS.md, "A `linear` fair").

Default: part 1 on P3 round 4 (MAGNIFICENT_MACARONS), part 2 on P3 round 1 and P4 rounds 1-2.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

from arena.cli import add_dataset_arguments, dataset_from
from arena.formats import FORMATS, prosperity
from experiments.day.imbalance import flows as _flows

_FLOWS: dict[tuple[int, str], tuple] = {}  # (id(day), product) -> (day, its flows): forecast_study per product reads every product's


def flows(day, product) -> list[dict | None]:
    """imbalance.flows, once per day and product (the day kept with it, so its id isn't reused)."""
    found = _FLOWS.get((id(day), product))
    if found is None or found[0] is not day:
        found = _FLOWS[(id(day), product)] = (day, _flows(day, product))
    return found[1]

FEED_DATASETS = [("p3", "4", ["MAGNIFICENT_MACARONS"])]
FORECAST_DATASETS = [
    ("p3", ["1"], ["RAINFOREST_RESIN", "KELP", "SQUID_INK"]),
    ("p4", ["1", "2"], ["ASH_COATED_OSMIUM", "INTARIAN_PEPPER_ROOT"]),
]
LEADS = (1, 5, 20, 100)
WINDOWS = (1, 20, 100)
OFFSETS = (-20, -5, -1, 0, 1, 5, 20, 100)
EVENT_QUANTILE = 0.99
HORIZONS = (1, 5, 20, 100)
MOMENTUM = (1, 5, 20, 100)
FLOW_FEATURES = ("rho", "rho3", "adds", "removals", "ofi", "trades")
RIDGE = 0.01


# ---------------------------------------------------------------------------- part 1: feeds


def wall_series(day, product: str) -> list[float | None]:
    out, last = [], None
    for tick in day.ticks:
        book = tick.books.get(product)
        if book is not None and book.bids and book.asks:
            last = book.wall_mid
        out.append(last)
    return out


def feed_files(day) -> list[Path]:
    """The extra files beside a Prosperity-layout day's prices and trades."""
    source = prosperity.source_of(day)
    if source is None:
        return []
    data_dir, rnd, num = source
    folder = data_dir / f"round{rnd}"
    return sorted(p for p in folder.glob(f"*_round_{rnd}_day_{num}.csv") if not p.name.startswith(("prices_", "trades_")))


def read_feed(path: Path, day, product: str) -> dict[str, list[float | None]]:
    """{column: value per tick of the day, carried forward} for the product (or every product if no product column)."""
    text = path.read_text()
    delimiter = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delimiter))
    if not rows or "timestamp" not in rows[0]:
        return {}
    if "product" in rows[0]:
        rows = [r for r in rows if r["product"] == product]
    columns = [c for c in rows[0] if c not in ("timestamp", "product", "day")] if rows else []
    by_time = {int(float(r["timestamp"])): r for r in rows}
    out = {}
    kind = path.name.split("_round_")[0]
    for column in columns:
        values, last = [], None
        for tick in day.ticks:
            r = by_time.get(tick.timestamp)
            if r is not None:
                try:
                    last = float(r[column])
                except (TypeError, ValueError):
                    pass
            values.append(last)
        out[f"{kind}.{column}"] = values
    return out


def _corr(xs, ys) -> float | None:
    try:
        return st.correlation(xs, ys)
    except st.StatisticsError:
        return None


def feed_study(days: list, product: str) -> dict:
    """Part 1 for one product: per feed column, the correlations, the leave-one-day-out change fit and the event study."""
    walls = [wall_series(day, product) for day in days]
    feeds = [{} for _ in days]
    for k, day in enumerate(days):
        for path in feed_files(day):
            feeds[k].update(read_feed(path, day, product))
    columns = sorted(set().union(*feeds)) if feeds else []
    out = {}
    for column in columns:
        xs = [f.get(column) for f in feeds]
        if any(x is None for x in xs):
            continue
        moving = [len({v for v in x if v is not None}) > 1 for x in xs]
        if not any(moving):
            out[column] = {"constant": True}
            continue
        res = {"constant": False, "same": [], "lead": {h: [] for h in LEADS}, "fit": {}, "events": None}
        for x, w in zip(xs, walls):
            n = len(w)
            pairs = [(x[i] - x[i - 1], w[i] - w[i - 1]) for i in range(1, n) if None not in (x[i], x[i - 1], w[i], w[i - 1])]
            res["same"].append(_corr([a for a, _ in pairs], [b for _, b in pairs]))
            for h in LEADS:
                pairs = [(x[i] - x[i - 1], w[i + h] - w[i]) for i in range(1, n - h) if None not in (x[i], x[i - 1], w[i + h], w[i])]
                res["lead"][h].append(_corr([a for a, _ in pairs], [b for _, b in pairs]))
        for h in WINDOWS:
            per_day = []
            for x, w in zip(xs, walls):
                per_day.append([(x[i] - x[i - h], w[i] - w[i - h]) for i in range(h, len(w), h) if None not in (x[i], x[i - h], w[i], w[i - h])])
            bs, r2s = [], []
            for k, test in enumerate(per_day):
                train = [p for j, d in enumerate(per_day) if j != k for p in d]
                den = sum(a * a for a, _ in train)
                b = sum(a * y for a, y in train) / den if den else 0.0
                sst = sum(y * y for _, y in test)
                bs.append(b)
                r2s.append(1 - sum((y - b * a) ** 2 for a, y in test) / sst if sst else None)
            res["fit"][h] = (bs, r2s)
        # The event study: the largest one-tick changes of the feed.
        changes = sorted(abs(x[i] - x[i - 1]) for x in xs for i in range(1, len(x)) if None not in (x[i], x[i - 1]) and x[i] != x[i - 1])
        if changes:
            cut = changes[min(int(EVENT_QUANTILE * len(changes)), len(changes) - 1)]
            paths = defaultdict(list)
            for x, w in zip(xs, walls):
                n = len(w)
                for i in range(max(-min(OFFSETS), 1), n - max(OFFSETS)):
                    if None in (x[i], x[i - 1]) or abs(x[i] - x[i - 1]) < cut or x[i] == x[i - 1] or w[i - 1] is None:
                        continue
                    s = 1 if x[i] > x[i - 1] else -1
                    for o in OFFSETS:
                        if w[i + o] is not None:
                            paths[o].append(s * (w[i + o] - w[i - 1]))
            res["events"] = (len(paths[0]), cut, {o: st.fmean(v) for o, v in paths.items() if v})
        out[column] = res
    return out


def _steady(values) -> str:
    known = [v for v in values if v is not None]
    if not known:
        return "-"
    mark = "*" if len(known) == len(values) and (all(v > 0 for v in known) or all(v < 0 for v in known)) else ""
    return f"{st.fmean(known):+.2f}{mark}"


def print_feeds(label: str, product: str, res: dict) -> None:
    print(f"\n### {label} {product}\n")
    constant = sorted(c for c, r in res.items() if r.get("constant"))
    if constant:
        print(f"Constant within every day (no same-tick or lead signal possible): {', '.join(constant)}\n")
    moving = {c: r for c, r in res.items() if not r.get("constant")}
    if not moving:
        print("no feed moves within a day")
        return
    print("Correlation of the feed's one-tick change with the wall mid's change at the same tick, and with its move h ticks ahead "
          "(mean over the days; * = the same sign on every day):\n")
    print("| Feed | Same tick | " + " | ".join(f"lead {h}" for h in LEADS) + " |")
    print("|---|---|" + "---|" * len(LEADS))
    for column, r in sorted(moving.items()):
        print(f"| {column} | {_steady(r['same'])} | " + " | ".join(_steady(r["lead"][h]) for h in LEADS) + " |")
    print("\nLeave one day out: the wall mid's change over h ticks on the feed's over the same h (the same-tick fair term): "
          "b fitted on the other days / out-of-sample R², per held-out day:\n")
    print("| Feed | " + " | ".join(f"h = {h}" for h in WINDOWS) + " |")
    print("|---|" + "---|" * len(WINDOWS))
    for column, r in sorted(moving.items()):
        cells = []
        for h in WINDOWS:
            bs, r2s = r["fit"][h]
            cells.append(", ".join(f"{b:+.3g} / {'-' if q is None else f'{q:+.2f}'}" for b, q in zip(bs, r2s)))
        print(f"| {column} | " + " | ".join(cells) + " |")
    print(f"\nEvent study: the wall mid's mean move in the direction of the feed's largest one-tick changes (the top "
          f"{1 - EVENT_QUANTILE:.0%} of its non-zero changes), from the tick before, at each offset in ticks:\n")
    print("| Feed | Events (change at least) | " + " | ".join(f"{o:+d}" for o in OFFSETS) + " |")
    print("|---|---|" + "---|" * len(OFFSETS))
    for column, r in sorted(moving.items()):
        if r["events"] is None:
            continue
        n, cut, path = r["events"]
        print(f"| {column} | {n} ({cut:.3g}) | " + " | ".join("-" if o not in path else f"{path[o]:+.2f}" for o in OFFSETS) + " |")


# ---------------------------------------------------------------------------- part 2: the forecast


def feature_rows(day, products: list[str], product: str) -> tuple[list[str], list[list[float] | None], list[dict | None]]:
    """Per tick: the feature vector (None if a feature is missing) and the flows row (the wall mid and spread in ticks)."""
    rows = flows(day, product)
    w = [r["wall_mid"] if r else None for r in rows]
    others = {}
    for other in products:
        if other == product or other not in day.products:
            continue
        o = flows(day, other)
        others[other] = [r["wall_mid"] if r else None for r in o]
    names = list(FLOW_FEATURES) + [f"mom{k}" for k in MOMENTUM] + ["time"] + [f"ret5:{p}" for p in others]
    n = len(rows)
    out = []
    for i, r in enumerate(rows):
        if r is None or w[i] is None or i < max(MOMENTUM) or any(w[i - k] is None for k in MOMENTUM) or rows[i - 1] is None:
            out.append(None)
            continue
        # tick i's trades are those after its snapshot (the engine hands them to the bot at i + 1), so the
        # bot at i knows i - 1's; before 2026-10-28 this took i's, a look-ahead at 1 tick (the fourth audit's R8)
        seen = {**r, "trades": rows[i - 1]["trades"]}
        x = [float(seen[f]) for f in FLOW_FEATURES] + [w[i] - w[i - k] for k in MOMENTUM] + [i / n]
        ok = True
        for series in others.values():
            if series[i] is None or series[i - 5] is None:
                ok = False
                break
            x.append(series[i] - series[i - 5])
        out.append(x if ok else None)
    return names, out, rows


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [row[:] + [b[k]] for k, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        if abs(m[col][col]) < 1e-15:
            continue
        for r in range(n):
            if r != col and m[r][col]:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[k][n] / m[k][k] if abs(m[k][k]) > 1e-15 else 0.0 for k in range(n)]


def sufficient(xs: list[list[float]], ys: list[float]) -> dict:
    """n, Σx, Σy, Σxx', Σxy, Σy² of one day's rows."""
    p = len(xs[0]) if xs else 0
    sx, sxx, sxy = [0.0] * p, [[0.0] * p for _ in range(p)], [0.0] * p
    sy = syy = 0.0
    for x, y in zip(xs, ys):
        sy += y
        syy += y * y
        for j in range(p):
            xj = x[j]
            sx[j] += xj
            sxy[j] += xj * y
            row = sxx[j]
            for k in range(j, p):
                row[k] += xj * x[k]
    for j in range(p):
        for k in range(j):
            sxx[j][k] = sxx[k][j]
    return {"n": len(ys), "sx": sx, "sy": sy, "sxx": sxx, "sxy": sxy, "syy": syy}


def ridge(stats: list[dict]) -> tuple[list[float], list[float], list[float], float]:
    """Ridge on standardised features from summed sufficient statistics: (β per standardised feature, means, sds, mean y)."""
    n = sum(s["n"] for s in stats)
    p = len(stats[0]["sx"])
    sx = [sum(s["sx"][j] for s in stats) for j in range(p)]
    sy = sum(s["sy"] for s in stats)
    mu, ybar = [v / n for v in sx], sy / n
    cov = [[sum(s["sxx"][j][k] for s in stats) / n - mu[j] * mu[k] for k in range(p)] for j in range(p)]
    sd = [math.sqrt(max(cov[j][j], 0.0)) or 1.0 for j in range(p)]
    cxy = [sum(s["sxy"][j] for s in stats) / n - mu[j] * ybar for j in range(p)]
    a = [[n * cov[j][k] / (sd[j] * sd[k]) + (RIDGE * n if j == k else 0.0) for k in range(p)] for j in range(p)]
    b = [n * cxy[j] / sd[j] for j in range(p)]
    return _solve(a, b), mu, sd, ybar


def forecast_study(days: list, products: list[str], product: str) -> dict:
    data = []  # per day: (xs, rows, spreads, moves by horizon)
    names = None
    for day in days:
        names, xs, rows = feature_rows(day, products, product)
        n = len(rows)
        per_h = {}
        for h in HORIZONS:
            keep = [i for i in range(n - h) if xs[i] is not None and rows[i + h] is not None and rows[i + h]["wall_mid"] is not None]
            per_h[h] = (keep, [rows[i + h]["wall_mid"] - rows[i]["wall_mid"] for i in keep])
        data.append((xs, rows, per_h))
    half = st.median(r["spread"] for _, rows, _ in data for r in rows if r) / 2
    out = {"names": names, "half": half, "h": {}}
    for h in HORIZONS:
        stats = [sufficient([xs[i] for i in per_h[h][0]], per_h[h][1]) for xs, _, per_h in data]
        folds = []
        pooled = [0.0, 0.0]
        all_pred, all_y = [], []
        for k, (xs, rows, per_h) in enumerate(data):
            beta, mu, sd, ybar = ridge([s for j, s in enumerate(stats) if j != k])
            keep, ys = per_h[h]
            preds = [ybar + sum(b * (xs[i][j] - mu[j]) / sd[j] for j, b in enumerate(beta)) for i in keep]
            sse = sum((y - f) ** 2 for y, f in zip(ys, preds))
            sst = sum((y - ybar) ** 2 for y in ys)
            pooled[0] += sse
            pooled[1] += sst
            trades = [(1 if f > 0 else -1) * y - rows[i]["spread"] / 2 for i, f, y in zip(keep, preds, ys) if abs(f) > rows[i]["spread"] / 2]
            folds.append({"r2": 1 - sse / sst if sst else None, "trades": len(trades), "share": len(trades) / len(keep) if keep else 0.0,
                          "net": st.fmean(trades) if trades else None, "beta": beta, "sd": sd})
            all_pred += preds
            all_y += ys
        slope = None
        if len(all_pred) > 1 and st.pvariance(all_pred) > 0:
            mp, my = st.fmean(all_pred), st.fmean(all_y)
            slope = sum((p - mp) * (y - my) for p, y in zip(all_pred, all_y)) / sum((p - mp) ** 2 for p in all_pred)
        out["h"][h] = {"folds": folds, "r2": 1 - pooled[0] / pooled[1] if pooled[1] else None,
                       "move_per_sd": slope * st.pstdev(all_pred) if slope is not None else None}
    return out


def print_forecast(label: str, product: str, res: dict) -> None:
    print(f"\n### {label} {product}: half-spread {res['half']:g} ticks; features {', '.join(res['names'])}\n")
    print("| h | R² pooled | R² per held-out day | Move per sd of the forecast | Beats the half-spread? | Sitaru's rule: trades share, net per trade per day |")
    print("|---|---|---|---|---|---|")
    for h, r in res["h"].items():
        r2 = ", ".join("-" if f["r2"] is None else f"{f['r2']:+.3f}" for f in r["folds"])
        every = all(f["r2"] is not None and f["r2"] > 0 for f in r["folds"])
        move = r["move_per_sd"]
        beats = "-" if move is None else ("yes" if move > res["half"] else "no")
        rule = ", ".join(f"{f['share']:.1%} {'-' if f['net'] is None else f'{f['net']:+.2f}'}" for f in r["folds"])
        print(f"| {h} | {'-' if r['r2'] is None else f'{r['r2']:+.3f}'} | {r2}{' (all > 0)' if every else ''} | "
              f"{'-' if move is None else f'{move:.3f}'} | {beats} | {rule} |")
    # The largest standardised coefficients at the longest horizon, with their sign on each fold.
    h = max(res["h"])
    folds = res["h"][h]["folds"]
    order = sorted(range(len(res["names"])), key=lambda j: -abs(st.fmean(f["beta"][j] for f in folds)))[:5]
    print(f"\nLargest coefficients at h = {h} (ticks per sd of the feature, per fold): "
          + "; ".join(f"{res['names'][j]} " + "/".join(f"{f['beta'][j]:+.2f}" for f in folds) for j in order))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m experiments.day.predict")
    parser.add_argument("--part", type=int, choices=(1, 2), help="run only part 1 (feeds) or part 2 (the forecast)")
    add_dataset_arguments(parser, bot=False)
    args = parser.parse_args(argv)
    try:
        dataset = dataset_from(args)
    except ValueError as error:
        parser.error(str(error))
    if dataset:
        feeds = [(dataset.name, dataset.data, dataset.format, list(dataset.days), list(dataset.products))]
        forecasts = feeds
    else:
        feeds = [(f"{a} r{r}", a, "prosperity", [r], p) for a, r, p in FEED_DATASETS]
        forecasts = [(f"{a} r{'-'.join(r)}", a, "prosperity", r, p) for a, r, p in FORECAST_DATASETS]
    if args.part in (None, 1):
        print("1. Feeds beyond the book against the wall mid")
        for label, data, format_name, specs, products in feeds:
            fmt = FORMATS[format_name]
            days = fmt.load_days(fmt.resolve_data_dir(data), specs)
            if not any(feed_files(day) for day in days):
                print(f"\n{label}: no files beside the prices and trades (part 1 reads Prosperity-layout folders)")
                continue
            for product in products:
                print_feeds(label, product, feed_study([d for d in days if product in d.products], product))
    if args.part in (None, 2):
        print("\n2. A leave-one-day-out ridge forecast of the wall mid's move h ticks ahead, in ticks")
        for label, data, format_name, specs, products in forecasts:
            fmt = FORMATS[format_name]
            days = fmt.load_days(fmt.resolve_data_dir(data), specs)
            if len(days) < 2:
                print(f"\n{label}: one day; leaving one out needs two")
                continue
            for product in products:
                print_forecast(label, product, forecast_study([d for d in days if product in d.products], products, product))


if __name__ == "__main__":
    main(sys.argv[1:])
