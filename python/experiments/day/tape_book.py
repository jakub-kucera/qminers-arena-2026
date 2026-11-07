"""A price-time priority book for the Arena's tape (the starter's matching: fills at the resting order's price, an IOC
residual cancelled), shared by tape_gen's fit (replaying the real tape) and its generator (building a synthetic one).
Market orders only; no user orders, no latency."""

from __future__ import annotations

from collections import deque


class Book:
    def __init__(self) -> None:
        self.levels = ({}, {})  # side 0 bids, 1 asks: price -> deque of [oid, qty]
        self.vol = ({}, {})  # side -> price -> lots
        self.orders = {}  # oid -> (side, price, entry)
        self.best = [None, None]

    def _refresh(self, side: int) -> None:
        vol = self.vol[side]
        self.best[side] = (max(vol) if side == 0 else min(vol)) if vol else None

    def insert(self, oid, side: int, price: int, qty: int, ioc: bool, fills: list | None = None) -> int:
        """Match, then rest the residual unless IOC. Appends (maker_oid, lots, price) to fills; returns the lots traded."""
        other = 1 - side
        traded = 0
        olevels, ovol = self.levels[other], self.vol[other]
        while qty > 0:
            best = self.best[other]
            if best is None or (side == 0 and price < best) or (side == 1 and price > best):
                break
            queue = olevels[best]
            while qty > 0 and queue:
                entry = queue[0]
                if entry[1] == 0:
                    queue.popleft()
                    continue
                take = min(qty, entry[1])
                entry[1] -= take
                qty -= take
                traded += take
                ovol[best] -= take
                if fills is not None:
                    fills.append((entry[0], take, best))
                if entry[1] == 0:
                    queue.popleft()
                    del self.orders[entry[0]]
            if ovol[best] == 0:
                del ovol[best]
                del olevels[best]
                self._refresh(other)
        if qty > 0 and not ioc:
            entry = [oid, qty]
            levels, vol = self.levels[side], self.vol[side]
            if price not in levels:
                levels[price] = deque()
                vol[price] = 0
            levels[price].append(entry)
            vol[price] += qty
            self.orders[oid] = (side, price, entry)
            best = self.best[side]
            if best is None or (side == 0 and price > best) or (side == 1 and price < best):
                self.best[side] = price
        return traded

    def cancel(self, oid) -> tuple | None:
        """Remove a resting order; returns (side, price, lots) or None if it is not resting."""
        found = self.orders.pop(oid, None)
        if found is None:
            return None
        side, price, entry = found
        qty = entry[1]
        entry[1] = 0
        vol = self.vol[side]
        vol[price] -= qty
        if vol[price] == 0:
            del vol[price]
            del self.levels[side][price]
            if price == self.best[side]:
                self._refresh(side)
        return side, price, qty

    def depth(self, side: int, price: int) -> int:
        return self.vol[side].get(price, 0)
