"""First-look diagnostics of a market's data, per product: what kind of market is this?

    uv run python -m arena.diagnose 1 --data p4        # every day of round 1
    uv run python -m arena.diagnose 3-0 --data p4 --csv results/diag.csv
    uv run python -m arena.diagnose 1 --data p3 --profile   # ...and each product by tenth of the day
    uv run python -m arena.diagnose 1 --data p4 --suggest   # ...and a PARAMS block for the template, from the notes

No bot is needed: it reads the days through the format plug-in, so it works on the Arena's
first data download as soon as its format module exists. For each product, pooled over the days:

- **Book:** the tick, the spread in ticks, the share of two-sided ticks at a one-tick spread (the
  large-tick regime, where queue position and book imbalance matter), how often one side of the
  book is empty, and how often the wall mid jumps: moves by more than half the spread (and at
  least a tick) from one tick to the next. Where orders rest, quotes near the touch of a product
  that jumps get filled at their stale price.
- **The market maker's size:** the median size of each side's largest level, and the share of
  sides with a level of at least `WALL_SIZE` lots, the template's default `wall_size`. Where that
  share is low, `sized_mid` falls back to the best level, i.e. the plain mid, on most ticks.
- **Jumps that snap back:** the wall mid's moves of at least `SNAP_SPREADS` times the day's median
  spread, and the share that went the opposite way to the one before. Where that share is high,
  fading each jump pays (the template's `jump` mode); elsewhere it is a coin flip. The note gives
  the jumps' usual size (their median), the share that is exactly that size, and the grid the wall
  mid sits on: the share of ticks at its most common value modulo that size (P4 round 5's
  ROBOT_DISHES: steps of 100 between multiples of 100). The template's `jump_min` is about half the size.
- **Large-tick market making** (Gao & Wang 2018, Theorem 4.1(c)): on the ticks at a one-tick
  spread, `λ` is the share after which the mid moves, and `λ+` (`λ-`) the share with a market buy
  at the ask (sell at the bid) after which it does not: the uninformed hits. In their model a quote
  at the best has a positive value on a side iff `λ±` > `λ/2`, since a fill there gains half a tick
  at rate `λ±` and loses half a tick when the mid jumps through it, at rate `λ/2`. A large-tick
  product gets a note saying on which sides that holds.
- **Spoofability** (Tao et al. 2022, Proposition 3.3 and eq. 5.1): a spoof pays only if the next
  move follows the book's imbalance, the real order is large next to the depth, and a level k deep
  is rarely reached by market orders. With `ı = B/(B + A)`, the bid's share of the volume on the
  best `SPOOF_LEVELS` levels (equal weights `w_k`): `µ+` is the slope of the mid's next move, in
  ticks, on `2ı - 1` over ticks without market trades (their `µ(ı) = µ+(2ı - 1)`); each tick's
  market buys (sells) are one order of size `H`, `y` the levels it empties (their `F(H)`), and
  `Q_k` and `ν_k` the share of orders with `y > k` and the mean of `(y - k)+`; `ρ` is the orders'
  mean size over the mean depth on the side they hit, and `ı̄` the mean imbalance after them (the
  sells' mirrored). The score is `max_k 2ρµ+(1 - ı̄)ı̄w_k - Q_kρ - ν_k`: above 0, a spoof at some
  depth k pays in their model; at or below 0, nowhere. Their detector's inputs, in the CSV only: the
  Wasserstein distance between `ı` just before market buys and `ı` on every tick (the same for sells
  with the ask's share), weighted by their counts, `spoof_before`; and between the share before them
  and after, `spoof_snap`. A spoof shows as both large: a
  book that leans before the trades and snaps back after. Read them against the product's own
  baseline, not 0: with no spoofer, Prosperity's books give 0.00-0.02 on the market-making products,
  0.01-0.08 on baskets and most options and 0.18-0.27 on P3's volcanic vouchers (IDEAS.md, "A spoof
  tell from the data").
- **Noise:** the lag-1 autocorrelation of one-tick changes of the mid, and the signature ratio of
  the mid and of the wall mid (the midpoint of the largest level on each side): the variance per
  tick of one-tick changes over that of `LAG`-tick changes. Near 1 is a random walk; well above 1
  is noise that reverts, which a fair value should filter out.
- **Kalman-implied smoothing:** a local-level model, the price a random walk of step variance `q`
  seen through noise of variance `r`, has `E[(p[t+h] - p[t])^2] = h q + 2 r`. A least-squares line
  through the mean squared change at each of `KALMAN_LAGS` gives `q` (its slope) and `r` (half its
  intercept), per reference. The steady-state Kalman filter for that model is an EMA with gain
  `K = P / (P + r)`, `P = (q + sqrt(q^2 + 4 q r)) / 2` (the predicted variance), so the template's
  `smoothing` (`fair = s * previous + (1 - s) * price`) that matches it is `1 - K`. Noise that
  reverts at one tick (a bouncing mid) gives a high `r`; a random walk gives `r` near 0 and 0.
  The fit takes each day's mean change out. An EMA lags a drift `mu` a tick by `mu s / (1 - s)`, so
  where the days drift the column is the `s` that minimises the EMA's steady-state squared error,
  `(mu s / (1 - s))^2 + (s^2 q + (1 - s)^2 r) / (1 - s^2)`, which is `1 - K` when `mu` is 0.
- **Book changes,** from one two-sided tick to the next, per side:
  - the wall (each side's largest level): the ticks its price stays (`wall_stay`), and the share of
    ticks at an unchanged price where its size is unchanged too (`wall_size_kept`);
  - the best level at an unchanged price: the share of ticks without a market trade at it where its
    size is unchanged (`best_kept`), and the lots added, cancelled and traded a tick as shares of its
    size (`best_added`, `best_cancelled`, `best_traded`; added and cancelled are their net, as in
    Cont et al.'s order flow imbalance: a snapshot can't tell both apart). A book that is one set of
    queues, like ABIDES's (0.90), keeps the best's size between trades; Prosperity's makers redraw
    every level each tick (0.01-0.39 over all 165 P2-P4 product-rounds), so there is no queue place
    to hold;
  - after market trades empty the best and the next is worse: the median ticks until the best is
    back at that price (`refill_ticks`, inf where most aren't within `LAG`), and the share back next
    tick;
  - the lead: the correlation of the wall mid's change with the mid's next one, less that of the
    mid's change with the wall mid's next (`lead`). Positive: the wall moves first, a lead for the
    fair; on P2-P4 and ABIDES it is within ±0.03.
- **Slow reversion:** the wall mid's variance per tick at `LAG` ticks over that at `LONG_LAG`
  ticks. Well above 1: the price returns to a level over hundreds of ticks, which the lag-1
  numbers can't see.
- **Drift:** the wall mid's change over each day, and that change over the day's noise.
- **Market trades:** each classified against its own tick's book, as `analysis.trade_impact` does
  (+1 at or above the best ask, -1 at or below the best bid; inside the spread: left out). Then:
  - the share of buys and `C(1)`, the correlation of consecutive trade signs;
  - against each reference (the mid, the wall mid): the taker's edge `sign × (ref − price)` and
    the signed move `R(h) = sign × (ref[t+h] − ref[t])` after 1 and `LAG` ticks;
  - the two margins per unit of a market maker who takes the other side, from Bouchaud et al.
    (2018), eqs. 17.13–17.14: slow `−edge − R(LAG)` and fast `−edge × (1 − C(1)) − R(1)`. The
    book writes `s/2` for `−edge`, which is the same against the mid when trades are at the touch;
    measuring it keeps the margin consistent with the reference.
- **Time of day:** the spread, the wall mid's mean move a tick and the market trades per 1,000
  ticks in each tenth of the day (`PARTS`), pooled over the days. When the first or the last tenth
  is `PROFILE_RATIO` times the middle's median, or less than its inverse, the notes say so: an open
  that is wider or faster than the day is a reason to quote wider there, a close that is to flatten
  earlier (`flatten_from`). `--profile` prints the whole table.
- **`--suggest`:** a PARAMS entry per product for the template, read off the notes as the wiki's
  day-one table says (see `suggest`): a starting point for the first backtest and grid, not a
  tuned setting. `python/experiments/day/suggest_check.py` scores it against the hand-tuned PARAMS.
- **Notes:** which regime the numbers point to, using the thresholds below. They are rules of
  thumb calibrated on Prosperity data, not verdicts.
  `references/wiki/concepts/reading-the-data-on-day-one.md` says what each one means for the
  strategy.

Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from arena.formats import FORMATS
from arena.model import Day

LAG = 50  # ticks: the "long run" for impact, noise and the slow margin
LONG_LAG = 1000  # ticks: the horizon for slow reversion to a level
REFERENCES = ("mid", "wall")
KALMAN_LAGS = (1, 2, 5, 10, 20, LAG)  # ticks: the lags the local-level model's h q + 2 r is fitted over
LARGE_TICK_SHARE = 0.5  # share of two-sided ticks at a one-tick spread from which a product is large-tick
EMPTY_SIDE_SHARE = 0.02  # share of ticks with one side empty from which it gets a note
WALL_SIZE = 15  # the template's DEFAULTS wall_size: the smallest level sized_mid counts as the market maker's
WALL_SEEN = 0.8  # share of book sides with a level of WALL_SIZE below which wall_size gets a note
# Share of ticks on which the wall mid jumps from which resting quotes get picked off: under --resting, the
# template's market making lost 140k-1.5M on P2/P3 products at 10-63% and still made 18k on Kelp at 0-0.1%.
JUMPY = 0.05
# Jumps that snap back: a wall mid move of at least SNAP_SPREADS × the day's median spread is a jump; a day with
# MIN_JUMPS of them, SNAP_BACK of which went the opposite way to the one before, gets a note. On P2-P4 (637
# product-days), the four product-days the template's jump mode made money on, all in P4 round 5, reverse 86-98%
# (ROBOT_DISHES day 4: 743 jumps, 87%); every other day with 20 such jumps reverses at most 67%.
SNAP_SPREADS = 6
MIN_JUMPS = 20
SNAP_BACK = 0.75
GRID_SHARE = 0.5  # share of a jumping day's ticks at one value modulo the jump size from which the note names that grid
MIN_ONE_TICK = 100  # ticks at a one-tick spread (with the next tick's mid) below which λ and λ± are left out
SPOOF_LEVELS = 3  # book levels the spoofability's imbalance and depth count, equally weighted
MEAN_REVERTING = -0.2  # lag-1 autocorrelation of the mid's changes at or below which the mid is mostly noise
NOISY_SIGNATURE = 1.5  # signature ratio from which a price is noisy
# Wall mid variance per tick at LAG over LONG_LAG from which it reverts to a level. Three days of 10,000 ticks hold
# only 30 LONG_LAG windows, so a random walk spreads widely: simulated, its median is 1.11 and 2% reach 1.8;
# P4 round 5's 50 products give 0.76-1.64 (median 1.16). A pull to the level of 0.2% a tick gives a median of 2.6.
SLOW_REVERSION = 1.8
FIXED_SD_TICKS = 1.0  # standard deviation of the wall mid, in ticks, up to which it counts as a fixed value
DRIFT_RATIO = 2.0  # |change over a day| / the day's noise from which a day counts as drifting
MIN_TRADES = 30  # market trades below which no trade statistics get a note
ONE_SIDED = 0.1  # share of buys (or sells) at or below which the flow is one-sided
PERSISTENT_SIGNS = 0.5  # C(1) from which trade signs persist
INFORMED_SHARE = 0.25  # |R(LAG)| against the wall mid, as a share of the taker's cost, from which the move gets a note
THIN_MARGIN_SHARE = 0.1  # slow margin against the wall mid, as a share of the spread, below which it is thin
T_STAT = 2.0  # |mean / standard error| from which a mean counts as non-zero (rough: overlapping horizons)
# Share of quiet ticks on which the best keeps its size, from which the queues persist: P2-P4's 165 product-rounds
# give 0.01-0.39 (median 0.08), ABIDES's RMSC04 0.90.
PERSISTENT_QUEUE = 0.6
WALL_LEAD = 0.1  # |lead| from which the wall moves before the mid (or after it): P2-P4 and ABIDES stay within ±0.03
PARTS = 10  # the time-of-day profile splits each day into this many parts
PROFILE_RATIO = 1.5  # the first or last part, over the middle parts' median, from which (or below whose inverse) it gets a note


@dataclass
class _Parts:
    """One day's time-of-day profile, per tenth (PARTS): ticks, the sum and count of spreads and of
    |wall mid moves|, and market trades."""

    ticks: list[int] = field(default_factory=lambda: [0] * PARTS)
    spreads: list[list[float]] = field(default_factory=lambda: [[0.0, 0] for _ in range(PARTS)])
    moves: list[list[float]] = field(default_factory=lambda: [[0.0, 0] for _ in range(PARTS)])
    trades: list[int] = field(default_factory=lambda: [0] * PARTS)


@dataclass
class _Acc:
    """What one product's days add up to."""

    ticks: int = 0
    two_sided: int = 0
    one_empty: int = 0
    tick_size: float | None = None
    spreads: list[float] = field(default_factory=list)
    largest: list[int] = field(default_factory=list)  # each side's largest level, per two-sided tick
    wall_moves: list[tuple[float, float]] = field(default_factory=list)  # (|wall mid change|, half the spread) a tick
    mids: list[float] = field(default_factory=list)
    walls: list[float] = field(default_factory=list)
    autocorr: list[tuple[float, int]] = field(default_factory=list)  # mid, (value, weight) per day
    signature: dict[str, list[tuple[float, int]]] = field(default_factory=lambda: {r: [] for r in REFERENCES})
    reversion: list[tuple[float, int]] = field(default_factory=list)  # wall mid, LAG over LONG_LAG, per day
    # Per reference, per KALMAN_LAGS lag: [sum of squared changes over that lag less each day's mean, their count].
    variogram: dict[str, list[list[float]]] = field(default_factory=lambda: {r: [[0.0, 0] for _ in KALMAN_LAGS] for r in REFERENCES})
    drifts: list[float] = field(default_factory=list)  # wall mid change per day
    drift_ratios: list[float] = field(default_factory=list)  # that change over the day's noise
    drift_rates: list[float] = field(default_factory=list)  # that change over the day's ticks
    day_means: list[float] = field(default_factory=list)  # the wall mid's mean per day
    limit: int | None = None  # the position limit the data gives
    bot_tick: float | None = None  # the data's price units in one of the bot's (a format with a tick per product: Day.info)
    trades: int = 0
    buys: int = 0
    inside: int = 0
    sign_pairs: list[int] = field(default_factory=list)  # products of consecutive trade signs
    trade_spreads: list[float] = field(default_factory=list)
    edges: dict[str, list[float]] = field(default_factory=lambda: {r: [] for r in REFERENCES})
    moves: dict[tuple[str, int], list[float]] = field(default_factory=dict)  # (reference, horizon)
    slow_gains: dict[str, list[float]] = field(default_factory=lambda: {r: [] for r in REFERENCES})
    one_tick: list[int] = field(default_factory=lambda: [0, 0, 0, 0])  # ticks at a one-tick spread: all, mid moved, buy hits, sell hits
    spoof_moves: list[tuple[float, float]] = field(default_factory=list)  # (2ı - 1, next mid move in ticks), ticks without trades
    spoof_orders: list[tuple[float, float, int, float]] = field(default_factory=list)  # (H, depth hit, levels emptied, ı after), per order
    spoof_shares: list[float] = field(default_factory=list)  # ı on every tick with a book
    spoof_before: list[tuple[int, float]] = field(default_factory=list)  # (side, ı before each order on its side; the after is spoof_orders')
    snaps: list[tuple[str, int, int, int]] = field(default_factory=list)  # (day, jumps, pairs, pairs reversed) per day
    jump_sizes: list[float] = field(default_factory=list)  # |wall mid move| of every jump that snaps back or not
    jump_days: dict[str, tuple[list[float], list[float]]] = field(default_factory=dict)  # day with MIN_JUMPS: (|jumps|, wall mids)
    parts: list[_Parts] = field(default_factory=list)  # per day, for the time-of-day profile
    # Per side, per pair of consecutive two-sided ticks: pairs, the wall's price changed, its price unchanged, and of
    # those its size unchanged too.
    wall_pairs: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    # Per side, per pair at an unchanged best price: pairs, those with no market trade at it, of those its size
    # unchanged; the best's size, lots added, cancelled and traded, summed.
    best: list[float] = field(default_factory=lambda: [0, 0, 0, 0.0, 0.0, 0.0, 0.0])
    refills: list[float] = field(default_factory=list)  # ticks until an emptied best is back (math.inf: not within LAG)
    leads: dict[str, list[float]] = field(default_factory=lambda: {"wall": [0.0] * 6, "mid": [0.0] * 6})  # moments of (Δ, the other's next Δ)


