"""Simple trend-following example: one-lot IOC orders in the direction of the trades just seen."""

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


class TrendFollowerStrategy(BaseStrategy):
    """Trend follower: after every market event, trade one lot the way the market just traded.

    Net buying since the previous callback lifts the best ask, net selling hits
    the best bid, always with an IOC order of one lot. One order is in flight at
    a time, and the same side is not sent twice in a row; a rejected or
    cancelled order flips the side to try.
    """

    def __init__(self) -> None:
        super().__init__()
        self._order_in_flight: bool = False
        self._current_order_side: None | Side = None

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        """Send a one-lot IOC order in the direction of the net trading since the previous call."""
        if self._order_in_flight:
            return

        # Calculate how much was traded in the market
        side_sign = {'ask': 1, 'bid': -1}
        total_traded = sum(t.quantity * side_sign[t.book_side] for t in trades)

        # Pick order side and price based on direction of trading and book
        if total_traded == 0:
            return
        elif total_traded > 0:
            if not snapshot.asks or self._current_order_side == Side.BUY:
                return
            self._current_order_side, best_price = Side.BUY, snapshot.asks[0].price
        else:
            if not snapshot.bids or self._current_order_side == Side.SELL:
                return
            self._current_order_side, best_price = Side.SELL, snapshot.bids[0].price

        # Send order
        self.send_order(
            OrderRequest(
                side=self._current_order_side,
                price=best_price,
                quantity=1,
                order_type=OrderType.IOC,
            )
        )
        self._order_in_flight = True

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        """Free the in-flight slot on a fill; flip the side to try after a reject or cancel."""
        if event.status == OrderStatus.FILLED:
            self._order_in_flight = False
        elif event.status == OrderStatus.REJECTED or event.status == OrderStatus.CANCELED:
            self._current_order_side = Side.BUY if self._current_order_side == Side.SELL else Side.SELL


import math

def follow_target(book: Book, fair: float, p: dict, memory: dict, underlying: Plan | None) -> int:
    if underlying is None or underlying.fair is None or (not book.bids) or (not book.asks):
        return memory.get('held', 0)
    s, k = (underlying.fair, p['strike'])
    delta = call_delta(s, k, implied_variance(fair, s, k))
    half_spread = (book.asks[0][0] - book.bids[0][0]) / 2
    cost = half_spread / delta if delta > 1e-06 else 1000000000.0
    cost = memory['cost'] = cost if 'cost' not in memory else 0.95 * memory['cost'] + 0.05 * cost
    if cost > p['max_cost_per_delta']:
        held = 0
    else:
        held = round(underlying.target / underlying.limit * p['limit'])
    memory['held'] = held
    return held


def h_normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def call_price(s: float, k: float, w: float) -> float:
    if w <= 0:
        return max(s - k, 0.0)
    d1 = (math.log(s / k) + w / 2) / math.sqrt(w)
    return s * h_normal_cdf(d1) - k * h_normal_cdf(d1 - math.sqrt(w))


def call_delta(s: float, k: float, w: float) -> float:
    if w <= 0:
        return 1.0 if s > k else 0.0
    return h_normal_cdf((math.log(s / k) + w / 2) / math.sqrt(w))


def implied_variance(price: float, s: float, k: float) -> float:
    if price <= max(s - k, 0.0):
        return 0.0
    lo, hi = (0.0, 4.0)
    for ignored in range(50):
        mid_w = (lo + hi) / 2
        if call_price(s, k, mid_w) < price:
            lo = mid_w
        else:
            hi = mid_w
    return (lo + hi) / 2


def smile_fair(book: Book, p: dict, memory: dict, market: Market) -> float | None:
    underlying = market.books.get(p['underlying'])
    s = price(underlying, p) if underlying is not None else None
    own = price(book, p)
    if s is None or own is None:
        return memory.get('fair')
    k, t = (p['strike'], max(p['expiry'] - market.timestamp / p['day_length'], 1e-06) / 365)
    a, b, c = p['smile']
    m = math.log(k / s) / math.sqrt(t)
    w = max(a * m * m + b * m + c, 0.0) ** 2 * t
    model = call_price(s, k, w)
    memory['delta'] = call_delta(s, k, w)
    offset = memory.get('offset', own - model)
    memory['offset'] = offset + 2 / (p['smile_window'] + 1) * (own - model - offset)
    memory['fair'] = model + offset
    return memory['fair']


