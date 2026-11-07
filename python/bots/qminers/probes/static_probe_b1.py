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

STRICT = False


DELAY = 0


ORDERS_REST = True


TOPUP_MIN = 0


DEFAULTS = {'limit': 50, 'fair': 'sized_mid', 'fixed_fair': None, 'fixed_guard': None, 'wall_size': 15, 'smoothing': 0.0, 'imbalance': 0.0, 'lin_rho3': 0.0, 'lin_momentum': 0.0, 'lin_window': 100, 'gate_move': None, 'gate_window': 20, 'take_edge': 1, 'clear_edge': 0, 'make_edge': 2, 'make_inside': 1, 'skew': 0.0, 'size_skew': 0.0, 'target': 0, 'make_size': None, 'take_edge_buy': None, 'take_edge_sell': None, 'make_edge_buy': None, 'make_edge_sell': None, 'make_levels': 1, 'make_step': 1, 'take_reserve': 0, 'join_min': None, 'join_ratio': 2.0, 'cross_max': None, 'cross_excess': None, 'level': None, 'level_weight': None, 'level_band': 20, 'level_exit': None, 'level_guard': None, 'cpd_hazard': None, 'cpd_reversion': None, 'cpd_sd': None, 'cpd_block': 50, 'cpd_action': 'level', 'cpd_threshold': 0.5, 'follow': None, 'strike': None, 'max_cost_per_delta': 20.0, 'smile': None, 'underlying': None, 'expiry': None, 'day_length': 1000000, 'smile_window': 20, 'basket': None, 'hedge_ratio': 0.0, 'hedge': False, 'jump_min': None, 'jump_hold': None, 'jump_edge': 10, 'jump_seen': 5, 'jump_share': 0.6, 'copy': None, 'copy_hold': None, 'copy_sizes': None, 'copy_warmup': 100, 'copy_edge': 5, 'stop_loss': None, 'stop_edge': None, 'flatten_from': None, 'flatten_edge': None, 'flatten_keep': None, 'flatten_widen': 0, 'reduce_only': False, 'vol_guard': None}


PARAMS: dict = {'ASSET': {'limit': 50, 'fair': 'mid', 'take_edge': 2, 'make_edge': 1, 'make_inside': 1, 'make_size': 5, 'flatten_from': 970000}}


def joined(items) -> str:
    text = ''
    for item in items:
        text = item if text == '' else text + ', ' + item
    return text


class Book:

    def __init__(self, bids: list[list[int]], asks: list[list[int]]):
        self.bids = bids
        self.asks = asks

    def copy(self) -> 'Book':
        return Book([level[:] for level in self.bids], [level[:] for level in self.asks])


class Plan:

    def __init__(self, position: int, limit: int, sent: list[tuple[int, int, bool]]=(), cancelling: list[tuple]=()):
        self.position = position
        self.limit = limit
        self.bought = sum((quantity for ignored, quantity, ignored in sent if quantity > 0))
        self.sold = -sum((quantity for ignored, quantity, ignored in sent if quantity < 0))
        self.held_buy = sum((quantity for ignored, ignored, quantity in cancelling if quantity > 0))
        self.held_sell = -sum((quantity for ignored, ignored, quantity in cancelling if quantity < 0))
        self.takes: list[tuple[int, int]] = []
        self.quotes: list[tuple[int, int]] = []
        self.fair: float | None = None
        self.target = 0
        self.legs: dict[str, float] = {}

    def net(self) -> int:
        return self.position + self.bought - self.sold

    def buy_room(self) -> int:
        return self.limit - self.position - self.bought - self.held_buy

    def sell_room(self) -> int:
        return self.limit + self.position - self.sold - self.held_sell

    def buy(self, price: int, quantity: int, quote: bool=False) -> int:
        quantity = min(quantity, self.buy_room())
        if quantity > 0:
            (self.quotes if quote else self.takes).append((price, quantity))
            self.bought += quantity
        return max(quantity, 0)

    def sell(self, price: int, quantity: int, quote: bool=False) -> int:
        quantity = min(quantity, self.sell_room())
        if quantity > 0:
            (self.quotes if quote else self.takes).append((price, -quantity))
            self.sold += quantity
        return max(quantity, 0)


class Market:

    def __init__(self, books: dict[str, Book], trades: dict[str, list[tuple[str, str, int, int]]] | None=None, fills: dict[str, list[tuple[float, int]]] | None=None, timestamp: int=0):
        self.books = books
        self.trades = trades or {}
        self.fills = fills or {}
        self.timestamp = timestamp
        self.plans: dict[str, Plan] = {}


