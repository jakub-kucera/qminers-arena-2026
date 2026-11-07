"""A drill format, deliberately unlike Prosperity's: the pattern to copy for the Arena's.

It stands in for a competition we haven't seen, so the toolchain has run through a second format
before the day. Copy this file rather than prosperity.py: it is shorter, and each place where it
had to differ from Prosperity is marked "Unlike Prosperity".

Data layout:
    <data>/instruments.json   {"price_unit": "0.01",
                               "instruments": {"ALPHA": {"tick": "0.05", "max_position": 40}, ...}}
    <data>/session_<n>.jsonl  one event per line, in time order:
        {"t": 250, "type": "level", "sym": "ALPHA", "side": "bid", "px": "100.05", "qty": 12}
                                  sets a price level; qty 0 removes it
        {"t": 250, "type": "trade", "sym": "ALPHA", "px": "100.10", "qty": 3, "aggressor": "buy"}
        {"t": 250, "type": "step"}
                                  ends a step: the book as it stands is one engine tick

Unlike Prosperity:
- **Book changes, not snapshots.** The loader keeps each book and publishes it at every step.
- **Decimal prices, a tick size per product.** The engine works in integer multiples of
  price_unit (cents here), so prices compare exactly and every product's PnL is in one unit:
  reports show cents. `Day.info` gives the bot wrapper each product's tick and the unit.
- **A callback API with calls for orders** (`drill_exchange`, provided as `exchange`):
  `Bot.on_tick(api)`, then `api.buy`, `api.sell` and `api.cancel`. Order ids are opaque strings,
  mapped to the engine's through `Order.tag`.
- **Orders rest until cancelled** (`RESTING`): the tools run as with `--resting`.
- **State lives on the Bot instance** for the whole session; there is no state string.

Make drill data: `uv run python -m experiments.format_drill <folder>` (simulated days, converted).
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from arena.botfile import BotFile
from arena.formats import drill_exchange as ex
from arena.model import Book, Cancel, Day, MarketTrade, OpenOrder, Order, Tick

PROVIDED_MODULES = {"exchange"}
RESTING = True  # orders rest until cancelled: the CLI runs this format as with --resting
TAKER = "taker"  # the trade's aggressor, shown as its buyer or seller

# ---------------------------------------------------------------------------- data


def resolve_data_dir(arg: str) -> Path:
    path = Path(arg)
    if not (path / "instruments.json").is_file():
        raise ValueError(f"not a drill data folder (no instruments.json): {path}")
    return path


def list_sessions(data_dir: Path) -> list[int]:
    return sorted(int(m[1]) for p in data_dir.glob("session_*.jsonl") if (m := re.fullmatch(r"session_(\d+)\.jsonl", p.name)))


def load_days(data_dir: Path, specs: list[str]) -> list[Day]:
    """Each spec is a session number, a range like 0..2, or `all`."""
    available = list_sessions(data_dir)
    selected: list[int] = []
    for spec in specs:
        if spec == "all":
            numbers = available
        elif match := re.fullmatch(r"(\d+)(?:\.\.(\d+))?", spec):
            low, high = int(match[1]), int(match[2] or match[1])
            numbers = [n for n in available if low <= n <= high]
        else:
            raise ValueError(f"bad session {spec!r}: use a number, a range like 0..2, or all")
        if not numbers:
            raise ValueError(f"no session {spec!r} in {data_dir}. Available: {', '.join(map(str, available))}")
        selected += [n for n in numbers if n not in selected]
    unit, instruments = _instruments(data_dir)
    return [_load_session(data_dir / f"session_{n}.jsonl", f"s{n}", unit, instruments) for n in selected]


def _instruments(data_dir: Path) -> tuple[Decimal, dict[str, tuple[Decimal, int]]]:
    raw = json.loads((data_dir / "instruments.json").read_text())
    unit = Decimal(raw["price_unit"])
    instruments = {sym: (Decimal(spec["tick"]), int(spec["max_position"])) for sym, spec in raw["instruments"].items()}
    for sym, (tick, _) in instruments.items():
        if tick % unit:
            raise ValueError(f"{sym}: tick {tick} is not a multiple of the price unit {unit}")
    return unit, instruments


def _load_session(path: Path, name: str, unit: Decimal, instruments: dict[str, tuple[Decimal, int]]) -> Day:
    levels: dict[str, dict[str, dict[int, int]]] = {sym: {"bid": {}, "ask": {}} for sym in instruments}
    trades: dict[str, list[MarketTrade]] = defaultdict(list)
    ticks: list[Tick] = []
    with path.open() as file:
        for line_no, line in enumerate(file, 1):
            where = f"{path}:{line_no}"
            event = json.loads(line)
            kind = event["type"]
            if kind == "step":
                books = {
                    sym: Book(tuple(sorted(side["bid"].items(), reverse=True)), tuple(sorted(side["ask"].items())))
                    for sym, side in levels.items()
                    if side["bid"] or side["ask"]
                }
                ticks.append(Tick(int(event["t"]), books, dict(trades), {}))  # no marks: the engine values at the mid
                trades = defaultdict(list)
                continue
            if kind not in ("level", "trade"):
                raise ValueError(f"{where}: unknown event type {kind!r}")
            sym = event["sym"]
            if sym not in instruments:
                raise ValueError(f"{where}: {sym!r} is not in instruments.json")
            price = _units(event["px"], unit, instruments[sym][0], where)
            if kind == "level":
                side = levels[sym][event["side"]]
                if event["qty"]:
                    side[price] = int(event["qty"])
                else:
                    side.pop(price, None)
            elif kind == "trade":
                buyer, seller = (TAKER, "") if event["aggressor"] == "buy" else ("", TAKER)
                trades[sym].append(MarketTrade(sym, price, int(event["qty"]), buyer, seller, int(event["t"])))
    info = {sym: {"tick": float(tick), "unit": float(unit)} for sym, (tick, _) in instruments.items()}
    return Day(name, sorted(instruments), {sym: limit for sym, (_, limit) in instruments.items()}, ticks, info)


def _units(px: str, unit: Decimal, tick: Decimal, where: str) -> int:
    try:
        price = Decimal(px)
    except InvalidOperation:
        raise ValueError(f"{where}: bad price {px!r}") from None
    if price % tick:
        raise ValueError(f"{where}: price {px} is off the {tick} tick grid")
    return int(price / unit)


# ---------------------------------------------------------------------------- bot


def load_bot(path: Path, overrides: dict[str, object], strict: bool, fresh_each_tick: bool = False):
    return DrillBot(BotFile(path, {"exchange": ex}, overrides, strict), fresh_each_tick)


def check_source(tree: ast.Module) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Bot":
            if any(isinstance(item, ast.FunctionDef) and item.name == "on_tick" for item in node.body):
                return []
            return ["class Bot has no on_tick method"]
    return ["no top-level class Bot"]


class DrillBot:
    """Calls `Bot().on_tick(api)` once a step and turns the api calls into engine orders."""

    max_state_chars = 0  # state lives on the Bot instance, not in a string

    def __init__(self, bot_file: BotFile, fresh_each_tick: bool = False):
        self._file = bot_file
        self._fresh = fresh_each_tick
        self._bot = bot_file.load().Bot()
        self._info: dict[str, dict] = {}
        self._limits: dict[str, int] = {}
        self._count = itertools.count(1)

    def begin_day(self, day: Day) -> None:
        self._info, self._limits = day.info, day.limits

    def new_id(self) -> str:
        # Opaque, as many exchanges' are: they don't sort by age.
        return hashlib.sha1(str(next(self._count)).encode()).hexdigest()[:10]

    def step(self, tick: Tick, positions, own_fills, market_trades, open_orders: list[OpenOrder]) -> list[Order | Cancel]:
        if self._fresh:
            # The official state is the instance: move it into a freshly loaded module, so only state
            # kept outside it (module globals) is lost, which is what the validator checks for.
            module = self._file.load()
            bot = module.Bot.__new__(module.Bot)
            bot.__dict__ = self._bot.__dict__
            self._bot = bot
        api = _Api(self, tick, positions, own_fills, market_trades, open_orders)
        self._bot.on_tick(api)
        return api.actions()


class _Api:
    """The `exchange.Api` a bot sees for one step."""

    def __init__(self, owner: DrillBot, tick: Tick, positions, own_fills, market_trades, open_orders):
        self.time = tick.timestamp
        self._owner, self._tick = owner, tick
        self._positions, self._own_fills, self._trades = positions, own_fills, market_trades
        self._open = list(open_orders)  # oldest first, as the engine keeps them
        self._resting = {order.tag: order for order in open_orders}
        self._new: list[Order] = []
        self._cancels: list[Cancel] = []

    def symbols(self) -> list[str]:
        return list(self._owner._limits)

    def tick_size(self, symbol: str) -> float:
        return self._meta(symbol)["tick"]

    def max_position(self, symbol: str) -> int:
        return self._owner._limits[symbol]

    def book(self, symbol: str) -> ex.Book | None:
        book = self._tick.books.get(symbol)
        if book is None or not (book.bids or book.asks):
            return None
        return ex.Book([ex.Level(self._px(symbol, p), v) for p, v in book.bids], [ex.Level(self._px(symbol, p), v) for p, v in book.asks])

    def position(self, symbol: str) -> int:
        return self._positions.get(symbol, 0)

    def trades(self, symbol: str) -> list[ex.Trade]:
        return [ex.Trade(self._px(symbol, t.price), t.quantity, "sell" if t.seller == TAKER else "buy") for t in self._trades.get(symbol, [])]

    def fills(self) -> list[ex.Fill]:
        return [ex.Fill(f.tag, f.product, self._px(f.product, f.price), f.quantity) for f in self._own_fills]

    def orders(self, symbol: str | None = None) -> list[ex.OrderView]:
        return [
            ex.OrderView(o.tag, o.product, self._px(o.product, o.price), o.quantity)
            for o in self._open
            if (symbol is None or o.product == symbol) and o.tag in self._resting
        ]

    def buy(self, symbol: str, price: float, size: int, ioc: bool = False) -> str:
        return self._order(symbol, price, size, ioc)

    def sell(self, symbol: str, price: float, size: int, ioc: bool = False) -> str:
        return self._order(symbol, price, -size if isinstance(size, int) else size, ioc)

    def cancel(self, order_id: str) -> None:
        if order_id in self._resting:
            self._cancels.append(Cancel(self._resting.pop(order_id).id))
        elif any(order.tag == order_id for order in self._new):
            self._new = [order for order in self._new if order.tag != order_id]
        else:
            raise ValueError(f"cancel {order_id!r}: no such open order")

    def actions(self) -> list[Order | Cancel]:
        return [*self._cancels, *self._new]

    def _order(self, symbol: str, price: float, signed: int, ioc: bool) -> str:
        if symbol not in self._owner._limits:
            raise ValueError(f"unknown symbol {symbol!r}")
        if not isinstance(signed, int) or isinstance(signed, bool) or signed == 0:
            raise ValueError(f"{symbol}: size must be a positive int")
        order_id = self._owner.new_id()
        self._new.append(Order(symbol, self._units(symbol, price), signed, bool(ioc), tag=order_id))
        return order_id

    def _meta(self, symbol: str) -> dict:
        return self._owner._info.get(symbol, {"tick": 0.01, "unit": 0.01})

    def _px(self, symbol: str, units: float) -> float:
        meta = self._meta(symbol)
        return round(units * meta["unit"], 10)

    def _units(self, symbol: str, price: float) -> int:
        meta = self._meta(symbol)
        units = price / meta["unit"]
        step = round(meta["tick"] / meta["unit"])
        if abs(units - round(units)) > 1e-6 or round(units) % step:
            raise ValueError(f"{symbol}: price {price} is off its {meta['tick']} tick grid")
        return round(units)


# ---------------------------------------------------------------------------- making drill data


def convert(source: Path, round_num: int, out: Path, ticks: tuple[str, ...] = ("0.05", "0.01", "0.25"), step_ms: int = 250) -> list[Path]:
    """Writes every day of `round_num` in a Prosperity-layout folder as drill sessions.

    Products are renamed ALPHA, BETA, ... in sorted order, and a price of p ticks becomes
    p × tick, the tick cycling through `ticks`. Each Prosperity tick becomes one step.
    """
    from arena.formats import prosperity

    days = prosperity.load_days(source, [str(round_num)])
    products = days[0].products
    names = {p: _name(i) for i, p in enumerate(products)}
    tick_of = {p: Decimal(ticks[i % len(ticks)]) for i, p in enumerate(products)}
    out.mkdir(parents=True, exist_ok=True)
    instruments = {names[p]: {"tick": str(tick_of[p]), "max_position": days[0].limits[p]} for p in products}
    (out / "instruments.json").write_text(json.dumps({"price_unit": "0.01", "instruments": instruments}, indent=2) + "\n")
    written = []
    for k, day in enumerate(days):
        path = out / f"session_{k}.jsonl"
        shown: dict[str, dict[str, dict[int, int]]] = {p: {"bid": {}, "ask": {}} for p in products}
        with path.open("w") as file:
            for step, tick in enumerate(day.ticks):
                t = step * step_ms
                for p in products:
                    book = tick.books.get(p, Book())
                    for side, levels in (("bid", book.bids), ("ask", book.asks)):
                        now = dict(levels)
                        for price in sorted(set(shown[p][side]) | set(now)):
                            if shown[p][side].get(price) != now.get(price):
                                file.write(_event(t, "level", names[p], price * tick_of[p], qty=now.get(price, 0), side=side))
                        shown[p][side] = now
                    for trade in tick.trades.get(p, []):
                        aggressor = "buy" if book.asks and trade.price >= book.asks[0][0] else "sell" if book.bids and trade.price <= book.bids[0][0] else "buy" if book.mid is not None and trade.price >= book.mid else "sell"
                        file.write(_event(t, "trade", names[p], trade.price * tick_of[p], qty=trade.quantity, aggressor=aggressor))
                file.write(json.dumps({"t": t, "type": "step"}) + "\n")
        written.append(path)
    return written


def _name(i: int) -> str:
    greek = ["ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON", "ZETA", "ETA", "THETA"]
    return greek[i] if i < len(greek) else f"P{i}"


def _event(t: int, kind: str, sym: str, px: Decimal, **fields) -> str:
    event = {"t": t, "type": kind, "sym": sym, **({"side": fields.pop("side")} if "side" in fields else {}), "px": str(px)}
    return json.dumps({**event, **fields}) + "\n"
