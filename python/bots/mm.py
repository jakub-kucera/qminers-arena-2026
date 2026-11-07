"""A plain market maker: the Python twin of rust/src/bots/mm.rs, for benchmarking the Rust engine.

On every product in PARAMS: fair is the wall mid (the largest level each side, ties nearer the
touch). It takes (IOC) every level at least `take_edge` through fair, then quotes the rest of its
room one tick inside the best, but no closer to fair than `make_edge`. Resting orders are
cancelled, except with `hold`: those already at the quote's price are kept (oldest first, while
they fit its room) and only the rest is posted, so they keep their place in the queue. Keep it
equal to mm.rs: python/experiments/rust_bench.py checks that both trade the same.
"""

import math

from datamodel import Cancel, Order

PARAMS = {"KELP": {"make_edge": 1, "take_edge": 1, "hold": False}}
LIMIT = 50


def wall(levels):
    best = levels[0]
    for level in levels[1:]:
        if level[1] > best[1]:
            best = level
    return best[0]


def quote(product, params, depth, position, resting):
    bids = sorted(depth.buy_orders.items(), reverse=True)
    asks = sorted((price, -volume) for price, volume in depth.sell_orders.items())
    fair = (wall(bids) + wall(asks)) / 2
    buy_room, sell_room = LIMIT - position, LIMIT + position
    orders = []
    for price, volume in asks:
        if price > fair - params["take_edge"] or buy_room == 0:
            break
        quantity = min(volume, buy_room)
        orders.append(Order(product, price, quantity, ioc=True))
        buy_room -= quantity
    for price, volume in bids:
        if price < fair + params["take_edge"] or sell_room == 0:
            break
        quantity = min(volume, sell_room)
        orders.append(Order(product, price, -quantity, ioc=True))
        sell_room -= quantity
    bid = min(bids[0][0] + 1, math.floor(fair - params["make_edge"]))
    ask = max(asks[0][0] - 1, math.ceil(fair + params["make_edge"]))
    kept_buys = kept_sells = 0
    cancels = []
    for order in resting:
        if params.get("hold") and order.quantity > 0 and order.price == bid and kept_buys + order.quantity <= buy_room:
            kept_buys += order.quantity
        elif params.get("hold") and order.quantity < 0 and order.price == ask and kept_sells - order.quantity <= sell_room:
            kept_sells -= order.quantity
        else:
            cancels.append(Cancel(order.id))
    if buy_room > kept_buys:
        orders.append(Order(product, bid, buy_room - kept_buys))
    if sell_room > kept_sells:
        orders.append(Order(product, ask, kept_sells - sell_room))
    return cancels + orders


class Trader:
    def run(self, state):
        result = {}
        for product, params in PARAMS.items():
            resting = state.open_orders.get(product, [])
            depth = state.order_depths.get(product)
            if depth and depth.buy_orders and depth.sell_orders:
                actions = quote(product, params, depth, state.position.get(product, 0), resting)
            else:
                actions = [Cancel(order.id) for order in resting]
            if actions:
                result[product] = actions
        return result, 0, ""