def trade_product(product: str, book: Book, position: int, p: dict, memory: dict, market: Market | None=None, sent: list[tuple[int, int, bool]]=(), cancelling: list[tuple]=()) -> Plan:
    plan = Plan(position, p['limit'], sent, cancelling)
    market = market or Market({product: book})
    fair = smile_fair(book, p, memory, market) if p['smile'] is not None else fair_value(book, p, memory)
    if fair is None:
        return plan
    spread = book.asks[0][0] - book.bids[0][0] if book.bids and book.asks else 0
    if p['flatten_from'] is not None and market.timestamp >= p['flatten_from']:
        edge = p['flatten_edge'] if p['flatten_edge'] is not None else spread
        keep = p['flatten_keep']
        if keep is not None and abs(position) <= keep:
            widen = {k: p[k] + p['flatten_widen'] for k in ('make_edge', 'make_edge_buy', 'make_edge_sell') if p[k] is not None}
            p = {**p, **widen, 'target': position, 'take_edge': math.inf, 'take_edge_buy': None, 'take_edge_sell': None, 'clear_edge': -math.inf, 'reduce_only': False}
        else:
            target = 0 if keep is None else int(math.copysign(keep, position))
            p = {**p, 'target': target, 'take_edge': math.inf, 'take_edge_buy': None, 'take_edge_sell': None, 'clear_edge': edge, 'reduce_only': True}
    elif p['stop_loss'] is not None and loss_stop(fair, position, market.fills.get(product, []), market.timestamp, p, memory):
        edge = p['stop_edge'] if p['stop_edge'] is not None else spread
        p = {**p, 'target': 0, 'take_edge': math.inf, 'take_edge_buy': None, 'take_edge_sell': None, 'make_size': 0, 'clear_edge': edge}
    elif p['vol_guard'] is not None and regime_guard(fair, p, memory):
        pass
    elif p['basket'] is not None:
        p = {**p, 'target': basket_target(fair, p, memory, market, plan)}
    elif p['level'] is not None:
        p = {**p, 'target': level_target(fair, p, memory)}
    elif p['copy'] is not None or p['copy_sizes'] is not None:
        target = copy_target(market.trades.get(product, []), p, memory, fair, book)
        p = {**p, 'target': target, 'clear_edge': p['copy_edge'] if target else p['clear_edge']}
    elif p['jump_min'] is not None:
        target = jump_target(fair, p, memory)
        p = {**p, 'target': target, 'clear_edge': p['jump_edge'] if target else p['clear_edge']}
    elif p['follow'] is not None:
        p = {**p, 'target': follow_target(book, fair, p, memory, market.plans.get(p['follow']))}
    elif p['hedge']:
        p = {**p, 'target': hedge_target(product, p, market)}
    if p['smile'] is not None and p['hedge_ratio']:
        plan.legs = {p['underlying']: -p['hedge_ratio'] * memory.get('delta', 0.0) * position}
    plan.fair, plan.target = (fair, p['target'])
    trend, recent = moves(fair, p, memory)
    if p['imbalance'] and book.bids and book.asks:
        fair += p['imbalance'] * imbalance(book)
    if p['lin_rho3'] and book.bids and book.asks:
        fair += p['lin_rho3'] * depth_imbalance(book, 3)
    fair += p['lin_momentum'] * trend
    if p['gate_move'] is not None and abs(recent) >= p['gate_move']:
        p = {**p, 'pull': 1 if recent > 0 else -1}
    book = book.copy()
    take(book, fair, p, plan)
    clear(book, fair, p, plan)
    make(book, fair, p, plan)
    return plan


def fair_value(book: Book, p: dict, memory: dict) -> float | None:
    if p['fair'] == 'fixed':
        if p['fixed_guard'] is not None:
            market = mid(h_sized(book.bids, p['wall_size']), h_sized(book.asks, p['wall_size']))
            if market is not None and abs(market - p['fixed_fair']) > p['fixed_guard']:
                return market
        return p['fixed_fair']
    fair = price(book, p)
    previous = memory.get('fair')
    if fair is None:
        return previous
    if p['fair'] == 'hysteresis_mid':
        if fair == math.floor(fair):
            last = memory.get('hysteresis')
            fair += 0.5 if last is not None and last > fair else -0.5
        memory['hysteresis'] = fair
    if previous is not None and p['smoothing']:
        fair = p['smoothing'] * previous + (1 - p['smoothing']) * fair
    memory['fair'] = fair
    return fair


def price(book: Book, p: dict) -> float | None:
    method = p['fair']
    if method == 'fixed':
        return p['fixed_fair']
    if method in ('mid', 'hysteresis_mid'):
        fair = mid(book.bids, book.asks)
    elif method == 'wall_mid':
        fair = mid(h_wall(book.bids), h_wall(book.asks))
    elif method == 'outer_mid':
        fair = mid(book.bids[-1:], book.asks[-1:])
    elif method == 'sized_mid':
        fair = mid(h_sized(book.bids, p['wall_size']), h_sized(book.asks, p['wall_size']))
    elif method == 'weighted_mid':
        if not book.bids or not book.asks:
            return None
        share = book.bids[0][1] / (book.bids[0][1] + book.asks[0][1])
        fair = share * book.asks[0][0] + (1 - share) * book.bids[0][0]
    else:
        raise ValueError('unknown fair value method ' + str(method))
    return fair