def diagnose(days: list[Day]) -> dict[str, dict[str, float | str | None]]:
    """Per product, the diagnostics in the module docstring, pooled over the days."""
    return {product: _summarise(acc) for product, acc in _accumulate(days).items()}


def time_profile(days: list[Day]) -> dict[str, dict[str, list[float | None]]]:
    """Per product, per tenth of the day: the mean spread in ticks, the wall mid's mean |move| a tick
    in ticks, and market trades per 1,000 ticks."""
    return {product: _profile(acc) for product, acc in _accumulate(days).items()}


def _accumulate(days: list[Day]) -> dict[str, _Acc]:
    accs: dict[str, _Acc] = {}
    for day in days:
        for product in day.products:
            _add_day(accs.setdefault(product, _Acc()), day, product)
    return dict(sorted(accs.items()))


def _add_day(acc: _Acc, day: Day, product: str) -> None:
    series: dict[str, list[float | None]] = {r: [] for r in REFERENCES}
    prices: set[float] = set()
    parts = _Parts()
    acc.parts.append(parts)
    for i, tick in enumerate(day.ticks):
        book = tick.books.get(product)
        acc.ticks += 1
        part = i * PARTS // len(day.ticks)
        parts.ticks[part] += 1
        parts.trades[part] += len(tick.trades.get(product, []))
        if book is not None:
            prices.update(p for p, _ in book.bids + book.asks)
        if book is None or not (book.bids and book.asks):
            acc.one_empty += book is not None and bool(book.bids or book.asks)
            series["mid"].append(None)
            series["wall"].append(None)
            continue
        acc.two_sided += 1
        acc.spreads.append(book.asks[0][0] - book.bids[0][0])
        acc.largest += [max(v for _, v in book.bids), max(v for _, v in book.asks)]
        parts.spreads[part][0] += acc.spreads[-1]
        parts.spreads[part][1] += 1
        if series["wall"] and series["wall"][-1] is not None and book.wall_mid is not None:
            acc.wall_moves.append((abs(book.wall_mid - series["wall"][-1]), acc.spreads[-1] / 2))
            parts.moves[part][0] += acc.wall_moves[-1][0]
            parts.moves[part][1] += 1
        series["mid"].append(book.mid)
        series["wall"].append(book.wall_mid)
    acc.mids += [m for m in series["mid"] if m is not None]
    acc.limit = day.limits.get(product, acc.limit)
    info = day.info.get(product, {})
    if "tick" in info and "unit" in info:
        acc.bot_tick = info["tick"] / info["unit"]
    if any(w is not None for w in series["wall"]):
        acc.day_means.append(statistics.fmean(w for w in series["wall"] if w is not None))
    acc.walls += [w for w in series["wall"] if w is not None]
    day_spreads = acc.spreads[len(acc.spreads) - sum(w is not None for w in series["mid"]):]
    if day_spreads:
        walls, spread = [w for w in series["wall"] if w is not None], statistics.median(day_spreads)
        acc.snaps.append((day.name, *_snap_backs(walls, spread)))
        sizes = [abs(m) for m in _jump_moves(walls, spread)]
        acc.jump_sizes += sizes
        if len(sizes) >= MIN_JUMPS:
            acc.jump_days[day.name] = (sizes, walls)
    ordered = sorted(prices)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    if gaps:
        acc.tick_size = min(gaps + ([acc.tick_size] if acc.tick_size else []))

    changes = [b - a for a, b in zip(series["mid"], series["mid"][1:]) if a is not None and b is not None]
    if len(changes) > 2:
        acc.autocorr.append((_lag1_autocorrelation(changes), len(changes)))
    for name in REFERENCES:
        ratio = _signature_ratio(series[name])
        if ratio is not None:
            acc.signature[name].append((ratio, len(series[name])))
        values = series[name]
        for k, lag in enumerate(KALMAN_LAGS):  # the day's mean change taken out, so a steady drift isn't read as a random walk
            changes = [b - a for a, b in zip(values, values[lag:]) if a is not None and b is not None]
            if changes:
                acc.variogram[name][k][0] += sum(c * c for c in changes) - sum(changes) ** 2 / len(changes)
                acc.variogram[name][k][1] += len(changes)

    refs = {name: _forward_fill(values) for name, values in series.items()}
    known = [w for w in refs["wall"] if w is not None]
    per_tick = _variance_per_tick(refs["wall"], LAG)
    per_tick_long = _variance_per_tick(refs["wall"], LONG_LAG)
    if per_tick and per_tick_long and len(known) >= 2 * LONG_LAG:
        acc.reversion.append((per_tick / per_tick_long, len(known)))
    if len(known) > LAG and per_tick is not None:
        noise = (per_tick * len(known)) ** 0.5
        acc.drifts.append(known[-1] - known[0])
        acc.drift_rates.append((known[-1] - known[0]) / len(known))
        acc.drift_ratios.append((known[-1] - known[0]) / noise if noise else 0.0)

    _add_book_changes(acc, day, product)
    unit, mids = acc.tick_size or 1.0, series["mid"]
    for i, tick in enumerate(day.ticks[:-1]):  # Gao & Wang's rates, at a one-tick spread
        book = tick.books.get(product)
        if mids[i] is None or mids[i + 1] is None or book.asks[0][0] - book.bids[0][0] > unit + 1e-9:
            continue
        acc.one_tick[0] += 1
        if mids[i + 1] != mids[i]:
            acc.one_tick[1] += 1
            continue
        prints = tick.trades.get(product, [])
        acc.one_tick[2] += any(t.price >= book.asks[0][0] for t in prints)
        acc.one_tick[3] += any(t.price <= book.bids[0][0] for t in prints)

    for i, tick in enumerate(day.ticks[:-1]):  # Tao et al.'s spoofability inputs
        book, after = tick.books.get(product), day.ticks[i + 1].books.get(product)
        if mids[i] is None or mids[i + 1] is None:
            continue
        prints = tick.trades.get(product, [])
        before = _depth_share(book)
        acc.spoof_shares.append(before)
        if not prints:
            acc.spoof_moves.append((2 * before - 1, (mids[i + 1] - mids[i]) / unit))
            continue
        for side, levels, hits in ((1, book.asks, [t.quantity for t in prints if t.price >= book.asks[0][0]]),
                                   (-1, book.bids, [t.quantity for t in prints if t.price <= book.bids[0][0]])):
            if hits:
                size, depth = sum(hits), [v for _, v in levels[:SPOOF_LEVELS]]
                emptied = sum(1 for k in range(len(depth)) if sum(depth[:k + 1]) < size)
                share = _depth_share(after)
                acc.spoof_orders.append((size, sum(depth), emptied, share if side > 0 else 1 - share))
                acc.spoof_before.append((side, before if side > 0 else 1 - before))

    last_sign = None
    for i, tick in enumerate(day.ticks):
        book = tick.books.get(product)
        if book is None or not (book.bids and book.asks):
            continue
        bid, ask = book.bids[0][0], book.asks[0][0]
        for trade in tick.trades.get(product, []):
            sign = 1 if trade.price >= ask else -1 if trade.price <= bid else 0
            if not sign:
                acc.inside += 1
                continue
            acc.trades += 1
            acc.buys += sign > 0
            acc.trade_spreads.append(ask - bid)
            if last_sign is not None:
                acc.sign_pairs.append(sign * last_sign)
            last_sign = sign
            for name, ref in refs.items():
                acc.edges[name].append(sign * (ref[i] - trade.price))
                for horizon in (1, LAG):
                    if i + horizon < len(ref):
                        acc.moves.setdefault((name, horizon), []).append(sign * (ref[i + horizon] - ref[i]))
                if i + LAG < len(ref):
                    acc.slow_gains[name].append(sign * (trade.price - ref[i + LAG]))


