"""DAY-OF SKELETON, prepared for the Arena's format: python/bots/probe.py until its TODO(day) lines are
rewritten for their API (then run it with --format qminers). Until then it is the Prosperity probe below.

A probe bot: runs the probes in ON_THE_DAY.md one after another and prints what it sees.

Run it once in the playground (or the backtester: `--print`) and read its output:
  SEEN {...}       every tick: the probed product's book (3 levels a side), position, our open
                   orders, our fills and the market's trades since the last tick. The lines double as
                   a dataset when no historical data is given: experiments.seen_days turns a log of
                   them into the Prosperity layout.
  PROBE <name>: <finding>
                   once per probe, what it found.

The probes, in order (numbers as in ON_THE_DAY.md, "Probes"): state (7), resting orders (1) and
whether the book shows them (2), self-trade (5), fill timing and price (3), cancelling a filled
order (12), limits (4), queue position (11), own impact (17), passive fills and their markout (18),
the mark (13: it buys one lot and holds it to the end; compare the platform's PnL with the mids it
prints), prints (9), and last the three that can stop the bot or get the file refused: imports
(10), an exception (6) and the time limit (8). They sit in one block, RISKY PROBES: delete it for
a sandbox that scans the source for dynamic imports or sleeps, or set RISKY = False to skip them. Probes
14-16 compare with data outside the bot. Between probes it cancels its orders and flattens, except
the lot the mark probe holds.

Prosperity format, like python/bots/template.py: only ADAPTER (and PRODUCT, LIMIT) change on the day.
State lives in traderData. Standard library only, except what probe 10 tries to import.
"""

from __future__ import annotations

import json

from datamodel import Cancel, Order, OrderDepth, TradingState  # TODO(day): their API's imports

PRODUCT = None  # TODO(day): the product to probe; None: the first with a two-sided book
LIMIT = 50  # TODO(day): its position limit, from the docs: probe 4 sends one more than it allows
MODULE_STATE = {"calls": 0}  # probe 7: does module state survive between calls?

# (name, ticks): each probe gets its own window, then one tick to cancel and flatten. The risky
# probes are appended at the end of the PROBES section.
SCHEDULE = [
    ("state", 2), ("resting", 4), ("self_trade", 10), ("fill_timing", 4), ("cancel_filled", 3), ("limits", 3),
    ("queue", 40), ("own_impact", 22), ("markout", 300), ("mark", 1), ("prints", 1),
]


# ------------------------------------------------------------------------------ PROBES
# Each probe gets (k, view, mem, act): k counts its ticks from 0, view is what ADAPTER read,
# mem is its own dict (kept in traderData), and act collects its orders. It returns a finding when
# it has one. view has: time, prev_time (the last call's), bids, asks (best first, [price, volume]),
# position, open (our resting orders as [id, price, signed quantity]), fills (ours since the last
# tick, [price, signed quantity]) and self_trades (those trades with ourselves on both sides).


def best(view):
    return (view.bids[0][0] if view.bids else None), (view.asks[0][0] if view.asks else None)


def probe_prints(k, view, mem, act):
    print("PRINT-TEST " + "x" * 10_000 + " END")
    return "printed 10,016 characters in one call: check the log for where it shows and whether it is cut"


def probe_state(k, view, mem, act):
    if k == 0:
        MODULE_STATE["probe"] = view.time
        act.instance["probe"] = view.time
        mem["at"] = view.time
        return None
    kept = [name for name, ok in (("traderData", mem.get("at") is not None), ("module globals", MODULE_STATE.get("probe") == mem.get("at")),
                                  ("instance attributes", act.instance.get("probe") == mem.get("at"))) if ok]
    return f"state kept between calls: {', '.join(kept) or 'nothing'}"


def probe_resting(k, view, mem, act):
    bid, _ = best(view)
    if k == 0:
        if bid is None:
            return "skipped: no bid to rest below"
        mem["price"] = bid - 5
        act.buy(mem["price"], 1)
        return None
    if k == 1:
        mine = [o for o in view.open if o[1] == mem["price"]]
        mem["rests"] = bool(mine)
        level = next((v for p, v in view.bids if p == mem["price"]), 0)
        mem["shown"] = level
        return None
    if k == 2:
        if mem["rests"]:
            shown = "yes" if mem["shown"] >= 1 else "no"
            return f"orders rest between ticks: yes (a bid 5 below the best was still open a tick later); the book shows our own order: {shown}"
        return "orders rest between ticks: no (a bid 5 below the best was gone a tick later)"
    return None