def imbalance(book: Book) -> float:
    bid, ask = (book.bids[0][1], book.asks[0][1])
    return (bid - ask) / (bid + ask)


def depth_imbalance(book: Book, depth: int) -> float:
    bid, ask = (sum((v for ignored, v in book.bids[:depth])), sum((v for ignored, v in book.asks[:depth])))
    return (bid - ask) / (bid + ask)


def moves(fair: float, p: dict, memory: dict) -> tuple[float, float]:
    windows = (p['lin_window'] if p['lin_momentum'] else 0, p['gate_window'] if p['gate_move'] is not None else 0)
    if not any(windows):
        return (0.0, 0.0)
    trail = memory.setdefault('trail', [])
    trail.append(fair)
    trail[:] = trail[-max(windows) - 1:]
    return tuple((fair - trail[-k - 1] if k and len(trail) > k else 0.0 for k in windows))


def mid(bids: list[list[int]], asks: list[list[int]]) -> float | None:
    if not bids or not asks:
        return None
    return (bids[0][0] + asks[0][0]) / 2


def h_wall(levels: list[list[int]]) -> list[list[int]]:
    if not levels:
        return []
    largest = levels[0]
    for level in levels:
        if level[1] > largest[1]:
            largest = level
    return [largest]


def h_sized(levels: list[list[int]], size: int) -> list[list[int]]:
    for level in levels:
        if level[1] >= size:
            return [level]
    return levels[:1]


def level_target(fair: float, p: dict, memory: dict) -> int:
    gap = fair - estimate_level(fair, p, memory)
    held = memory.get('held', 0)
    exit_within = p['level_exit']
    if p['level_guard'] is not None:
        if abs(gap) > p['level_guard'] * p['level_band']:
            memory['broken'] = True
        elif abs(gap) < p['level_band']:
            memory.pop('broken', None)
    if p['cpd_hazard'] is not None and p['cpd_action'] == 'drop' and (memory.get('cp_moved', 0) > p['cpd_threshold']):
        memory['broken'] = True
    if memory.get('broken'):
        held = 0
    elif gap >= p['level_band']:
        held = -p['limit']
    elif gap <= -p['level_band']:
        held = p['limit']
    elif exit_within is not None and (held < 0 and gap <= exit_within or (held > 0 and gap >= -exit_within)):
        held = 0
    memory['held'] = held
    return held


def loss_stop(fair: float, position: int, fills: list[tuple[float, int]], timestamp: int, p: dict, memory: dict) -> bool:
    if timestamp < memory.get('stop_t', -1):
        memory.pop('stopped', None)
        memory['cash'], memory['peak'] = (-position * fair, 0.0)
    memory['stop_t'] = timestamp
    memory['cash'] = memory.get('cash', 0.0) - sum((price * quantity for price, quantity in fills))
    pnl = memory['cash'] + position * fair
    memory['peak'] = max(memory.get('peak', 0.0), pnl)
    if memory['peak'] - pnl > p['stop_loss']:
        memory['stopped'] = True
    return memory.get('stopped', False)


def regime_guard(fair: float, p: dict, memory: dict) -> bool:
    last = memory.get('vg_last')
    memory['vg_last'] = fair
    if last is None:
        return False
    change = (fair - last) ** 2
    memory['vg_fast'] = 0.95 * memory.get('vg_fast', change) + 0.05 * change
    memory['vg_slow'] = 0.999 * memory.get('vg_slow', change) + 0.001 * change
    memory['vg_n'] = memory.get('vg_n', 0) + 1
    return memory['vg_n'] >= 200 and memory['vg_fast'] > p['vol_guard'] ** 2 * max(memory['vg_slow'], 1e-09)


def estimate_level(fair: float, p: dict, memory: dict) -> float:
    memory['level_sum'] = memory.get('level_sum', 0.0) + fair
    memory['level_n'] = memory.get('level_n', 0) + 1
    if p['level'] == 'day':
        return memory['level_sum'] / memory['level_n']
    if p['cpd_hazard'] is not None:
        return changepoint_level(fair, p, memory)
    if p['level_weight'] is None:
        return p['level']
    return (p['level'] * p['level_weight'] + memory['level_sum']) / (p['level_weight'] + memory['level_n'])


