"""DAY-OF SKELETON: the Arena's format, already registered as `--format qminers`. Fill it in on the day.

Until then it is python/arena/formats/snapshots.py word for word (`diff` shows only the TODO(day) markers and
this docstring), and SKELETON = True keeps the scaffold tests on it. On the day follow ON_THE_DAY.md, "The format
swap, step by step": set SKELETON = False, then replace the two halves separately:
  - the loader (FILES, COLUMNS, DELIMITER, DEPTH, PRICE_SCALE, resolve_data_dir .. _tick): rename the fields for
    CSV snapshots; for an order-by-order log take orderlog.py's loader, for book changes drill.py's;
  - the wrapper (PROVIDED_MODULES, RESTING, ENTRY, load_bot, check_source, the bot class): a bot answering a
    state with orders stays as it is, renamed; a callback API with ids and resting orders takes drill.py's
    wrapper and RESTING = True.
Rules for the loader: integer prices in one unit (1 / PRICE_SCALE), `Day.info[p] = {"tick", "unit"}`, a limit for
every product or raise, books best first with positive volumes, the taker side kept, timestamps mapped onto
0..999,900 in steps of 100. Their SDK or module file is copied unchanged into python/arena/formats/ and named in
PROVIDED_MODULES, never retyped.

Until then (snapshots.py's layout and API):

Data layout (the names in FILES and COLUMNS):
    <data>/limits.json        {"KELP": 50, ...}
    <data>/<day>_book.csv     one row per step and product: timestamp, product, then
                              bid_price_1, bid_volume_1, ... ask_price_N, ask_volume_N (empty = no level)
    <data>/<day>_trades.csv   optional: timestamp, product, price, quantity[, buyer, seller]

Prices are decimals: the engine's are whole units of 1 / PRICE_SCALE (cents by default), so they
compare exactly; `Day.info` gives each product's tick and that unit, as the drill's does.

Bot API (`api`, python/arena/formats/snapshots_api.py): `class Strategy` with
`on_tick(self, state) -> list[api.Order | api.Cancel]`. Its state lives on the instance.
"""

from __future__ import annotations

import ast
import csv
import json
import math
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from arena.botfile import BotFile
from arena.formats import snapshots_api as api
from arena.model import Book, Cancel, Day, MarketTrade, OpenOrder, Order, Tick

PROVIDED_MODULES = {"api"}  # TODO(day): the module names their bot file imports
RESTING = False  # TODO(day): True if their orders rest until cancelled: the CLI then runs as with --resting
CREDITS = 1.0  # TODO(day): the credits a lot one unit of their quoted price is worth, if not 1 (formats/__init__.py)
ENGINE: dict = {}  # TODO(day): the engine settings their rules fix, e.g. {"queue": "prob", "fee": 1, "maker_fee": 0, "mark": "touch"} (arena.cli.format_config)
SKELETON = True  # TODO(day): False once this file is the Arena's format (the scaffold tests then skip it)
FILES = {  # TODO(day): their file names
    "limits": "limits.json", "book": "{day}_book.csv", "trades": "{day}_trades.csv"}
COLUMNS = {  # TODO(day): their column names
    "timestamp": "timestamp", "product": "product", "bid_price": "bid_price_{k}", "bid_volume": "bid_volume_{k}",
           "ask_price": "ask_price_{k}", "ask_volume": "ask_volume_{k}", "price": "price", "quantity": "quantity",
           "buyer": "buyer", "seller": "seller"}
DELIMITER = ","  # TODO(day)
DEPTH = 10  # TODO(day): book levels a side to look for (bid_price_1 .. bid_price_DEPTH)
PRICE_SCALE = 100  # TODO(day): price units a currency unit: 100 keeps cents
ENTRY = ("Strategy", "on_tick")  # TODO(day): the class the bot file defines and the method called once a step; (None, "trade") for a module-level function

# ---------------------------------------------------------------------------- data (TODO(day): the loader half)


def resolve_data_dir(arg: str) -> Path:
    path = Path(arg)
    if not (path / FILES["limits"]).is_file():
        raise ValueError(f"not a snapshots data folder (no {FILES['limits']}): {path}")
    return path


def list_days(data_dir: Path) -> list[str]:
    suffix = FILES["book"].format(day="")
    return sorted(p.name.removesuffix(suffix) for p in data_dir.glob(FILES["book"].format(day="*")))