def basket_target(fair: float, p: dict, memory: dict, market: Market, plan: Plan) -> int:
    legs = [price(market.books[leg], p) if leg in market.books else None for leg in p['basket']]
    if None in legs:
        target = memory.get('held', 0)
    else:
        spread = fair - sum((weight * leg for weight, leg in zip(p['basket'].values(), legs)))
        target = level_target(spread, p, memory)
    plan.legs = {leg: -weight * p['hedge_ratio'] * target for leg, weight in p['basket'].items()}
    return target


def hedge_target(product: str, p: dict, market: Market) -> int:
    wanted = sum((plan.legs.get(product, 0.0) for plan in market.plans.values()))
    return max(-p['limit'], min(p['limit'], round(wanted)))


def take(book: Book, fair: float, p: dict, plan: Plan) -> None:
    buy_edge = p['take_edge'] if p['take_edge_buy'] is None else p['take_edge_buy']
    sell_edge = p['take_edge'] if p['take_edge_sell'] is None else p['take_edge_sell']
    for level in book.asks:
        if level[0] > fair - buy_edge:
            break
        level[1] -= plan.buy(level[0], h_crossable(level[1], p, plan))
    for level in book.bids:
        if level[0] < fair + sell_edge:
            break
        level[1] -= plan.sell(level[0], h_crossable(level[1], p, plan))


def h_crossable(volume: int, p: dict, plan: Plan) -> int:
    if p['cross_max'] is None:
        return volume
    return min(volume, max(p['cross_max'] - sum((abs(q) for ignored, q in plan.takes)), 0))


def clear(book: Book, fair: float, p: dict, plan: Plan) -> None:
    target, excess = (p['target'], p['cross_excess'] or 0)
    if plan.net() > target + excess:
        for level in book.bids:
            if level[0] < fair - p['clear_edge'] or plan.net() <= target + excess:
                break
            level[1] -= plan.sell(level[0], h_crossable(min(level[1], plan.net() - target - excess), p, plan))
    elif plan.net() < target - excess:
        for level in book.asks:
            if level[0] > fair + p['clear_edge'] or plan.net() >= target - excess:
                break
            level[1] -= plan.buy(level[0], h_crossable(min(level[1], target - excess - plan.net()), p, plan))


