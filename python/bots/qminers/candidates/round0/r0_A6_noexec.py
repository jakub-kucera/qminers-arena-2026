import math
from simulator.models import OrderBookSnapshot, OrderRequest, OrderStatus, OrderType, PrivateOrderEvent, Side, Trade
from simulator.strategy import BaseStrategy
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

class ArenaBot(BaseStrategy):

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
