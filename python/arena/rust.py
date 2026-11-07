"""The Rust port (rust/) from Python: building it, exporting days for it, and running backtests on it.

rust/ ports python/arena/engine.py and some bots, each with its Python twin listed in rust/twins.json
(rust/README.md has the table of what is in which language). This module is the bridge:

  export_day    a Day as rust/src/support/dayfile.rs reads it (the format plug-ins stay in Python)
  write_day     a reference to a Prosperity day's own CSVs instead, which Rust reads itself
                (rust/src/arena/formats/prosperity.rs), when the day came from them; else export_day
  bot_spec      a twin bot for Rust: its kind, and its Python file's globals after any --set
                overrides, so the Rust bot reads the same settings (the template's DEFAULTS and
                PARAMS, a rival's constants)
  prepare       --engine rust's checks: bots with a twin for the format, twins checked since their
                Python code changed (--allow-stale to run anyway), a built binary; require for an experiment
  run_days      `arena-rs run`: participants in one market on each day, on threads, back as Python
                DayResults (arena.backtest --engine rust)
  run_batch     `arena-rs batch`: many backtests on every core, each returning what arena.grid's
                Piece holds (arena.grid, arena.compare, arena.stress --engine rust)
  run_sim       `arena-rs sim`: arena.sim's market (rust/src/arena/sim.rs) on a range of seeds, with twin
                bots in it, read back as arena.sim.SimDay (arena.sim --engine rust)
  cscv, mean_correlation, snooping
                python/arena/stats.py's statistics that grow with a grid's cells, in rust/src/arena/stats.rs
                (arena.grid --engine rust): the same results to the bit
  read_day, read_results
                a day and DayResults as Rust wrote them, back as Python's own types, so the reports
                and CSVs work unchanged
  stale_twins   the twins whose Python file changed since the Rust port was last checked against it

Standard library only, like the rest of python/arena/ outside analysis.py. Nothing here is needed unless
a tool is asked for the Rust engine.
"""

from __future__ import annotations

import ast
import dataclasses
import functools
import hashlib
import itertools
import json
import shutil
import subprocess
import weakref
from collections import defaultdict
from dataclasses import fields
from pathlib import Path

from arena.botfile import BotFile
from arena.engine import DayResult, EngineConfig, Mark, TradeMatching
from arena.formats import prosperity
from arena.model import Book, Day, Fill, MarketTrade, OpenOrder, Tick

ROOT = Path(__file__).resolve().parents[2]  # the repository: python/arena/rust.py
RUST = ROOT / "rust"
BINARY = RUST / "target" / "release" / "arena-rs"
TWINS = RUST / "twins.json"


def build() -> None:
    """Builds the release binary (cargo skips it when nothing changed)."""
    if shutil.which("cargo") is None:
        raise RuntimeError("the Rust engine needs cargo (brew install rust), see rust/README.md")
    subprocess.run(["cargo", "build", "--release", "--quiet", "--manifest-path", str(RUST / "Cargo.toml")], check=True)


# ---------------------------------------------------------------------------- twins


def twins() -> dict[str, dict]:
    """rust/twins.json: each Python file with a Rust port, by its path from the repo root."""
    return json.loads(TWINS.read_text())


@functools.lru_cache(maxsize=None)
def _rows() -> dict[str, dict]:
    """twins(), read once per process for the lookups below."""
    return twins()


@functools.lru_cache(maxsize=None)
def _kinds() -> dict[str, str]:
    return {path: twin["kind"] for path, twin in _rows().items() if "kind" in twin}


def format_of(path: Path) -> str:
    """The format plug-in a twinned bot file runs under (its row's `format`, default prosperity)."""
    kind_of(path)  # a ValueError for a file without a twin
    return _rows()[_relative(path)].get("format", "prosperity")


def adapter_of(path: Path) -> str | dict | None:
    """A template twin's ADAPTER choices (its row's `adapter`): None for the kind's own, else a preset
    ("prosperity", "drill") or the choices themselves (rust/src/bots/template.rs `Adapter::read`)."""
    kind_of(path)
    return _rows()[_relative(path)].get("adapter")


@functools.lru_cache(maxsize=None)
def _reads_settings() -> dict[str, bool]:
    """Per kind: whether the Rust bot reads its settings from the Python file's globals (the zoo's don't)."""
    return {twin["kind"]: twin.get("settings", True) for twin in _rows().values() if "kind" in twin}