def probe_self_trade(k, view, mem, act):
    bid, ask = best(view)
    if "placed" not in mem:  # wait for a spread with room inside it
        if bid is None or ask is None or ask - bid < 2:
            return "skipped: never room inside the spread for a bid and an ask at one price" if k == 8 else None
        mem["placed"] = k
        act.buy(bid + 1, 1)
        act.sell(bid + 1, 1)
        return None
    return f"a bid and an ask at one price trade with each other: {'yes' if view.self_trades else 'no'}"


def probe_fill_timing(k, view, mem, act):
    _, ask = best(view)
    if k == 0:
        if ask is None:
            return "skipped: no ask"
        mem["price"] = ask
        act.buy(ask, 1, ioc=True)
        return None
    if view.fills:
        price, qty = view.fills[0]
        return f"a buy at the best ask ({mem['price']}) fills at {price}, reported {k} call(s) later"
    if k == 3:
        return "a buy at the best ask: no fill reported within 3 calls"
    return None


def probe_cancel_filled(k, view, mem, act):
    _, ask = best(view)
    if k == 0:
        if ask is None:
            return "skipped: no ask"
        act.buy(ask, 1)
        return None
    if k == 1:
        mem["filled"] = bool(view.fills)
        mem["ids"] = [o[0] for o in view.open]
        for order_id in mem["ids"]:
            act.cancel(order_id)
        return None
    if not mem["ids"]:
        return (f"bought at the best ask (filled: {'yes' if mem['filled'] else 'no'}); it was never listed as open, so there "
                "was no id to cancel. On an API that returns ids when an order is sent, cancel it by that id instead")
    return f"bought at the best ask, then cancelled {len(mem['ids'])} order(s) still open by id: check the log for an error"


