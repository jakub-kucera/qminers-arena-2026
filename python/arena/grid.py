"""Grid search over bot parameters, with robustness checks.

    uv run python -m arena.grid python/bots/template.py 1 \\
        --grid PARAMS.KELP.make_edge=1,2,3 --grid PARAMS.KELP.take_edge=0..2 --modes all,worse

Every combination of --grid values is backtested on every given day, under each trade-matching
mode in --modes, in parallel. The combination with the best PnL is usually overfit, so each
combination also gets:

  min day   its worst single day: a good setting should do well on every day, not just one
  nbhd      the mean PnL of it and its grid neighbours (one step along any axis), leaving out
            neighbours that failed. Prefer a plateau, where nearby values do about as well, to a
            lone spike.
  <mode>    PnL under each extra --modes entry, e.g. `worse` fill matching. A gain that only
            exists with optimistic fills is probably a backtest artefact. A --scenario (arena.scenario:
            engine settings and rivals of its own) is one more mode, and with one the summary adds
  worst     the least PnL over the modes and scenarios: a measure to read, not a rule (picked by it,
            cells lost most often on unseen days: python/experiments/day/selection_rules.py, part 2).

Next to them, the shape of the first mode's PnL path, from each day's PnL at the end of every
FINE_TICKS block (report.PathRisk): max dd (the largest fall from a running high within a day),
conc (the largest share of a day's PnL made in one report.WINDOW_TICKS window), under (the time
below the running high), run (its longest stretch, as a share of the day) and sharpe/d (mean over
sd of the days' PnL). A cell is flagged `late` when one window made half a day's PnL or more after
a stretch without a new high lasting half the day: a lucky late reversal. --sort takes each, and
--out writes them per mode.

The summary names the best combination by each measure and says whether they agree. It flags the
best cell by --sort where it sits on the lowest or highest value of a numeric axis (the best may lie
past it: widen the axis), and prints a finer grid around it, from the value below to the value above
at half the step, for one second pass judged by the same gates. With two or
more days it also holds out each day in turn: the combination with the best PnL on the other days
is scored on the held-out day. The total of those scores is what choosing by PnL earns on days it
didn't see, and its gap to the best combination's PnL is the selection bias of a grid this size.
It only covers the gridded values: a setting the bot fits to the data itself (say a level taken
from the days' mean) needs its own held-out test. Days whose data repeats are flagged, since
holding one out still trains on its copy.

Last, how much the choice can be trusted, on the first mode's PnL cut into blocks of ticks within
days (BLOCKS in all, as evenly as the days allow), with cells whose block PnL is identical counted
once:
  PBO       Bailey et al.'s probability of backtest overfitting by CSCV: over halvings of the blocks,
            how often the best cell on one half ranks at or below the median on the other. Near 50%
            the grid's pick carries no information. The same halvings give the pick's mean relative
            rank out of sample (1 is the top, 0.5 the median) and how often it loses money there.
            (Not the paper's slope of out-of-sample on in-sample performance: with PnL summed over
            blocks, a pick that stays the same cell gives -1 by construction.)
  DSR       Bailey and Lopez de Prado's deflated Sharpe ratio of the best cell's gain over the bot as
            is (--set only), block by block: the chance that the gain's per-block Sharpe ratio beats
            the best of N^ cells with no gain, N^ the cells' count discounted by the average
            correlation of their gains. On the cells' own PnL it would only say that the bot makes
            money. Below 0.95 the summary warns.
  SPA       Hansen's test that no cell beats the bot as is, on each cell's gain per block of
            FINE_TICKS ticks, with Politis and Romano's stationary bootstrap. Its p-value is the
            consistent one (c), between the liberal (l) and the studentized Reality Check (u). Unlike
            the DSR it discounts cells that are clearly worse, so a wide grid's poor corners don't
            hide a real gain.
  StepM     Romano and Wolf's step-down test on the same resamples: every cell that beats the bot as
            is, with the chance of naming even one false cell held at ALPHA (5%). Both studentize each
            resample by its own omega (arena.stats.bootstrap), as Romano and Wolf do; with the
            original's in every resample they named a noise cell in 8-22% of null grids. Both are
            read at TEST_ALPHA (4%), where null grids name a noise cell about 5% of the time.
  pick      StepM's best cell that also beats the bot as is under every other --modes entry, else
            the bot as is. Of ten ways of choosing, scored on unseen Prosperity days and on fresh
            simulated ones, it lost least often among those that gained (python/experiments/
            selection_rules.py, selection_rules_sim.py).
With --permute N the whole grid is also run on N copies of the days made of their own ticks in a
shuffled order (arena.stress.permute, in runs of --permute-block ticks), after Masters' permutation
test of a whole search (our adaptation; his book is unread). Two statistics of the search, on the
PnL of the products the axes set, are compared with each copy's: the best cell's PnL, and its lift
over the median cell. p is the share of copies, the real days counted as one, at least as large.
A small p for the lift says choosing exploits the order of the ticks (a trend, a level the price
returns to, a signal that leads it); a large one says a search this wide finds as much without
it, from what the copies keep (each tick's book and the fill model). Neither is measured against
the bot as is: its settings were tuned to the real order, which the copies remove.
With --screen SHARE (successive halving, one rung) every combination first runs on the first day
under the first mode, and only that share of them, the best there, on every day and mode. The
summary says what it dropped and how the screen day ranks the kept cells against the other days.
PBO, the DSR, SPA and StepM then see the kept cells only, on days that include the screen's, so
they understate the selection bias of the cells tried; with two or more days SPA, StepM and the
pick are also given on the other days alone, which the screen's choice can't bias. --permute
screens each copy the same way. --halving SHARE does it in steps: the cells run one day under one
mode at a time, the first mode's days first, and after each step but the last that share of the
cells still alive, by their PnL so far, goes on; the unseen-days section then leaves out every day a
step ranked on. --sample N runs N cells drawn at random from the whole grid, never listing it.
--search coord|tpe --budget N runs at most N cells (each on every day and mode), chosen as it goes
(arena.search): coordinate descent from the bot as is, or a tree-structured Parzen estimator. It
maximises a cell's smaller gain over the bot as is under the gate's modes (every --modes entry, or
the first with --gate first), on the data --holdout keeps, so the held-out check stays free of
its choice. Past about 100,000 cells either found the whole grid's best training cell in 0.1-5% of
its backtests, where random cells didn't (IDEAS.md, "Searching a big grid without running all of
it"). As with the screen, the tests see only the cells it ran.
Halvings and bootstrap blocks mix blocks of the same days, so a day-level change is invisible to
all of them: the held-out days are the check for that, and a cell they accept still has to hold
under the other --modes (references/wiki/concepts/validation-and-overfitting.md).
"""

from __future__ import annotations

import argparse
import csv
import itertools
import math
import os
import random
import statistics
import sys
import tempfile
import time
from array import array
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path

from arena import report, rust, search, stress
from arena.stats import (  # the statistics live in python/arena/stats.py (twinned in rust/src/arena/stats.rs); these names stay importable from here
    ALPHA, EULER_GAMMA, TEST_ALPHA, MAX_SPLITS, Cscv, _scales, bootstrap_means, cscv, deflated_sharpe, expected_max_sharpe, independent_trials,
    STUDENTIZE, bootstrap, mean_correlation, omega2, resamples, snooping, spa, standardized, stepm,
)
from arena.botfile import OverrideError, parse_value
from arena.cli import Setup, add_common_arguments, add_engine_argument, add_rival_argument, bot_module, participant_names, run_with_rivals, setup
from arena.engine import TradeMatching
from arena.formats import FORMATS
from arena.model import Day
from arena.scenario import Scenario, add_scenario_argument, config_for, every_rival, rivals_for, scenarios_from

SMOKE_TEST_TICKS = 200
BLOCKS = 16  # CSCV's S over all the days: Bailey et al. call 16 reasonable (p. 21-22)
FINE_TICKS = 100  # ticks per block for SPA and StepM: about 100 blocks a day
SPA_Q = 0.1  # stationary bootstrap: a new block starts with probability q, so blocks average 1/q
BOOTSTRAP = 1000  # resamples; Romano and Wolf recommend at least 1,000 (p. 15)
MIN_FINE_BLOCKS = 20  # fewer and the bootstrap tests are skipped


@dataclass(frozen=True)
class Axis:
    target: str
    values: list

    @property
    def label(self) -> str:
        return self.target.removeprefix("PARAMS.")


@dataclass
class Outcome:
    """One combination's results, summed over its backtests."""

    index: tuple[int, ...]  # position of each value on its axis
    values: tuple
    day_pnl: dict[TradeMatching, dict[str, float]] = field(default_factory=dict)  # mode -> day -> pnl
    product_pnl: dict[TradeMatching, dict[str, float]] = field(default_factory=dict)  # mode -> product -> pnl
    block_pnl: dict[TradeMatching, list[float]] = field(default_factory=dict)  # mode -> PnL per block, days in order
    fine_pnl: dict[TradeMatching, list[float]] = field(default_factory=dict)  # the same per block of FINE_TICKS ticks
    risk: dict[TradeMatching, dict[str, report.PathRisk | None]] = field(default_factory=dict)  # mode -> day -> its path at FINE_TICKS
    fills: int = 0  # under the first mode
    errors: int = 0  # over all modes
    limit_breaches: int = 0
    first_error: str = ""

    def pnl(self, mode: TradeMatching) -> float:
        return sum(self.day_pnl[mode].values())

    def risks(self, mode: TradeMatching) -> list[report.PathRisk]:
        return [r for r in self.risk.get(mode, {}).values() if r is not None]

    def min_day(self, mode: TradeMatching) -> float:
        return min(self.day_pnl[mode].values())

    @property
    def failed(self) -> bool:
        return bool(self.errors or self.limit_breaches)


@dataclass(frozen=True)
class Risk:
    """A combination's PnL path under one mode, from its days' PathRisks at FINE_TICKS (None: not measured)."""

    drawdown: float | None  # the largest fall from a running high within a day
    conc: float | None  # the largest share of a day's PnL made in one WINDOW_TICKS window (days that made money)
    under: float | None  # the share of the time below the running high (at FINE_TICKS: a tick path wobbles below it most of the time)
    run: float | None  # the longest stretch without a new high, as a share of its day (the most over the days)
    sharpe_day: float | None  # mean over sd of the days' PnL (two or more days)
    sharpe_block: float | None  # mean over sd of the PnL changes per FINE_TICKS block, within days
    late: int  # days that look like a lucky late reversal (report.PathRisk.late)


def risk_of(outcome: Outcome, mode: TradeMatching) -> Risk:
    risks = outcome.risks(mode)
    shares = [r.share for r in risks if r.share is not None]
    steps = sum(r.steps for r in risks)
    return Risk(
        drawdown=max((r.drawdown for r in risks), default=None),
        conc=max(shares, default=None),
        under=sum(r.underwater for r in risks) / steps if steps else None,
        run=max((r.longest / r.steps for r in risks), default=None),
        sharpe_day=report.day_sharpe(list(outcome.day_pnl[mode].values())),
        sharpe_block=report.sharpe(risks),
        late=sum(r.late for r in risks),
    )