def code_hash(source: str, reads: list[str] | tuple[str, ...] = ()) -> str:
    """The hash of what a Rust twin must match in a Python file: its syntax tree without docstrings,
    so comments, docstrings and layout don't count. `reads` names the upper-case globals the Rust
    twin reads from the file at run time (bot_globals: the template's DEFAULTS and PARAMS, a rival's
    constants): top-level statements that only set those are left out too, since Rust gets their
    values when it runs, not from its own code."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and _docstring(node.body):
            node.body = node.body[1:] or [ast.Pass()]
    if reads:
        tree.body = [node for node in tree.body if not _sets_only(node, set(reads))]
    return hashlib.sha256(ast.dump(tree).encode()).hexdigest()


def _docstring(body: list[ast.stmt]) -> bool:
    return bool(body) and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)


def _root(target: ast.expr) -> list[str]:
    """The global names an assignment target sets: `PARAMS["X"]["y"]` sets PARAMS."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Subscript, ast.Attribute)):
        return _root(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _root(element)]
    return [""]


def _sets_only(node: ast.stmt, names: set[str]) -> bool:
    """Whether a top-level statement does nothing but set `names` (a loop over private names counts,
    such as the template's `for _strike in ...: PARAMS[...] = {...}`)."""
    if isinstance(node, ast.Assign):
        return all(name in names for target in node.targets for name in _root(target))
    if isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        return all(name in names for name in _root(node.target))
    if isinstance(node, ast.For):
        return (all(name.startswith("_") for name in _root(node.target)) and not node.orelse
                and all(_sets_only(statement, names) for statement in node.body))
    return False


def file_hash(relative: str, reads: list[str] | tuple[str, ...] = ()) -> str:
    """code_hash of a twin's Python file, by its path from the repo root."""
    return code_hash((ROOT / relative).read_text(encoding="utf-8"), reads)


def stale_twins() -> list[str]:
    """The twins whose Python code isn't what their Rust port was last checked against."""
    return [path for path, twin in twins().items() if file_hash(path, twin.get("reads", ())) != twin["sha256"]]


def record_hashes(paths: list[str] | None = None) -> None:
    """Writes the current hash of each twin, or of those in `paths`: run only after the parity check
    passed (python/experiments/rust_bench.py --record, or --twin FILE --record for one)."""
    table = twins()
    for path, twin in table.items():
        if paths is None or path in paths:
            twin["sha256"] = file_hash(path, twin.get("reads", ()))
    TWINS.write_text(json.dumps(table, indent=2) + "\n")


def kind_of(path: Path) -> str:
    """The Rust bot kind of a bot file, or a ValueError naming the bots that have one."""
    relative = _relative(path)
    kinds = _kinds()
    if relative not in kinds:
        raise ValueError(f"{path} has no Rust twin (bots with one: {', '.join(kinds)})")
    return kinds[relative]


# ---------------------------------------------------------------------------- bots


def _jsonable(value) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_jsonable(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _jsonable(v) for k, v in value.items())
    return False


@functools.lru_cache(maxsize=None)
def _bot_file(path: Path) -> BotFile:
    from arena.formats import drill_exchange

    return BotFile(path, {"datamodel": prosperity.dm, "exchange": drill_exchange}, strict=False)


def bot_globals(path: Path, overrides: dict[str, object]) -> dict:
    """The bot file's upper-case globals that JSON can hold, after the overrides: what its Rust
    twin reads its settings from."""
    module = _bot_file(Path(path).resolve()).load(overrides)
    return {name: value for name, value in vars(module).items() if name.isupper() and not name.startswith("_") and _jsonable(value)}


def bot_spec(path: Path, overrides: dict[str, object], requote: bool = False) -> dict:
    kind = kind_of(path)
    if overrides and not _reads_settings()[kind]:
        raise ValueError(f"{path}'s Rust twin doesn't read its settings from the file (a zoo bot runs as written): drop the --set or use --engine python")
    spec = {"kind": kind, "globals": bot_globals(path, overrides) if _reads_settings()[kind] else {}, "requote": requote}
    adapter = adapter_of(path)
    return spec if adapter is None else {**spec, "adapter": adapter}


def config_json(config: EngineConfig) -> dict:
    return {f.name: (str(getattr(config, f.name)) if f.name in ("trade_matching", "queue", "mark") else getattr(config, f.name)) for f in fields(config)}


# ---------------------------------------------------------------------------- days


def _whole(price) -> int:
    if price != int(price):
        raise ValueError(f"the Rust engine takes whole prices, got {price}")
    return int(price)


def _name(text: str) -> str:
    if not text.isprintable() or text != text.strip():
        raise ValueError(f"a trader name in a day file is one printable line, without leading or trailing spaces: {text!r}")
    return text