def make(book: Book, fair: float, p: dict, plan: Plan) -> None:
    best_bid = best_ask = None
    for price, volume in book.bids:
        if volume > 0:
            best_bid = price
            break
    for price, volume in book.asks:
        if volume > 0:
            best_ask = price
            break
    bid = math.floor(fair - (p['make_edge'] if p['make_edge_buy'] is None else p['make_edge_buy']))
    ask = math.ceil(fair + (p['make_edge'] if p['make_edge_sell'] is None else p['make_edge_sell']))
    if best_bid is not None and p['make_inside'] is not None:
        bid = min(bid, best_bid + p['make_inside'])
    if best_ask is not None and p['make_inside'] is not None:
        ask = max(ask, best_ask - p['make_inside'])
    shift = round(p['skew'] * (plan.net() - p['target']) / plan.limit)
    bid, ask = (bid - shift, ask - shift)
    if best_ask is not None:
        bid = min(bid, best_ask - 1)
    if best_bid is not None:
        ask = max(ask, best_bid + 1)
    if bid >= ask:
        if plan.net() >= p['target']:
            bid = ask - 1
        else:
            ask = bid + 1
    if p['join_min'] is not None and best_bid is not None and (best_ask is not None):
        bids, asks = (h_volume(book.bids, best_bid), h_volume(book.asks, best_ask))
        if bid == best_bid and (bids < p['join_min'] or asks > p['join_ratio'] * bids):
            bid -= 1
        if ask == best_ask and (asks < p['join_min'] or bids > p['join_ratio'] * asks):
            ask += 1
    size = p['make_size']
    gap = p['size_skew'] * (plan.net() - p['target']) / plan.limit
    buy = h_scaled(plan.buy_room() if size is None else size, 1 - gap)
    sell = h_scaled(plan.sell_room() if size is None else size, 1 + gap)
    if p['reduce_only']:
        buy, sell = (min(buy, max(p['target'] - plan.net(), 0)), min(sell, max(plan.net() - p['target'], 0)))
    if p['take_reserve']:
        buy, sell = (min(buy, max(plan.buy_room() - p['take_reserve'], 0)), min(sell, max(plan.sell_room() - p['take_reserve'], 0)))
    if p.get('pull') == 1:
        sell = 0
    elif p.get('pull') == -1:
        buy = 0
    levels, step = (p['make_levels'], p['make_step'])
    for k in range(levels):
        plan.buy(bid - k * step, buy // levels + (buy % levels if k == 0 else 0), quote=True)
        plan.sell(ask + k * step, sell // levels + (sell % levels if k == 0 else 0), quote=True)


def h_volume(levels: list[list[int]], price: int) -> int:
    for level_price, volume in levels:
        if level_price == price:
            return volume
    return 0


def h_scaled(size: int, factor: float) -> int:
    return int(size * max(factor, 0.0))


h_TARGET_MODES = ('basket', 'level', 'copy', 'jump_min', 'follow', 'hedge')


h_MODE_SETTINGS = {'level': ('level_weight', 'level_band', 'level_exit', 'level_guard', 'cpd_hazard'), 'cpd_hazard': ('cpd_reversion', 'cpd_sd', 'cpd_block', 'cpd_action', 'cpd_threshold'), 'copy': ('copy_hold', 'copy_edge'), 'jump_min': ('jump_hold', 'jump_edge', 'jump_seen', 'jump_share'), 'follow': ('max_cost_per_delta',), 'smile': ('expiry', 'smile_window'), 'stop_loss': ('stop_edge',), 'flatten_from': ('flatten_edge',), 'vol_guard': ()}


def param_conflicts(product: str) -> list[str]:
    own = PARAMS[product]
    p = {**DEFAULTS, **own}
    found = []
    modes = [mode for mode in h_TARGET_MODES if p[mode] not in (None, False)]
    if 'basket' in modes and 'level' in modes:
        modes.remove('level')
    if len(modes) > 1:
        found.append(str(modes[0]) + ' sets the target, so ' + joined(modes[1:]) + (' is' if len(modes) == 2 else ' are') + ' ignored')
    if modes and own.get('target', 0) != 0:
        found.append('target is ignored: ' + str(modes[0]) + ' sets the target')
    for mode, keys in h_MODE_SETTINGS.items():
        on = p[mode] is not None or (mode == 'level' and p['basket'] is not None) or (mode == 'copy' and p['copy_sizes'] is not None)
        found += [str(key) + ' does nothing without ' + str(mode) for key in keys if key in own and (not on)]
    if p['fair'] != 'fixed':
        found += [str(key) + ' does nothing unless fair is "fixed"' for key in ('fixed_fair', 'fixed_guard') if key in own]
    if p['basket'] is not None and p['level'] is None:
        found.append("basket needs level, its spread's usual value")
    return found


def place_orders(plan: Plan, resting: list[tuple[int, int, int]], max_resting: int | None=None, sent: list[tuple[int, int, bool]]=(), topup_min: int=0) -> tuple[list[int], list[tuple[int, int, bool]]]:
    wanted: dict[tuple[bool, int], int] = {}
    for price, quantity in plan.quotes:
        key = (quantity > 0, price)
        wanted[key] = wanted.get(key, 0) + quantity
    cancels = []
    for order_id, price, quantity in resting:
        key = (quantity > 0, price)
        if abs(quantity) <= abs(wanted.get(key, 0)):
            wanted[key] -= quantity
        else:
            cancels.append(order_id)
    if topup_min:
        working = {(quantity > 0, price) for order_id, price, quantity in resting if order_id not in cancels}
        for key in working:
            if key in wanted and abs(wanted[key]) < topup_min:
                wanted[key] = 0
    flying = [(price, quantity) for price, quantity, ioc in sent if not ioc]
    for price, quantity in flying:
        key = (quantity > 0, price)
        if key in wanted:
            wanted[key] -= quantity if abs(quantity) <= abs(wanted[key]) else wanted[key]
    orders = [(price, quantity, True) for price, quantity in plan.takes]
    posts = [(price, quantity, False) for (ignored, price), quantity in wanted.items() if quantity]
    if max_resting is not None:
        posts = posts[:max(0, max_resting - (len(resting) - len(cancels)) - len(flying))]
    return (cancels, orders + posts)


def on_the_way(memory: dict, resting: list[tuple]) -> tuple[list[tuple[int, int, bool]], list[tuple], list[tuple]]:
    batches = memory.get('flight', [])
    sent = [(price, quantity, ioc) for batch in batches for price, quantity, ioc in batch[0]]
    cancelled = {order_id for batch in batches for order_id in batch[1]}
    return (sent, [o for o in resting if o[0] not in cancelled], [o for o in resting if o[0] in cancelled])


def went(memory: dict, cancels: list, new: list[tuple[int, int, bool]], delay: int, rest: bool=True) -> None:
    if delay:
        batch = [[price, quantity, ioc] for price, quantity, ioc in new if ioc or rest]
        memory['flight'] = (memory.get('flight', []) + [[batch, list(cancels)]])[-delay:]


PRODUCT = 'ASSET'


LIMIT = 100


SESSION_US = 3600000000


def read_book(snapshot: OrderBookSnapshot) -> Book:
    bids: dict[int, int] = {}
    asks: dict[int, int] = {}
    for orders, levels in ((snapshot.bids, bids), (snapshot.asks, asks)):
        for order in orders:
            if order.owner == 'market':
                levels[order.price] = levels.get(order.price, 0) + order.quantity
    return Book([[price, size] for price, size in sorted(bids.items(), reverse=True)], [[price, size] for price, size in sorted(asks.items())])


def params_for(product: str) -> dict | None:
    if product not in PARAMS:
        return None
    unknown = set(PARAMS[product]) - set(DEFAULTS)
    if unknown:
        raise ValueError('unknown params for ' + str(product) + ': ' + joined(sorted(unknown)))
    return {**DEFAULTS, **PARAMS[product], 'limit': min(PARAMS[product].get('limit', LIMIT), LIMIT)}


def read_trades(trades: list[Trade]) -> dict[str, list[tuple[str, str, int, int]]]:
    return {PRODUCT: [('', '', trade.quantity, trade.price) for trade in trades if trade.taker_owner == 'market' and trade.maker_owner == 'market']}


def within_limit(new: list[tuple[int, int, bool]], position: int, limit: int, orders) -> list[tuple[int, int, bool]]:
    room = {True: limit - position, False: limit + position}
    for order in orders:
        room[order[1] > 0] -= abs(order[1])
    kept = []
    for price, quantity, ioc in new:
        size = min(abs(quantity), max(0, room[quantity > 0]))
        if size:
            room[quantity > 0] -= size
            kept.append((price, size if quantity > 0 else -size, ioc))
    return kept


class ArenaHalf:

    def __init__(self):
        super().__init__()
        self.memory: dict = {}
        self.position = 0
        self.orders: dict[str, list] = {}
        self.fills: list[tuple[float, int]] = []

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        order = self.orders.get(event.order_id)
        if order is None:
            return
        sign = 1 if order[1] > 0 else -1
        if event.status == OrderStatus.ACCEPTED:
            if order[3] == 'sent':
                order[3] = 'live'
        elif event.status == OrderStatus.PARTIALLY_FILLED or event.status == OrderStatus.FILLED:
            self.position += sign * event.filled_quantity
            self.fills.append((event.fill_price, sign * event.filled_quantity))
            order[1] = sign * event.remaining_quantity
            if event.status == OrderStatus.FILLED or event.remaining_quantity == 0:
                self.orders.pop(event.order_id, None)
        elif event.status == OrderStatus.MODIFIED:
            order[1] = sign * event.remaining_quantity
        else:
            self.orders.pop(event.order_id, None)

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        try:
            p = params_for(PRODUCT)
            if p is None:
                return
            book = read_book(snapshot)
            clock = min(999900, snapshot.timestamp_us * 1000000 // SESSION_US // 100 * 100)
            market = Market({PRODUCT: book}, read_trades(trades), {PRODUCT: self.fills}, clock)
            self.fills = []
            mine = self.memory.setdefault(PRODUCT, {})
            sent = [(o[0], o[1], o[2]) for o in self.orders.values() if o[3] == 'sent']
            resting = [(order_id, o[0], o[1]) for order_id, o in self.orders.items() if o[3] == 'live' and (not o[2])]
            cancelling = [(order_id, o[0], o[1]) for order_id, o in self.orders.items() if o[3] == 'cancelling']
            plan = trade_product(PRODUCT, book, self.position, p, mine, market, sent, cancelling)
            market.plans[PRODUCT] = plan
            cancels, new = place_orders(plan, resting, sent=sent, topup_min=TOPUP_MIN)
            for order_id in cancels:
                self.cancel_order(order_id)
                self.orders[order_id][3] = 'cancelling'
            for price, quantity, ioc in within_limit(new, self.position, p['limit'], self.orders.values()):
                side = Side.BUY if quantity > 0 else Side.SELL
                kind = OrderType.IOC if ioc else OrderType.LIMIT
                order_id = self.send_order(OrderRequest(side=side, price=int(price), quantity=abs(int(quantity)), order_type=kind))
                self.orders[order_id] = [int(price), int(quantity), ioc, 'sent']
        except Exception as error:
            if STRICT:
                raise
            last = self.memory.setdefault('errors', {})
            last[PRODUCT] = str(error)
            for order_id, order in list(self.orders.items()):
                if order[3] == 'live':
                    try:
                        self.cancel_order(order_id)
                        order[3] = 'cancelling'
                    except Exception:
                        pass