def fine_risk(fine) -> report.PathRisk | None:
    """A day's PathRisk from its FINE_TICKS blocks: the path sampled at each block's end, the window
    report.WINDOW_TICKS long."""
    return report.path_risk(list(itertools.accumulate(fine)), max(1, report.WINDOW_TICKS // FINE_TICKS))


@dataclass(frozen=True)
class Row:
    """A combination as shown in the summary."""

    values: tuple
    pnl: dict[TradeMatching, float]
    min_day: float  # under the first mode
    nbhd: float  # under the first mode
    fills: int
    failed: bool
    worst: float = 0.0  # the least pnl over the modes (scenarios)
    risk: Risk | None = None  # under the first mode


# ---------------------------------------------------------------------------- axes


def parse_axis(text: str) -> Axis:
    """`PATH=V1,V2,...` or `PATH=START..STOP[..STEP]` (inclusive).

    Values are Python literals; bare words are strings, e.g. PARAMS.KELP.fair=mid,wall_mid.
    """
    target, sep, raw = text.partition("=")
    target, raw = target.strip(), raw.strip()
    if not sep or not target or not raw:
        raise ValueError(f"expected PATH=V1,V2,... or PATH=START..STOP[..STEP], got {text!r}")
    values = _range(raw) if ".." in raw else [_literal(part.strip()) for part in raw.split(",")]
    if len({repr(v) for v in values}) != len(values):
        raise ValueError(f"{target}: duplicate values")
    return Axis(target, values)


def _literal(text: str):
    return parse_value(text)


def _range(text: str) -> list:
    parts = [_literal(part.strip()) for part in text.split("..")]
    if len(parts) not in (2, 3) or not all(isinstance(p, (int, float)) and not isinstance(p, bool) for p in parts):
        raise ValueError(f"bad range {text!r}: use START..STOP or START..STOP..STEP with numbers")
    start, stop, step = parts[0], parts[1], parts[2] if len(parts) == 3 else 1
    if step <= 0 or stop < start:
        raise ValueError(f"bad range {text!r}: needs STOP >= START and STEP > 0")
    count = math.floor((stop - start) / step + 1e-9) + 1
    values = [start + i * step for i in range(count)]
    return values if all(isinstance(p, int) for p in parts) else [round(v, 10) for v in values]


# ---------------------------------------------------------------------------- running

# Set once per worker process by _init_worker, read by _run_piece.
_WORKER: dict = {}


def only(day: Day, products: list[str]) -> Day:
    """The day with only these products' books, trades and marks."""
    keep = set(products)
    ticks = [replace(t, books={p: b for p, b in t.books.items() if p in keep}, trades={p: ts for p, ts in t.trades.items() if p in keep},
                     marks={p: m for p, m in t.marks.items() if p in keep}) for t in day.ticks]
    return replace(day, products=[p for p in day.products if p in keep], limits={p: v for p, v in day.limits.items() if p in keep},
                   ticks=ticks, info={p: v for p, v in day.info.items() if p in keep})


def _init_worker(format_name, data_arg, day_specs, bot_path, base_overrides, targets, modes, config, rivals, requote, subset, days=None):
    fmt = FORMATS[format_name]
    days = days if days is not None else fmt.load_days(fmt.resolve_data_dir(data_arg), day_specs)
    _WORKER.update(
        fmt=fmt,
        days=days,
        restricted=[only(day, subset) for day in days] if subset else None,
        bot=bot_path,
        base=base_overrides,
        targets=targets,
        modes=modes,
        config=config,
        rivals=rivals,
        requote=requote,
    )


@dataclass
class Piece:
    """One combination on one day under one mode."""

    pnl: float
    blocks: list[float]
    fine: list[float]
    products: dict[str, float]
    fills: int
    errors: int
    breaches: int
    first_error: str


def _run_piece(values: tuple, day_index: int, mode: TradeMatching, restricted: bool, permutation: tuple[int, int] | None) -> Piece:
    """One backtest: the combination on one day (only the axes' products if `restricted`, a permuted
    copy with `permutation` (seed, block)) under one mode."""
    w = _WORKER
    overrides = {**w["base"], **dict(zip(w["targets"], values))}
    days = w["restricted"] if restricted else w["days"]
    day = days[day_index]
    if permutation is not None:
        cache = w.setdefault("permuted", {})
        key = (permutation, restricted, day_index)
        if key not in cache:
            if len(cache) > 4 * len(days):  # tasks come seed by seed, so a few copies are enough
                cache.clear()
            cache[key] = stress.permute(day, *permutation)
        day = cache[key]
    result = run_with_rivals(w["fmt"], day, w["bot"], overrides, rivals_for(w["rivals"], mode), config_for(w["config"], mode), requote=w["requote"])[0]
    series = report.total_pnl(result) or [0.0] * len(day.ticks)
    return Piece(
        pnl=series[-1],
        blocks=block_pnl(series, blocks_per_day(len(days))),
        fine=block_pnl(series, len(series) // FINE_TICKS),
        products={stats.product: stats.pnl for stats in report.product_stats(result)},
        fills=len(result.fills),
        errors=len(result.errors),
        breaches=len(result.limit_breaches),
        first_error=report.last_line(result.errors[0][1]) if result.errors else "",
    )


def _assemble(index: tuple, values: tuple, pieces: dict, days: list[Day], modes: list[TradeMatching], extra: dict | None = None) -> Outcome:
    """An Outcome from its pieces, keyed (day index, mode), days in order. `extra` holds, per key,
    what the products left out of a restricted run add: their Piece from the bot as is."""
    outcome = Outcome(index, values)
    for mode_number, mode in enumerate(modes):
        day_pnl, products = outcome.day_pnl.setdefault(mode, {}), outcome.product_pnl.setdefault(mode, {})
        # arrays, not lists: a grid of 100,000 cells holds every cell's block PnL
        blocks, fine = outcome.block_pnl.setdefault(mode, array("d")), outcome.fine_pnl.setdefault(mode, array("d"))
        risk = outcome.risk.setdefault(mode, {})
        for d, day in enumerate(days):
            piece = pieces[(d, mode)]
            more = extra[(d, mode)] if extra else None
            day_pnl[day.name] = piece.pnl + (more.pnl if more else 0.0)
            blocks.extend([a + b for a, b in zip(piece.blocks, more.blocks)] if more else piece.blocks)
            day_fine = [a + b for a, b in zip(piece.fine, more.fine)] if more else piece.fine
            fine.extend(day_fine)
            risk[day.name] = fine_risk(day_fine)  # from the blocks: they add up across products, as a path's shape doesn't
            for source in (piece, more) if more else (piece,):
                for product, value in source.products.items():
                    products[product] = products.get(product, 0.0) + value
            if mode_number == 0:
                outcome.fills += piece.fills + (more.fills if more else 0)
            outcome.errors += piece.errors + (more.errors if more else 0)
            outcome.limit_breaches += piece.breaches + (more.breaches if more else 0)
            outcome.first_error = outcome.first_error or piece.first_error or (more.first_error if more else "")
    return outcome


def _difference(full: Piece, part: Piece, kept: set[str]) -> Piece:
    """What the products outside `kept` add to a full run: its totals minus the restricted run's."""
    return Piece(
        pnl=full.pnl - part.pnl,
        blocks=[a - b for a, b in zip(full.blocks, part.blocks)],
        fine=[a - b for a, b in zip(full.fine, part.fine)],
        products={p: v for p, v in full.products.items() if p not in kept},
        fills=full.fills - part.fills,
        errors=full.errors - part.errors,
        breaches=full.breaches - part.breaches,
        first_error=full.first_error if not part.first_error else "",
    )


class _Runner:
    """Runs backtests in one pool (or in-process with jobs 1), with a progress line per batch. With
    `s.engine` "rust", each batch is one `arena-rs batch` on `jobs` threads instead (python/arena/rust.py)."""

    def __init__(self, s: Setup, bot: Path, axes: list[Axis], modes: list[TradeMatching], jobs: int, format_name: str, data_arg: str,
                 day_specs: list[str], subset: list[str] | None):
        self.init_args = (format_name, data_arg, day_specs, bot, s.overrides, [axis.target for axis in axes], modes, s.config, s.rivals,
                          s.requote, subset)
        self.jobs, self.days = jobs, s.days
        self.s, self.bot, self.targets, self.subset, self.axes = s, bot, [axis.target for axis in axes], subset, axes
        self.pool = self.scratch = self.base = None

    def __enter__(self):
        if self.s.engine == "rust":
            self.scratch = tempfile.TemporaryDirectory(prefix="arena-grid-")
            self.exported, self.specs = {}, {}
            self.base = self._base()
        elif self.jobs <= 1:
            _init_worker(*self.init_args, days=self.days)  # reuse the days already loaded
        else:
            self.pool = ProcessPoolExecutor(self.jobs, initializer=_init_worker, initargs=self.init_args)
        return self

    def __exit__(self, *exc):
        if self.pool:
            self.pool.shutdown()
        if self.scratch:
            self.scratch.cleanup()

    def _base(self) -> dict | None:
        """One spec for every combination, each task carrying its combination as `set` for Rust to
        apply as --set does, when every axis sets one of the spec's globals with values JSON can carry;
        else None, and each combination's settings are read from the bot file."""
        spec = rust.bot_spec(self.bot, self.s.overrides)
        held = set(spec["globals"])
        if all(axis.target.split(".")[0] in held for axis in self.axes) and all(rust._jsonable(v) for axis in self.axes for v in axis.values):
            return spec
        return None

    def _rust(self, tasks: list[tuple]) -> dict:
        """The batch on the Rust engine: each day (restricted, permuted) exported once per run, and one
        spec for the bot with each combination applied by Rust (_base), or each combination's settings
        read from the bot file once; the results read back in binary."""
        s, folder = self.s, Path(self.scratch.name)
        paths: list[Path] = []
        specs: list[dict] = []
        local_days: dict[Path, int] = {}
        local_specs: dict[tuple, int] = {}

        def day_index(d: int, restricted: bool) -> tuple[int, int]:
            key = (d, restricted)
            if key not in self.exported:  # a Prosperity day goes as a reference to its CSVs (rust.write_day)
                path = rust.write_day(s.days[d], folder / f"day{len(self.exported)}", self.subset if restricted else None)
                self.exported[key] = (path, len(s.days[d].ticks))
            path, ticks = self.exported[key]
            if path not in local_days:
                local_days[path] = len(paths)
                paths.append(path)
            return local_days[path], ticks

        def spec_index(key: tuple, make) -> int:
            if key not in self.specs:
                self.specs[key] = make()
            if key not in local_specs:
                local_specs[key] = len(specs)
                specs.append(self.specs[key])
            return local_specs[key]

        # a grid's tasks share their configs, cells, rivals and product lists: each is sent, or made, once
        batch, products, configs, cells = [], [], {}, {}
        listed: dict[tuple, list[str]] = {}
        markets: dict = {}  # mode -> (the participants' names, the rivals' [name, spec index]s)

        def field_of(mode) -> tuple[list[str], list]:
            if mode not in markets:
                rivals = rivals_for(s.rivals, mode)
                names = participant_names(self.bot, rivals)
                markets[mode] = names, [[names[k + 1], spec_index(("rival", str(r)), lambda r=r: rust.bot_spec(getattr(r, "path", r), getattr(r, "overrides", {}),
                                                                                                         s.requote))] for k, r in enumerate(rivals)]
            return markets[mode]

        for _key, values, d, mode, restricted, permutation in tasks:
            day, ticks = day_index(d, restricted)
            config = configs.setdefault(mode, len(configs))
            names, rivals = field_of(mode)
            if self.base is not None:
                bots = [[names[0], spec_index(("base",), lambda: self.base)]]
                cell = {"cell": cells.setdefault(repr(values), (len(cells), values))[0]} if values else {}  # repr: a value may be a dict
            else:
                overrides = {**s.overrides, **dict(zip(self.targets, values))}
                bots = [[names[0], spec_index(("bot", repr(values)), lambda: rust.bot_spec(self.bot, overrides))]]
                cell = {}
            transform = None if permutation is None else "permuted:{}:{}".format(*permutation)  # Rust makes the copy (rust/src/arena/stress.rs)
            batch.append({"day": day, "transform": transform, "config": config, "bots": bots + rivals, "blocks": blocks_per_day(len(s.days)),
                          "fine": ticks // FINE_TICKS, **cell})
            if (d, restricted) not in listed:
                listed[(d, restricted)] = [p for p in s.days[d].products if not restricted or p in self.subset]
            products.append(listed[(d, restricted)])
        results = rust.run_batch(paths, specs, batch, self.jobs, folder, products, [rust.config_json(config_for(s.config, m)) for m in configs],
                                 [[[target, value] for target, value in zip(self.targets, values)] for _, values in cells.values()])
        kept, out = Piece.__dataclass_fields__, {}
        for k, (key, *_) in enumerate(tasks):
            found, results[k] = results[k], None  # each result's dict let go as its Piece is made
            out[key] = Piece(**{f: v for f, v in found.items() if f in kept})
        return out

    def run(self, tasks: list[tuple]) -> dict:
        """tasks: (key, values, day index, mode, restricted, permutation) -> {key: Piece}."""
        if self.s.engine == "rust":
            return self._rust(tasks)
        out, progress = {}, _Progress(len(tasks))
        if self.pool is None:
            for key, *args in tasks:
                out[key] = _run_piece(*args)
                progress.step()
        else:
            futures = {self.pool.submit(_run_piece, *args): key for key, *args in tasks}
            for future in as_completed(futures):
                out[futures[future]] = future.result()
                progress.step()
        progress.done()
        return out


def _cells(axes: list[Axis], sample: int | None = None, seed: int = 0) -> list[tuple[tuple, tuple]]:
    """Every combination as (its index on each axis, its values); with `sample`, that many drawn at
    random (seeded) by their place in the whole product, so a space of millions is never listed."""
    sizes = [len(axis.values) for axis in axes]
    total = math.prod(sizes)
    if sample is None or sample >= total:
        combos = itertools.product(*(range(n) for n in sizes))
    else:
        combos = sorted(_unrank(k, sizes) for k in random.Random(seed).sample(range(total), sample))
    return [(index, tuple(axes[i].values[j] for i, j in enumerate(index))) for index in combos]


_unrank = search.unrank  # the k-th combination in itertools.product's order (the last axis fastest)


@dataclass
class Screen:
    """The first rung of successive halving: every cell on the first day under the first mode."""

    share: float
    day: str
    mode: TradeMatching
    pnl: dict[tuple[int, ...], float]  # every cell's PnL there (the axes' products only, when restricted)
    failed: set[tuple[int, ...]]
    kept: list[tuple[int, ...]]  # best first


@dataclass
class Rung:
    """One step of --halving: the cells alive ranked by their PnL on the (day, mode)s so far, a share kept."""

    seen: str  # the (day, mode) this step added, e.g. "r1d-1 under all"
    pnl: dict[tuple[int, ...], float]  # every alive cell's PnL over the (day, mode)s so far
    failed: set[tuple[int, ...]]
    kept: list[tuple[int, ...]]  # best first


@dataclass
class Searched:
    """What --search ran: its method, budget and seed, the cell it started from (coord), and when it found its best."""

    method: str
    budget: int
    seed: int
    start: tuple[int, ...]
    found_at: int  # cells completed when the best one was (1-based)
    best: tuple[int, ...] | None
    objective: str  # what it maximised, in words


@dataclass
class GridRun:
    baseline: Outcome
    outcomes: dict[tuple[int, ...], Outcome]  # with a screen or halving, only the cells it kept
    restricted: list[str] | None  # the products the cells ran on, when not every product
    note: str  # why the run was or wasn't restricted
    screen: Screen | None = None
    rungs: list[Rung] | None = None  # --halving's steps
    tried: int = 0  # cells that ran at all (all of them, or --sample's)
    seen: set[int] = field(default_factory=set)  # the days (indices) the screen or a halving step ranked on
    searched: Searched | None = None  # --search's run


def screened(cells: list[tuple[tuple, tuple]], found: dict, share: float) -> tuple[list[tuple[tuple, tuple]], dict, set]:
    """The top `share` of the cells (at least one) by their screen Piece's PnL, working ones first."""
    failed = {index for index, _ in cells if found[index].errors or found[index].breaches}
    ranked = sorted(cells, key=lambda cell: (cell[0] in failed, -found[cell[0]].pnl))
    return ranked[:max(1, math.ceil(share * len(cells)))], {index: found[index].pnl for index, _ in cells}, failed


def start_cell(bot: Path, format_name: str, axes: list[Axis]) -> tuple[int, ...]:
    """Each axis at the bot's own value for it (a PARAMS entry it lacks falls back to DEFAULTS, as the
    template reads them), or at its middle value if that isn't on the axis: where --search coord starts."""
    module = bot_module(bot, format_name)
    missing = object()
    out = []
    for axis in axes:
        names = axis.target.split(".")
        value = getattr(module, names[0], missing)
        for name in names[1:]:
            value = value.get(name, missing) if isinstance(value, dict) else missing
        if value is missing and names[0] == "PARAMS" and len(names) == 3:
            value = getattr(module, "DEFAULTS", {}).get(names[2], missing)
        out.append(axis.values.index(value) if value is not missing and value in axis.values else len(axis.values) // 2)
    return tuple(out)


def search_objective(keys: list[tuple[int, object]], base: dict, modes: list, gate: str, holdout: tuple[str, int | float] | None):
    """--search's objective from a cell's pieces in `keys`' order: its smaller gain over the bot as is
    (`base`: (day, mode) -> its Piece) under the gate's modes, on the data --holdout keeps; failed
    cells last. Returns (objective, a description of it)."""
    gating = modes if gate == "every" else modes[:1]
    part = holdout[1] if holdout else None

    def kept(pieces: list, mode) -> float:
        own = [(d, p) for (d, m), p in zip(keys, pieces) if m == mode]
        if isinstance(part, float):  # a share: the last blocks of FINE_TICKS ticks, the days in order (split_holdout)
            fine = [x for _, p in own for x in p.fine]
            return sum(fine[: len(fine) - max(1, round(part * len(fine)))])
        return sum(p.pnl for d, p in own if d != part)  # without the held-out day, if any

    reference = [base[k] for k in keys]

    def objective(pieces: list) -> float:
        if any(p.errors or p.breaches for p in pieces):
            return -math.inf
        return min(kept(pieces, m) - kept(reference, m) for m in gating)

    described = f"the smaller gain over the bot as is under {', '.join(str(m) for m in gating)}" if len(gating) > 1 else \
        f"the gain over the bot as is under {gating[0]}"
    return objective, described + (f", without {holdout[0]}" if holdout else "")


def run_grid(
    s: Setup, bot: Path, axes: list[Axis], modes: list[TradeMatching], jobs: int, format_name: str, data_arg: str, day_specs: list[str],
    all_products: bool = False, screen: float | None = None, sample: int | None = None, sample_seed: int = 0, halving: float | None = None,
    searching: tuple[str, int, int] | None = None, gate: str = "every", holdout: tuple[str, int | float] | None = None,
) -> GridRun:
    """The baseline (the bot with only --set applied) and every combination, one backtest per worker
    task. Unless `all_products`, when the axes set only some products, the combinations run on days
    holding only those, if the bot as is makes the same PnL on them with and without the others on
    every day and mode; the others' PnL is then added from the bot as is's run. With `screen`, every
    combination first runs on the first day under the first mode, and only that share of them, the
    best there, runs on the other days and modes. With `halving`, successive halving in steps: each
    adds the next (day, mode), the first mode's days first, and keeps that share of the cells still
    alive, ranked by their PnL so far; the last ones run everywhere. `sample` runs that many cells
    drawn at random (seeded by `sample_seed`) instead of every combination. `searching` (method,
    budget in cells, seed) runs arena.search's search instead, on search_objective."""
    products = sorted({p for day in s.days for p in day.products})
    traded = axis_products(axes, products)
    subset = traded if not all_products and len(traded) < len(products) else None
    keys = [(d, m) for m in modes for d in range(len(s.days))]
    with _Runner(s, bot, axes, modes, jobs, format_name, data_arg, day_specs, subset) as runner:
        tasks = [(("full", d, m), (), d, m, False, None) for d, m in keys]
        if subset:
            tasks += [(("part", d, m), (), d, m, True, None) for d, m in keys]
        base = runner.run(tasks)
        full = {(d, m): base[("full", d, m)] for d, m in keys}
        restricted, note = None, ""
        if subset:
            kept = set(subset)
            same = all(abs(sum(v for p, v in full[k].products.items() if p in kept) - sum(base[("part", *k)].products.values())) < 1e-6
                       and not base[("part", *k)].errors for k in keys)
            if same:
                restricted = subset
                note = (f"the combinations ran on {', '.join(subset) if len(subset) <= 4 else f'{len(subset)} products'} only: the bot as is "
                        "makes the same PnL there with or without the other products, so theirs is added from its run (--all-products to run them all)")
            else:
                note = "the combinations ran on every product: the bot as is trades the axes' products differently without the others"
        first, chosen, rungs, seen, searched = keys[0], None, None, set(), None
        if searching:
            method, budget, seed = searching
            ref = {k: base[("part", *k)] if restricted is not None else full[k] for k in keys}
            objective, described = search_objective(keys, ref, modes, gate, holdout)
            values_of = lambda index: tuple(axes[i].values[j] for i, j in enumerate(index))
            pieces = {}

            def ask(wanted: list[tuple[tuple, int]]) -> dict:
                found = runner.run([((index, *keys[k]), values_of(index), *keys[k], restricted is not None, None) for index, k in wanted])
                pieces.update(found)
                return {(index, k): found[(index, *keys[k])] for index, k in wanted}

            start = start_cell(bot, format_name, axes)
            space = search.Space([len(axis.values) for axis in axes], start)
            run = search.run(method, search.Search(space, ask, len(keys), budget, objective), seed)
            cells = [(index, values_of(index)) for index in run.seen]
            pieces = {key: piece for key, piece in pieces.items() if key[0] in run.seen}
            searched = Searched(method, budget, seed, start, run.found_at(), run.best(), described)
        else:
            cells = _cells(axes, sample, sample_seed)
        tried = len(cells)
        if searching:
            pass  # its cells ran as it chose them
        elif halving:
            rungs, pieces = [], {}
            for r, key in enumerate(keys):
                pieces |= runner.run([((index, *key), values, *key, restricted is not None, None) for index, values in cells])
                if r == len(keys) - 1 or len(cells) <= 1:
                    continue
                ranked = keys[: r + 1]
                pnl = {index: sum(pieces[(index, *k)].pnl for k in ranked) for index, _ in cells}
                failed = {index for index, _ in cells if any(pieces[(index, *k)].errors or pieces[(index, *k)].breaches for k in ranked)}
                cells = sorted(cells, key=lambda cell: (cell[0] in failed, -pnl[cell[0]]))[: max(1, math.ceil(halving * len(cells)))]
                rungs.append(Rung(f"{s.days[key[0]].name} under {key[1]}", pnl, failed, [index for index, _ in cells]))
                alive = set(rungs[-1].kept)
                pieces = {k: v for k, v in pieces.items() if k[0] in alive}
            seen = {d for d, _ in keys[: len(rungs)]}
        elif screen:
            found = runner.run([(index, values, *first, restricted is not None, None) for index, values in cells])
            cells, pnl, failed = screened(cells, found, screen)
            chosen, seen = Screen(screen, s.days[0].name, modes[0], pnl, failed, [index for index, _ in cells]), {0}
            pieces = {(index, *first): found[index] for index, _ in cells}
            pieces |= runner.run([((index, d, m), values, d, m, restricted is not None, None) for index, values in cells for d, m in keys[1:]])
        else:
            pieces = runner.run([((index, d, m), values, d, m, restricted is not None, None) for index, values in cells for d, m in keys])
    extra = {k: _difference(full[k], base[("part", *k)], set(restricted)) for k in keys} if restricted else None
    # each cell's pieces let go once it is assembled: with many cells they are most of the memory
    outcomes = {index: _assemble(index, values, {k: pieces.pop((index, *k)) for k in keys}, s.days, modes, extra) for index, values in cells}
    return GridRun(_assemble((), (), full, s.days, modes), outcomes, restricted, note, chosen, rungs, tried, seen, searched)


def run_permutations(
    s: Setup, bot: Path, axes: list[Axis], modes: list[TradeMatching], jobs: int, format_name: str, data_arg: str,
    day_specs: list[str], copies: int, block: int, restricted: list[str] | None, screen: float | None = None,
    sample: int | None = None, sample_seed: int = 0,
) -> list[dict[tuple[int, ...], Outcome]]:
    """The whole grid on `copies` permuted copies of the days (seeds 1..copies), under the first mode,
    on the products the grid itself ran on: for each copy, every combination, or with `screen` the
    share of them that the same screen keeps on the copy's first day."""
    mode, seeds, days = modes[0], range(1, copies + 1), range(len(s.days))
    cells = _cells(axes, sample, sample_seed)
    with _Runner(s, bot, axes, modes, jobs, format_name, data_arg, day_specs, restricted) as runner:
        if screen:
            found = runner.run([((seed, index, 0), values, 0, mode, restricted is not None, (seed, block)) for seed in seeds for index, values in cells])
            kept = {seed: screened(cells, {index: found[(seed, index, 0)] for index, _ in cells}, screen)[0] for seed in seeds}
            pieces = found | runner.run([((seed, index, d), values, d, mode, restricted is not None, (seed, block))
                                         for seed in seeds for index, values in kept[seed] for d in days[1:]])
        else:
            kept = {seed: cells for seed in seeds}
            pieces = runner.run([((seed, index, d), values, d, mode, restricted is not None, (seed, block))
                                 for seed in seeds for index, values in cells for d in days])
    shown = [only(day, restricted) for day in s.days] if restricted else s.days
    return [{index: _assemble(index, values, {(d, mode): pieces[(seed, index, d)] for d in days}, shown, [mode])
             for index, values in kept[seed]} for seed in seeds]


LINKING_KEYS = ("basket", "follow", "hedge", "underlying")  # settings that tie a product to another's book or plan


def axis_products(axes: list[Axis], products: list[str]) -> list[str]:
    """The products the axes set (PARAMS.<product>.<key>); every product if an axis sets something
    else, or a setting that ties a product to another (LINKING_KEYS): the check that a restricted
    run gives the same PnL is made on the bot as is, which an axis value could link differently."""
    named = [axis.target.split(".")[1] if axis.target.startswith("PARAMS.") and axis.target.count(".") >= 2 else None for axis in axes]
    if any(n not in products for n in named) or any(axis.target.rsplit(".", 1)[-1] in LINKING_KEYS for axis in axes):
        return products
    return sorted(set(named))


def search_stats(outcomes: dict[tuple[int, ...], Outcome], mode: TradeMatching, products: list[str]) -> tuple[float, float] | None:
    """The best working combination's PnL over `products`, and its lift over the median combination's."""
    pnl = sorted(sum(o.product_pnl[mode].get(p, 0.0) for p in products) for o in outcomes.values() if not o.failed)
    return (pnl[-1], pnl[-1] - statistics.median(pnl)) if pnl else None


def format_permutations(axes: list[Axis], outcomes: dict[tuple[int, ...], Outcome], copies: list, mode: TradeMatching, block: int, products: list[str]) -> str:
    traded = axis_products(axes, products)
    real = search_stats(outcomes, mode, traded)
    found = [x for x in (search_stats(o, mode, traded) for o in copies) if x is not None]
    shown = ", ".join(traded) if len(traded) <= 3 else f"{len(traded)} products"
    lines = [f"permutation test: the whole grid on {len(copies)} copies of the days, their ticks shuffled in runs of {block:,} (pnl({mode}) of {shown}):"]
    if real is None or not found:
        lines.append("  no working combination: skipped")
        return "\n".join(lines)
    smallest = 1 / (1 + len(found))
    for k, name, meaning in ((0, "best cell's PnL", "the search's best does as well without the order of the ticks"),
                             (1, "lift of the best cell over the median one", "choosing among the cells adds as much without the order of the ticks")):
        values = sorted(x[k] for x in found)
        p = (1 + sum(v >= real[k] for v in values)) / (1 + len(values))
        q95 = values[min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)]
        lines.append(f"  {name}: {real[k]:+,.0f} on the real days; on the copies mean {statistics.fmean(values):+,.0f}, "
                     f"95th percentile {q95:+,.0f}; p {p:.3f} that {meaning} (smallest possible {smallest:.3f})")
    lift_p = (1 + sum(x[1] >= real[1] for x in found)) / (1 + len(found))
    if lift_p > ALPHA:
        lines.append("! the copies' searches lift as much: what choosing finds here doesn't need the order of the ticks "
                     "(it comes from each tick's book and the fill model, or from the width of the search)")
    return "\n".join(lines)


def smoke_test(s: Setup, bot: Path, axes: list[Axis], modes: list | None = None) -> None:
    """Runs the first combination briefly, under each scenario that sets more than the trade
    matching (its own rivals load then), so a typo fails fast instead of in every run."""
    overrides = {**s.overrides, **{axis.target: axis.values[0] for axis in axes}}
    day = s.days[0]
    sample = replace(day, ticks=day.ticks[:SMOKE_TEST_TICKS])  # info too: a format's ticks and units
    runs = [(s.config, s.rivals, "")] + [(config_for(s.config, m), rivals_for(s.rivals, m), f" under {m}") for m in modes or []
                                          if isinstance(m, Scenario) and not m.plain]
    for config, rivals, where in runs:
        result = run_with_rivals(s.format, sample, bot, overrides, rivals, config, requote=s.requote)[0]
        if result.errors:
            raise ValueError(f"the bot fails with the first combination{where}: {report.last_line(result.errors[0][1])}")


class _Progress:
    def __init__(self, total: int):
        self.total, self.done_count = total, 0
        self.live = sys.stderr.isatty()

    def step(self) -> None:
        self.done_count += 1
        if self.live:
            print(f"\r  {self.done_count}/{self.total} combinations", end="", file=sys.stderr, flush=True)

    def done(self) -> None:
        if self.live:
            print("\r" + " " * 40 + "\r", end="", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------- results


def neighborhood_mean(outcomes: dict[tuple[int, ...], Outcome], index: tuple[int, ...], shape: tuple[int, ...], mode) -> float:
    """Mean PnL of a combination and its neighbours one step along each axis.

    Neighbours that failed (errors or limit breaches) are left out: their PnL isn't what the
    setting would make, and the summary leaves them out too. So are neighbours that --screen dropped.
    """
    pnls = [outcomes[index].pnl(mode)]
    for axis, size in enumerate(shape):
        for step in (-1, 1):
            position = index[axis] + step
            if 0 <= position < size:
                neighbour = outcomes.get(index[:axis] + (position,) + index[axis + 1 :])
                if neighbour is not None and not neighbour.failed:  # None: dropped by --screen
                    pnls.append(neighbour.pnl(mode))
    return statistics.fmean(pnls)


def build_rows(axes: list[Axis], modes: list[TradeMatching], outcomes: dict[tuple[int, ...], Outcome]) -> list[Row]:
    shape, primary = tuple(len(axis.values) for axis in axes), modes[0]
    return [
        Row(
            values=outcome.values,
            pnl={mode: outcome.pnl(mode) for mode in modes},
            min_day=outcome.min_day(primary),
            nbhd=neighborhood_mean(outcomes, index, shape, primary),
            fills=outcome.fills,
            failed=outcome.failed,
            worst=worst_case(outcome, modes),
            risk=risk_of(outcome, primary),
        )
        for index, outcome in sorted(outcomes.items())
    ]


def scored_worst(modes: list) -> bool:
    """Whether the summaries add the worst case over the modes: with any scenario beyond --modes."""
    return any(isinstance(mode, Scenario) and not mode.plain for mode in modes)


def worst_case(outcome: Outcome, modes: list) -> float:
    return min(outcome.pnl(mode) for mode in modes)


def measures(modes: list[TradeMatching]) -> dict[str, Callable[[Row], float]]:
    """Ranking measures by name: pnl, nbhd, min-day, and one per extra mode."""
    primary = modes[0]
    named = {
        "pnl": lambda row: row.pnl[primary],
        "nbhd": lambda row: row.nbhd,
        "min-day": lambda row: row.min_day,
    }
    for mode in modes[1:]:
        named[mode.value] = lambda row, mode=mode: row.pnl[mode]
    if scored_worst(modes):
        named["worst"] = lambda row: row.worst
    return named


RISK_KEYS = {  # --sort keys on the first mode's PnL path, best first; not among the summary's "best by" measures
    "sharpe-day": lambda r: r.sharpe_day,
    "sharpe-block": lambda r: r.sharpe_block,
    "drawdown": lambda r: None if r.drawdown is None else -r.drawdown,
    "conc": lambda r: None if r.conc is None else -r.conc,
    "under": lambda r: None if r.under is None else -r.under,
    "run": lambda r: None if r.run is None else -r.run,
}


def sort_keys(modes: list[TradeMatching]) -> dict[str, Callable[[Row], float]]:
    """Every --sort key: the measures, then the risk keys (a cell without the measure last)."""
    def risky(get):
        def key(row: Row) -> float:
            value = get(row.risk) if row.risk is not None else None
            return float("-inf") if value is None else value
        return key
    return measures(modes) | {name: risky(get) for name, get in RISK_KEYS.items()}


def format_summary(axes, modes, baseline: Outcome, rows: list[Row], sort: str, top: int) -> str:
    primary = modes[0]
    named = measures(modes)
    lines = [
        "baseline (bot as is): "
        + " · ".join(f"pnl({mode}) {baseline.pnl(mode):,.0f}" for mode in modes)
        + (f" · ! {baseline.errors} errors" if baseline.errors else "")
    ]

    header = ["rank", *(axis.label for axis in axes), f"pnl({primary})", "min day", "nbhd"]
    worst = scored_worst(modes)
    daily = any(row.risk is not None and row.risk.sharpe_day is not None for row in rows)
    header += [f"pnl({mode})" for mode in modes[1:]] + (["worst"] if worst else []) + ["max dd", "conc", "under", "run"] + (["sharpe/d"] if daily else [])
    header += ["fills", ""]
    ranked = sorted(rows, key=sort_keys(modes)[sort], reverse=True)
    table = []
    for rank, row in enumerate(ranked[:top], 1):
        cells = [str(rank), *(str(v) for v in row.values), _num(row.pnl[primary]), _num(row.min_day), _num(row.nbhd)]
        cells += [_num(row.pnl[mode]) for mode in modes[1:]] + ([_num(row.worst)] if worst else []) + _risk_cells(row.risk, daily)
        cells += [f"{row.fills:,}", " ".join(flag for flag, on in (("!", row.failed), ("late", row.risk is not None and row.risk.late)) if on)]
        table.append(cells)
    widths = [max(len(cell) for cell in column) for column in zip(header, *table)]
    lines.append("")
    for cells in [header, *table]:
        lines.append("  ".join(cell.rjust(width) for cell, width in zip(cells, widths)).rstrip())
    if len(ranked) > top:
        lines.append(f"  ... {len(ranked) - top} more (--top, or --out for all)")

    usable = [row for row in rows if not row.failed]
    failed = len(rows) - len(usable)
    lines.append("")
    lines.append(format_late(axes, primary, rows))
    if failed:
        lines.append(f"! {failed} combinations had errors or limit breaches and are left out below")
    if not usable:
        lines.append("every combination failed")
        return "\n".join(lines)

    picks = {}
    width = max(len(name) for name in named)
    for name, key in named.items():
        best = max(usable, key=key)
        picks[name] = best.values
        setting = ", ".join(f"{axis.label}={str(v)}" for axis, v in zip(axes, best.values))
        lines.append(f"best by {name:<{width}}  {setting}  ({_num(key(best))})")
    if len(set(picks.values())) == 1:
        lines.append("all measures agree")
    else:
        lines.append("measures disagree: prefer a setting near the top on every measure over the single best pnl")
    return "\n".join(lines)


def _risk_cells(risk: Risk | None, daily: bool) -> list[str]:
    """The summary's max dd, conc, under, run (and sharpe/d) cells."""
    risk = risk or Risk(None, None, None, None, None, None, 0)
    share = lambda x: "-" if x is None else f"{x:.0%}"
    shown = [_num(risk.drawdown) if risk.drawdown is not None else "-", share(risk.conc), share(risk.under), share(risk.run)]
    return shown + ([f"{risk.sharpe_day:.2f}" if risk.sharpe_day is not None else "-"] if daily else [])


def format_late(axes: list[Axis], mode: TradeMatching, rows: list[Row]) -> str:
    """The cells with a day that looks like a lucky late reversal (report.PathRisk.late), or that none has."""
    late = sorted((row for row in rows if row.risk is not None and row.risk.late and not row.failed), key=lambda row: -row.pnl[mode])
    rule = (f"one {report.WINDOW_TICKS:,}-tick window made {report.CONCENTRATED:.0%}+ of a day's pnl({mode}), which went {report.UNDERWATER:.0%}+ "
            f"of the day without a new high, in blocks of {FINE_TICKS} ticks")
    if not late:
        return f"late reversals: none ({rule})"
    named = [", ".join(f"{a.label}={v}" for a, v in zip(axes, row.values)) + f" ({row.risk.late} day{'s' if row.risk.late > 1 else ''})" for row in late]
    shown = " | ".join(named[:5]) + (f" | ... {len(named) - 5} more" if len(named) > 5 else "")
    return f"! late reversals in {len(late)} of {len(rows)} cells ({rule}): {shown}"


def _fingerprint(outcome: Outcome, modes: list[TradeMatching]) -> tuple:
    return tuple((mode, tuple(outcome.day_pnl[mode].items()), tuple(sorted(outcome.product_pnl[mode].items()))) for mode in modes)


def dead_axes(axes: list[Axis], outcomes: dict[tuple[int, ...], Outcome], modes: list[TradeMatching]) -> list[Axis]:
    """The axes whose values never change a working combination's PnL, day by day, product by product
    and mode by mode, with the other axes held fixed: a typo'd key (--set accepts a new leaf), or a
    setting that another one overrides (the template's param_conflicts lists those)."""
    dead = []
    for a, axis in enumerate(axes):
        groups: dict[tuple, set] = defaultdict(set)
        sizes: dict[tuple, int] = defaultdict(int)
        for index, outcome in outcomes.items():
            if not outcome.failed:
                key = index[:a] + index[a + 1 :]
                groups[key].add(_fingerprint(outcome, modes))
                sizes[key] += 1
        if any(n > 1 for n in sizes.values()) and all(len(found) == 1 for found in groups.values()):
            dead.append(axis)
    return dead


def format_dead_axes(axes: list[Axis], outcomes: dict[tuple[int, ...], Outcome], modes: list[TradeMatching]) -> str:
    return "\n".join(f"! {axis.label} never changed the PnL: a typo'd key, or a setting another one overrides "
                     "(python/bots/template.py's param_conflicts lists those; arena.validate prints them)" for axis in dead_axes(axes, outcomes, modes))


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _plain(value) -> str:
    return str(value) if isinstance(value, int) else repr(round(value, 10))


def format_axis_ends(axes: list[Axis], modes: list[TradeMatching], rows: list[Row], sort: str) -> str:
    """The best working cell by --sort against its numeric axes: a note for each axis of three or more values
    where it sits on the lowest or highest (the best may lie past it), and a finer grid around it, from the
    value below to the value above at half the step (whole numbers stay whole down to a step of 1, then
    halve with a caveat: an edge takes a fraction, a size or a window doesn't), the other axes held at its
    values. A second pass only: it adds cells, and so selection bias, to the first."""
    usable = [row for row in rows if not row.failed]
    if not usable:
        return ""
    best = max(usable, key=sort_keys(modes)[sort])
    lines, finer, held, fractional = [], [], [], []
    for axis, value in zip(axes, best.values):
        values = sorted(set(axis.values)) if all(_numeric(v) for v in axis.values) else None
        if values is None or len(values) < 2:
            held.append(f"--set {axis.target}={value}")
            continue
        i = values.index(value)
        if len(values) >= 3 and i in (0, len(values) - 1):
            lines.append(f"! the best cell by {sort} has {axis.label}={value}, the axis' {'lowest' if i == 0 else 'highest'} value: the best may "
                         "lie past it, so widen the axis unless that end is a bound the setting can't pass (a size of 0, a share of 1)")
        low, high = values[max(i - 1, 0)], values[min(i + 1, len(values) - 1)]
        gap = min(g for g in (value - low, high - value) if g > 0)
        whole = all(isinstance(v, int) for v in values)
        step = gap // 2 if whole and gap >= 2 else gap / 2
        if whole and gap < 2:
            fractional.append(axis.label)
        finer.append(f"--grid {axis.target}={_plain(low)}..{_plain(high)}..{_plain(step)}")
    if finer:
        lines.append(f"finer around the best cell by {sort}, a second pass judged by the same gates on held-out data: {' '.join(finer + held)}")
    if fractional:
        lines.append(f"  ({', '.join(fractional)} below a step of 1: only if the setting takes a fraction, as an edge does; a size or a window "
                     "doesn't, so --set it at the best cell's value instead)")
    return "\n".join(lines)


def leave_one_day_out(outcomes: dict[tuple[int, ...], Outcome], mode: TradeMatching) -> dict[str, Outcome]:
    """For each day, the combination with the best PnL on the other days (failed ones left out)."""
    usable = [outcome for _, outcome in sorted(outcomes.items()) if not outcome.failed]
    if not usable or len(usable[0].day_pnl[mode]) < 2:
        return {}
    return {
        day: max(usable, key=lambda outcome, day=day: outcome.pnl(mode) - outcome.day_pnl[mode][day])
        for day in usable[0].day_pnl[mode]
    }


def repeated_days(days: list[Day]) -> list[tuple[list[str], list[str]]]:
    """Days whose data repeats, as (day names, the products whose books and trades are the same).

    Compared product by product, since Prosperity reuses a day for the products a later round keeps
    (P3 round 3's days 0 and 1 are round 2's for every round 2 product), and trades without
    counterparty names (P4's round 4 repeats two days of round 3 with names added).
    """
    by_product: dict[tuple, list[str]] = {}
    for day in days:
        ticks = day.ticks[:SMOKE_TEST_TICKS]
        for product in day.products:
            books = [(t.timestamp, t.books.get(product)) for t in ticks]
            trades = [sorted((tr.price, tr.quantity) for tr in t.trades.get(product, [])) for t in ticks]
            by_product.setdefault((product, len(day.ticks), repr(books), repr(trades)), []).append(day.name)
    groups: dict[tuple[str, ...], list[str]] = {}
    for (product, *_), names in by_product.items():
        if len(names) > 1:
            groups.setdefault(tuple(names), []).append(product)
    return [(list(names), sorted(products)) for names, products in groups.items()]


def format_held_out(
    axes: list[Axis], modes: list[TradeMatching], outcomes: dict[tuple[int, ...], Outcome], repeats: list[tuple[list[str], list[str]]]
) -> str:
    mode = modes[0]
    picks = leave_one_day_out(outcomes, mode)
    if not picks:
        return ""
    best = max((o for o in outcomes.values() if not o.failed), key=lambda outcome: outcome.pnl(mode))
    lines = [f"held-out days: the best pnl({mode}) on the other days, scored on the day left out"]
    for day, pick in picks.items():
        setting = ", ".join(f"{axis.label}={str(v)}" for axis, v in zip(axes, pick.values))
        lines.append(f"  {day}: {setting}  {_num(pick.day_pnl[mode][day])}  (best combination: {_num(best.day_pnl[mode][day])})")
    held, full = sum(pick.day_pnl[mode][day] for day, pick in picks.items()), best.pnl(mode)
    gap = f" ({(held - full) / abs(full):+.0%})" if full else ""
    choices = len({pick.values for pick in picks.values()})
    lines.append(f"held out {_num(held)} against {_num(full)} for the best combination{gap}; {choices} different settings chosen over {len(picks)} days")
    for names, products in repeats:
        which = ", ".join(products) if len(products) <= 4 else f"{len(products)} products"
        lines.append(f"! {', '.join(names)} hold the same data for {which}: holding one out still trains on the other")
    return "\n".join(lines)


def format_screen(axes: list[Axis], screen: Screen, outcomes: dict[tuple[int, ...], Outcome]) -> str:
    """What the screen tried and dropped, and whether its day ranks the kept cells as the other days do."""
    tried, kept = len(screen.pnl), len(screen.kept)
    setting = lambda index: ", ".join(f"{a.label}={a.values[i]}" for a, i in zip(axes, index))
    lines = [f"screen: all {tried} cells on {screen.day} under {screen.mode}, the best {kept} ({screen.share:.0%}) kept for every day and mode",
             f"  kept from {_num(screen.pnl[screen.kept[0]])} to {_num(screen.pnl[screen.kept[-1]])} on {screen.day}"]
    dropped = [index for index in screen.pnl if index not in outcomes]
    working = [index for index in dropped if index not in screen.failed]
    if working:
        best = max(working, key=screen.pnl.get)
        lines[-1] += f"; best dropped {setting(best)} ({_num(screen.pnl[best])})"
    if len(dropped) > len(working):
        lines[-1] += f"; {len(dropped) - len(working)} dropped with errors or limit breaches"
    names = list(next(iter(outcomes.values())).day_pnl[screen.mode])
    usable = [o for o in outcomes.values() if not o.failed]
    if len(names) >= 2 and len(usable) >= 3:
        rho = _spearman([o.day_pnl[screen.mode][screen.day] for o in usable], [o.pnl(screen.mode) - o.day_pnl[screen.mode][screen.day] for o in usable])
        lines.append(f"  among the kept cells, {screen.day}'s pnl against the other days': Spearman {rho:+.2f}")
        if rho < 0.3:
            lines.append(f"! {screen.day} ranks the kept cells unlike the other days: the screen may have dropped good cells (a larger --screen share, or another day first)")
    lines.append(f"! the tests below see the {kept} kept cells only, chosen on {screen.day}, which they include: they understate the selection "
                 f"bias of {tried} cells" + ("; the unseen-days section after them does not" if len(names) >= 2 else ""))
    return "\n".join(lines)


def format_halving(axes: list[Axis], rungs: list[Rung], tried: int, share: float, outcomes: dict[tuple[int, ...], Outcome]) -> str:
    """What each step of --halving kept and dropped."""
    setting = lambda index: ", ".join(f"{a.label}={a.values[i]}" for a, i in zip(axes, index))
    lines = [f"halving: {tried:,} cells, keeping {share:.0%} at each of {len(rungs)} steps (each adds a day under a mode, the PnL so far ranks)"]
    for k, rung in enumerate(rungs, 1):
        kept = set(rung.kept)
        working = [index for index in rung.pnl if index not in kept and index not in rung.failed]
        line = f"  {k}. through {rung.seen}: {len(rung.pnl):,} cells, kept {len(rung.kept):,}"
        if working:
            best = max(working, key=rung.pnl.get)
            line += f"; best dropped {setting(best)} ({_num(rung.pnl[best])})"
        failed = len(rung.failed - kept)
        if failed:
            line += f"; {failed:,} dropped with errors or limit breaches"
        lines.append(line)
    lines.append(f"  then every day and mode for the last {len(outcomes):,}")
    lines.append(f"! the tests below see the {len(outcomes):,} kept cells only, chosen on the days they include: they understate the selection "
                 f"bias of {tried:,} cells; the unseen-days section after them leaves out every day a step ranked on")
    return "\n".join(lines)


def format_search(axes: list[Axis], searched: Searched, total: int, outcomes: dict[tuple[int, ...], Outcome]) -> str:
    """What --search ran and found."""
    setting = lambda index: ", ".join(f"{a.label}={a.values[i]}" for a, i in zip(axes, index))
    how = {"coord": f"coordinate descent from {setting(searched.start)}", "tpe": "a tree-structured Parzen estimator"}[searched.method]
    lines = [f"search: {how} (seed {searched.seed}), {len(outcomes):,} of {total:,} cells ({len(outcomes) / total:.2%}; budget {searched.budget:,}), "
             f"maximising {searched.objective}"]
    if searched.best is not None:
        lines.append(f"  its best, found at cell {searched.found_at:,} of {len(outcomes):,}: {setting(searched.best)}"
                     + ("" if searched.found_at <= len(outcomes) * 0.75 else ": late in the budget, so a larger one may find better"))
    lines.append(f"! the tests below see the {len(outcomes):,} cells the search ran, chosen by their PnL: they understate the selection bias "
                 f"of {total:,} cells")
    return "\n".join(lines)


def _spearman(x: list[float], y: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=v.__getitem__)
        r = [0.0] * len(v)
        k = 0
        while k < len(order):
            j = k
            while j + 1 < len(order) and v[order[j + 1]] == v[order[k]]:
                j += 1
            for i in order[k:j + 1]:
                r[i] = (k + j) / 2
            k = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    if statistics.pstdev(rx) == 0 or statistics.pstdev(ry) == 0:
        return 0.0
    return statistics.correlation(rx, ry)


def without_days(outcome: Outcome, days: list[Day], seen: set[int]) -> Outcome:
    """The outcome on the days not in `seen` (indices into `days`): its day PnL and fine blocks (for SPA and StepM)."""
    names, keep, start = {days[d].name for d in seen}, [], 0
    for d, day in enumerate(days):
        end = start + len(day.ticks) // FINE_TICKS
        if d not in seen:
            keep.append((start, end))
        start = end
    return replace(outcome, day_pnl={m: {d: v for d, v in pnl.items() if d not in names} for m, pnl in outcome.day_pnl.items()},
                   fine_pnl={m: [x for a, b in keep for x in fine[a:b]] for m, fine in outcome.fine_pnl.items()})


def format_unseen(axes: list[Axis], baseline: Outcome, outcomes: dict[tuple[int, ...], Outcome], modes: list[TradeMatching], days: list[Day],
                  seen: set[int], engine: str = "python", by: str = "screen", gate: str = "every") -> str:
    """SPA, StepM and the pick on the days no screen or halving step ranked on: their choice can't bias them."""
    unseen = [day.name for d, day in enumerate(days) if d not in seen]
    if not unseen:
        return (f"! every day was ranked on by a halving step, so no day is free of its choice: hold a day out of --days and score the pick on it, "
                f"or halve under one mode (the last day is then never ranked on)")
    trimmed = {index: without_days(o, days, seen) for index, o in outcomes.items()}
    head = f"on the days the {by} didn't see ({', '.join(unseen)}), so free of its choice:"
    return head + "\n" + format_snooping(axes, without_days(baseline, days, seen), trimmed, modes, None, engine, gate)


def parse_holdout(text: str, days: list[Day]) -> tuple[str, int | float]:
    """--holdout: "last" or a day's name (a day), or a share of the data ("25%" or 0.25: its last
    blocks of FINE_TICKS ticks, for a download of one long day). Returns (description, day index or share)."""
    names = [day.name for day in days]
    if text == "last" or text in names:
        if len(days) < 2:
            raise ValueError("--holdout of a day needs two or more days: hold out a share of the data instead, e.g. --holdout 25%")
        d = len(days) - 1 if text == "last" else names.index(text)
        return f"day {names[d]}", d
    try:
        share = float(text.removesuffix("%")) / (100 if text.endswith("%") else 1)
    except ValueError:
        raise ValueError(f"--holdout takes last, a day's name ({', '.join(names)}) or a share of the data such as 25%, not {text!r}") from None
    if not 0 < share < 1:
        raise ValueError(f"--holdout's share must be between 0 and 1 (e.g. 25%), not {text!r}")
    return f"the last {share:.0%} of the data", share


def split_holdout(outcome: Outcome, days: list[Day], part: int | float) -> tuple[Outcome, Outcome]:
    """The outcome on the data a --holdout keeps for the search, and on the data it holds out. A day
    is split exactly; a share splits the FINE_TICKS blocks (days in order), each part's PnL then
    being its blocks' sum."""
    if isinstance(part, int):
        return without_days(outcome, days, {part}), without_days(outcome, days, set(range(len(days))) - {part})
    total = max((len(fine) for fine in outcome.fine_pnl.values()), default=0)
    cut = total - max(1, round(part * total))
    halves = []
    for name, sl in (("kept", slice(None, cut)), ("held out", slice(cut, None))):
        fine = {m: array("d", f[sl]) for m, f in outcome.fine_pnl.items()}
        halves.append(replace(outcome, day_pnl={m: {name: sum(f)} for m, f in fine.items()}, fine_pnl=fine))
    return halves[0], halves[1]


def format_holdout(axes: list[Axis], baseline: Outcome, outcomes: dict[tuple[int, ...], Outcome], modes: list[TradeMatching], days: list[Day],
                   holdout: tuple[str, int | float], engine: str = "python", gate: str = "every") -> str:
    """SPA, StepM and the pick on the data --holdout keeps, then that pick checked on the data it
    holds out: it is kept only if it beats the bot as is there too, under the gate's modes. On noise
    the check passes about half the time, so it halves the bootstrap tests' false positives, which
    run above their nominal 5% (IDEAS.md, "Bootstrap tests of the best cell")."""
    described, part = holdout
    kept = {index: split_holdout(o, days, part)[0] for index, o in outcomes.items()}
    base_kept, base_held = split_holdout(baseline, days, part)
    lines, pick = snooping_pick(axes, base_kept, kept, modes, None, engine, gate)
    head = f"held out {described}: SPA, StepM and the pick on the rest, then the pick checked on {described}:"
    if pick is None:
        return "\n".join([head, *lines, "  pick, held out: the bot as is: nothing to check"])
    held = split_holdout(outcomes[pick.index], days, part)[1]
    gains = {m: held.pnl(m) - base_held.pnl(m) for m in modes}
    shown = " · ".join(f"{m} {g:+,.0f}" for m, g in gains.items())
    setting = ", ".join(f"{a.label}={v}" for a, v in zip(axes, pick.values))
    gating = modes if gate == "every" else modes[:1]
    if all(gains[m] > 0 for m in gating):
        verdict = f"  pick, held out: {setting}: it also beats the bot as is on {described} ({shown})"
    else:
        verdict = f"  pick, held out: the bot as is: {setting} doesn't beat it on {described} ({shown})"
    return "\n".join([head, *lines, verdict])


# ---------------------------------------------------------------------------- overfitting


def blocks_per_day(days: int) -> int:
    """Blocks to cut each day into: about BLOCKS in all, an even number over the days (CSCV halves them)."""
    per_day = math.ceil(BLOCKS / days)
    return per_day + (per_day * days) % 2


def block_pnl(series: list[float], blocks: int) -> list[float]:
    """A day's cumulative PnL series cut into contiguous blocks: each block's PnL. Empty if too short."""
    if len(series) < blocks:
        return []
    out, last = [], 0.0
    for k in range(blocks):
        end = series[round(len(series) * (k + 1) / blocks) - 1]
        out.append(end - last)
        last = end
    return out


def _key(values) -> bytes:
    """Equal block PnL to 6 decimals as one dict key: the rounded values' bytes (-0.0 counted as 0.0),
    far smaller than a tuple of floats for a grid of many cells."""
    return array("d", (round(x, 6) + 0.0 for x in values)).tobytes()


def format_snooping(axes: list[Axis], baseline: Outcome, outcomes: dict[tuple[int, ...], Outcome], modes: list[TradeMatching], dsr: float | None,
                    engine: str = "python", gate: str = "every") -> str:
    """SPA and StepM on each distinct cell's gain over the bot as is, per block of FINE_TICKS ticks,
    under the first mode; StepM's cells are then checked against the bot as is under the others.
    With engine "rust" the bootstrap runs in rust/src/arena/stats.rs, the same to the bit."""
    return "\n".join(snooping_pick(axes, baseline, outcomes, modes, dsr, engine, gate)[0])


def snooping_pick(axes: list[Axis], baseline: Outcome, outcomes: dict[tuple[int, ...], Outcome], modes: list[TradeMatching], dsr: float | None,
                  engine: str = "python", gate: str = "every") -> tuple[list[str], Outcome | None]:
    """format_snooping's lines, and its pick (None for the bot as is). With gate "every" the pick
    must beat the bot as is under every mode; with "first" only under the first, the others shown
    as columns to read (for once the playground has shown which mode the Arena's fills follow)."""
    mode = modes[0]
    base = baseline.fine_pnl.get(mode, [])
    cells: dict[bytes, tuple[array, list[Outcome]]] = {}
    for _, o in sorted(outcomes.items()):
        fine = o.fine_pnl.get(mode, [])
        if o.failed or len(fine) != len(base):
            continue
        gain = array("d", (x - b for x, b in zip(fine, base)))
        if any(gain):
            cells.setdefault(_key(gain), (gain, []))[1].append(o)
    if baseline.failed or len(base) < MIN_FINE_BLOCKS or not cells:
        return [f"  SPA, StepM: skipped (needs a working bot as is, a cell that differs from it, and {MIN_FINE_BLOCKS}+ blocks of {FINE_TICKS} ticks)"], None
    groups = list(cells.values())
    d = [gain for gain, _ in groups]
    p, winners = (rust.snooping if engine == "rust" else snooping)(d, SPA_Q, BOOTSTRAP)
    lines = [
        f"  SPA on pnl({mode}) gains over the bot as is, {len(base):,} blocks of {FINE_TICKS} ticks, {len(d):,} distinct cells, "
        f"bootstrap blocks of {round(FINE_TICKS / SPA_Q):,} ticks on average, {BOOTSTRAP:,} resamples:",
        f"  p {p['c']:.3f} that no cell beats the bot as is (bounds {p['l']:.3f} to {p['u']:.3f}; the upper is the Reality Check)",
    ]
    if winners:
        ranked = sorted(winners, key=lambda k: -statistics.fmean(d[k]))
        named = ["; ".join(", ".join(f"{a.label}={v}" for a, v in zip(axes, o.values)) for o in groups[k][1]) for k in ranked]
        shown = " | ".join(named[:5]) + (f" | ... {len(named) - 5} more" if len(named) > 5 else "")
        lines.append(f"  StepM at {TEST_ALPHA:.0%}: {len(winners)} cells beat the bot as is: {shown}")
    else:
        lines.append(f"  StepM at {TEST_ALPHA:.0%}: no cell beats the bot as is")
    if p["c"] < TEST_ALPHA and dsr is not None and dsr < 0.95:
        lines.append("! SPA finds a gain the DSR doesn't: the DSR's bar rises with the spread of all cells, poor ones included, "
                     "and SPA discounts those (references/wiki/contradictions.md, row 18)")
    failing = []
    for other in modes[1:]:
        found = [o for k in winners for o in groups[k][1]]
        if not found:
            break
        holds = [o for o in found if o.pnl(other) > baseline.pnl(other)]
        best = max(o.pnl(other) - baseline.pnl(other) for o in found)
        lines.append(f"  under {other}: {len(holds)} of StepM's {len(found)} cells beat the bot as is (best by {best:+,.0f})")
        if not holds:
            failing.append(str(other))
    if failing and len(modes) == 2:
        lines.append(f"! StepM's cells only beat the bot as is under {mode}: the gain depends on the fill model")
    elif failing:
        lines.append(f"! none of StepM's cells beats the bot as is under {', '.join(failing)}: the gain depends on the fill model")
    if p["c"] < TEST_ALPHA and len(modes) == 1:
        lines.append("  a gain under one matching mode still has to hold under the others: rerun with --modes all,worse")
    found = [o for k in winners for o in groups[k][1]]
    gating = modes[1:] if gate == "every" else []
    holding = [o for o in found if all(o.pnl(m) > baseline.pnl(m) for m in gating)]
    under = "under every mode" if gate == "every" or len(modes) == 1 else f"under {mode} (--gate first: the other modes are columns to read)"
    if holding:
        best = max(holding, key=lambda o: o.pnl(mode))
        setting = ", ".join(f"{a.label}={v}" for a, v in zip(axes, best.values))
        gains = " · ".join(f"{m} {best.pnl(m) - baseline.pnl(m):+,.0f}" for m in modes)
        lines.append(f"  pick: {setting} ({gains}): StepM's best cell that beats the bot as is {under}")
        return lines, best
    lines.append(f"  pick: the bot as is: no StepM cell beats it {under}")
    return lines, None


def format_overfitting(baseline: Outcome, outcomes: dict[tuple[int, ...], Outcome], modes: list[TradeMatching], days: int, axes: list[Axis] | None = None,
                       engine: str = "python", gate: str = "every") -> str:
    mode = modes[0]
    usable = [o for _, o in sorted(outcomes.items()) if not o.failed]
    columns = list({_key(o.block_pnl[mode]): o.block_pnl[mode] for o in usable}.values())
    lines = [f"overfitting: {len(outcomes):,} cells × {len(modes)} modes = {len(outcomes) * len(modes):,} trials on {days} days"]
    blocks = len(columns[0]) if columns else 0
    if len(columns) < 2 or blocks < 2 or any(len(c) != blocks for c in columns):
        lines.append("  fewer than two distinct cells, or days too short to cut into blocks: no PBO or DSR")
        if axes is not None:
            lines.append(format_snooping(axes, baseline, outcomes, modes, None, engine, gate))
        return "\n".join(lines)
    result = (rust.cscv if engine == "rust" else cscv)(columns)
    sampled = f"{result.splits:,} of {result.of:,}" if result.splits < result.of else f"all {result.of:,}"
    coarse = " (under 10: coarse ranks)" if len(columns) < 10 else ""
    lines.append(f"  CSCV on pnl({mode}) in {blocks} blocks ({blocks // days} a day), {len(columns):,} distinct cells{coarse}, {sampled} halvings:")
    lines.append(f"  PBO {result.pbo:.0%}  ·  the pick's mean rank out of sample {result.rank:.2f} (1 top, 0.5 median)  ·  it loses money there in {result.loss:.0%}")
    base = baseline.block_pnl[mode]
    gains = [[x - b for x, b in zip(c, base)] for c in columns] if len(base) == blocks else []
    best = [x - b for x, b in zip(max(usable, key=lambda o: o.pnl(mode)).block_pnl[mode], base)] if gains else []
    sharpes = [statistics.fmean(g) / statistics.stdev(g) for g in gains if statistics.stdev(g) > 0]
    trials = independent_trials(gains, rust.mean_correlation if engine == "rust" else None) if gains else 0.0
    dsr = None
    if best and not any(best):
        lines.append("  the best cell is the bot as is: no gain to deflate")
    elif best and statistics.stdev(best) > 0 and len(sharpes) >= 2:
        mean, sd = statistics.fmean(best), statistics.pstdev(best)
        skew = statistics.fmean(((x - mean) / sd) ** 3 for x in best)
        kurtosis = statistics.fmean(((x - mean) / sd) ** 4 for x in best)
        sharpe, sharpe0 = statistics.fmean(best) / statistics.stdev(best), expected_max_sharpe(statistics.variance(sharpes), trials)
        dsr = deflated_sharpe(sharpe, sharpe0, blocks, skew, kurtosis)
        rough = " (more cells than blocks: N^ is rough)" if len(columns) > blocks else ""
        shown = f"{dsr:.2f}" if dsr is not None else "-"
        lines.append(f"  DSR {shown} for the best cell's gain over the bot as is: per-block Sharpe {sharpe:.2f} against {sharpe0:.2f}, "
                     f"the best of N^ {trials:.1f} cells with no gain{rough}")
        if dsr is not None and dsr < 0.95:
            lines.append("! the best cell's gain over the bot as is is not clearly more than the best of that many cells with no gain (DSR < 0.95)")
    if result.pbo >= 0.5:
        lines.append("! PBO >= 50%: the best cell in one half of the blocks is as likely as not to be below the median in the other")
    if axes is not None:
        lines.append(format_snooping(axes, baseline, outcomes, modes, dsr, engine, gate))
    return "\n".join(lines)


RISK_COLUMNS = {"max_dd": "drawdown", "conc": "conc", "under": "under", "run": "run", "sharpe_day": "sharpe_day", "sharpe_block": "sharpe_block",
                "late_days": "late"}


def write_csv(path: Path, axes: list[Axis], modes: list[TradeMatching], outcomes: dict[tuple[int, ...], Outcome]) -> None:
    """One row per combination: axis values, then per mode its pnl, min day, nbhd, per-day and per-product pnl; after
    the counts, per mode its PnL path's measures (Risk: max_dd, conc, under, run, sharpe_day, sharpe_block, late_days)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(outcomes.items())
    shape = tuple(len(axis.values) for axis in axes)
    first = ordered[0][1]
    days = {mode: list(first.day_pnl[mode]) for mode in modes}
    products = {mode: sorted({p for _, o in ordered for p in o.product_pnl[mode]}) for mode in modes}

    header = [axis.target for axis in axes]
    for mode in modes:
        header += [f"pnl_{mode}", f"min_day_{mode}", f"nbhd_{mode}"]
        header += [f"pnl_{mode}_{day}" for day in days[mode]]
        header += [f"pnl_{mode}_{product}" for product in products[mode]]
    worst = scored_worst(modes)
    header += (["worst"] if worst else []) + ["fills", "errors", "limit_breaches"]
    header += [f"{name}_{mode}" for mode in modes for name in RISK_COLUMNS]

    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for index, outcome in ordered:
            row = list(outcome.values)
            for mode in modes:
                row += [outcome.pnl(mode), outcome.min_day(mode), neighborhood_mean(outcomes, index, shape, mode)]
                row += [outcome.day_pnl[mode][day] for day in days[mode]]
                row += [outcome.product_pnl[mode].get(product, 0.0) for product in products[mode]]
            row += ([worst_case(outcome, modes)] if worst else []) + [outcome.fills, outcome.errors, outcome.limit_breaches]
            for mode in modes:
                risk = risk_of(outcome, mode)
                row += ["" if getattr(risk, name) is None else getattr(risk, name) for name in RISK_COLUMNS.values()]
            writer.writerow(row)


def _num(value: float) -> str:
    return f"{value:,.0f}"



# ---------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m arena.grid", description="Grid-search bot parameters, with robustness checks."
    )
    add_common_arguments(parser)
    add_rival_argument(parser)
    parser.add_argument(
        "--grid",
        dest="axes",
        action="append",
        required=True,
        metavar="PATH=VALUES",
        help="a parameter to vary: PATH=V1,V2,... or PATH=START..STOP[..STEP], inclusive. Repeat for more axes.",
    )
    parser.add_argument(
        "--modes",
        help="comma-separated trade-matching modes to run every combination under, e.g. all,worse. "
        "The first is the main one (default: --match-trades)",
    )
    add_scenario_argument(parser)
    parser.add_argument("--sort", default="pnl", help="rank by pnl, nbhd, min-day, an extra mode's pnl, with --scenario the worst over them, or the "
                        "first mode's PnL path: sharpe-day, sharpe-block, drawdown, conc, under, run (the last four smallest first) (default: pnl)")
    parser.add_argument("--top", type=int, default=15, help="rows to show (default: 15)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="worker processes (default: CPU count)")
    parser.add_argument("--out", type=Path, help="write every combination's results to this CSV")
    parser.add_argument("--all-products", action="store_true",
                        help="run every product in every combination, even when the axes set only some (default: only those, when that gives the bot as is the same PnL)")
    parser.add_argument("--permute", type=int, default=0, metavar="N",
                        help="also run the whole grid on N copies of the days with their ticks shuffled, for a permutation test (default: 0)")
    parser.add_argument("--permute-block", type=int, default=1, metavar="TICKS",
                        help="shuffle the ticks in runs of this many, keeping the order inside a run (default: 1)")
    add_engine_argument(parser, "run the backtests and the statistics in Python, or on the Rust port (rust/: needs cargo, and a bot with a "
                        "Rust twin, rust/twins.json), with the same results: a backtest about 130 times faster on one core, a whole grid 40-80 times (default: python)")
    parser.add_argument("--sample", type=int, metavar="N", help="run N cells drawn at random from the grid instead of every one (seeded by --sample-seed)")
    parser.add_argument("--sample-seed", type=int, default=0, help="--sample's seed (default: 0)")
    parser.add_argument("--halving", type=float, metavar="SHARE",
                        help="successive halving in steps: each adds the next day (the first mode's days, then the others') and keeps this "
                        "share of the cells still alive, by their PnL so far; the last ones run on every day and mode (e.g. 0.5)")
    parser.add_argument("--holdout", metavar="DAY|SHARE",
                        help="choose the pick without this data, then keep it only if it also beats the bot as is there: last, a day's name, "
                        "or a share of the data's end such as 25%% (for a download of one day)")
    parser.add_argument("--gate", choices=("every", "first"), default="every",
                        help="the modes the pick must beat the bot as is under: every one of --modes (default), or only the first, the others "
                        "shown as columns (once the playground has shown which mode the Arena's fills follow)")
    parser.add_argument("--search", choices=sorted(search.SEARCHES),
                        help="run at most --budget cells, chosen as it goes: coord (coordinate descent from the bot as is) or tpe (a "
                        "tree-structured Parzen estimator), maximising the smaller gain over the bot as is under the gate's modes, without "
                        "the --holdout data; for grids past about 100,000 cells")
    parser.add_argument("--budget", type=int, metavar="N", help="--search's cells, each on every day and mode (e.g. 1000)")
    parser.add_argument("--search-seed", type=int, default=0, help="--search's seed (default: 0)")
    parser.add_argument("--screen", type=float, metavar="SHARE",
                        help="successive halving: run every combination on the first day under the first mode, then only this share "
                        "of them, the best there, on every day and mode (e.g. 0.25)")
    args = parser.parse_args(argv)

    try:
        s = setup(args)
        axes = [parse_axis(text) for text in args.axes]
        modes = scenarios_from(args.modes, args.scenarios, s.config.trade_matching)
        _check(axes, modes, s, args.sort)
        if args.permute < 0 or args.permute_block < 1:
            raise ValueError("--permute needs N >= 0 and --permute-block a run of at least 1 tick")
        if args.screen is not None and not 0 < args.screen < 1:
            raise ValueError("--screen needs a share between 0 and 1, e.g. 0.25")
        if args.halving is not None and not 0 < args.halving < 1:
            raise ValueError("--halving needs a share between 0 and 1, e.g. 0.5")
        if args.halving is not None and (args.screen is not None or args.permute):
            raise ValueError("--halving is a screen of its own: drop --screen, and --permute (it screens each copy with --screen only)")
        if args.search is not None and (args.budget is None or args.budget < 1):
            raise ValueError("--search needs --budget, a number of cells, e.g. 1000")
        if args.budget is not None and args.search is None:
            raise ValueError("--budget is --search's: name one (coord or tpe)")
        if args.search is not None and (args.screen is not None or args.halving is not None or args.sample is not None or args.permute):
            raise ValueError("--search chooses its own cells: drop --screen, --halving, --sample and --permute")
        if args.sample is not None and args.sample < 1:
            raise ValueError("--sample needs a number of cells, e.g. 10000")
        holdout = parse_holdout(args.holdout, s.days) if args.holdout else None
        if s.engine == "rust":
            rust.prepare(args.format, [args.bot, *every_rival(s.rivals, modes)], args.allow_stale)
            for mode in modes:
                for rival in rivals_for([], mode):
                    rust.bot_spec(rival.path, rival.overrides)  # settings on a twin that takes none: refused
        smoke_test(s, args.bot, axes, modes)
    except (ValueError, OSError, OverrideError, RuntimeError) as error:
        parser.error(str(error))

    combos = math.prod(len(axis.values) for axis in axes)
    if args.sample is not None and args.sample < combos:
        print(f"{args.sample:,} of {combos:,} combinations, drawn at random (--sample-seed {args.sample_seed})")
        combos = args.sample
    runs = (combos + 1) * len(s.days) * len(modes)
    if args.search:
        budget = min(args.budget, combos)
        print(f"{args.search} search: at most {budget:,} of {combos:,} combinations ({budget / combos:.2%}) × {len(s.days)} days × {len(modes)} modes "
              f"({(budget + 1) * len(s.days) * len(modes):,} backtests at most) on {args.jobs} workers")
    elif args.halving:
        alive, runs, steps = combos, len(s.days) * len(modes), len(s.days) * len(modes)
        for k in range(steps):
            runs += alive
            if k < steps - 1 and alive > 1:
                alive = max(1, math.ceil(args.halving * alive))
        print(f"{combos:,} combinations, one day under one mode at a time ({steps} steps), keeping {args.halving:.0%} after each but the last: "
              f"{alive:,} at the end ({runs:,} backtests) on {args.jobs} workers")
    elif args.screen:
        kept = max(1, math.ceil(args.screen * combos))
        runs = len(s.days) * len(modes) + combos + kept * (len(s.days) * len(modes) - 1)
        print(f"{combos} combinations screened on {s.days[0].name}, the best {kept} then × {len(s.days)} days × {len(modes)} modes "
              f"({runs} backtests) on {args.jobs} workers")
    else:
        print(f"{combos:,} combinations × {len(s.days)} days × {len(modes)} modes ({runs:,} backtests) on {args.jobs} workers")
    if s.rivals:
        print(f"each against {', '.join(participant_names(args.bot, s.rivals)[1:])} in the same market")
    described = format_scenarios(modes, s)
    if described:
        print(described)
    start = time.perf_counter()
    run = run_grid(s, args.bot, axes, modes, args.jobs, args.format, args.data, args.days, args.all_products, args.screen, args.sample, args.sample_seed,
                   args.halving, (args.search, args.budget, args.search_seed) if args.search else None, args.gate, holdout)
    baseline, outcomes = run.baseline, run.outcomes
    print(f"done in {time.perf_counter() - start:.1f} s" + (f"; {run.note}" if run.note else "") + "\n")

    rows = build_rows(axes, modes, outcomes)
    print(format_summary(axes, modes, baseline, rows, args.sort, args.top))
    dead = format_dead_axes(axes, outcomes, modes)
    if dead:
        print(dead)
    ends = format_axis_ends(axes, modes, rows, args.sort)
    if ends:
        print(ends)
    held_out = format_held_out(axes, modes, outcomes, repeated_days(s.days))
    if held_out:
        print("\n" + held_out)
    if run.screen:
        print("\n" + format_screen(axes, run.screen, outcomes))
    if run.rungs:
        print("\n" + format_halving(axes, run.rungs, run.tried, args.halving, outcomes))
    if run.searched:
        print("\n" + format_search(axes, run.searched, math.prod(len(axis.values) for axis in axes), outcomes))
    stats = rust.stats_engine(s.engine)  # the statistics in Rust whenever it builds: the same numbers, far faster
    print("\n" + format_overfitting(baseline, outcomes, modes, len(s.days), axes, stats, args.gate))
    if (run.screen or run.rungs) and len(s.days) >= 2:
        print("\n" + format_unseen(axes, baseline, outcomes, modes, s.days, run.seen, stats, "halving" if run.rungs else "screen", args.gate))
    if holdout:
        print("\n" + format_holdout(axes, baseline, outcomes, modes, s.days, holdout, stats, args.gate))
    if args.permute > 0:
        start = time.perf_counter()
        copies = run_permutations(s, args.bot, axes, modes, args.jobs, args.format, args.data, args.days, args.permute, args.permute_block,
                                  run.restricted, args.screen, args.sample, args.sample_seed)
        products = sorted({p for day in s.days for p in day.products})
        print(f"\n{format_permutations(axes, outcomes, copies, modes[0], args.permute_block, products)}  ({time.perf_counter() - start:.0f} s)")
    failed = [o for o in outcomes.values() if o.first_error]
    if failed:
        print(f"first error: {failed[0].first_error}")
    if args.out:
        write_csv(args.out, axes, modes, outcomes)
        print(f"\nall combinations written to {args.out}")
    return 1 if all(outcome.failed for outcome in outcomes.values()) else 0


def format_scenarios(modes: list, s: Setup) -> str:
    """What each --scenario changes, or nothing when every mode is plain."""
    lines = []
    for mode in modes:
        if isinstance(mode, Scenario) and not mode.plain:
            config, rivals = config_for(s.config, mode), rivals_for(s.rivals, mode)
            setting = f"match {config.trade_matching}, " + (f"resting, queue {config.queue}" + (f" (power {config.queue_power:g})" if config.queue == "prob" else "")
                                                            if config.resting else "per tick")
            setting += (f", fill {config.fill_ratio:g}" if config.fill_ratio != 1 else "") + (f", seed {config.seed}" if config.seed else "")
            setting += f", {config.print_share:g} of each print" if config.print_share != 1 else ""
            setting += (f", mark {config.mark}" if config.mark != "mid" else "") + (f", limit penalty {config.limit_penalty:g}" if config.limit_penalty is not None else "")
            setting += f", delay {config.delay}" if config.delay else ""
            setting += (f", fee {config.fee:g} a lot" if config.fee else "") + (f", fee {config.fee_bps:g} bps" if config.fee_bps else "")
            setting += (f", maker {config.maker_fee:g} a lot" if config.maker_fee is not None else "") + (
                f", maker {config.maker_fee_bps:g} bps" if config.maker_fee_bps is not None else "")
            setting += f", {config.order_fee:g} an order" if config.order_fee else ""
            setting += ", deplete" if config.deplete else ""
            setting += f", at most {config.max_orders} orders a tick" if config.max_orders is not None else ""
            setting += f", at most {config.max_actions} actions a tick" if config.max_actions is not None else ""
            setting += f", at most {config.max_resting} orders working a product" if config.max_resting is not None else ""
            setting += f"; against {', '.join(str(r) for r in rivals)}" if rivals else "; no rivals"
            lines.append(f"  {mode}: {setting}")
    return "scenarios:\n" + "\n".join(lines) if lines else ""


def _check(axes: list[Axis], modes: list[TradeMatching], s: Setup, sort: str) -> None:
    targets = [axis.target for axis in axes]
    duplicated = {t for t in targets if targets.count(t) > 1} | (set(targets) & set(s.overrides))
    if duplicated:
        raise ValueError(f"set more than once by --grid/--set: {', '.join(sorted(duplicated))}")
    if len(set(modes)) != len(modes):
        raise ValueError("--modes lists a mode twice")
    if sort not in sort_keys(modes):
        raise ValueError(f"--sort must be one of {', '.join(sort_keys(modes))}")


if __name__ == "__main__":
    sys.exit(main())