def changepoint_level(fair: float, p: dict, memory: dict) -> float:
    memory['cp_sum'] = memory.get('cp_sum', 0.0) + fair
    memory['cp_n'] = memory.get('cp_n', 0) + 1
    if memory['cp_n'] < p['cpd_block']:
        return memory.get('cp_level', p['level']) if p['cpd_action'] == 'level' else p['level']
    x = memory.pop('cp_sum') / memory.pop('cp_n')
    block, theta, sd = (p['cpd_block'], p['cpd_reversion'], p['cpd_sd'])
    phi = math.exp(-theta * block)
    stationary = sd * sd / (2 * theta)
    noise = stationary * (1 - phi * phi) / (1 - phi) ** 2
    runs = memory.get('cp_runs') or [[1.0, p['level'], stationary / 4, 0]]
    last = memory.get('cp_last')
    memory['cp_last'] = x
    memory['cp_k'] = k = memory.get('cp_k', 0) + 1
    if last is not None:
        z = (x - phi * last) / (1 - phi)
        hazard = min(block / p['cpd_hazard'], 1.0)
        grown, shifted = ([], 0.0)
        for chance, mean, var, first in runs:
            spread = var + noise
            likelihood = math.exp(-(z - mean) ** 2 / (2 * spread)) / math.sqrt(spread)
            grown.append([chance * likelihood * (1 - hazard), (mean / var + z / noise) / (1 / var + 1 / noise), 1 / (1 / var + 1 / noise), first])
            shifted += chance * likelihood * hazard
        runs = [[shifted, x, stationary, k]] + grown
        total = sum((r[0] for r in runs)) or 1.0
        runs = sorted(([c / total, m, v, f] for c, m, v, f in runs if c / total > 1e-06), reverse=True)[:40]
    memory['cp_runs'] = runs
    memory['cp_moved'] = 1 - sum((c for c, ignored, ignored, first in runs if first == 0))
    memory['cp_level'] = sum((c * m for c, m, ignored, ignored in runs)) / sum((c for c, ignored, ignored, ignored in runs))
    return memory['cp_level'] if p['cpd_action'] == 'level' else p['level']


def jump_target(fair: float, p: dict, memory: dict) -> int:
    last, memory['jump_last'] = (memory.get('jump_last'), fair)
    held, age = (memory.get('held', 0), memory.get('jump_age', 0) + 1)
    if last is not None and abs(fair - last) >= p['jump_min']:
        sign = 1 if fair > last else -1
        if memory.get('jump_sign'):
            memory['jump_n'] = memory.get('jump_n', 0) + 1
            memory['jump_rev'] = memory.get('jump_rev', 0) + (sign != memory['jump_sign'])
        memory['jump_sign'] = sign
        n, reversed_ = (memory.get('jump_n', 0), memory.get('jump_rev', 0))
        held = -sign * p['limit'] if n >= p['jump_seen'] and reversed_ >= p['jump_share'] * n else 0
        age = 0
    elif p['jump_hold'] is not None and age >= p['jump_hold']:
        held = 0
    memory['held'], memory['jump_age'] = (held, age)
    return held


def copy_target(trades: list[tuple[str, str, int, int]], p: dict, memory: dict, fair: float=0.0, book: Book | None=None) -> int:
    weights = p['copy'] or {}
    signal = sum((weights.get(buyer, 0) - weights.get(seller, 0) for buyer, seller, ignored, ignored in trades))
    if p['copy_sizes'] is not None:
        signal += informed_signal(trades, fair, book, p, memory)
    held, age = (memory.get('held', 0), memory.get('copy_age', 0) + 1)
    if signal:
        held, age = (round(max(-1.0, min(1.0, signal)) * p['limit']), 0)
    elif p['copy_hold'] is not None and age >= p['copy_hold']:
        held = 0
    memory['held'], memory['copy_age'] = (held, age)
    return held


def informed_signal(trades: list[tuple[str, str, int, int]], fair: float, book: Book | None, p: dict, memory: dict) -> int:
    low, high, seen = (memory.get('cp_low'), memory.get('cp_high'), memory.get('cp_ticks', 0))
    last, bid, ask = (memory.get('cp_fair'), memory.get('cp_bid'), memory.get('cp_ask'))
    signal = 0
    if seen >= p['copy_warmup'] and None not in (bid, ask, low, high, last):
        for ignored, ignored, quantity, price in trades:
            if quantity in p['copy_sizes']:
                buying = price >= ask or (price > bid and price >= (bid + ask) / 2)
                if buying and last <= low:
                    signal += 1
                elif not buying and last >= high:
                    signal -= 1
    if last is not None:
        memory['cp_low'] = last if low is None else min(low, last)
        memory['cp_high'] = last if high is None else max(high, last)
    memory['cp_fair'], memory['cp_ticks'] = (fair, seen + 1)
    if book is not None and book.bids and book.asks:
        memory['cp_bid'], memory['cp_ask'] = (book.bids[0][0], book.asks[0][0])
    return signal