def _add_book_changes(acc: _Acc, day: Day, product: str) -> None:
    """The wall's and the best level's changes from one two-sided tick to the next (module docstring, "Book changes")."""
    last, deltas, emptied = None, [], []  # emptied: (side, price, tick) of each best emptied by market trades
    for i, tick in enumerate(day.ticks):
        book = tick.books.get(product)
        if book is None or not (book.bids and book.asks):
            last = None
            deltas.append(None)
            continue
        for event in list(emptied):
            side, price, start = event
            if side * ((book.bids if side > 0 else book.asks)[0][0] - price) >= 0 or i - start >= LAG:
                acc.refills.append(i - start if side * ((book.bids if side > 0 else book.asks)[0][0] - price) >= 0 else math.inf)
                emptied.remove(event)
        if last is None:
            deltas.append(None)
        else:
            deltas.append((book.wall_mid - last.wall_mid, book.mid - last.mid))
            prints = day.ticks[i - 1].trades.get(product, [])  # a tick's trades come after its book, before the next
            for side, before, now in ((1, last.bids, book.bids), (-1, last.asks, book.asks)):
                wall_before, wall_now = max(before, key=lambda level: level[1]), max(now, key=lambda level: level[1])
                acc.wall_pairs[0] += 1
                acc.wall_pairs[1 if wall_now[0] != wall_before[0] else 2] += 1
                acc.wall_pairs[3] += wall_now == wall_before
                price, size = before[0]
                traded = min(size, sum(t.quantity for t in prints if t.price == price))
                if now[0][0] == price:
                    net = now[0][1] - size + traded  # added less cancelled
                    acc.best[0] += 1
                    acc.best[1] += not traded
                    acc.best[2] += not traded and now[0][1] == size
                    acc.best[3:7] = [acc.best[3] + size, acc.best[4] + max(net, 0), acc.best[5] + max(-net, 0), acc.best[6] + traded]
                elif traded >= size and side * (now[0][0] - price) < 0:
                    emptied.append((side, price, i))
        last = book
    acc.refills += [math.inf] * len(emptied)
    for a, b in zip(deltas, deltas[1:]):
        if a is not None and b is not None:
            for name, x, y in (("wall", a[0], b[1]), ("mid", a[1], b[0])):
                m = acc.leads[name]
                m[:] = [m[0] + 1, m[1] + x, m[2] + y, m[3] + x * x, m[4] + y * y, m[5] + x * y]