def export_day(day: Day, path: Path) -> None:
    """Writes the day in rust/src/support/dayfile.rs's format: products sorted by name plus the day's own
    order and its limits' order, a format's tick sizes and price unit (Day.info), trader names by
    first appearance, each tick's books in its dict order."""
    products = sorted(day.products)
    index = {p: k for k, p in enumerate(products)}
    names = {"": 0}
    for tick in day.ticks:
        for trades in tick.trades.values():
            for t in trades:
                names.setdefault(_name(t.buyer), len(names))
                names.setdefault(_name(t.seller), len(names))
    info = [(p, meta) for p, meta in day.info.items() if p in index and "tick" in meta]
    lines = ["arena-day 3", f"name {day.name}", f"products {len(products)}", *(f"{p} {day.limits[p]}" for p in products),
             "order" + "".join(f" {index[p]}" for p in day.products), "limits" + "".join(f" {index[p]}" for p in day.limits if p in index),
             f"info {len(info)}", *(f"{index[p]} {float(meta['tick'])!r} {float(meta.get('unit', 0.01))!r}" for p, meta in info),
             f"names {len(names)}", *names, f"ticks {len(day.ticks)}"]
    side = lambda levels: f"{len(levels)}" + "".join(f" {_whole(price)} {volume}" for price, volume in levels)
    for tick in day.ticks:
        trades = [t for p in tick.trades for t in tick.trades[p]]
        lines.append(f"t {tick.timestamp} {len(tick.books)} {len(trades)} {len(tick.marks)}")
        lines += [f"b {index[p]} {side(book.bids)} {side(book.asks)}" for p, book in tick.books.items()]
        lines += [f"x {index[t.product]} {_whole(t.price)} {t.quantity} {names[t.buyer]} {names[t.seller]} {t.timestamp}" for t in trades]
        lines += [f"m {index[p]} {float(mark)!r}" for p, mark in tick.marks.items()]
    path.write_text("\n".join(lines) + "\n")


def write_day(day: Day, stem: Path, only: list[str] | None = None) -> Path:
    """The day for Rust at stem.json, a reference to its Prosperity CSVs that Rust reads itself
    (rust/src/arena/formats/prosperity.rs), if it was loaded from them (prosperity.reference); else exported to
    stem.day. With `only`, just those products (arena.grid.only). Returns the path written."""
    ref = prosperity.reference(day, only)
    if ref is not None:
        path = stem.with_suffix(".json")
        path.write_text(json.dumps(ref))
        return path
    if only is not None:
        from arena.grid import only as restrict

        day = restrict(day, only)
    path = stem.with_suffix(".day")
    export_day(day, path)
    return path


# ---------------------------------------------------------------------------- runs


def prepare(format_name: str, bots: list[Path], allow_stale: bool = False) -> None:
    """--engine rust: bots with a Rust twin written for the format (prosperity, or drill for
    python/bots/drill/template.py), and a built binary. A ValueError if a bot has no twin for the
    format, or if its twin or one of the engine's (the twins with no bot kind: the engine, the loader,
    the sim, the stress copies, the statistics) was last checked against older Python code: Rust
    would run that older code. With allow_stale (--allow-stale) it runs anyway, with a warning."""
    for path in bots:
        if format_of(path) != format_name:
            raise ValueError(f"{path}'s Rust twin is for --format {format_of(path)}, not {format_name}")
    _check_stale([*(path for path, twin in twins().items() if "kind" not in twin), *map(_relative, bots)], allow_stale)
    build()


def stats_engine(engine: str) -> str:
    """Where a run's statistics go: Rust for --engine rust, and also for a Python run when cargo
    builds the binary and stats.py's twin is current, since they give the same numbers to the bit
    and the studentized bootstrap takes about 0.8 s a distinct cell in Python. Else Python."""
    if engine == "rust":
        return "rust"
    if shutil.which("cargo") is None or "python/arena/stats.py" in stale_twins():
        return "python"
    try:
        build()
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        return "python"
    return "rust"


def require(allow_stale: bool = False) -> None:
    """An experiment's --engine rust: every twin checked since its Python code changed (an
    experiment may run any of them), else a ValueError, and a built binary."""
    _check_stale(list(twins()), allow_stale)
    build()


