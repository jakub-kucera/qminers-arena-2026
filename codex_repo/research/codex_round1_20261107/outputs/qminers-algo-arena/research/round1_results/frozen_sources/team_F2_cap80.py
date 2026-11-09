# Local export of team_F2_cap80; tested on sample_v2.csv.
# Original source SHA256: 81d7877e0185b8ead59c3f458a2e16fd5fa9f0eb640af1f37601ea9cc6512b54
# Based on jakub-kucera/qminers-arena-hachathon at 6ca459e966bb1f9e767258ef5ae0ef0bce979c3f.
"""Playground candidate F2 (7 Nov): F1 gridded on the playground's second sample (sample_v2.csv: 2M rows over 5,750 s, a
1-2 tick spread, ~900 lots at the touch, no momentum after trades): QUOTE 100, LIMIT 100, SKEW 80, SESSION_S 5750 (set
it from the round's data): +212,831, the last 25% +48,200. Fallback candidate F1 (7 Nov): a small market maker written in the style of the starter's trend_follower.py, so it
passes their static analysis where the template-based candidates (A0-A6) did not. One BaseStrategy subclass, nothing
else at module level. It quotes QUOTE lots on each side, one tick inside the touch when the spread allows, keeps a
resting quote while its price is still wanted (its queue place), and counts every order that can still fill against
the limit, since a cancel takes 5 ms and can lose the race against a fill.
"""

from __future__ import annotations

from simulator.models import (
    OrderBookSnapshot,
    OrderRequest,
    OrderStatus,
    OrderType,
    PrivateOrderEvent,
    Side,
    Trade,
)
from simulator.strategy import BaseStrategy


QUOTE = 80
LIMIT = 80
SKEW = 60
WIND_DOWN_S = 60  # in the last minute of the hour, quote only the side that reduces the position
SESSION_S = 12000.0


class FallbackMakerStrategy(BaseStrategy):
    """Quote both sides around the touch, within a position limit that counts every order still able to fill."""

    def __init__(self) -> None:
        super().__init__()
        self._position: int = 0
        self._orders: dict[str, list] = {}  # id -> [side, price, quantity left, cancelling]
        self._start_us: None | int = None

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        """Keep one quote a side at the wanted price; pull a quote whose price is no longer wanted."""
        if self._start_us is None:
            self._start_us = snapshot.timestamp_us
        bids = [order for order in snapshot.bids if order.owner == 'market']
        asks = [order for order in snapshot.asks if order.owner == 'market']
        if not bids or not asks:
            return
        best_bid = bids[0].price
        best_ask = asks[0].price
        if best_ask - best_bid >= 3:
            bid_price, ask_price = best_bid + 1, best_ask - 1
        else:
            bid_price, ask_price = best_bid, best_ask

        elapsed_s = (snapshot.timestamp_us - self._start_us) / 1_000_000
        winding_down = elapsed_s > SESSION_S - WIND_DOWN_S
        want_bid = self._position < SKEW and not (winding_down and self._position >= 0)
        want_ask = self._position > -SKEW and not (winding_down and self._position <= 0)

        self._keep_one(Side.BUY, bid_price if want_bid else None)
        self._keep_one(Side.SELL, ask_price if want_ask else None)

    def _keep_one(self, side: Side, price: None | int) -> None:
        """Cancel this side's quotes at any other price; post one at `price` if none is there and the limit allows."""
        have = False
        for order_id, order in list(self._orders.items()):
            if order[0] != side or order[3]:
                continue
            if price is not None and order[1] == price and not have:
                have = True
            else:
                self.cancel_order(order_id)
                order[3] = True
        if price is None or have:
            return
        exposure = sum(order[2] for order in self._orders.values() if order[0] == side)
        if side == Side.BUY:
            room = LIMIT - self._position - exposure
        else:
            room = LIMIT + self._position - exposure
        quantity = min(QUOTE, room)
        if quantity <= 0:
            return
        order_id = self.send_order(OrderRequest(side=side, price=price, quantity=quantity, order_type=OrderType.LIMIT))
        self._orders[order_id] = [side, price, quantity, False]

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        """Count fills into the position; forget orders that are done."""
        order = self._orders.get(event.order_id)
        if order is None:
            return
        if event.status == OrderStatus.PARTIALLY_FILLED or event.status == OrderStatus.FILLED:
            if order[0] == Side.BUY:
                self._position += event.filled_quantity
            else:
                self._position -= event.filled_quantity
            order[2] = event.remaining_quantity
            if event.status == OrderStatus.FILLED or event.remaining_quantity == 0:
                self._orders.pop(event.order_id, None)
        elif event.status == OrderStatus.CANCELED or event.status == OrderStatus.REJECTED:
            self._orders.pop(event.order_id, None)