def _correlation(m: list[float]) -> float | None:
    """The correlation from the moments n, Σx, Σy, Σx², Σy², Σxy."""
    n, sx, sy, sxx, syy, sxy = m
    vx, vy = n * sxx - sx * sx, n * syy - sy * sy
    return (n * sxy - sx * sy) / math.sqrt(vx * vy) if n > 2 and vx > 0 and vy > 0 else None


def _summarise(acc: _Acc) -> dict[str, float | str | None]:
    tick = acc.tick_size or 1.0
    spread_ticks = [s / tick for s in acc.spreads]
    c1 = _mean(acc.sign_pairs)
    row: dict[str, float | str | None] = {
        "ticks": acc.ticks,
        "two_sided": _share(acc.two_sided, acc.ticks),
        "one_side_empty": _share(acc.one_empty, acc.ticks),
        "tick": acc.tick_size,
        "mean_mid": _mean(acc.mids),
        "wall_median": statistics.median(acc.walls) if acc.walls else None,
        "wall_sd": statistics.pstdev(acc.walls) if acc.walls else None,
        "wall_mean": _mean(acc.walls),
        "wall_day_means_sd": statistics.pstdev(acc.day_means) if len(acc.day_means) > 1 else None,
        "limit": acc.limit,
        "bot_tick": acc.bot_tick,
        "spread_ticks_median": statistics.median(spread_ticks) if spread_ticks else None,
        "spread_ticks_mean": _mean(spread_ticks),
        "wall_size": statistics.median(acc.largest) if acc.largest else None,
        "wall_seen": _share(sum(1 for v in acc.largest if v >= WALL_SIZE), len(acc.largest)),
        "at_one_tick": _share(sum(1 for s in spread_ticks if s <= 1 + 1e-9), len(spread_ticks)),
        "jump_share": _share(sum(1 for move, half in acc.wall_moves if move > max(half, tick) + 1e-9), len(acc.wall_moves)),
        "snap_jumps": sum(n for _, n, _, _ in acc.snaps),
        "snap_back": _share(sum(r for *_, r in acc.snaps), sum(p for _, _, p, _ in acc.snaps)) if sum(n for _, n, _, _ in acc.snaps) >= MIN_JUMPS else None,
        "jump_size": statistics.median(acc.jump_sizes) if acc.jump_sizes else None,
        "wall_stay": acc.wall_pairs[0] / acc.wall_pairs[1] if acc.wall_pairs[1] else (math.inf if acc.wall_pairs[0] else None),
        "wall_size_kept": _share(acc.wall_pairs[3], acc.wall_pairs[2]),
        "wall_leads": _correlation(acc.leads["wall"]),
        "mid_leads": _correlation(acc.leads["mid"]),
        "lead": None if None in (_correlation(acc.leads["wall"]), _correlation(acc.leads["mid"])) else _correlation(acc.leads["wall"]) - _correlation(acc.leads["mid"]),
        "best_kept": _share(acc.best[2], acc.best[1]),
        "best_added": acc.best[4] / acc.best[3] if acc.best[3] else None,
        "best_cancelled": acc.best[5] / acc.best[3] if acc.best[3] else None,
        "best_traded": acc.best[6] / acc.best[3] if acc.best[3] else None,
        "refills": len(acc.refills),
        "refill_ticks": statistics.median(acc.refills) if acc.refills else None,
        "refill_next": _share(sum(1 for r in acc.refills if r <= 1), len(acc.refills)),
        "one_tick_ticks": acc.one_tick[0],
        **dict(zip(("lambda", "lambda_buy", "lambda_sell"), (n / acc.one_tick[0] if acc.one_tick[0] >= MIN_ONE_TICK else None for n in acc.one_tick[1:]))),
        **_spoofability(acc),
        "mid_lag1_autocorr": _weighted(acc.autocorr),
        "mid_signature": _weighted(acc.signature["mid"]),
        "wall_signature": _weighted(acc.signature["wall"]),
        "wall_reversion": _weighted(acc.reversion),
        "drift_per_day": _mean(acc.drifts),
        "drift_ratio_least": min(acc.drift_ratios, key=abs) if acc.drift_ratios else None,
        "drift_ratio_most": max(acc.drift_ratios, key=abs) if acc.drift_ratios else None,
        "trades": acc.trades,
        "inside_share": _share(acc.inside, acc.trades + acc.inside),
        "buy_share": _share(acc.buys, acc.trades),
        "c1": c1,
        "spread_at_trades": _mean(acc.trade_spreads),
    }
    for name in REFERENCES:
        row[f"q_{name}"], row[f"r_{name}"], row[f"smoothing_{name}"] = _kalman(acc.variogram[name], _mean([d * d for d in acc.drift_rates]) or 0.0)
    for name in REFERENCES:
        edge = _mean(acc.edges[name])
        r1, rl = _mean(acc.moves.get((name, 1))), _mean(acc.moves.get((name, LAG)))
        row[f"edge_{name}"] = edge
        row[f"r1_{name}"] = r1
        row[f"r{LAG}_{name}"] = rl
        row[f"r{LAG}_{name}_t"] = _t_stat(acc.moves.get((name, LAG)))
        row[f"slow_{name}"] = _mean(acc.slow_gains[name])
        row[f"slow_{name}_t"] = _t_stat(acc.slow_gains[name])
        row[f"fast_{name}"] = -edge * (1 - c1) - r1 if None not in (edge, r1, c1) else None
    pooled = _edges(_profile(acc))
    row.update(pooled)
    # A note needs every day to agree: the pooled ratio past PROFILE_RATIO, and each day's on its side.
    daily = [_edges(_profile(acc, [parts])) for parts in acc.parts]
    for key, ratio in pooled.items():
        agree = ratio is not None and all(d[key] is not None and (d[key] >= PROFILE_RATIO if ratio >= 1 else d[key] <= 1 / PROFILE_RATIO) for d in daily)
        row[f"{key}_every_day"] = agree
    row["notes"] = "; ".join(_notes(row, acc)) or "-"
    return row