def load_days(data_dir: Path, specs: list[str]) -> list[Day]:
    """Each spec is a day's name (the part before `_book.csv`) or `all`."""
    available = list_days(data_dir)
    selected: list[str] = []
    for spec in specs:
        names = available if spec == "all" else [spec] if spec in available else []
        if not names:
            raise ValueError(f"no day {spec!r} in {data_dir}. Available: {', '.join(available)} (or all)")
        selected += [n for n in names if n not in selected]
    limits = {product: int(limit) for product, limit in json.loads((data_dir / FILES["limits"]).read_text()).items()}
    return [_load_day(data_dir, name, limits) for name in selected]


def _load_day(data_dir: Path, name: str, limits: dict[str, int]) -> Day:
    c = COLUMNS
    books: dict[int, dict[str, Book]] = defaultdict(dict)
    path = data_dir / FILES["book"].format(day=name)
    with path.open(newline="") as file:
        for line_no, row in enumerate(csv.DictReader(file, delimiter=DELIMITER), 2):
            where = f"{path}:{line_no}"
            product = row[c["product"]]
            if product not in limits:
                raise ValueError(f"{where}: {product!r} has no limit in {FILES['limits']}")
            sides = []
            for side in ("bid", "ask"):
                levels = []
                for k in range(1, DEPTH + 1):
                    price, volume = row.get(c[f"{side}_price"].format(k=k)), row.get(c[f"{side}_volume"].format(k=k))
                    if price not in (None, "") and volume not in (None, ""):
                        levels.append((_units(price, where), abs(int(float(volume)))))
                sides.append(tuple(sorted(levels, reverse=side == "bid")))
            books[int(float(row[c["timestamp"]]))][product] = Book(*sides)
    trades: dict[int, dict[str, list[MarketTrade]]] = defaultdict(lambda: defaultdict(list))
    path = data_dir / FILES["trades"].format(day=name)
    if path.is_file():
        with path.open(newline="") as file:
            for line_no, row in enumerate(csv.DictReader(file, delimiter=DELIMITER), 2):
                t, product = int(float(row[c["timestamp"]])), row[c["product"]]
                trades[t][product].append(MarketTrade(product, _units(row[c["price"]], f"{path}:{line_no}"), int(float(row[c["quantity"]])),
                                                      row.get(c["buyer"]) or "", row.get(c["seller"]) or "", t))
    products = sorted({p for by_product in books.values() for p in by_product})
    ticks = [Tick(t, books[t], dict(trades.get(t, {})), {}) for t in sorted(books)]  # no marks: the engine values at the mid
    info = {p: {"tick": _tick(ticks, p) / PRICE_SCALE, "unit": 1 / PRICE_SCALE} for p in products}
    return Day(name, products, {p: limits[p] for p in products}, ticks, info)


def _units(text: str, where: str) -> int:
    try:
        units = Decimal(text) * PRICE_SCALE
    except InvalidOperation:
        raise ValueError(f"{where}: bad price {text!r}") from None
    whole = units.to_integral_value()
    if abs(units - whole) > Decimal("1e-6"):  # a float's error (2001 * 0.05 = 100.05000000000001) passes, as in the drill
        raise ValueError(f"{where}: price {text} is finer than 1/{PRICE_SCALE}: raise PRICE_SCALE")
    return int(whole)


def _tick(ticks: list[Tick], product: str) -> int:
    """The product's price increment in units: the gcd of the gaps between its prices (1 if none)."""
    prices = sorted({p for t in ticks if (b := t.books.get(product)) for p, _ in b.bids + b.asks})
    return math.gcd(*(b - a for a, b in zip(prices, prices[1:]))) or 1


# ---------------------------------------------------------------------------- bot


# TODO(day): the wrapper half: load_bot, check_source and the bot class below
def load_bot(path: Path, overrides: dict[str, object], strict: bool, fresh_each_tick: bool = False):
    return SnapshotBot(BotFile(path, {"api": api}, overrides, strict), fresh_each_tick)


def check_source(tree: ast.Module) -> list[str]:
    cls, method = ENTRY
    if cls is None:
        found = any(isinstance(node, ast.FunctionDef) and node.name == method for node in tree.body)
        return [] if found else [f"no top-level function {method}"]
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            if any(isinstance(item, ast.FunctionDef) and item.name == method for item in node.body):
                return []
            return [f"class {cls} has no {method} method"]
    return [f"no top-level class {cls}"]


