"""A nameless informed-trade detector: trades of one size at a new running daily extreme, in the extreme's direction.

usage (from the repo root): uv run python -m experiments.day.informed [--jobs N] [--engine rust]
       uv run python -m experiments.day.informed --data DIR --days 1 [--format F --products A,B] [--informed NAME]

Before P3 round 5 named its traders, Frankfurt Hedgehogs found Olivia without a name
(references/prosperity3-frankfurt-hedgehogs/README.md:270, :311): a trade of her usual size at a new
running daily extreme of the price, a buy at the low or a sell at the high. The Arena may well
anonymise its trades (ON_THE_DAY.md, "Other traders"), so this is the same rule, made general:

  - a trade's side is read from the book it printed against (at or above the best ask a buy, at or
    below the best bid a sell, inside it by the mid); its size class is its quantity (in octaves when
    a product has more than MAX_SIZES distinct sizes, as ABIDES does);
  - it is **at an extreme** if, after WARMUP ticks, the wall mid at its tick is at or beyond the day's
    running low (a buy) or high (a sell) so far;
  - its move: the wall mid's change from the tick after it (when the bot sees it) to HORIZONS ticks
    later, in its direction; the **product's own reversion**: the same move after every new extreme,
    with or without a trade, in the reversal's direction;
  - a (product, size class) is **informed** on a day if its trades at extremes move at MAIN ticks by at
    least RATIO times the larger of the product's own reversion and its half-spread, with a hit rate
    of at least HIT_SHARE. A class is chosen when that holds on every training day (leave one day out).

1. Per product and day: the classes whose extreme trades move most at MAIN, against the same size's
   trades anywhere ("size alone") and the product's reversion.
2. Leave one day out: the classes chosen on the other days, flagged on the held-out day (their trades
   at extremes): flags, hit rate and mean move, against every trade of the named informed trader
   (--informed, Olivia by default) on that day, the upper bound names give; with names in the data,
   the share of flags that are that trader's (and the share of all trades that are, by chance), and
   the share of that trader's trades the detector flags.
3. Copying the detector (on the held-out days, the products with a chosen class): the template's
   `copy_sizes` (its copy mode following the chosen sizes, an octave as every size in it, at the day's
   running extremes of its fair after copy_warmup = WARMUP ticks; python/bots/template.py,
   `informed_signal`), on the day's trades with their names blanked, as an anonymous feed gives them.
   Against plain market making and copying the named trader with names kept (counterparties' part 2
   settings: the data's limits, wall_mid, make_edge 1).

Default: P3 round 5 (KELP, SQUID_INK, CROISSANTS; Olivia named). With --data any dataset; for ABIDES's
days with --names, --informed ValueAgent.
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import statistics as st
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from arena import rust
from arena.cli import TEMPLATE, add_dataset_arguments, add_engine_argument, backtest, dataset_from
from arena.engine import EngineConfig
from arena.formats import FORMATS
from arena.model import MarketTrade, Tick

DATA, DAYS, FORMAT = "p3", ["5"], "prosperity"
PRODUCTS = ["KELP", "SQUID_INK", "CROISSANTS"]
INFORMED = "Olivia"
HORIZONS = (100, 500, 1000)
MAIN = 1000
WARMUP = 200
RATIO = 3.0
HIT_SHARE = 0.8
MAX_SIZES = 30
ENGINE = ["python"]
BOT = TEMPLATE
_DAYS: dict = {}


def walls(day, product: str) -> list[float | None]:
    out, last = [], None
    for tick in day.ticks:
        book = tick.books.get(product)
        if book is not None and book.bids and book.asks:
            last = book.wall_mid
        out.append(last)
    first = next((w for w in out if w is not None), None)
    return [first if w is None else w for w in out]


def side_of(trade, book) -> int:
    if book is None or not (book.bids or book.asks):
        return 0
    if book.asks and trade.price >= book.asks[0][0]:
        return 1
    if book.bids and trade.price <= book.bids[0][0]:
        return -1
    mid = book.mid
    return 0 if mid is None or trade.price == mid else 1 if trade.price > mid else -1


def size_classes(days, product: str):
    """The class of a trade size: the size itself, or its octave (2^k .. 2^(k+1) - 1) if the product has many sizes."""
    sizes = {abs(t.quantity) for day in days for tick in day.ticks for t in tick.trades.get(product, [])}
    if len(sizes) <= MAX_SIZES:
        return lambda q: str(abs(q))
    return lambda q: f"{2 ** int(math.log2(max(abs(q), 1)))}-{2 ** (int(math.log2(max(abs(q), 1))) + 1) - 1}"


def events(day, product: str, classify) -> dict:
    """Every trade (tick, side, class, at an extreme, moves at HORIZONS, the side's name) and the moves after
    every new extreme (the reversion), on one day."""
    w, n = walls(day, product), len(day.ticks)
    trades, reversion = [], []
    low = high = None
    for i, tick in enumerate(day.ticks):
        p = w[i]
        if p is None:
            continue
        new_low, new_high = low is not None and p <= low, high is not None and p >= high
        start = w[min(i + 1, n - 1)]
        if i >= WARMUP and (new_low or new_high):
            s = 1 if new_low else -1
            reversion.append(s * (w[min(i + 1 + MAIN, n - 1)] - start))
        for trade in tick.trades.get(product, []):
            s = side_of(trade, tick.books.get(product))
            if not s:
                continue
            trades.append({"i": i, "side": s, "size": classify(trade.quantity), "extreme": i >= WARMUP and ((s > 0 and new_low) or (s < 0 and new_high)),
                           "moves": [s * (w[min(i + 1 + h, n - 1)] - start) for h in HORIZONS], "name": trade.buyer if s > 0 else trade.seller,
                           "trade": trade})
        low = p if low is None else min(low, p)
        high = p if high is None else max(high, p)
    return {"trades": trades, "reversion": st.fmean(reversion) if reversion else 0.0, "extremes": len(reversion)}


def half_spread(day, product: str) -> float:
    spreads = [b.asks[0][0] - b.bids[0][0] for t in day.ticks if (b := t.books.get(product)) is not None and b.bids and b.asks]
    return st.median(spreads) / 2 if spreads else 0.0


def class_stats(ev: dict, size: str) -> dict:
    k = HORIZONS.index(MAIN)
    at = [t["moves"] for t in ev["trades"] if t["size"] == size and t["extreme"]]
    anywhere = [t["moves"] for t in ev["trades"] if t["size"] == size]
    return {"n": len(at), "move": [st.fmean(m[j] for m in at) for j in range(len(HORIZONS))] if at else None,
            "hit": sum(m[k] > 0 for m in at) / len(at) if at else None,
            "n_all": len(anywhere), "move_all": st.fmean(m[k] for m in anywhere) if anywhere else None,
            "hit_all": sum(m[k] > 0 for m in anywhere) / len(anywhere) if anywhere else None}


def informed_on(ev: dict, size: str, half: float) -> bool:
    s = class_stats(ev, size)
    if not s["n"]:
        return False
    return s["move"][HORIZONS.index(MAIN)] >= RATIO * max(ev["reversion"], half) and s["hit"] >= HIT_SHARE


def choose(train: list[tuple[dict, float]]) -> list[str]:
    """The size classes informed on every training day."""
    sizes = set.intersection(*({t["size"] for t in ev["trades"] if t["extreme"]} for ev, _ in train)) if train else set()
    return sorted(s for s in sizes if all(informed_on(ev, s, half) for ev, half in train))


def anonymous(day):
    """The day with every trade's names blanked, as an anonymous feed gives them."""
    ticks = [Tick(tick.timestamp, tick.books, {product: [MarketTrade(t.product, t.price, t.quantity, "", "", t.timestamp) for t in prints]
                                               for product, prints in tick.trades.items()}, tick.marks) for tick in day.ticks]
    return dataclasses.replace(day, ticks=ticks)


def _init(engine: str, settings: dict | None = None) -> None:
    ENGINE[0] = engine
    globals().update(settings or {})
    fmt = FORMATS[FORMAT]
    _DAYS.clear()
    _DAYS.update({d.name: d for d in fmt.load_days(fmt.resolve_data_dir(DATA), list(DAYS))})


def _params(day, copy: dict[str, dict], sizes: dict[str, list[int]] | None = None) -> dict:
    out = {}
    for product in day.products:
        p = {"limit": day.limits[product], "fair": "wall_mid", "make_edge": 1}
        if product in copy:
            p["copy"] = dict(copy[product])
        if sizes and product in sizes:
            p.update(copy_sizes=sizes[product], copy_warmup=WARMUP)
        out[product] = p
    return out


def sizes_in(classes: list[str]) -> list[int]:
    """Every size in the chosen classes: a size itself, or each one of an octave "a-b"."""
    out = set()
    for c in classes:
        low, _, high = c.partition("-")
        out.update(range(int(low), int(high or low) + 1))
    return sorted(out)


def _run(job) -> tuple:
    day_name, variant, products, flagged = job
    day = _DAYS[day_name]
    sizes = None
    if variant == "detector":
        day = anonymous(day)
        sizes = {p: sizes_in(classes) for p, classes in flagged}
        copy = {}
    elif variant == "named":
        copy = {p: {INFORMED: 1} for p in products}
    else:
        copy = {}
    (result,) = backtest(day, [("you", BOT, {"PARAMS": _params(day, copy, sizes)}, False)], EngineConfig(), ENGINE[0], True, ("pnl",), FORMAT)
    return job, {p: result.pnl[p][-1] if result.pnl.get(p) else 0.0 for p in products}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m experiments.day.informed")
    parser.add_argument("--jobs", type=int, default=None)
    parser.add_argument("--informed", default=None, help=f"the trader the names say is informed, the answer key (default {INFORMED})")
    add_engine_argument(parser, "run part 3's backtests in rust/ (the same results)")
    add_dataset_arguments(parser)
    args = parser.parse_args(argv)
    products = args.products
    args.products = None
    try:
        dataset = dataset_from(args)
    except ValueError as error:
        parser.error(str(error))
    settings = {}
    if dataset:
        fmt = FORMATS[dataset.format]
        everything = sorted({p for d in fmt.load_days(fmt.resolve_data_dir(dataset.data), list(dataset.days)) for p in d.products})
        settings = {"DATA": dataset.data, "DAYS": list(dataset.days), "FORMAT": dataset.format, "BOT": Path(dataset.bot),
                    "PRODUCTS": [p.strip() for p in products.split(",")] if products else everything}
    if args.informed:
        settings["INFORMED"] = args.informed
    if args.engine == "rust":
        rust.require(args.allow_stale)
    _init(args.engine, settings)
    days = list(_DAYS.values())
    names = [d.name for d in days]
    products = [p for p in PRODUCTS if any(p in d.products for d in days)]
    k = HORIZONS.index(MAIN)

    evs, halves = {}, {}
    for product in products:
        classify = size_classes(days, product)
        for day in days:
            if product in day.products:
                evs[(product, day.name)] = events(day, product, classify)
                halves[(product, day.name)] = half_spread(day, product)

    print(f"1. Trades at a new running daily extreme in its direction, by size class: mean move at {', '.join(map(str, HORIZONS))} "
          f"ticks, hit rate at {MAIN}; the same size's trades anywhere ('size alone') at {MAIN}; the product's own reversion "
          f"after a new extreme at {MAIN}, and its half-spread. The four classes with the largest move at {MAIN}, per day.\n")
    print(f"| Product | Day | Reversion / half-spread | Size | At extremes: n, moves, hit | Size alone: n, move, hit | Informed |")
    print("|---|---|---|---|---|---|---|")
    for product in products:
        for name in names:
            ev = evs.get((product, name))
            if ev is None:
                continue
            half = halves[(product, name)]
            sizes = {t["size"] for t in ev["trades"] if t["extreme"]}
            stats = sorted(((class_stats(ev, s), s) for s in sizes), key=lambda x: -(x[0]["move"][k] if x[0]["n"] >= 2 or len(sizes) < 5 else -1e9))
            for s, size in stats[:4]:
                moves = " / ".join(f"{m:+.1f}" for m in s["move"])
                alone = f"{s['n_all']}, {s['move_all']:+.1f}, {s['hit_all']:.0%}" if s["n_all"] else "-"
                print(f"| {product} | {name} | {ev['reversion']:+.1f} / {half:g} | {size} | {s['n']}, {moves}, {s['hit']:.0%} | {alone} | "
                      f"{'yes' if informed_on(ev, size, half) else ''} |")

    print(f"\n2. Leave one day out: the classes chosen on the other days (informed on each), flagged on the held-out day; "
          f"against every trade of {INFORMED} that day (moves at {MAIN}).\n")
    print(f"| Held out | Product | Chosen | Flags: n, hit, mean move | {INFORMED}'s trades: n, hit, mean move | Flags that are {INFORMED}'s (by chance) | {INFORMED}'s trades flagged |")
    print("|---|---|---|---|---|---|---|")
    chosen_by_fold = {}
    for test in names:
        chosen_by_fold[test] = {}
        for product in products:
            train = [(evs[(product, n)], halves[(product, n)]) for n in names if n != test and (product, n) in evs]
            if (product, test) not in evs or not train:
                continue
            chosen = choose(train)
            ev = evs[(product, test)]
            flags = [t for t in ev["trades"] if t["extreme"] and t["size"] in chosen]
            named = [t for t in ev["trades"] if t["name"] == INFORMED]
            if chosen:
                chosen_by_fold[test][product] = tuple(chosen)

            def summary(rows):
                if not rows:
                    return "0"
                return f"{len(rows)}, {sum(t['moves'][k] > 0 for t in rows) / len(rows):.0%}, {st.fmean(t['moves'][k] for t in rows):+.1f}"

            any_names = any(t["name"] for t in ev["trades"])
            precision = (f"{sum(t['name'] == INFORMED for t in flags)}/{len(flags)} ({sum(t['name'] == INFORMED for t in ev['trades']) / len(ev['trades']):.1%})"
                         if any_names and flags else "-")
            recall = f"{sum(t['extreme'] and t['size'] in chosen for t in named)}/{len(named)}" if named else "-"
            print(f"| {test} | {product} | {', '.join(chosen) or 'none'} | {summary(flags)} | {summary(named) if any_names else '-'} | {precision} | {recall} |")

    jobs, shown = [], {}
    for test, chosen in chosen_by_fold.items():
        named = tuple(p for p in products if (p, test) in evs and any(t["name"] == INFORMED for t in evs[(p, test)]["trades"]))
        shown[test] = sorted(set(chosen) | set(named))
        if not shown[test]:
            continue
        jobs.append((test, "plain", tuple(shown[test]), ()))
        if chosen:
            jobs.append((test, "detector", tuple(sorted(chosen)), tuple(sorted(chosen.items()))))
        if named:
            jobs.append((test, "named", named, ()))
    print(f"\n3. The template's copy_sizes following the chosen classes, names blanked, on the held-out day's chosen products, and {INFORMED} "
          f"by name on the products where the name trades, against plain market making (PnL per product, thousands)\n")
    if not jobs:
        print(f"   no class chosen on any fold and no trades named {INFORMED}: nothing to copy")
        return
    with ProcessPoolExecutor(args.jobs, initializer=_init, initargs=(args.engine, settings)) as pool:
        out = dict(pool.map(_run, jobs))
    print(f"| Held out | Product | Plain | Detector | {INFORMED} by name |")
    print("|---|---|---|---|---|")
    totals = defaultdict(lambda: [0.0, 0.0])  # variant -> [its PnL, plain's on the same product-days]
    for test in names:
        runs = {variant: pnl for (day, variant, _, _), pnl in out.items() if day == test}
        for product in shown.get(test, []):
            cells = []
            for variant in ("plain", "detector", "named"):
                if product in runs.get(variant, {}):
                    cells.append(f"{runs[variant][product] / 1000:.1f}")
                    totals[variant][0] += runs[variant][product]
                    totals[variant][1] += runs["plain"][product]
                else:
                    cells.append("-")
            print(f"| {test} | {product} | " + " | ".join(cells) + " |")
    print("| total, against plain on the same product-days | | " + " | ".join(
        f"{totals[v][0] / 1000:.1f} ({(totals[v][0] - totals[v][1]) / 1000:+.1f})" if v in totals else "-" for v in ("plain", "detector", "named")) + " |")


if __name__ == "__main__":
    main(sys.argv[1:])