def _profile(acc: _Acc, days: list[_Parts] | None = None) -> dict[str, list[float | None]]:
    """Per tenth of the day, over `days` (default: all of them): the mean spread in ticks, the wall mid's
    mean |move| a tick in ticks, and market trades per 1,000 ticks."""
    tick, days = acc.tick_size or 1.0, acc.parts if days is None else days
    spreads = [[sum(d.spreads[k][j] for d in days) for j in (0, 1)] for k in range(PARTS)]
    moves = [[sum(d.moves[k][j] for d in days) for j in (0, 1)] for k in range(PARTS)]
    trades = [(sum(d.trades[k] for d in days), sum(d.ticks[k] for d in days)) for k in range(PARTS)]
    return {
        "spread": [total / n / tick if n else None for total, n in spreads],
        "move": [total / n / tick if n else None for total, n in moves],
        "trades": [1000 * t / n if n else None for t, n in trades],
    }


def _edges(profile: dict[str, list[float | None]]) -> dict[str, float | None]:
    """The first and the last tenth of each profile row over the median of the tenths between."""
    out = {}
    for edge, k in (("open", 0), ("close", PARTS - 1)):
        for name, values in profile.items():
            middle = [v for v in values[1:-1] if v is not None]
            base = statistics.median(middle) if middle else None
            out[f"{edge}_{name}"] = values[k] / base if values[k] is not None and base else None
    return out


def _notes(row: dict, acc: _Acc) -> list[str]:
    notes = []
    if row["at_one_tick"] is not None:
        if row["at_one_tick"] >= LARGE_TICK_SHARE:
            notes.append(f"large-tick (one-tick spread {row['at_one_tick']:.0%} of the time)")
            if row["lambda"] is not None:
                sides = [side for side, key in (("ask", "lambda_buy"), ("bid", "lambda_sell")) if row[key] > row["lambda"] / 2]
                where = "both sides" if len(sides) == 2 else f"the {sides[0]} only" if sides else "neither side: take only or stand aside"
                notes.append(f"making at a one-tick spread pays on {where} (Gao & Wang: uninformed hits λ+ {row['lambda_buy']:.3f}, "
                             f"λ- {row['lambda_sell']:.3f} a tick against λ/2 {row['lambda'] / 2:.3f})")
        else:
            notes.append(f"small-tick (median spread {row['spread_ticks_median']:g} ticks)")
    if row["wall_seen"] is not None and row["wall_seen"] < WALL_SEEN:
        notes.append(
            f"a level of {WALL_SIZE}+ on only {row['wall_seen']:.0%} of sides (largest level median {row['wall_size']:g}): "
            "set wall_size near it, or sized_mid falls back to the mid"
        )
    if (row["one_side_empty"] or 0) >= EMPTY_SIDE_SHARE:
        notes.append(f"a side empty {row['one_side_empty']:.0%} of ticks")
    if (row["jump_share"] or 0) >= JUMPY:
        notes.append(f"wall mid jumps past half the spread on {row['jump_share']:.0%} of ticks: if orders rest, take only")
    snapping = [(day, n, r / p) for day, n, p, r in acc.snaps if n >= MIN_JUMPS and p and r / p >= SNAP_BACK]
    if snapping:
        days = ", ".join(f"{day} {share:.0%} of {n}" for day, n, share in snapping)
        size, exact, residue, on_grid = _jump_grid(acc.jump_days, [day for day, _, _ in snapping], row["tick"] or 1.0)
        grid = f", the wall mid at {residue:g} mod {size:g} on {on_grid:.0%} of ticks" if on_grid >= GRID_SHARE else ""
        notes.append(f"jumps of {SNAP_SPREADS}+ spreads snap back ({days} reversed the one before; usual size {size:g}, "
                     f"exactly that on {exact:.0%}{grid}): fade them, the template's jump mode with jump_min about {size / 2:g}")
    fixed = row["wall_sd"] is not None and row["wall_sd"] <= FIXED_SD_TICKS * (row["tick"] or 1.0)
    if fixed:
        notes.append(f"wall mid nearly fixed at {row['wall_median']:g} (sd {row['wall_sd']:.2f})")
    if row["best_kept"] is not None and row["best_kept"] >= PERSISTENT_QUEUE:
        notes.append(f"queues persist (the best keeps its size on {row['best_kept']:.0%} of ticks without a trade at it): "
                     "if orders rest, queue place matters; calibrate --queue on the first upload")
    if row["lead"] is not None and abs(row["lead"]) >= WALL_LEAD:
        notes.append(f"the {'wall moves before the mid' if row['lead'] > 0 else 'mid moves before the wall'} (lead {row['lead']:+.2f}): "
                     f"{'a lead for the fair' if row['lead'] > 0 else 'the wall mid lags; try the mid or sized_mid'}")
    if row["mid_lag1_autocorr"] is not None and row["mid_lag1_autocorr"] <= MEAN_REVERTING:
        notes.append("mid mean-reverts at one tick")
    mid_sig, wall_sig = row["mid_signature"], row["wall_signature"]
    if mid_sig is not None and wall_sig is not None and mid_sig >= NOISY_SIGNATURE:
        smoothing = f" (Kalman smoothing: wall mid {_cell(row['smoothing_wall'], '{:.2f}')}, mid {_cell(row['smoothing_mid'], '{:.2f}')})"
        if wall_sig < mid_sig / 2:
            notes.append("wall mid filters the mid's noise" + smoothing)
        else:
            notes.append("mid and wall mid both noisy" + smoothing)
    if not fixed and row["wall_reversion"] is not None and row["wall_reversion"] >= SLOW_REVERSION:
        notes.append(f"wall mid reverts to a level over ~{LONG_LAG:,} ticks")
    ratios = acc.drift_ratios
    drifting = [r for r in ratios if abs(r) >= DRIFT_RATIO]
    if ratios and len(drifting) == len(ratios) and len({r > 0 for r in ratios}) == 1:
        notes.append(f"drifts {'up' if ratios[0] > 0 else 'down'} every day ({row['drift_per_day']:+,.0f} a day)")
    elif drifting:
        notes.append(f"drifts on {len(drifting)} of {len(ratios)} days")

    names = {"spread": "spread", "move": "volatility", "trades": "trades"}
    for edge, label in (("open", "the open (first tenth)"), ("close", "the close (last tenth)")):
        unusual = [f"{names[name]} {row[f'{edge}_{name}']:.1f}x" for name in names
                   if row[f"{edge}_{name}_every_day"] and (name != "trades" or acc.trades >= MIN_TRADES * PARTS) and (name != "move" or not fixed)]
        if unusual:
            notes.append(f"{label}: {', '.join(unusual)} the day's middle (--profile)")

    if row["spoof_score"] is not None and row["spoof_score"] > 0:
        notes.append(f"spoofable (Tao et al.'s score {row['spoof_score']:+.2f}: the move follows the imbalance, µ+ {row['spoof_mu']:.2f}, "
                     f"orders are {row['spoof_size']:.0%} of the depth and reach level {SPOOF_LEVELS - 1} on {row[f'spoof_q{SPOOF_LEVELS - 1}']:.0%}): "
                     "expect spoofers if the market is shared")
    if acc.trades < MIN_TRADES:
        notes.append(f"{acc.trades} market trades: too few for trade statistics")
        return notes
    buys = row["buy_share"]
    one_sided = buys <= ONE_SIDED or buys >= 1 - ONE_SIDED
    if one_sided:
        notes.append(f"trades nearly all {'buys' if buys > 0.5 else 'sells'}")
    if row["c1"] >= PERSISTENT_SIGNS:
        notes.append(f"trade signs persist (C(1) {row['c1']:.2f})")
    cost, move, t = -row["edge_wall"], row[f"r{LAG}_wall"], row[f"r{LAG}_wall_t"]
    if t is not None and abs(t) >= T_STAT and abs(move) >= INFORMED_SHARE * abs(cost):
        notes.append("trades move the wall mid" if move > 0 else "wall mid reverts after trades")
    slow, slow_t, spread = row["slow_wall"], row["slow_wall_t"], row["spread_at_trades"]
    if slow is not None and spread:
        share = slow / spread
        if one_sided or row["c1"] >= PERSISTENT_SIGNS:
            fast = row["fast_wall"] / spread if row["fast_wall"] is not None else 0.0
            notes.append(f"a maker's position only grows: fast margin {fast:+.2f} of the spread")
        elif slow_t is not None and abs(slow_t) < T_STAT:
            notes.append(f"market-making margin not measurably non-zero ({share:+.2f} of the spread)")
        elif share < THIN_MARGIN_SHARE:
            notes.append(f"thin or negative market-making margin ({share:+.2f} of the spread)")
        else:
            notes.append(f"market making pays ({share:.2f} of the spread a unit)")
    return notes