class SnapshotBot:
    """Calls `Strategy().on_tick(state)` once a step and turns what it returns into engine orders."""

    max_state_chars = 0  # state lives on the Strategy instance, not in a string

    def __init__(self, bot_file: BotFile, fresh_each_tick: bool = False):
        self._file, self._fresh = bot_file, fresh_each_tick
        module = bot_file.load()
        self._bot = module if ENTRY[0] is None else getattr(module, ENTRY[0])()  # a module-level function's "instance" is its module
        self._limits: dict[str, int] = {}

    def begin_day(self, day: Day) -> None:
        self._limits = day.limits

    def step(self, tick: Tick, positions, own_fills, market_trades, open_orders: list[OpenOrder]) -> list[Order | Cancel]:
        if self._fresh and ENTRY[0] is None:  # a function API keeps nothing between calls but what it is handed
            self._bot = self._file.load()
        elif self._fresh:  # as the drill's: keep the instance's state, lose module globals
            module = self._file.load()
            bot = getattr(module, ENTRY[0]).__new__(getattr(module, ENTRY[0]))
            bot.__dict__ = self._bot.__dict__
            self._bot = bot
        mine: dict[str, list[api.OpenOrder]] = defaultdict(list)
        for o in open_orders:
            mine[o.product].append(api.OpenOrder(o.id, o.product, _price(o.price), o.quantity))
        state = api.State(
            tick.timestamp,
            {p: api.Book([(_price(x), v) for x, v in b.bids], [(_price(x), v) for x, v in b.asks]) for p, b in tick.books.items()},
            dict(positions),
            {p: [api.Trade(_price(t.price), t.quantity, t.buyer, t.seller) for t in ts] for p, ts in market_trades.items()},
            [api.Fill(f.order_id, f.product, _price(f.price), f.quantity) for f in own_fills],
            dict(mine),
            dict(self._limits),
        )
        returned = getattr(self._bot, ENTRY[1])(state)
        if not isinstance(returned, list):
            raise TypeError(f"{ENTRY[0]}.{ENTRY[1]} must return a list of api.Order and api.Cancel, not {type(returned).__name__}")
        out: list[Order | Cancel] = []
        for item in returned:
            if isinstance(item, api.Cancel):
                out.append(Cancel(item.order_id))
            elif isinstance(item, api.Order):
                if not isinstance(item.quantity, int) or isinstance(item.quantity, bool) or not item.quantity:
                    raise ValueError(f"{item.product}: quantity must be a non-zero int, not {item.quantity!r}")
                out.append(Order(item.product, _units(str(item.price), f"{item.product} order"), item.quantity, bool(item.ioc)))
            else:
                raise TypeError(f"{ENTRY[0]}.{ENTRY[1]} returned a {type(item).__name__}: use api.Order or api.Cancel")
        return out


def _price(units: float) -> float:
    return round(units / PRICE_SCALE, 10)


# ---------------------------------------------------------------------------- example data


def write_example(out: Path, source: str = "p3", round_number: int = 1, ticks: int = 1000) -> list[Path]:
    """Writes the first `ticks` steps of a Prosperity round's days in this layout, prices ÷ 10 (so on a
    0.1 grid), for the skeleton's tests and a first try of a copy."""
    from arena.formats import prosperity

    days = prosperity.load_days(prosperity.resolve_data_dir(source), [str(round_number)])
    out.mkdir(parents=True, exist_ok=True)
    (out / FILES["limits"]).write_text(json.dumps(days[0].limits, indent=2) + "\n")
    written = []
    for day in days:
        name = day.name.replace("-", "m")
        book_path, trades_path = out / FILES["book"].format(day=name), out / FILES["trades"].format(day=name)
        depth = max((max(len(b.bids), len(b.asks)) for t in day.ticks[:ticks] for b in t.books.values()), default=1)
        header = [COLUMNS["timestamp"], COLUMNS["product"]] + [COLUMNS[f"{s}_{f}"].format(k=k) for s in ("bid", "ask") for k in range(1, depth + 1)
                                                                 for f in ("price", "volume")]
        with book_path.open("w", newline="") as file, trades_path.open("w", newline="") as tfile:
            writer, twriter = csv.writer(file, delimiter=DELIMITER), csv.writer(tfile, delimiter=DELIMITER)
            twriter.writerow([COLUMNS[k] for k in ("timestamp", "product", "price", "quantity", "buyer", "seller")])
            writer.writerow(header)
            for tick in day.ticks[:ticks]:
                for product, book in sorted(tick.books.items()):
                    row = [tick.timestamp, product]
                    for levels in (book.bids, book.asks):
                        for k in range(depth):
                            row += [Decimal(int(levels[k][0])) / 10, levels[k][1]] if k < len(levels) else ["", ""]
                    writer.writerow(row)
                for product, trades in sorted(tick.trades.items()):
                    for t in trades:
                        twriter.writerow([tick.timestamp, product, Decimal(int(t.price)) / 10, t.quantity, t.buyer, t.seller])
        written += [book_path, trades_path]
    return written