def _relative(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _check_stale(paths: list[str], allow_stale: bool) -> None:
    import sys

    stale = [path for path in stale_twins() if path in paths]
    if not stale:
        return
    table = twins()
    new = [path for path in stale if not table[path]["sha256"]]
    old = [path for path in stale if path not in new]
    parts = ([f"the Rust twins of {', '.join(old)} were checked against older Python code, so Rust would run that"] if old else [])
    parts += [f"the Rust twins of {', '.join(new)} have never been checked against their Python files"] if new else []
    message = ("; ".join(parts) + ": port the change to the Rust file rust/twins.json names, then "
               "`uv run python -m experiments.rust_bench --parity-only --record`")
    if not allow_stale:
        raise ValueError(message + " (or pass --allow-stale to run the old code anyway)")
    print(f"! {message}", file=sys.stderr)


def run_days(days: list[Day], bots: list[tuple[str, Path, dict, bool]], config: EngineConfig, threads: int = 1) -> list[list[DayResult]]:
    """`arena-rs run`: the (name, bot file, overrides, requote) participants in one market on each
    day, the days on `threads` threads; per day, each participant's DayResult (read_results)."""
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        paths = [write_day(day, scratch / f"day{k}") for k, day in enumerate(days)]
        dump = scratch / "dump.jsonl"
        out = subprocess.run([str(BINARY), "run", *map(str, paths), *_engine_args(config), *_bot_args(bots, scratch), "--dump", str(dump),
                              "--threads", str(threads)], stdout=subprocess.DEVNULL)
        if out.returncode != 0:
            raise RuntimeError(f"arena-rs run failed (exit {out.returncode}); its message is above")
        lines = dump.read_text().splitlines()
    n = len(bots)
    found = []
    for k, day in enumerate(days):
        results = read_results("\n".join(lines[k * n:(k + 1) * n]), day)
        found.append([results[name] for name, *_ in bots])
    return found


# ---------------------------------------------------------------------------- batches


def run_batch(day_paths: list[Path], specs: list[dict], tasks: list[dict], threads: int, scratch: Path,
              products: list[list[str]] | None = None, configs: list[dict] | None = None, cells: list[list] | None = None) -> list[dict]:
    """`arena-rs batch`: each task {day, config, bots: [[name, spec index], ...], blocks, fine, and
    optionally set: [[path, value], ...], overrides of its first bot's globals} on `threads` threads,
    where a task's config may be an index into `configs` and its set a `cell`, an index into `cells`,
    returning per task the first participant's {pnl, blocks, fine, products, drawdowns, fills,
    errors, breaches, races, first_error} (as arena.grid's Piece, plus each product's
    report.max_drawdown) and "others", the other participants' {pnl, products, fills, errors,
    breaches, races}, in task order. With `products` (each task's day's products, in its order) the
    results come back in binary instead (read_pieces): just the Piece's fields, with its blocks as
    arrays, for a grid too large for JSON."""
    path = scratch / "batch.json"
    batch = {"days": [str(p) for p in day_paths], "bots": specs, "tasks": tasks}
    batch |= {"configs": configs} if configs is not None else {}
    batch |= {"cells": cells} if cells is not None else {}
    with path.open("w") as file:
        json.dump(batch, file)
    command = [str(BINARY), "batch", str(path), "--threads", str(threads)]
    if products is not None:
        results = scratch / "pieces.bin"
        if subprocess.run([*command, "--binary", str(results)]).returncode != 0:
            raise RuntimeError("arena-rs batch failed; its message is above")
        return read_pieces(results, products)
    out = subprocess.run(command, stdout=subprocess.PIPE, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"arena-rs batch failed (exit {out.returncode}); its message is above")
    return [json.loads(line) for line in out.stdout.splitlines()]


def read_pieces(path: Path, products: list[list[str]]) -> list[dict]:
    """`arena-rs batch --binary`'s file (commands/batch.rs `piece_binary`): per task, in the order they
    finished, its index and the Piece's fields, the blocks as array('d'); returned in task order."""
    import array
    import struct

    out: list[dict | None] = [None] * len(products)
    with path.open("rb") as file:
        def floats() -> array.array:
            (n,) = struct.unpack("<I", file.read(4))
            values = array.array("d")
            values.frombytes(file.read(8 * n))
            return values

        for _ in products:
            k, pnl = struct.unpack("<Id", file.read(12))
            blocks, fine, pnls = floats(), floats(), floats()
            fills, errors, breaches, races, length = struct.unpack("<5I", file.read(20))
            out[k] = {"pnl": pnl, "blocks": blocks, "fine": fine, "products": dict(zip(products[k], pnls)), "fills": fills, "errors": errors,
                      "breaches": breaches, "races": races, "first_error": file.read(length).decode()}
    if any(piece is None for piece in out):
        raise RuntimeError(f"{path}: arena-rs batch left out a task")
    return out


def _engine_args(config: EngineConfig) -> list[str]:
    args = ["--match-trades", str(config.trade_matching), "--queue", str(config.queue), "--queue-power", repr(config.queue_power),
            "--fill-ratio", repr(config.fill_ratio), "--seed", str(config.seed)]
    args += [] if config.mark is Mark.MID else ["--mark", str(config.mark)]
    args += [] if config.limit_penalty is None else ["--limit-penalty", repr(float(config.limit_penalty))]
    args += ["--delay", str(config.delay)] if config.delay else []
    args += ["--fee", repr(float(config.fee))] if config.fee else []
    args += ["--fee-bps", repr(float(config.fee_bps))] if config.fee_bps else []
    args += [] if config.maker_fee is None else ["--maker-fee", repr(float(config.maker_fee))]
    args += [] if config.maker_fee_bps is None else ["--maker-fee-bps", repr(float(config.maker_fee_bps))]
    args += ["--order-fee", repr(float(config.order_fee))] if config.order_fee else []
    args += ["--print-share", repr(float(config.print_share))] if config.print_share != 1 else []
    args += ["--deplete"] if config.deplete else []
    args += [] if config.max_orders is None else ["--max-orders", str(config.max_orders)]
    args += [] if config.max_actions is None else ["--max-actions", str(config.max_actions)]
    args += [] if config.max_resting is None else ["--max-resting", str(config.max_resting)]
    return args + (["--resting"] if config.resting else [])


def _bot_args(bots: list[tuple[str, Path, dict, bool]], scratch: Path) -> list[str]:
    """--bot options for (name, bot file, overrides, requote) participants, their specs written to scratch."""
    args = []
    for j, (name, path, overrides, requote) in enumerate(bots):
        spec = scratch / f"bot{j}.json"
        spec.write_text(json.dumps(bot_spec(path, overrides, requote)))
        args += ["--bot", f"{name}={spec}"]
    return args


# ---------------------------------------------------------------------------- reading Rust's output


def _number(text: str) -> int | float:
    """A number as Rust wrote it: an int without a point, a float with one (repr's form)."""
    try:
        return int(text)
    except ValueError:
        return float(text)


def read_day(path: Path, with_books: bool = True) -> Day:
    """A day in rust/src/support/dayfile.rs's format as Python's Day: products and books in the day's own
    order, each tick's trades grouped by product in the order they appear, marks as written (an int
    stays an int). Without `with_books` every tick's books are left empty (quicker, for read_results)."""
    lines = iter(Path(path).read_text().splitlines())
    version = next(lines)
    assert version in ("arena-day 2", "arena-day 3"), f"{path}: not an arena-day 3 file"
    name = next(lines).removeprefix("name ")
    sorted_products, limits = [], {}
    for _ in range(int(next(lines).split()[1])):
        product, limit = next(lines).rsplit(" ", 1)
        sorted_products.append(product)
        limits[product] = int(limit)
    order = [sorted_products[int(k)] for k in next(lines).split()[1:]]
    limits_order, info = order, {}
    if version == "arena-day 3":
        limits_order = [sorted_products[int(k)] for k in next(lines).split()[1:]]
        for _ in range(int(next(lines).split()[1])):
            p, tick, unit = next(lines).split()
            info[sorted_products[int(p)]] = {"tick": float(tick), "unit": float(unit)}
    names = [next(lines) for _ in range(int(next(lines).split()[1]))]
    ticks = []
    for _ in range(int(next(lines).split()[1])):
        _, timestamp, nb, nt, nm = next(lines).split()
        books, trades, marks = {}, defaultdict(list), {}
        for _ in range(int(nb)):
            line = next(lines)
            if not with_books:
                continue
            f = line.split()
            product, k = sorted_products[int(f[1])], 2
            sides = []
            for _ in range(2):
                n = int(f[k])
                sides.append(tuple((int(f[k + 1 + 2 * j]), int(f[k + 2 + 2 * j])) for j in range(n)))
                k += 1 + 2 * n
            books[product] = Book(*sides)
        for _ in range(int(nt)):
            _, p, price, quantity, buyer, seller, ts = next(lines).split()
            product = sorted_products[int(p)]
            trades[product].append(MarketTrade(product, int(price), int(quantity), names[int(buyer)], names[int(seller)], int(ts)))
        for _ in range(int(nm)):
            _, p, mark = next(lines).split()
            marks[sorted_products[int(p)]] = _number(mark)
        ticks.append(Tick(int(timestamp), books, dict(trades), marks))
    return Day(name, order, {p: limits[p] for p in limits_order}, ticks, info)


SERIES = ("positions", "marks", "pnl", "best_bids", "best_asks", "wall_mids")  # per product, one value per tick


def read_dump(text: str) -> dict[str, dict]:
    """`arena-rs run --dump` (and sim's .dump files), one JSON line per participant: its DayResult's
    fields as tuples (fills as (timestamp, product, price, quantity, source, order id, counterparty)),
    by participant name."""
    out = {}
    for line in text.splitlines():
        r = json.loads(line)
        for key in ("fills", "orders", "cancels", "breaches", "races", "errors"):
            r[key] = [tuple(item) for item in r[key]]
        out[r.pop("participant")] = r
    return out


def read_results(text: str, day: Day | None = None) -> dict[str, DayResult]:
    """A dump as Python DayResults: what our engine records, except step timings and output sizes
    (a Rust bot has neither); the fields left out of the dump (--fields) are empty. The market
    trades come from `day`, the day Rust ran on as Python holds it, if given (else none)."""
    out = {}
    market_trades = [(t.timestamp, trade) for t in day.ticks for trades in t.trades.values() for trade in trades] if day is not None else []
    for name, r in read_dump(text).items():
        products = r["products"]
        result = DayResult(r["day"], list(products), dict(zip(products, r["limits"])), r["timestamps"])
        result.units = dict(zip(products, r["units"]))
        for field in SERIES:
            setattr(result, field, {p: r["series"][p][field] for p in products})
        result.market_trades = list(market_trades)
        result.orders = [(ts, OpenOrder(i, product, price, quantity, placed)) for ts, i, product, price, quantity, placed in r["orders"]]
        result.cancels = r["cancels"]
        result.fills = [Fill(ts, product, price, quantity, source, counterparty, i) for ts, product, price, quantity, source, i, counterparty in r["fills"]]
        result.errors = r["errors"]
        result.limit_breaches = r["breaches"]
        result.races = r["races"]
        out[name] = result
    return out


# ---------------------------------------------------------------------------- one backtest at a time (the experiments)

_SCRATCH: list = []  # this process's folder for exported days, made on first use
_EXPORTED: dict[int, Path] = {}  # id(day) -> its file, while the day lives
_SIM_DAYS: dict[tuple, Path] = {}
_COUNT = itertools.count()  # names this process's day files


def _scratch() -> Path:
    if not _SCRATCH:
        import atexit
        import tempfile

        folder = tempfile.TemporaryDirectory()
        atexit.register(folder.cleanup)
        _SCRATCH.append(folder)
    return Path(_SCRATCH[0].name)


def day_file(day: Day) -> Path:
    """The day for Rust (write_day: a reference to its CSVs, or exported), once per process and
    day: the entry and its file go when the day does."""
    if id(day) not in _EXPORTED:
        _EXPORTED[id(day)] = write_day(day, _scratch() / f"day{next(_COUNT)}")
        weakref.finalize(day, _forget, id(day))
    return _EXPORTED[id(day)]


def _forget(key: int) -> None:
    path = _EXPORTED.pop(key, None)
    if path is not None:
        path.unlink(missing_ok=True)


_REFERENCES: dict[tuple, Path] = {}


def prosperity_day(data: str | Path, round_num: int, day_num: int, only: list[str] | None = None) -> Path:
    """A Prosperity day for Rust that Rust reads from its CSVs itself, with nothing loaded in Python
    (prosperity.reference_to), once per process, into a day file the later runs read: for a worker
    that only backtests on it. `data` is
    a folder or an alias (p2, p3, p4); the results' days are named as the plug-in names them, r{round}d{day}."""
    key = (str(data), round_num, day_num, tuple(only) if only is not None else None)
    if key not in _REFERENCES:
        # Rust reads the CSVs once and writes the day file it reads several times faster (`arena-rs day`)
        folder = _scratch() / f"ref{next(_COUNT)}"
        folder.mkdir()
        reference = folder / "day.json"
        reference.write_text(json.dumps(prosperity.reference_to(prosperity.resolve_data_dir(str(data)), round_num, day_num, only)))
        out = subprocess.run([str(BINARY), "day", str(reference), "--out", str(folder)], stdout=subprocess.DEVNULL)
        if out.returncode != 0:
            raise RuntimeError(f"arena-rs day failed (exit {out.returncode}); its message is above")
        _REFERENCES[key] = folder / f"r{round_num}d{day_num}.day"
    return _REFERENCES[key]


def named_day(data: str | Path, name: str, only: list[str] | None = None) -> Path:
    """prosperity_day for a day named as the plug-in names it (r{round}d{day}, e.g. r1d-2)."""
    round_num, day_num = name.removeprefix("r").split("d")
    return prosperity_day(data, int(round_num), int(day_num), only)


def prosperity_days(data: str | Path, specs: list[str], only: list[str] | None = None) -> list[Path]:
    """prosperity_day for each day the specs select (ROUND or ROUND-DAY, as load_days takes them)."""
    directory = prosperity.resolve_data_dir(str(data))
    return [prosperity_day(data, r, d, only) for r, d in prosperity.parse_day_specs(specs, directory)]


def sim_day_file(spec, seed: int) -> Path:
    """arena.sim's recording of the spec and seed (no bots), written by Rust straight to a day file,
    once per process: what `day_file(arena.sim.run(spec, seed).day)` holds, without the Python run."""
    key = (json.dumps(spec_json(spec), sort_keys=True), seed)
    if key not in _SIM_DAYS:
        folder = _scratch() / f"sim{len(_SIM_DAYS)}"
        folder.mkdir()
        path = folder / "spec.json"
        path.write_text(key[0])
        out = subprocess.run([str(BINARY), "sim", str(path), "--market-seed", str(seed), "--out", str(folder)], stdout=subprocess.DEVNULL)
        if out.returncode != 0:
            raise RuntimeError(f"arena-rs sim failed (exit {out.returncode}); its message is above")
        _SIM_DAYS[key] = folder / f"sim{seed}.day"
    return _SIM_DAYS[key]


def backtest(day: Day | Path, bots: list[tuple[str, Path, dict, bool]], config: EngineConfig, fields: tuple[str, ...] | None = None,
             transform: str | None = None) -> list[DayResult]:
    """The (name, bot file, overrides, requote) participants in one market on one day (a Day, or a
    day file from day_file or sim_day_file), each one's DayResult; with `fields` only those are
    filled (e.g. ("pnl", "errors", "breaches")), which reads back much faster. A Day gives the
    results its market trades (not with a `transform`, which has Rust perturb or permute the day
    first, as arena.stress does)."""
    path = day if isinstance(day, Path) else day_file(day)
    folder = _scratch()
    dump = folder / "dump.jsonl"
    args = [str(BINARY), "run", str(path), *_engine_args(config), *_bot_args(bots, folder), "--dump", str(dump)]
    if fields is not None:
        args += ["--fields", ",".join(fields)]
    if transform is not None:  # rust/src/arena/stress.rs: "trend_up", "vol2:0.5", "permuted:SEED:BLOCK"
        args += ["--transform", transform]
    out = subprocess.run(args, stdout=subprocess.DEVNULL)
    if out.returncode != 0:
        raise RuntimeError(f"arena-rs run failed (exit {out.returncode}); its message is above")
    results = read_results(dump.read_text(), None if isinstance(day, Path) or transform is not None else day)
    return [results[name] for name, *_ in bots]


# ---------------------------------------------------------------------------- arena.sim


def spec_json(spec) -> dict:
    """An arena.sim MarketSpec as rust/src/arena/sim.rs reads it."""
    return dataclasses.asdict(spec)


def run_sim(spec, seed: int, days: int = 1, bots: list[tuple[str, Path, dict, bool]] = (), config: EngineConfig = EngineConfig(),
            replay: bool = False, read: bool | str = False, csv: Path | None = None, round_number: int = 1, threads: int = 1) -> list[dict]:
    """`arena-rs sim`: the market on seeds seed..seed+days-1 with the (name, bot file, overrides,
    requote) participants in it (resting if config.resting), on `threads` threads. Per day, in seed
    order: {"seed", "day", "trades", "bots": {name: totals}}, the totals being {"pnl", "products":
    {product: pnl}, "fills", "errors", "breaches", "races", "first_error"}; with `replay` also
    "replays" ({trade matching: {name: totals}}: the bots on the day without them, under config's
    other settings, as arena.sim run prints). `read` adds the whole of it as Python objects, which
    costs more than the run: "sim" (an arena.sim.SimDay, as arena.sim.run returns it), and with
    `replay` "recording" (the day without the bots) and "replay_results" ({trade matching: the
    bots' DayResults}); read="results" adds only "results", the bots' DayResults in the market.
    `csv` writes the Prosperity layout there (limits.json is the caller's)."""
    import tempfile

    from arena.sim import SimDay

    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        path = scratch / "spec.json"
        path.write_text(json.dumps(spec_json(spec)))
        args = [str(BINARY), "sim", str(path), "--market-seed", str(seed), "--days", str(days), "--threads", str(threads),
                *_engine_args(config), *_bot_args(list(bots), scratch)]
        if read:
            args += ["--out", str(scratch)]
        if replay:
            args.append("--replay")
        if csv is not None:
            args += ["--csv", str(csv), "--round", str(round_number)]
        out = subprocess.run(args, stdout=subprocess.PIPE, text=True)
        if out.returncode != 0:
            raise RuntimeError(f"arena-rs sim failed (exit {out.returncode}); its message is above")
        found = [json.loads(line) for line in out.stdout.splitlines()]
        for row in found:
            if "replays" in row:
                row["replays"] = {TradeMatching(mode): totals for mode, totals in row["replays"].items()}
            if not read:
                continue
            stem = scratch / f"sim{row['seed']}"
            if read == "results":
                results = read_results(stem.with_suffix(".dump").read_text(), read_day(stem.with_suffix(".day"), with_books=False))
                row["results"] = [results[name] for name, *_ in bots]
                continue
            day = read_day(stem.with_suffix(".day"))
            fundamentals = {}
            for line in stem.with_suffix(".fundamentals").read_text().splitlines():
                product, *values = line.split(" ")
                fundamentals[product] = [float(v) for v in values]
            results = read_results(stem.with_suffix(".dump").read_text(), day) if bots else {}
            row["sim"] = SimDay(day, {p: fundamentals[p] for p in day.products}, [results[name] for name, *_ in bots])
            if replay and bots:
                recording = read_day(Path(f"{stem}.recording.day"))
                row["recording"] = recording
                row["replay_results"] = {}
                for mode in TradeMatching:
                    results = read_results(Path(f"{stem}.replay.{mode}.dump").read_text(), recording)
                    row["replay_results"][mode] = [results[name] for name, *_ in bots]
        return found


# ---------------------------------------------------------------------------- arena.stats


def _matrix(rows: list, folder: Path, name: str) -> dict:
    """A matrix for `arena-rs stats` as a binary file (rust/src/commands/stats.rs `matrix`): its rows'
    floats back to back, little-endian, where JSON would hold a grid of many cells as text."""
    import array
    import sys

    flat = array.array("d")
    for row in rows:
        flat.extend(row)
    if sys.byteorder != "little":
        flat.byteswap()
    path = folder / f"{name}.bin"
    with path.open("wb") as file:
        flat.tofile(file)
    return {"file": str(path), "rows": len(rows), "cols": len(rows[0]) if rows else 0}


def _stats(request: dict):
    """`arena-rs stats` on one request; a matrix under "matrices" goes as a binary file (_matrix)."""
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        for body in request.values():
            for key in body.pop("matrices", ()):
                body[key] = _matrix(body[key], Path(folder), key)
        path = Path(folder) / "stats.json"
        path.write_text(json.dumps(request, default=list))
        out = subprocess.run([str(BINARY), "stats", str(path)], stdout=subprocess.PIPE, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"arena-rs stats failed (exit {out.returncode}); its message is above")
    return json.loads(out.stdout)


def cscv(columns: list[list[float]], max_splits: int | None = None, seed: int = 0):
    """arena.stats.cscv in rust/src/arena/stats.rs."""
    from arena import stats

    found = _stats({"cscv": {"columns": columns, "max_splits": stats.MAX_SPLITS if max_splits is None else max_splits, "seed": seed, "matrices": ["columns"]}})
    return stats.Cscv(found["pbo"], found["loss"], found["rank"], found["splits"], found["of"])


def mean_correlation(scaled: list[list[float]]) -> float | None:
    """arena.stats.mean_correlation in rust/src/arena/stats.rs."""
    return _stats({"correlation": {"scaled": scaled, "matrices": ["scaled"]}})


def snooping(d: list[list[float]], q: float, boot: int, alpha: float | None = None, seed: int = 0, studentize: str = "resample") -> tuple[dict[str, float], list[int]]:
    """arena.stats.snooping in rust/src/arena/stats.rs."""
    from arena import stats

    found = _stats({"snooping": {"d": d, "q": q, "boot": boot, "alpha": stats.TEST_ALPHA if alpha is None else alpha, "seed": seed, "studentize": studentize,
                                 "matrices": ["d"]}})
    return found["spa"], found["stepm"]


def spa(d: list[list[float]], q: float, boot: int, seed: int = 0, studentize: str = "resample") -> dict[str, float]:
    """arena.stats.spa (its own studentization and resamples) in rust/src/arena/stats.rs."""
    return _stats({"spa": {"d": d, "q": q, "boot": boot, "seed": seed, "studentize": studentize, "matrices": ["d"]}})


def stepm(d: list[list[float]], q: float, boot: int, alpha: float | None = None, seed: int = 1, studentize: str = "resample") -> list[int]:
    """arena.stats.stepm (its own studentization and resamples) in rust/src/arena/stats.rs."""
    from arena import stats

    return _stats({"stepm": {"d": d, "q": q, "boot": boot, "alpha": stats.TEST_ALPHA if alpha is None else alpha, "seed": seed, "studentize": studentize,
                             "matrices": ["d"]}})


def scales(d: list[list[float]], q: float) -> list[float]:
    """arena.stats._scales in rust/src/arena/stats.rs."""
    return _stats({"scales": {"d": d, "q": q, "matrices": ["d"]}})