def _depth_share(book) -> float:
    """ı: the bid's share of the volume on the best SPOOF_LEVELS levels of each side (0.5 for an empty book)."""
    bids, asks = sum(v for _, v in book.bids[:SPOOF_LEVELS]), sum(v for _, v in book.asks[:SPOOF_LEVELS])
    return bids / (bids + asks) if bids + asks else 0.5


def _spoofability(acc: _Acc) -> dict[str, float | None]:
    """Tao et al.'s inputs and score (module docstring); None where there are too few orders or quiet ticks."""
    keys = ["spoof_mu", "spoof_size", "spoof_imbalance"] + [f"spoof_q{k}" for k in range(SPOOF_LEVELS)] + [f"spoof_nu{k}" for k in range(SPOOF_LEVELS)] + ["spoof_score"]
    out: dict[str, float | None] = dict.fromkeys(keys + ["spoof_before", "spoof_snap"])
    if len(acc.spoof_orders) >= MIN_TRADES:
        parts = [([x for s, x in acc.spoof_before if s == side], [x if side > 0 else 1 - x for x in acc.spoof_shares]) for side in (1, -1)]
        out["spoof_before"] = sum(len(xs) * _wasserstein(xs, usual) for xs, usual in parts if xs) / len(acc.spoof_before)
        out["spoof_snap"] = _wasserstein([x for _, x in acc.spoof_before], [o[3] for o in acc.spoof_orders])
    xs = [x for x, _ in acc.spoof_moves]
    if len(acc.spoof_orders) < MIN_TRADES or len(xs) < MIN_TRADES or len(set(xs)) < 2:
        return out
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(y for _, y in acc.spoof_moves)
    mu = sum((x - mean_x) * (y - mean_y) for x, y in acc.spoof_moves) / sum((x - mean_x) ** 2 for x in xs)
    size = statistics.fmean(o[0] for o in acc.spoof_orders) / statistics.fmean(o[1] for o in acc.spoof_orders)
    imbalance = statistics.fmean(o[3] for o in acc.spoof_orders)
    q = [_share(sum(1 for o in acc.spoof_orders if o[2] > k), len(acc.spoof_orders)) for k in range(SPOOF_LEVELS)]
    nu = [statistics.fmean(max(o[2] - k, 0) for o in acc.spoof_orders) for k in range(SPOOF_LEVELS)]
    score = max(2 * size * mu * (1 - imbalance) * imbalance / SPOOF_LEVELS - q[k] * size - nu[k] for k in range(SPOOF_LEVELS))
    return out | dict(zip(keys, [mu, size, imbalance, *q, *nu, score]))


def _wasserstein(xs: list[float], ys: list[float], points: int = 200) -> float:
    """The 1-Wasserstein distance between two samples: the mean gap between their quantiles at `points` levels."""
    xs, ys = sorted(xs), sorted(ys)

    def at(sample: list[float], u: float) -> float:
        return sample[min(int(u * len(sample)), len(sample) - 1)]

    return statistics.fmean(abs(at(xs, (k + 0.5) / points) - at(ys, (k + 0.5) / points)) for k in range(points))


def _jump_moves(walls: list[float], spread: float) -> list[float]:
    """One day's wall mid moves of at least SNAP_SPREADS × spread, signed."""
    return [b - a for a, b in zip(walls, walls[1:]) if spread and abs(b - a) >= SNAP_SPREADS * spread]


def _jump_grid(jump_days: dict[str, tuple[list[float], list[float]]], days: list[str], tick: float) -> tuple[float, float, float, float]:
    """Over these days' jumps: (their median size, the share within half a tick of it, the wall mid's most common value
    modulo that size, the share of ticks there)."""
    sizes = [v for day in days for v in jump_days[day][0]]
    size = statistics.median(sizes)
    exact = _share(sum(1 for v in sizes if abs(v - size) <= tick / 2 + 1e-9), len(sizes))
    residues = Counter(round(round((w % size) / tick) * tick % size, 9) for day in days for w in jump_days[day][1])
    residue, count = residues.most_common(1)[0]
    return size, exact, residue, count / sum(residues.values())


def _snap_backs(walls: list[float], spread: float) -> tuple[int, int, int]:
    """One day's wall mids: (jumps of at least SNAP_SPREADS × spread, consecutive pairs of them, pairs in opposite directions)."""
    jumps = _jump_moves(walls, spread)
    pairs = list(zip(jumps, jumps[1:]))
    return len(jumps), len(pairs), sum(1 for a, b in pairs if a * b < 0)


def _kalman(variogram: list[list[float]], drift2: float = 0.0) -> tuple[float | None, float | None, float | None]:
    """(q, r, smoothing) of the local-level model fitted to [sum, count] of squared changes at each of KALMAN_LAGS.

    `drift2` is the squared drift a tick: with it, the smoothing that minimises the EMA's error (_ema_error)."""
    points = [(lag, total / n) for lag, (total, n) in zip(KALMAN_LAGS, variogram) if n]
    if len(points) < 2:
        return None, None, None
    mean_h, mean_m = statistics.fmean(h for h, _ in points), statistics.fmean(m for _, m in points)
    slope = sum((h - mean_h) * (m - mean_m) for h, m in points) / sum((h - mean_h) ** 2 for h, _ in points)
    q, r = max(slope, 0.0), max((mean_m - slope * mean_h) / 2, 0.0)
    if drift2 and (q or r):  # golden-section search: the error is unimodal in s
        lo, hi = 0.0, 0.9999
        for _ in range(60):
            a, b = hi - 0.618 * (hi - lo), lo + 0.618 * (hi - lo)
            lo, hi = (lo, b) if _ema_error(a, q, r, drift2) <= _ema_error(b, q, r, drift2) else (a, hi)
        return q, r, round((lo + hi) / 2, 4)
    if not q:
        return q, r, 1.0 if r else None  # no random walk: noise around a fixed value (or no moves at all)
    predicted = (q + math.sqrt(q * q + 4 * q * r)) / 2
    return q, r, r / (predicted + r)  # 1 - K, K = P / (P + r)