def probe_limits(k, view, mem, act):
    _, ask = best(view)
    if k == 0:
        if ask is None:
            return "skipped: no ask"
        room = LIMIT - view.position
        mem["sent"] = [(room + 1) // 2, room + 1 - (room + 1) // 2]
        mem["visible"] = sum(v for p, v in view.asks if p <= ask + 2)
        for qty in mem["sent"]:
            act.buy(ask + 2, qty, ioc=True)  # priced to fill, so a rejection shows as no fill
        return None
    if k == 1:
        bought = sum(q for _, q in view.fills if q > 0)
        if bought == 0:
            how = "both rejected (every order for the product, as in Prosperity)"
        elif bought < sum(mem["sent"]):
            how = (f"partly filled ({bought} of {sum(mem['sent'])}, with {mem['visible']} shown): one rejected, clipped to "
                   "the limit, or the book was thin")
        else:
            how = f"both filled ({bought}): no limit at {LIMIT}, or LIMIT is wrong"
        return f"two buys that together exceed the limit by one: {how}"
    return None


def probe_queue(k, view, mem, act):
    bid, _ = best(view)
    if k == 0:
        if bid is None:
            return "skipped: no bid"
        mem["price"], mem["ahead"] = bid, next((v for p, v in view.bids if p == bid), 0)
        act.buy(bid, 1)
        return None
    if view.fills:
        return f"joined the best bid at {mem['price']} behind {mem['ahead']} shown; filled after {k} ticks"
    if not view.open:
        return f"joined the best bid at {mem['price']} behind {mem['ahead']} shown; gone after {k} tick(s) without a fill (orders don't rest)"
    if k == 39:
        return f"joined the best bid at {mem['price']} behind {mem['ahead']} shown; not filled in 39 ticks"
    return None


def probe_own_impact(k, view, mem, act):
    _, ask = best(view)
    if k == 0:
        if ask is None:
            return "skipped: no ask"
        volume = next((v for p, v in view.asks if p == ask), 0)
        mem["took"] = [ask, min(volume, LIMIT - view.position)]
        act.buy(ask, mem["took"][1], ioc=True)
        return None
    if k == 21:
        return (f"took {mem['took'][1]} at {mem['took'][0]} (the whole best ask), then sent nothing for 20 ticks: "
                "compare these ticks' SEEN books with the downloaded data (the same books mean a replay)")
    return None


def probe_markout(k, view, mem, act):
    bid, ask = best(view)
    mids = mem.setdefault("mids", [])
    mids.append(None if bid is None or ask is None else (bid + ask) / 2)
    for price, qty in view.fills:
        mem.setdefault("fills", []).append([len(mids) - 1, price, qty])
    if k < 299:
        resting = {o[1]: o for o in view.open}
        for o in view.open:
            if o[1] not in (bid, ask):
                act.cancel(o[0])
        if bid is not None and bid not in resting and view.position < LIMIT:
            act.buy(bid, 1)
        if ask is not None and ask not in resting and view.position > -LIMIT:
            act.sell(ask, 1)
        return None
    out = []
    for horizon in (1, 10, 50):
        edges = [(mids[i + horizon] - price) * (1 if qty > 0 else -1) for i, price, qty in mem.get("fills", [])
                 if i + horizon < len(mids) and mids[i + horizon] is not None]
        out.append(f"{horizon}: {sum(edges) / len(edges):+.2f}" if edges else f"{horizon}: -")
    return f"kept one lot at the best bid and ask for 300 ticks: {len(mem.get('fills', []))} fills; markout per unit after " + ", ".join(out)


def probe_mark(k, view, mem, act):
    _, ask = best(view)
    if ask is not None:
        act.buy(ask, 1, ioc=True)
    return "bought one lot and holds it from here: compare the platform's PnL with the mids in the SEEN lines"


# ------------------------------------------------------------------------------ RISKY PROBES
# Last in the schedule, since each can end the run: importing numpy, pandas and scipy can take
# longer than a call is allowed (and importlib alone gets a file refused by a sandbox that scans the
# source), an exception may stop the bot, and the sleeps go up to 500 ms. For a strict sandbox,
# delete from this line to "END RISKY PROBES": the bot then runs only the probes above.
RISKY = True


def probe_imports(k, view, mem, act):
    import importlib

    found = []
    for name in ("numpy", "pandas", "scipy"):
        try:
            importlib.import_module(name)
            found.append(name)
        except Exception:
            pass
    return f"imports that load: {', '.join(found) or 'none'} (of numpy, pandas, scipy)"


def probe_exception(k, view, mem, act):
    # The raising call's traderData is lost, so the next call arrives at k == 1 again: raise only on
    # the call right after k == 0 (by the timestamp step), and report on any later one.
    if k == 0:
        mem["t0"], mem["step"] = view.time, view.time - (view.prev_time if view.prev_time is not None else view.time)
        return None
    if k == 1 and view.time <= mem["t0"] + mem["step"]:
        raise RuntimeError("probe 6: an exception on purpose")
    return (f"after an exception at {mem['t0'] + mem['step']} the bot was called again at {view.time}; the state it returned "
            "before the exception was kept, and what the raising call changed was lost")


def probe_time_limit(k, view, mem, act):
    import time

    if k < 3:
        pause = (0.05, 0.2, 0.5)[k]
        start = time.perf_counter()
        time.sleep(pause)
        mem.setdefault("slept", []).append([pause, round(time.perf_counter() - start, 3)])
        return None
    return f"slept 50, 200 and 500 ms in three calls ({mem['slept']}) and was called again: check the log for warnings or skips"


if RISKY:
    SCHEDULE += [("imports", 1), ("exception", 3), ("time_limit", 4)]
# ------------------------------------------------------------------------------ END RISKY PROBES


PROBES = {name: globals()[f"probe_{name}"] for name, _ in SCHEDULE}


class Act:
    """Orders and cancels a probe sends this tick."""

    def __init__(self, instance: dict):
        self.orders: list[tuple[int, int, bool]] = []  # (price, signed quantity, ioc)
        self.cancels: list[int] = []
        self.instance = instance  # the Trader's own attributes, for probe 7

    def buy(self, price: int, qty: int, ioc: bool = False) -> None:
        if qty > 0:
            self.orders.append((int(price), int(qty), ioc))

    def sell(self, price: int, qty: int, ioc: bool = False) -> None:
        if qty > 0:
            self.orders.append((int(price), -int(qty), ioc))

    def cancel(self, order_id: int) -> None:
        self.cancels.append(order_id)


def step(view, memory: dict, act: Act) -> list[str]:
    """One tick of the schedule: run the current probe, or tidy up after it. Returns findings."""
    tick = memory.get("tick", 0)
    memory["tick"] = tick + 1
    view.prev_time, memory["last_time"] = memory.get("last_time"), view.time
    start = 0
    for name, length in SCHEDULE:
        if tick < start + length:
            mem = memory.setdefault(name, {})
            if mem.get("done"):  # it has reported: it sits out the rest of its window
                return []
            finding = PROBES[name](tick - start, view, mem, act)
            if finding:
                mem["done"] = True
                return [f"PROBE {name}: {finding}"]
            return []
        if tick == start + length:  # the tidy-up tick after each probe
            for order in view.open:
                act.cancel(order[0])
            bid, ask = best(view)
            holding = "mark" in memory  # the mark probe holds its lot to the end
            if view.position > 0 and bid is not None and not holding:
                act.sell(bid - 2, view.position, ioc=True)
            elif view.position < 0 and ask is not None and not holding:
                act.buy(ask + 2, -view.position, ioc=True)
            return []
        start += length + 1
    return []


# ------------------------------------------------------------------------------ ADAPTER
# TODO(day): View, choose and the entry class below, for their API (python/bots/qminers/template.py's ADAPTER
# as written for the day is the model).


US = "SUBMISSION"  # how Prosperity names us in own_trades


class View:
    def __init__(self, state: TradingState, product: str):
        depth = state.order_depths[product]
        self.time = state.timestamp
        self.bids = [[p, v] for p, v in sorted(depth.buy_orders.items(), reverse=True)]
        self.asks = [[p, -v] for p, v in sorted(depth.sell_orders.items())]
        self.position = state.position.get(product, 0)
        resting = sorted(getattr(state, "open_orders", {}).get(product, []), key=lambda o: (o.timestamp, o.id))
        self.open = [[o.id, o.price, o.quantity] for o in resting]
        own = state.own_trades.get(product, [])
        self.fills = [[t.price, t.quantity if t.buyer == US else -t.quantity] for t in own]
        self.self_trades = sum(1 for t in own if t.buyer == US and t.seller == US)
        # the market's trades since the last tick, with their own timestamps: with the books, a dataset
        # (experiments.seen_days) when the round gives no data
        self.prints = [[t.price, t.quantity, t.timestamp] for t in state.market_trades.get(product, [])]
        self.prev_time = None  # set by step


def choose(state: TradingState) -> str | None:
    if PRODUCT is not None:
        return PRODUCT if PRODUCT in state.order_depths else None
    two_sided = [p for p, d in sorted(state.order_depths.items()) if d.buy_orders and d.sell_orders]
    return two_sided[0] if two_sided else None


class Trader:  # TODO(day): their entry class and method (python/arena/formats/qminers.py's ENTRY)
    def __init__(self):
        self.instance: dict = {}

    def run(self, state: TradingState):
        MODULE_STATE["calls"] += 1
        memory = json.loads(state.traderData) if state.traderData else {}
        product = memory.get("product") or choose(state)
        if product is None or product not in state.order_depths:
            return {}, 0, json.dumps(memory)
        memory["product"] = product
        view = View(state, product)
        act = Act(self.instance)
        findings = step(view, memory, act)
        seen = {"t": view.time, "p": product, "b": view.bids[:3], "a": view.asks[:3], "pos": view.position, "open": view.open, "fills": view.fills, "trades": view.prints}
        print("SEEN " + json.dumps(seen, separators=(",", ":")))
        for finding in findings:
            print(finding)
        orders: list = [Cancel(order_id) for order_id in act.cancels]
        orders += [Order(product, price, qty, ioc=ioc) for price, qty, ioc in act.orders]
        return {product: orders}, 0, json.dumps(memory)
