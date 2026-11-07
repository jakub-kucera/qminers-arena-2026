"""A probe strategy for rust/arena_sim's parity test (its twin: rust/arena_sim/src/strategies/probe.rs).

It exercises what the two real strategies don't: resting and crossing limit orders of random sizes, IOCs,
cancels of live, done and unknown orders, modifies (valid, not shrinking, of done orders), orders sent from
inside a private callback while the exchange is activating others, the potential-position cap and the breach
penalty. Its decisions come from a 64-bit LCG into which every trade, the snapshot's contents and every private
event are mixed, so any difference in what either simulator shows it changes everything after.
"""

from __future__ import annotations

from simulator.models import OrderBookSnapshot, OrderRequest, OrderStatus, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy

QMAX = 40  # orders of 1..QMAX lots
EVERY = 3  # act on about one callback in EVERY
SEED = 1

MASK = (1 << 64) - 1
STATUS_CODE = {
    OrderStatus.ACCEPTED: 0,
    OrderStatus.PARTIALLY_FILLED: 1,
    OrderStatus.FILLED: 2,
    OrderStatus.MODIFIED: 3,
    OrderStatus.CANCELED: 4,
    OrderStatus.REJECTED: 5,
}


class ProbeStrategy(BaseStrategy):
    def __init__(self) -> None:
        super().__init__()
        self._x = SEED
        self._ids: list[str] = []  # sent and not known to be done
        self._orders: dict[str, tuple[Side, int]] = {}  # id -> (side, price)
        self._sent = 0

    def _draw(self, mix: int) -> int:
        self._x = (self._x * 6364136223846793005 + 1442695040888963407 + mix) & MASK
        return self._x >> 33

    def _send(self, side: Side, price: int, quantity: int, ioc: bool) -> None:
        order_id = self.send_order(OrderRequest(side=side, price=price, quantity=quantity, order_type=OrderType.IOC if ioc else OrderType.LIMIT))
        self._sent += 1
        self._ids.append(order_id)
        self._orders[order_id] = (side, price)

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        mix = sum(t.quantity * (1 if t.book_side == 'ask' else 3) + (5 if t.taker_owner == 'user' else 0)
                  + (11 if t.maker_owner == 'user' else 0) + t.price for t in trades)
        mix += 13 * len(snapshot.bids) + 17 * len(snapshot.asks) + sum(o.quantity for o in snapshot.bids)
        mix += 19 * sum(1 for o in snapshot.asks if o.owner == 'user') + snapshot.timestamp_us + self.now_us()
        r = self._draw(mix)
        if r % EVERY:
            return
        r //= EVERY
        action = r % 8
        r //= 8
        if action < 4:
            side = Side.BUY if action % 2 == 0 else Side.SELL
            ioc = action >= 2
            quantity = 1 + (r // 5) % QMAX
            if side == Side.BUY:
                if not snapshot.bids or not snapshot.asks:
                    return
                price = snapshot.asks[0].price + r % 3 if ioc else snapshot.bids[0].price + r % 5 - 2
            else:
                if not snapshot.bids or not snapshot.asks:
                    return
                price = snapshot.bids[0].price - r % 3 if ioc else snapshot.asks[0].price - r % 5 + 2
            self._send(side, max(price, 1), quantity, ioc)
        elif action == 4 and self._ids:
            self.cancel_order(self._ids[r % len(self._ids)])
        elif action == 5 and self._ids:
            self.modify_order(self._ids[r % len(self._ids)], (r // 7) % 12)
        elif action == 6 and self._sent:
            self.cancel_order(f'u{1 + r % self._sent:09d}')  # live, done or never ours
        elif action == 7 and self._sent:
            self.modify_order(f'u{1 + r % (self._sent + 3):09d}', 1 + r % 3)

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        self._x = (self._x + 7 * STATUS_CODE[event.status] + 3 * event.filled_quantity + event.remaining_quantity
                   + (event.fill_price or 0) + event.timestamp_us + (1 if event.message else 0)) & MASK
        if event.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED) and event.order_id in self._ids:
            self._ids.remove(event.order_id)
        if event.status == OrderStatus.PARTIALLY_FILLED and event.remaining_quantity > 2 and event.filled_quantity % 2 == 0:
            self.modify_order(event.order_id, event.remaining_quantity // 2)
        if event.status == OrderStatus.REJECTED and event.message is None and event.remaining_quantity == 0:
            side, price = self._orders[event.order_id]  # the cap refused it: try one lot, sent mid-activation
            if self._x % 2:
                self._send(side, price, 1, False)