def _ema_error(s: float, q: float, r: float, drift2: float) -> float:
    """Steady-state mean squared error of fair = s * fair + (1 - s) * price against the local level, which
    steps by a drift (squared: drift2) plus noise of variance q, seen through noise of variance r."""
    return drift2 * (s / (1 - s)) ** 2 + (s * s * q + (1 - s) ** 2 * r) / (1 - s * s)


def _lag1_autocorrelation(x: list[float]) -> float:
    mean = statistics.fmean(x)
    var = sum((v - mean) ** 2 for v in x)
    return sum((a - mean) * (b - mean) for a, b in zip(x, x[1:])) / var if var else 0.0


def _variance_per_tick(series: list[float | None], lag: int) -> float | None:
    """Mean squared change over `lag` ticks, over `lag` (no mean taken out, as in a variogram)."""
    squares = [
        (series[i + lag] - series[i]) ** 2
        for i in range(len(series) - lag)
        if series[i] is not None and series[i + lag] is not None
    ]
    return sum(squares) / len(squares) / lag if squares else None


def _signature_ratio(series: list[float | None]) -> float | None:
    short, long = _variance_per_tick(series, 1), _variance_per_tick(series, LAG)
    return short / long if short is not None and long else None


def _forward_fill(values: list[float | None]) -> list[float | None]:
    out, last = [], None
    for value in values:
        last = value if value is not None else last
        out.append(last)
    # Ticks before the first price take the first price.
    first = next((v for v in out if v is not None), None)
    return [first if v is None else v for v in out]


def _t_stat(values: list[float] | None) -> float | None:
    if not values or len(values) < 2:
        return None
    mean, sd = statistics.fmean(values), statistics.stdev(values)
    if not sd:
        return math.copysign(math.inf, mean) if mean else 0.0
    return mean / (sd / len(values) ** 0.5)


def _weighted(pairs: list[tuple[float, int]]) -> float | None:
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def _mean(values) -> float | None:
    return statistics.fmean(values) if values else None


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


# ---------------------------------------------------------------------------- suggest

STOP_SDS = 10  # stop_loss: this many times the limit times the sd of the wall mid's STOP_HORIZON-tick moves...
STOP_HORIZON = 500
STOP_SPREADS = 2  # ...and at least the limit times this many median spreads (the hand-set stops: 7.5-12 times, Kelp to Velvetfruit)
LEVEL_SPREADS = 2  # a level is faded only where the wall mid's sd is at least this many median spreads, so the swings pay for crossing
LEVEL_AGREE = 0.5  # the days' mean wall mids agree when their sd is at most this share of the wall mid's sd: a fixed level
MIN_SMOOTHING = 0.1  # a Kalman smoothing below this is left out
MAX_SMOOTHING = 0.95  # ...and one above is capped: at 1.0 (q 0, noise around a fixed value) the template's fair never moves
SIZE_TO_DEPTH = 5  # a limit this many times the largest level's median gets make_size at that level
PRICES = ("fixed_fair", "fixed_guard", "make_edge", "jump_min", "jump_edge", "level", "level_band", "clear_edge", "skew", "stop_loss")


def suggest(row: dict) -> tuple[dict, list[str]]:
    """A template PARAMS entry from one product's diagnostics, and why each setting is there.

    The day-one table in references/wiki/concepts/reading-the-data-on-day-one.md, row by row: a nearly
    fixed wall mid is `fair: fixed` with a guard; otherwise `wall_mid`, smoothed at the Kalman value
    where mid and wall mid are both noisy; a level the wall mid reverts to is `level` (the days' mean
    when they agree, else "day"); a drift every day is a `target` at the limit; jumps that snap back
    are the jump mode at half their size; make_edge a tick where market making pays, at the touch
    where it is thin or the position only grows, half a tick (joining the best) on a large-tick book where it pays; no quotes where Gao & Wang's condition fails on
    both sides; make_size where the limit dwarfs the depth; stop_loss from the wall mid's moves. A
    large-tick book that also drifts gets a note to grid taking only (make_size 0) against the quotes
    under `worse` fills, where a trend turned joining the best into a loss.
    Prices are in the data's unit, or in the bot's ticks where the format gives one (the drill's).
    """
    notes, tick = row["notes"], row["tick"] or 1.0
    spread = (row["spread_ticks_median"] or 2) * tick
    out: dict = {"limit": row["limit"]} if row.get("limit") else {}
    why: list[str] = []
    if "nearly fixed" in notes:
        out.update(fair="fixed", fixed_fair=round(row["wall_median"] / tick) * tick, fixed_guard=spread / 2 + tick)
        why.append("pegged")
    else:
        out["fair"] = "wall_mid"
        if "both noisy" in notes and (row["smoothing_wall"] or 0) >= MIN_SMOOTHING:
            out["smoothing"] = round(min(row["smoothing_wall"], MAX_SMOOTHING), 2)
            why.append("noisy wall mid: Kalman smoothing")
    if "market making pays" in notes:
        out["make_edge"] = tick
        why.append("margin pays: a tick")
    elif "thin or negative" in notes or "only grows" in notes:
        out["make_edge"] = max(2 * tick, spread / 2)
        why.append("thin margin: quote at the touch")
    if "large-tick" in notes and "market making pays" in notes:  # not where the margin is thin: standing back is the point there
        out["make_edge"] = tick / 2  # a tick away sits behind a one-tick book and never fills (IDEAS.md, "A large-tick book")
        why.append("large-tick: join the best")
        if "drifts" in notes:  # a trend turns joining the best into a loss under worse fills (IDEAS.md, "`arena.diagnose --suggest`")
            why.append("and drifting: grid make_size=0,None against it under --modes worse before trusting these quotes")
    if "pays on neither side" in notes:
        out["make_size"] = 0
        why.append("Gao & Wang: no side pays")
    elif row.get("wall_size") and row.get("limit") and row["limit"] >= SIZE_TO_DEPTH * row["wall_size"]:
        out["make_size"] = round(row["wall_size"])
        why.append("limit dwarfs the depth")
    if "snap back" in notes and row.get("jump_size"):
        out.update(jump_min=row["jump_size"] / 2, jump_edge=spread / 2 + tick)
        why.append("jumps snap back")
    elif "reverts to a level" in notes and row["wall_sd"] and row["wall_sd"] >= LEVEL_SPREADS * spread:
        agree = row["wall_day_means_sd"] is not None and row["wall_day_means_sd"] <= LEVEL_AGREE * row["wall_sd"]
        out.update(level=round(row["wall_mean"]) if agree else "day", level_band=round(row["wall_sd"]), clear_edge=round(spread / 2))
        why.append("reverts to a level" + ("" if agree else " that moves across days"))
    elif "drifts up every day" in notes or "drifts down every day" in notes:
        sign = 1 if "drifts up" in notes else -1
        out.update(target=sign * (row["limit"] or 0), skew=(row["limit"] or 0) / 4)
        why.append("drifts every day")
    if row.get("limit") and row["q_wall"] is not None:
        stop = max(STOP_SDS * row["limit"] * math.sqrt(STOP_HORIZON * row["q_wall"]), STOP_SPREADS * row["limit"] * spread)
        out["stop_loss"] = float(f"{stop:.2g}")
    scale = row.get("bot_tick") or 1.0
    out = {k: v / scale if k in PRICES and isinstance(v, (int, float)) else v for k, v in out.items()}
    return {k: int(v) if isinstance(v, float) and v.is_integer() else round(v, 6) if isinstance(v, float) else v for k, v in out.items()}, why


def format_suggestion(rows: dict[str, dict]) -> str:
    lines = ["PARAMS = {  # arena.diagnose --suggest: a starting point to backtest and grid, not a tuned setting"]
    for product, row in rows.items():
        params, why = suggest(row)
        lines.append(f"    {product!r}: {params!r},  # {'; '.join(why) or 'plain market making'}")
    return "\n".join(lines + ["}"])


# ---------------------------------------------------------------------------- report

