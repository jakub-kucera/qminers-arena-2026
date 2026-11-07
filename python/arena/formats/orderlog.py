"""A skeleton format: an order-by-order event log, rebuilt into a book a step. One of the API shapes
the Arena's site makes likely (the second audit, A2); snapshots.py and drill.py are the others.

If the Arena's download is a log of individual orders (an exchange's own feed: each order added,
changed, cancelled or executed, by id), copy this file to qminers.py, register it in FORMATS, and
rename the event and column names in EVENTS and COLUMNS. The bot side is the drill's callback API
(`exchange`, python/arena/formats/drill_exchange.py): replace it with theirs as drill.py's bot
wrapper shows.

Data layout:
    <data>/limits.json     {"KELP": 50, ...}
    <data>/<day>.csv       one event a row, in time order: timestamp, event, order_id, product,
                           side (buy/sell), price, quantity
        add        an order rests: order_id, product, side, price, quantity
        modify     its quantity becomes `quantity` (its price, if given, moves it to the back)
        delete     it is gone
        execute    `quantity` of it traded at its price: a market trade, the order's side the passive one
        trade      a trade with no order behind it in the log: product, price, quantity, side = the aggressor's
    Every distinct timestamp is a step: the book as it stands after the step's events is one engine tick.

Prices are decimals, whole units of 1 / PRICE_SCALE in the engine, as in snapshots.py.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from arena.formats import drill
from arena.model import Book, Day, MarketTrade, Tick

PROVIDED_MODULES = drill.PROVIDED_MODULES
RESTING = True  # an exchange that publishes orders by id keeps them until cancelled
FILES = {"limits": "limits.json", "events": "{day}.csv"}
COLUMNS = {"timestamp": "timestamp", "event": "event", "order_id": "order_id", "product": "product", "side": "side", "price": "price",
           "quantity": "quantity"}
EVENTS = {"add": "add", "modify": "modify", "delete": "delete", "execute": "execute", "trade": "trade"}
SIDES = {"buy": "buy", "sell": "sell"}
DELIMITER = ","
PRICE_SCALE = 100
TAKER = drill.TAKER

load_bot = drill.load_bot
check_source = drill.check_source


def resolve_data_dir(arg: str) -> Path:
    path = Path(arg)
    if not (path / FILES["limits"]).is_file():
        raise ValueError(f"not an order-log data folder (no {FILES['limits']}): {path}")
    return path


def list_days(data_dir: Path) -> list[str]:
    return sorted(p.stem for p in data_dir.glob(FILES["events"].format(day="*")))


def load_days(data_dir: Path, specs: list[str]) -> list[Day]:
    """Each spec is a day's name (its file's stem) or `all`."""
    available = list_days(data_dir)
    selected: list[str] = []
    for spec in specs:
        names = available if spec == "all" else [spec] if spec in available else []
        if not names:
            raise ValueError(f"no day {spec!r} in {data_dir}. Available: {', '.join(available)} (or all)")
        selected += [n for n in names if n not in selected]
    limits = {product: int(limit) for product, limit in json.loads((data_dir / FILES["limits"]).read_text()).items()}
    return [_load_day(data_dir / FILES["events"].format(day=name), name, limits) for name in selected]


def _load_day(path: Path, name: str, limits: dict[str, int]) -> Day:
    c, e = COLUMNS, EVENTS
    orders: dict[str, tuple[str, bool, int, int]] = {}  # id -> (product, buy, price, quantity)
    trades: dict[str, list[MarketTrade]] = defaultdict(list)
    ticks: list[Tick] = []
    current: int | None = None

    def publish(timestamp: int) -> None:
        levels: dict[str, tuple[dict[int, int], dict[int, int]]] = {}
        for product, buy, price, quantity in orders.values():
            side = levels.setdefault(product, ({}, {}))[0 if buy else 1]
            side[price] = side.get(price, 0) + quantity
        books = {p: Book(tuple(sorted(b.items(), reverse=True)), tuple(sorted(a.items()))) for p, (b, a) in levels.items()}
        ticks.append(Tick(timestamp, books, dict(trades), {}))  # no marks: the engine values at the mid
        trades.clear()

    with path.open(newline="") as file:
        for line_no, row in enumerate(csv.DictReader(file, delimiter=DELIMITER), 2):
            where = f"{path}:{line_no}"
            timestamp, kind = int(float(row[c["timestamp"]])), row[c["event"]]
            if current is not None and timestamp != current:
                publish(current)
            current = timestamp
            order_id = row.get(c["order_id"]) or ""
            if kind == e["add"]:
                product = row[c["product"]]
                if product not in limits:
                    raise ValueError(f"{where}: {product!r} has no limit in {FILES['limits']}")
                orders[order_id] = (product, _buy(row[c["side"]], where), _units(row[c["price"]], where), int(float(row[c["quantity"]])))
            elif kind in (e["modify"], e["delete"], e["execute"]):
                if order_id not in orders:
                    raise ValueError(f"{where}: {kind} of unknown order {order_id!r}")
                product, buy, price, quantity = orders.pop(order_id)
                if kind == e["modify"]:
                    if row.get(c["price"]):
                        price = _units(row[c["price"]], where)
                    orders[order_id] = (product, buy, price, int(float(row[c["quantity"]])))  # re-added: to the back
                elif kind == e["execute"]:
                    size = int(float(row[c["quantity"]]))
                    buyer, seller = ("", TAKER) if buy else (TAKER, "")  # the resting order is passive
                    trades[product].append(MarketTrade(product, price, size, buyer, seller, timestamp))
                    if quantity > size:
                        orders[order_id] = (product, buy, price, quantity - size)
            elif kind == e["trade"]:
                if row[c["product"]] not in limits:  # an add checks its product; a trade can name one no order did
                    raise ValueError(f"{where}: {row[c['product']]!r} has no limit in {FILES['limits']}")
                product, aggressor_buys = row[c["product"]], _buy(row[c["side"]], where)
                buyer, seller = (TAKER, "") if aggressor_buys else ("", TAKER)
                trades[product].append(MarketTrade(product, _units(row[c["price"]], where), int(float(row[c["quantity"]])), buyer, seller, timestamp))
            else:
                raise ValueError(f"{where}: unknown event {kind!r} (known: {', '.join(e.values())})")
    if current is not None:
        publish(current)
    products = sorted({p for t in ticks for p in t.books} | {p for t in ticks for p in t.trades})
    info = {p: {"tick": _tick(ticks, p) / PRICE_SCALE, "unit": 1 / PRICE_SCALE} for p in products}
    return Day(name, products, {p: limits[p] for p in products}, ticks, info)


def _buy(side: str, where: str) -> bool:
    if side not in SIDES.values():
        raise ValueError(f"{where}: side {side!r} is not {' or '.join(SIDES.values())}")
    return side == SIDES["buy"]


def _units(text: str, where: str) -> int:
    try:
        units = Decimal(text) * PRICE_SCALE
    except InvalidOperation:
        raise ValueError(f"{where}: bad price {text!r}") from None
    if units != units.to_integral_value():
        raise ValueError(f"{where}: price {text} is finer than 1/{PRICE_SCALE}: raise PRICE_SCALE")
    return int(units)


def _tick(ticks: list[Tick], product: str) -> int:
    prices = sorted({p for t in ticks if (b := t.books.get(product)) for p, _ in b.bids + b.asks})
    return math.gcd(*(b - a for a, b in zip(prices, prices[1:]))) or 1