COLUMNS = (  # (key, header, format)
    ("spread_ticks_median", "spread", "{:g}t"),
    ("at_one_tick", "1 tick", "{:.0%}"),
    ("one_side_empty", "empty", "{:.0%}"),
    ("wall_size", "wall", "{:g}"),
    ("wall_seen", f"{WALL_SIZE}+", "{:.0%}"),
    ("jump_share", "jumps", "{:.0%}"),
    ("lambda", "λ", "{:.3f}"),
    ("lambda_buy", "λ+", "{:.3f}"),
    ("lambda_sell", "λ-", "{:.3f}"),
    ("spoof_score", "spoof", "{:+.2f}"),
    ("snap_back", "snap", "{:.0%}"),
    ("wall_stay", "stay", "{:,.0f}"),
    ("best_kept", "kept", "{:.0%}"),
    ("refill_ticks", "refill", "{:g}"),
    ("lead", "lead", "{:+.2f}"),
    ("mid_lag1_autocorr", "mid AC1", "{:+.2f}"),
    ("mid_signature", "mid sig", "{:.1f}"),
    ("wall_signature", "wall sig", "{:.1f}"),
    ("wall_reversion", "slow rev", "{:.1f}"),
    ("smoothing_wall", "smooth", "{:.2f}"),
    ("drift_per_day", "drift/day", "{:+,.0f}"),
    ("trades", "trades", "{:,}"),
    ("buy_share", "buys", "{:.0%}"),
    ("c1", "C(1)", "{:+.2f}"),
    ("edge_wall", "edge", "{:+.2f}"),
    ("r1_wall", "R(1)", "{:+.2f}"),
    (f"r{LAG}_wall", f"R({LAG})", "{:+.2f}"),
    ("slow_wall", "slow", "{:+.2f}"),
    ("fast_wall", "fast", "{:+.2f}"),
)

LEGEND = (
    "spread: median, in ticks. 1 tick: share of two-sided ticks at a one-tick spread. empty: share of ticks with one side empty.\n"
    f"wall: median size of each side's largest level. {WALL_SIZE}+: share of sides with a level of {WALL_SIZE} or more (the template's wall_size).\n"
    "jumps: share of ticks on which the wall mid moves more than half the spread (and at least a tick).\n"
    "λ: at a one-tick spread, the share of ticks after which the mid moves; λ+ (λ-): with a buy at the ask (sell at the bid) after which it doesn't.\n"
    "  Gao & Wang: a quote at the best pays on a side iff its λ± > λ/2.\n"
    f"spoof: Tao et al.'s spoofability, max over the best {SPOOF_LEVELS} levels k of 2 ρ µ+ (1 - ı) ı w_k - Q_k ρ - ν_k (above 0: a spoof could pay).\n"
    f"snap: share of the wall mid's jumps of {SNAP_SPREADS}+ median spreads that went the opposite way to the one before "
    f"(with {MIN_JUMPS} or more; a day at {SNAP_BACK:.0%} gets a note).\n"
    "stay: ticks the wall's price stays. kept: share of ticks without a trade at an unchanged best where its size is unchanged\n"
    f"  (high: the queues persist). refill: median ticks until a best emptied by trades is back (inf: mostly not in {LAG}).\n"
    "lead: corr(wall mid change, next mid change) - corr(mid change, next wall mid change); positive: the wall moves first.\n"
    f"mid AC1: lag-1 autocorrelation of the mid's changes. sig: variance per tick at lag 1 over lag {LAG} (1 = random walk).\n"
    f"slow rev: the wall mid's variance per tick at lag {LAG} over lag {LONG_LAG:,} (above 1: it returns to a level).\n"
    f"smooth: the template's smoothing of the wall mid that a Kalman filter would use: a random walk (step variance q) in noise (r),\n"
    f"fitted as h q + 2 r to its squared changes at lags {', '.join(map(str, KALMAN_LAGS))}; 0 = a random walk, near 1 = mostly noise.\n"
    "drift/day: the wall mid's change per day. buys: share of market trades at or above the ask. C(1): sign correlation of consecutive trades.\n"
    f"Against the wall mid: edge = the taker's mean edge (negative = paid), R(h) = the signed move h ticks after a trade,\n"
    f"and a market maker's margin a unit, slow = -edge - R({LAG}), fast = -edge (1 - C(1)) - R(1) (Bouchaud et al. eqs. 17.13-17.14).\n"
    "The CSV (--csv) also has them against the mid. See references/wiki/concepts/reading-the-data-on-day-one.md."
)


def format_report(rows: dict[str, dict]) -> str:
    width = max([len(p) for p in rows] + [len("product")])
    cells = [[_cell(row.get(key), fmt) for key, _, fmt in COLUMNS] for row in rows.values()]
    widths = [max([len(header)] + [len(c[i]) for c in cells]) for i, (_, header, _) in enumerate(COLUMNS)]
    lines = ["  ".join([f"{'product':<{width}}"] + [f"{h:>{w}}" for (_, h, _), w in zip(COLUMNS, widths)])]
    for product, row_cells in zip(rows, cells):
        lines.append("  ".join([f"{product:<{width}}"] + [f"{c:>{w}}" for c, w in zip(row_cells, widths)]))
    lines.append("")
    lines += [f"{product}: {row['notes']}" for product, row in rows.items()]
    lines += ["", LEGEND]
    return "\n".join(lines)


def format_profile(profiles: dict[str, dict[str, list[float | None]]]) -> str:
    heads = [f"{100 * k // PARTS}-{100 * (k + 1) // PARTS}%" for k in range(PARTS)]
    rows = (("spread", "spread (ticks)", "{:.2f}"), ("move", "wall mid |move| a tick (ticks)", "{:.3f}"), ("trades", "market trades per 1,000 ticks", "{:.0f}"))
    width = max(len(label) for _, label, _ in rows)
    lines = ["By tenth of the day, pooled over the days:"]
    for product, profile in profiles.items():
        cells = [[_cell(v, fmt) for v in profile[key]] for key, _, fmt in rows]
        widths = [max(len(h), *(len(c[k]) for c in cells)) for k, h in enumerate(heads)]
        lines += ["", f"{product:<{width}}  " + "  ".join(f"{h:>{w}}" for h, w in zip(heads, widths))]
        lines += [f"{label:<{width}}  " + "  ".join(f"{c:>{w}}" for c, w in zip(row, widths)) for (_, label, _), row in zip(rows, cells)]
    return "\n".join(lines)


def _cell(value, fmt: str) -> str:
    return "-" if value is None else fmt.format(value)


def write_csv(rows: dict[str, dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(next(iter(rows.values()), {}))
    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["product", *keys])
        for product, row in rows.items():
            writer.writerow([product, *("" if row.get(k) is None else row[k] for k in keys)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.diagnose", description="Per-product diagnostics of a market's data.")
    parser.add_argument("days", nargs="+", help="days to read: ROUND for all its days, or ROUND-DAY (e.g. 1, 1-0, 1--1)")
    parser.add_argument("--format", default="prosperity", choices=sorted(FORMATS), help="competition format (default: prosperity)")
    parser.add_argument("--data", default="p3", help="data folder, or p2 / p3 / p4 for the Prosperity data in references/ (default: p3)")
    parser.add_argument("--csv", type=Path, help="also write every diagnostic, against both references, to this CSV")
    parser.add_argument("--profile", action="store_true", help="also print each product's spread, volatility and trades by tenth of the day")
    parser.add_argument("--suggest", action="store_true", help="also print a PARAMS block for the template, read off the notes")
    args = parser.parse_args(argv)
    fmt = FORMATS[args.format]
    try:
        days = fmt.load_days(fmt.resolve_data_dir(args.data), args.days)
    except ValueError as error:
        parser.error(str(error))
    rows = diagnose(days)
    print(f"{len(days)} day(s): {', '.join(d.name for d in days)}\n")
    print(format_report(rows))
    if args.profile:
        print("\n" + format_profile(time_profile(days)))
    if args.suggest:
        print("\n" + format_suggestion(rows))
    if args.csv:
        write_csv(rows, args.csv)
        print(f"\nwritten to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
