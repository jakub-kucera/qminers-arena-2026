"""Round 1 candidate R1-G2 (7 Nov, 16:00): R1-F8 plus the latent-price signal (LAT_*). The tape's new passive orders centre on
a latent price the mid only follows (at a 1-tick spread a new bid lands at the touch 80% of the time when the mid is up
0.5 s later, 23% when it is down): from each snapshot against the previous one, a new market order at the touch or in the
LAT_LEVELS-1 levels behind it is seen as a rise in that level's market lots (the touch price unchanged), and one inside
the old touch as a better price. Per side the decayed share (time constant LAT_TAU s) of those inserts that land at or
inside the touch; the signal is the bid share minus the ask share (experiments.day.latent_price). While it is above
LAT_TH the asks are the side the price moves toward: their touch cap times LAT_PULL (trimmed, the place kept) and the bids'
times LAT_UP; mirrored below -LAT_TH. LAT_TAU 0 gives R1-F8 exactly, and so do LAT_PULL 1, LAT_BLOCK 0, LAT_TAKE 0, LAT_VETO and
LAT_JVETO 99. Chosen on round1's first 75% (IDEAS.md, "The latent price"): only LAT_VETO -0.2 (the dying-touch take only while
the signal is not against it by 0.2+), +519,955 (in 387,743, out 132,212; F8 519,027 / 386,964 / 132,063), within noise; pulling,
blocking and IOC takes on the signal all lose.
Round 1 candidate R1-F8 (7 Nov, 15:05): R1-F7 plus three additions chosen together on round1's first 75% (F7 368,589):
1. TAKE (TAKE_LOTS 60, TAKE_DEPLETE 150, TAKE_MAX off, TAKE_MS 250, TAKE_OWN 800): while the OTHER side's touch is dying (its
   market lots under TAKE_DEPLETE and under DEPL_FRAC of their peak since it became the touch), the spread is 1 tick and OUR
   side's touch holds at least TAKE_OWN lots, one limit order at the dying price takes its last lots and rests the remainder
   there, first in the queue of the level the followers form (the ladder's own orders untouched; exempt from the alone-cancel
   for TAKE_MS). Mechanism (experiments.day.spread_episodes): after a touch clears, the other side follows into the gap in
   71% of 13,949 episodes at a median 20 ms, 79% when the follower's touch holds 2,000+ lots, 35% under 100 lots.
2. ALLOC_K -0.5 (family 12's alloc maker, R1-F6b): the touch cap x (1 + ALLOC_K * imbalance) on the bid, (1 - ...) on the ask,
   the lots taken off a touch going to the level behind: fewer lots at the back of the thick side's queue.
3. JOIN_OWN 400: F7's sweep join (one tick inside on the flow's side for 50 ms after a 400+ lot sweep) only while the flow's
   side's own touch holds at least 400 lots, the same follower-depth gate.
Chosen on the first 75% with arena.qgrid --holdout 0.25 (the grids in data/arena/round1/CANDIDATES.md, "Trials"): in 386,964
(+18.4k), full 519,027, the last 25% 132,063 (+4.1k); sample_v2 checked once afterwards. Every knob at F7's value gives F7 exactly.
Round 1 candidate R1-H4 (7 Nov, hypothesis D, TAKE_DYING): R1-F7 plus a limit order that takes the last lots of the OTHER
side's dying touch (TAKE_LOTS, 0 = off; only while the spread is 1 tick, that touch holds at most TAKE_MAX market lots, our
side wants to quote and has room, and no such order went out on that side in the last TAKE_MS). A BUY at the best ask takes
what is left there and its residual rests at that price, in front of the market's bid touch and first in the queue; it is
exempt from CANCEL_ALONE for TAKE_MS, or until the market's bid joins its price (symmetric: a SELL at the best bid while the bid
touch is dying). Mechanism on round 1's tape (experiments.day.spread_episodes): after a touch clears and the spread opens to
2 ticks, the other side follows into the gap in 71% of 13,949 episodes at a median 20 ms, so the lots bought at the dying ask
are marked half a tick higher and the residual holds the front of the new bid queue; in the 29% the asks step back, a
price-improving insert (median 14 lots) fills the bid resting inside. The order's full quantity counts against the side's
room like any other order, so the limit holds. Every default reproduces R1-F7 exactly (+496,564).
Round 1 candidate R1-F7 (7 Nov, 14:25): R1-F6 with a dying touch's room one tick back (DYING_DEEP 80, DEPL_FRAC 0.12) and, for 50 ms
after a 400+ lot sweep, joining one tick inside on the flow's side (MOM_JOIN 1, MOM_BLOCK 0); chosen on round1's first 75% (368,589):
full +496,564, the last 25% +127,975, ahead of F6 in 11 of 12 segments; sample_v2 228,893 (-7,950 against F6: no momentum there).
Family 12 (7 Nov, round 1): the signal maker, the shrink maker at R1-F6's cell (every default reproduces R1-F6) plus three
signals, each a cap on one side's lots (shrunk with modify_order, so the place is kept) rather than a cancel:
MOM_SIZE, the lots kept on the side a big aggressive order (MOM_LOTS or more) hit, for MOM_MS after it (round 1's
trades run on a little; fills against 800+ lot aggressors lose 0.38 ticks a lot); IMB_TRIM / IMB_SIZE, the lots kept on a
side whose touch holds fewer than IMB_TRIM times the other touch's lots (the book imbalance says that side is about to
be run through); SIZE_SKEW, the adding side's touch and deep sizes scaled by 1 - SIZE_SKEW * |position| / LIMIT (dealers'
size skew, GLFT's inventory term as size rather than price), trimmed when SKEW_TRIM is 1. Two that add orders rather than
cut them: DYING_DEEP, the lots a side posts one tick behind while the depletion guard has emptied its touch (the level
about to become the touch, where an early order holds the front of the queue; order stacking), with that deep order
topped up; MOM_JOIN, a quote one tick inside the touch on the flow's side for MOM_MS after a big aggressive order (the
side whose price the trade pushes toward us), with MOM_BLOCK 0 so the hold does not also stop the hit side.
Family 10 (7 Nov, round 1): the room maker with a shrinking-level guard (DEPL_FRAC): F3's round-1 fills from a level left
with 0-50 market lots lost 0.05-0.23 ticks a lot; the plain depletion guard also stopped us joining new (small) levels.
Family 7 (7 Nov): the room maker, candidate F3 (the ladder maker at one level, all the limit's room quoted at the
touch) with knobs whose defaults reproduce F3 exactly (+263,282 on sample_v2.csv): SIZE_NARROW, the lots at the touch
while the spread is one tick (SHRINK_NARROW 1: resting orders are shrunk to it with modify_order, which keeps their
place); DEPLETE_LOTS / DEPLETE_SIZE, the lots kept at a touch whose market queue holds fewer than DEPLETE_LOTS lots (the
level about to be cleared); BACK_POS, beyond which the side that adds to the position quotes one tick behind the touch;
FLAT_S, an IOC flattening the position at the touch FLAT_S seconds before the end. F3's notes follow.

Playground candidate F3 (7 Nov): the ladder maker (families/ladder_maker.py) at its best cell on the playground's
second sample (sample_v2.csv, 5,750 s): one level, the touch only, and every lot of room the limit gives quoted there
(SIZE_TOUCH 200 = LIMIT + |position|, topped up behind our order once TOPUP lots of room are free), no skew beyond the
limit itself: +263,604 for the 5,750 s, the last 25% +62,039 (F2: +212,831 / +48,200), no penalty. SESSION_S 5750: set
it from the round's data. The family's notes follow.

Family 6 (7 Nov): ladder market maker. Rest orders on LEVELS price levels a side (the market's touch and the next
LEVELS-1 behind it), SIZE_TOUCH lots at the touch and SIZE_DEEP behind. An order stays where it is when the touch moves
away from it (its queue place is worth something when the price comes back), until it is more than KEEP_DEPTH-1 ticks
behind the touch; an order left alone in front of the market's touch is cancelled when CANCEL_ALONE is 1. A level gets
an order only where we have none. The limit counts every order that can still fill, each side separately (buys at most
LIMIT - position, sells at most LIMIT + position); with REBALANCE 1 the deepest order of a side is cancelled to make
room at an empty touch. Inventory: beyond SKEW lots the side that adds to the position is not quoted (SKEW_CANCEL 1:
its orders are cancelled, 0: they stay but no new ones are posted); beyond UNWIND lots an IOC at the touch sells (or
buys) back down to UNWIND_TO. In the last WIND_DOWN_S seconds only the reducing side is quoted.
"""

from __future__ import annotations

import math

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


LEVELS = 2  # price levels quoted a side, the touch first
KEEP_DEPTH = 2  # an order more than KEEP_DEPTH-1 ticks behind the touch is cancelled
SIZE_TOUCH = 65  # lots at the touch: 200 is all the room the limit gives (LIMIT + |position|)
SIZE_DEEP = 80  # lots on each level behind it
LIMIT = 100  # every order that can still fill, counted against the 100 the penalty starts at
SKEW = 100  # beyond this many lots, stop quoting the side that adds to the position (100: the limit does it)
SKEW_CANCEL = 1  # 1: cancel that side's orders beyond SKEW; 0: keep them, post none
CANCEL_ALONE = 1  # 1: cancel an order priced in front of the market's touch
REBALANCE = 0  # 1: cancel the side's deepest order to make room at an empty touch
IMB = 0.0  # quote a side only while the market's lots at its touch are at least IMB times the other touch's (0: off)
MIN_QUEUE = 0  # quote a side only while the market has at least this many lots at its touch
INSIDE_POS = 1000  # beyond this |position|, the reducing side quotes one tick inside the touch (1000: never)
INSIDE_SPREAD = 2  # ... when the spread is at least this many ticks
TOPUP = 1  # with TOPUP lots or more of room left, add another order behind ours at the touch (0: one order a level)
UNWIND = 1000  # beyond this |position| an IOC at the touch trades back to UNWIND_TO (1000: never)
UNWIND_TO = 50
WIND_DOWN_S = 60  # in the last this many seconds, quote only the side that reduces the position
SESSION_S = 1_000_000_000  # the session's length in seconds (set it from the round's data)
SIZE_NARROW = 115  # lots at the touch while the spread is one tick (200: as SIZE_TOUCH)
SHRINK_NARROW = 0  # 1: shrink resting touch orders to SIZE_NARROW (modify keeps the place) while the spread is one tick
DEPLETE_LOTS = 100  # a touch whose market queue holds fewer lots than this is about to clear (0: off)
DEPLETE_SIZE = 0  # ... our lots kept there (shrunk with modify_order; 0: cancelled)
REACT_CANCEL = 1  # 1: re-quote from the last snapshot as soon as one of our cancels lands (the queue maker's knob)
MOM_LOTS = 400  # >0: after an aggressive order of at least this many lots, post nothing new on the side it hit for MOM_MS (round 1's trades run on)
MOM_MS = 50
MOM_SIZE = -1  # >=0: during that hold, also cap the hit side's touch at this many lots (trimmed, the place kept; -1: off)
IMB_TRIM = 0.0  # >0: cap a side's touch at IMB_SIZE lots while its market lots are under IMB_TRIM times the other touch's
IMB_SIZE = 0
MOM_BLOCK = 0  # 1: during that hold, post nothing new on the hit side (0: the hold only drives MOM_SIZE and MOM_JOIN)
MOM_JOIN = 1  # 1: during that hold, while the spread is 2+ ticks, the other side (the flow's side) quotes one tick inside the touch
DYING_DEEP = 80  # >0: while a side's touch is dying (the depletion guard), its room goes to the level behind, up to this many lots
SIZE_SKEW = 0.0  # >0: the adding side's sizes times max(0, 1 - SIZE_SKEW * |position| / LIMIT)
SKEW_TRIM = 0  # 1: trim the adding side's touch orders down to that size too
DEPL_FRAC = 0.12  # >0: the depletion guard fires only on a touch that has shrunk below this share of its peak since it became the touch (a new level never fires)
BACK_POS = 1000  # beyond this |position|, the side that adds to it quotes one tick behind the touch (1000: never)
FLAT_S = 0  # this many seconds before the end, one IOC at the touch flattens the position (0: never)
ALLOC_K = -0.5 # touch cap x (1 + ALLOC_K * imbalance) on the bid, (1 - ALLOC_K * imbalance) on the ask; the rest behind (0: off)
ALLOC_UP = 1  # 1: the factor may also raise a touch cap (up to ALLOC_HI times); 0: only shrink it
ALLOC_HI = 2.0
ALLOC_DEEP = 1  # 1: lots taken off a touch go to the level behind; 0: they are not quoted
TAKE_LOTS = 60 # >0: while the other side's touch is dying (the depletion guard) at a 1-tick spread, a limit order at its price takes its last lots and rests the rest there, first in the queue (0: off)
TAKE_MAX = 1000 # ... only while that touch holds at most this many market lots
ANY_CLEAR = 0  # 1: the sweep hold (MOM_MS) also starts whenever a side's touch price moves away (the market's best ask rises or best bid falls, by a sweep or by cancels), so the joins fire after any clear
JOIN_LOTS = 0  # >0: the sweep join as an EXTRA order (the ladder's anchors untouched, so the deep order keeps its place): for MOM_MS after a MOM_LOTS+ sweep, while the spread is 2+ ticks, a limit order of this many lots one tick inside on the flow's side, exempt from CANCEL_ALONE for JOIN_MS (use it with MOM_JOIN 0)
JOIN_MS = 200  # ... at most one such order a side per this many ms, and its exemption from the alone-cancel
JOIN_OWN = 400 # MOM_JOIN's inside quote only while its own side's touch (the follower) holds at least this many market lots (0: always)
TAKE_OWN = 800 # ... only while OUR side's touch (the follower) holds at least this many market lots (the follower's depth predicts whether it follows: 35% under 100 lots, 79% above 2,000)
TAKE_RATIO = 0.0  # ... and at least this many times the market lots at the dying side's next level (the level that becomes its touch)
TAKE_DEPLETE = 150 # >0: the take's own depletion threshold in place of DEPLETE_LOTS (lots under it and under DEPL_FRAC times the peak)
LAT_TAU = 0.1  # >0: the latent-price signal's time constant in seconds (0: off, R1-F8)
LAT_LEVELS = 4  # inserts seen at the touch and this many levels in all (the touch included)
LAT_TH = 0.4  # |signal| above this moves sizes
LAT_PULL = 1.0  # the touch cap of the side the price moves toward, times this
LAT_UP = 1.0  # the other side's touch cap, times this
LAT_TAKE = 0.0  # >0: while |signal| is above this at a 1-tick spread, an IOC at the far touch for LAT_TAKE_LOTS lots the signal's way (0: off)
LAT_TAKE_LOTS = 20
LAT_TAKE_MS = 100  # ... at most one a side per this many ms
LAT_TAKE_POS = 100  # ... only while the position the signal's way is below this
LAT_BLOCK = 0  # 1: while |signal| is above LAT_TH, post nothing new on the side the price moves toward (its resting orders kept)
LAT_VETO = -0.2  # the dying-touch take (TAKE_LOTS) only while the signal is not against it by more than this: a buy needs signal >= -LAT_VETO, a sell <= LAT_VETO (99: off; negative: the signal must agree)
LAT_JVETO = 99.0  # the same veto on MOM_JOIN's inside quote: a bid inside needs signal >= -LAT_JVETO, an ask inside <= LAT_JVETO (99: off)
LAT_DEEP = 1  # 1: the lots pulled off the touch go to the level behind (like ALLOC_DEEP)
TAKE_MS = 250 # ... at most one such order a side per this many ms; for that long the order is exempt from CANCEL_ALONE (or until the market joins its price)


class LadderMakerStrategy(BaseStrategy):
    """Rest a ladder of orders on each side; keep queue places; a limit that counts every order able to fill."""

    def __init__(self) -> None:
        super().__init__()
        self._position: int = 0
        self._orders: dict[str, list] = {}  # id -> [side, price, quantity left, cancelling, is_ioc, modify target, take order: exempt from CANCEL_ALONE until]
        self._start_us: None | int = None
        self._snap: None | OrderBookSnapshot = None
        self._hold_until: dict = {'bid': 0, 'ask': 0}  # book side -> the time until which nothing new is posted there
        self._peak: dict = {}  # side -> [touch price, the market lots there at their most since it became the touch]
        self._ioc_pending: bool = False
        self._flattened: bool = False
        self._take_block: dict = {'B': 0, 'A': 0}  # our order's side -> the time until which no take goes out there
        self._join_block: dict = {'B': 0, 'A': 0}  # the same for the extra join orders
        self._prev_touch: None | tuple = None  # the previous snapshot's market touches, for ANY_CLEAR
        self._takes: int = 0  # take orders sent
        self._now_us: int = 0  # the current snapshot's time
        self._lat_prev: dict = {'B': None, 'A': None}  # side -> (touch price, market lots by level)
        self._lat_s: dict = {'B': 0.0, 'A': 0.0}  # decayed sums of the at-touch indicator
        self._lat_w: dict = {'B': 0.0, 'A': 0.0}  # decayed counts of inserts seen
        self._lat_t: int = 0
        self.lat_signal: float = 0.0
        self._lat_take_block: dict = {'B': 0, 'A': 0}

    def on_order_book_change(self, snapshot: OrderBookSnapshot, trades: list[Trade]) -> None:
        """Keep the ladder on each side."""
        self._snap = snapshot
        self._now_us = snapshot.timestamp_us
        if self._start_us is None:
            self._start_us = snapshot.timestamp_us
        best_bid = None
        bid_lots = 0
        bid_lots2 = 0
        bid_price2 = None
        for order in snapshot.bids:
            if order.owner == 'market':
                if best_bid is None:
                    best_bid = order.price
                elif order.price != best_bid:
                    if bid_price2 is None:
                        bid_price2 = order.price
                    elif order.price != bid_price2:
                        break
                    bid_lots2 += order.quantity
                    continue
                bid_lots += order.quantity
        best_ask = None
        ask_lots = 0
        ask_lots2 = 0
        ask_price2 = None
        for order in snapshot.asks:
            if order.owner == 'market':
                if best_ask is None:
                    best_ask = order.price
                elif order.price != best_ask:
                    if ask_price2 is None:
                        ask_price2 = order.price
                    elif order.price != ask_price2:
                        break
                    ask_lots2 += order.quantity
                    continue
                ask_lots += order.quantity
        if best_bid is None or best_ask is None:
            return
        if LAT_TAU > 0:
            self._latent(snapshot, best_bid, best_ask)
        bid_ok = bid_lots >= MIN_QUEUE and bid_lots >= IMB * ask_lots
        ask_ok = ask_lots >= MIN_QUEUE and ask_lots >= IMB * bid_lots

        elapsed_s = (snapshot.timestamp_us - self._start_us) / 1_000_000
        winding_down = elapsed_s > SESSION_S - WIND_DOWN_S
        position = self._position
        if FLAT_S and not self._flattened and not self._ioc_pending and elapsed_s > SESSION_S - FLAT_S:
            self._flattened = True
            if position > 0:
                self._send(Side.SELL, best_bid, position, True)
            elif position < 0:
                self._send(Side.BUY, best_ask, -position, True)
        if not self._ioc_pending and position > UNWIND:
            self._send(Side.SELL, best_bid, position - UNWIND_TO, True)
        elif not self._ioc_pending and position < -UNWIND:
            self._send(Side.BUY, best_ask, -position - UNWIND_TO, True)
        if MOM_LOTS > 0 and trades:
            swept: dict = {}
            for trade in trades:
                if trade.taker_owner == 'market':
                    key = (trade.taker_order_id, trade.book_side)
                    swept[key] = swept.get(key, 0) + trade.quantity
            for (taker, book_side), lots in swept.items():
                if lots >= MOM_LOTS:
                    self._hold_until[book_side] = snapshot.timestamp_us + MOM_MS * 1000
        if ANY_CLEAR:
            prev = self._prev_touch
            if prev is not None:
                if best_ask > prev[1]:
                    self._hold_until['ask'] = snapshot.timestamp_us + MOM_MS * 1000
                if best_bid < prev[0]:
                    self._hold_until['bid'] = snapshot.timestamp_us + MOM_MS * 1000
            self._prev_touch = (best_bid, best_ask)
        hold_bid = snapshot.timestamp_us < self._hold_until['bid']
        hold_ask = snapshot.timestamp_us < self._hold_until['ask']
        lat_block_bid = LAT_TAU > 0 and LAT_BLOCK and self.lat_signal < -LAT_TH
        lat_block_ask = LAT_TAU > 0 and LAT_BLOCK and self.lat_signal > LAT_TH
        want_bid = not lat_block_bid and position < SKEW and not (winding_down and position >= 0) and bid_ok and not (hold_bid and MOM_BLOCK)
        want_ask = not lat_block_ask and position > -SKEW and not (winding_down and position <= 0) and ask_ok and not (hold_ask and MOM_BLOCK)
        cancel_bid = (winding_down and position >= 0) or (SKEW_CANCEL and position >= SKEW) or not bid_ok
        cancel_ask = (winding_down and position <= 0) or (SKEW_CANCEL and position <= -SKEW) or not ask_ok
        spread = best_ask - best_bid
        bid_anchor = best_bid + 1 if position <= -INSIDE_POS and spread >= INSIDE_SPREAD else best_bid
        ask_anchor = best_ask - 1 if position >= INSIDE_POS and spread >= INSIDE_SPREAD else best_ask
        jveto = LAT_TAU > 0 and LAT_JVETO < 99
        if MOM_JOIN and spread >= 2 and hold_ask and not hold_bid and bid_lots >= JOIN_OWN and not (jveto and self.lat_signal < -LAT_JVETO):
            bid_anchor = best_bid + 1
        if MOM_JOIN and spread >= 2 and hold_bid and not hold_ask and ask_lots >= JOIN_OWN and not (jveto and self.lat_signal > LAT_JVETO):
            ask_anchor = best_ask - 1
        if position >= BACK_POS:
            bid_anchor = best_bid - 1
        if position <= -BACK_POS:
            ask_anchor = best_ask + 1
        bid_cap = SIZE_TOUCH if spread >= 2 else SIZE_NARROW
        ask_cap = bid_cap
        bid_trim = SHRINK_NARROW and spread < 2
        ask_trim = bid_trim
        bid_dying = bid_lots < DEPLETE_LOTS
        ask_dying = ask_lots < DEPLETE_LOTS
        if DEPL_FRAC > 0:
            for key, price, lots in (('B', best_bid, bid_lots), ('A', best_ask, ask_lots)):
                peak = self._peak.get(key)
                if peak is None or peak[0] != price:
                    self._peak[key] = [price, lots]
                elif lots > peak[1]:
                    peak[1] = lots
            bid_dying = bid_dying and bid_lots < DEPL_FRAC * self._peak['B'][1]
            ask_dying = ask_dying and ask_lots < DEPL_FRAC * self._peak['A'][1]
        if bid_dying:
            bid_cap = min(bid_cap, DEPLETE_SIZE)
            bid_trim = True
        if ask_dying:
            ask_cap = min(ask_cap, DEPLETE_SIZE)
            ask_trim = True
        if MOM_SIZE >= 0 and hold_bid:
            bid_cap = min(bid_cap, MOM_SIZE)
            bid_trim = True
        if MOM_SIZE >= 0 and hold_ask:
            ask_cap = min(ask_cap, MOM_SIZE)
            ask_trim = True
        if IMB_TRIM > 0:
            if bid_lots < IMB_TRIM * ask_lots:
                bid_cap = min(bid_cap, IMB_SIZE)
                bid_trim = True
            if ask_lots < IMB_TRIM * bid_lots:
                ask_cap = min(ask_cap, IMB_SIZE)
                ask_trim = True
        bid_deep = SIZE_DEEP
        ask_deep = SIZE_DEEP
        bid_skip = DYING_DEEP > 0 and bid_dying
        ask_skip = DYING_DEEP > 0 and ask_dying
        if bid_skip:
            bid_deep = DYING_DEEP
        if ask_skip:
            ask_deep = DYING_DEEP
        if ALLOC_K:
            imb = (bid_lots - ask_lots) / (bid_lots + ask_lots)
            hi = ALLOC_HI if ALLOC_UP else 1.0
            if not bid_dying:
                new = int(bid_cap * min(hi, max(0.0, 1.0 + ALLOC_K * imb)) + 0.5)
                if new < bid_cap and ALLOC_DEEP:
                    bid_deep += bid_cap - new
                bid_cap = new
            if not ask_dying:
                new = int(ask_cap * min(hi, max(0.0, 1.0 - ALLOC_K * imb)) + 0.5)
                if new < ask_cap and ALLOC_DEEP:
                    ask_deep += ask_cap - new
                ask_cap = new
        if LAT_TAU > 0 and spread == 1:
            sig = self.lat_signal
            if sig > LAT_TH:
                new = int(ask_cap * LAT_PULL + 0.5)
                if new < ask_cap:
                    if LAT_DEEP:
                        ask_deep += ask_cap - new
                    ask_cap = new
                    ask_trim = True
                bid_cap = int(bid_cap * LAT_UP + 0.5)
            elif sig < -LAT_TH:
                new = int(bid_cap * LAT_PULL + 0.5)
                if new < bid_cap:
                    if LAT_DEEP:
                        bid_deep += bid_cap - new
                    bid_cap = new
                    bid_trim = True
                ask_cap = int(ask_cap * LAT_UP + 0.5)
        if LAT_TAU > 0 and LAT_TAKE > 0 and spread == 1:
            sig = self.lat_signal
            if sig > LAT_TAKE and position < LAT_TAKE_POS and self._now_us >= self._lat_take_block['B']:
                self._lat_take_block['B'] = self._now_us + LAT_TAKE_MS * 1000
                self._take_ioc(Side.BUY, best_ask, LAT_TAKE_LOTS)
            elif sig < -LAT_TAKE and position > -LAT_TAKE_POS and self._now_us >= self._lat_take_block['A']:
                self._lat_take_block['A'] = self._now_us + LAT_TAKE_MS * 1000
                self._take_ioc(Side.SELL, best_bid, LAT_TAKE_LOTS)
        if SIZE_SKEW > 0 and position != 0:
            factor = max(0.0, 1.0 - SIZE_SKEW * abs(position) / LIMIT)
            if position > 0:
                bid_cap = int(bid_cap * factor)
                bid_deep = int(SIZE_DEEP * factor)
                bid_trim = bid_trim or SKEW_TRIM == 1
            else:
                ask_cap = int(ask_cap * factor)
                ask_deep = int(SIZE_DEEP * factor)
                ask_trim = ask_trim or SKEW_TRIM == 1
        if JOIN_LOTS > 0 and spread >= 2:
            if hold_ask and not hold_bid and want_bid and bid_lots >= JOIN_OWN:
                self._take(Side.BUY, best_bid + 1, JOIN_LOTS, JOIN_MS, self._join_block)
            if hold_bid and not hold_ask and want_ask and ask_lots >= JOIN_OWN:
                self._take(Side.SELL, best_ask - 1, JOIN_LOTS, JOIN_MS, self._join_block)
        if TAKE_LOTS > 0 and spread == 1:
            ask_take = ask_dying
            bid_take = bid_dying
            if TAKE_DEPLETE > 0 and DEPL_FRAC > 0:
                ask_take = ask_lots < TAKE_DEPLETE and ask_lots < DEPL_FRAC * self._peak['A'][1]
                bid_take = bid_lots < TAKE_DEPLETE and bid_lots < DEPL_FRAC * self._peak['B'][1]
            if LAT_TAU > 0 and LAT_VETO < 99:
                ask_take = ask_take and self.lat_signal >= -LAT_VETO
                bid_take = bid_take and self.lat_signal <= LAT_VETO
            if ask_take and ask_lots <= TAKE_MAX and want_bid and bid_lots >= TAKE_OWN and bid_lots >= TAKE_RATIO * max(1, ask_lots2):
                self._take(Side.BUY, best_ask, TAKE_LOTS, TAKE_MS, self._take_block)
            if bid_take and bid_lots <= TAKE_MAX and want_ask and ask_lots >= TAKE_OWN and ask_lots >= TAKE_RATIO * max(1, bid_lots2):
                self._take(Side.SELL, best_bid, TAKE_LOTS, TAKE_MS, self._take_block)
        self._ladder(Side.BUY, bid_anchor, want_bid, cancel_bid, bid_cap, bid_trim, bid_deep, bid_skip)
        self._ladder(Side.SELL, ask_anchor, want_ask, cancel_ask, ask_cap, ask_trim, ask_deep, ask_skip)

    def _latent(self, snapshot: OrderBookSnapshot, best_bid: int, best_ask: int) -> None:
        """Update the latent-price signal: per side the decayed share of new market inserts landing at or inside the touch."""
        now = snapshot.timestamp_us
        if now > self._lat_t:
            f = math.exp(-(now - self._lat_t) / (LAT_TAU * 1_000_000))
            self._lat_t = now
            for key in ('B', 'A'):
                self._lat_s[key] *= f
                self._lat_w[key] *= f
        for key, orders, best, sign in (('B', snapshot.bids, best_bid, 1), ('A', snapshot.asks, best_ask, -1)):
            levels = [0] * LAT_LEVELS
            for order in orders:
                dist = (best - order.price) * sign
                if dist >= LAT_LEVELS:
                    break
                if order.owner == 'market':
                    levels[dist] += order.quantity
            prev = self._lat_prev[key]
            self._lat_prev[key] = (best, levels)
            if prev is None:
                continue
            if (best - prev[0]) * sign > 0:
                if best_ask - best_bid >= 1:
                    self._lat_s[key] += 1.0
                    self._lat_w[key] += 1.0
                continue
            if best != prev[0]:
                continue
            old = prev[1]
            for dist in range(LAT_LEVELS):
                if levels[dist] > old[dist]:
                    if dist == 0:
                        self._lat_s[key] += 1.0
                    self._lat_w[key] += 1.0
                    break
        wb = self._lat_w['B']
        wa = self._lat_w['A']
        mb = self._lat_s['B'] / wb if wb > 1e-6 else 0.5
        ma = self._lat_s['A'] / wa if wa > 1e-6 else 0.5
        self.lat_signal = mb - ma

    def _trim(self, side: Side, best: int, cap: int) -> None:
        """Shrink our orders at the touch to cap lots in all, the newest (the back of the queue) first."""
        mine = []
        total = 0
        for order_id, order in self._orders.items():
            if order[0] == side and not order[3] and not order[4] and order[1] == best:
                mine.append(order_id)
                total += order[2]
        excess = total - cap
        for order_id in reversed(mine):
            if excess <= 0:
                return
            order = self._orders[order_id]
            if order[5]:
                excess -= order[2] - order[5]
                continue
            if order[2] <= excess:
                self.cancel_order(order_id)
                order[3] = True
                excess -= order[2]
            else:
                self.modify_order(order_id, order[2] - excess)
                order[5] = order[2] - excess
                excess = 0

    def _ladder(self, side: Side, best: int, want: bool, cancel_all: bool, cap: int = SIZE_TOUCH, trim: bool = False, deep: int = SIZE_DEEP, skip_touch: bool = False) -> None:
        """Cancel this side's orders outside the ladder; post an order on each empty level the limit has room for."""
        sign = 1 if side == Side.BUY else -1
        have = {}  # ticks behind the touch -> our lots there
        exposure = 0
        deepest_id = None
        deepest_dist = -1
        for order_id, order in self._orders.items():
            if order[0] != side:
                continue
            exposure += order[2]
            if order[3] or order[4]:
                continue
            dist = (best - order[1]) * sign  # ticks behind the touch
            if cancel_all or dist >= KEEP_DEPTH or (dist < 0 and CANCEL_ALONE and self._now_us >= order[6]):
                self.cancel_order(order_id)
                order[3] = True
                continue
            have[dist] = have.get(dist, 0) + order[2]
            if dist > deepest_dist:
                deepest_dist = dist
                deepest_id = order_id
        if trim:
            self._trim(side, best, cap)
        if not want:
            return
        if side == Side.BUY:
            room = LIMIT - self._position - exposure
        else:
            room = LIMIT + self._position - exposure
        if REBALANCE and 0 not in have and room < SIZE_TOUCH and deepest_id is not None and deepest_dist > 0:
            self.cancel_order(deepest_id)
            self._orders[deepest_id][3] = True
        for level in range(LEVELS):
            size = cap if level == 0 else deep
            if level in have:
                deep_topup = skip_touch and level == 1
                if not TOPUP or (level > 0 and not deep_topup) or size - have[level] < TOPUP or room < TOPUP:
                    continue
                size -= have[level]
            quantity = min(size, room)
            if quantity <= 0:
                if skip_touch and level == 0:
                    continue
                return
            self._send(side, best - sign * level, quantity, False)
            room -= quantity

    def _take(self, side: Side, price: int, lots: int, ms: int, block: dict) -> None:
        """An extra limit order at `price` (a dying touch's last lots, or one tick inside after a sweep), exempt from the
        alone-cancel for `ms`; at most one a side per `ms`, the ladder's own orders untouched."""
        key = 'B' if side == Side.BUY else 'A'
        if self._now_us < block[key]:
            return
        exposure = 0
        for order in self._orders.values():
            if order[0] == side:
                exposure += order[2]
        if side == Side.BUY:
            room = LIMIT - self._position - exposure
        else:
            room = LIMIT + self._position - exposure
        quantity = min(lots, room)
        if quantity <= 0:
            return
        until = self._now_us + ms * 1000
        block[key] = until
        order_id = self._send(side, price, quantity, False)
        self._orders[order_id][6] = until
        self._takes += 1

    def _take_ioc(self, side: Side, price: int, lots: int) -> None:
        """An IOC for up to `lots` at `price`, within the room the limit leaves after every order that can still fill."""
        exposure = 0
        for order in self._orders.values():
            if order[0] == side:
                exposure += order[2]
        if side == Side.BUY:
            room = LIMIT - self._position - exposure
        else:
            room = LIMIT + self._position - exposure
        quantity = min(lots, room)
        if quantity > 0:
            order_id = self.send_order(OrderRequest(side=side, price=price, quantity=quantity, order_type=OrderType.IOC))
            self._orders[order_id] = [side, price, quantity, False, True, 0, 0]

    def _send(self, side: Side, price: int, quantity: int, ioc: bool) -> str:
        """Send an order and remember it."""
        order_type = OrderType.IOC if ioc else OrderType.LIMIT
        order_id = self.send_order(OrderRequest(side=side, price=price, quantity=quantity, order_type=order_type))
        self._orders[order_id] = [side, price, quantity, False, ioc, 0, 0]  # ... , the time until which a take order may rest in front of the touch
        if ioc:
            self._ioc_pending = True
        return order_id

    def on_private_order_update(self, event: PrivateOrderEvent) -> None:
        """Count fills into the position; forget orders that are done."""
        order = self._orders.get(event.order_id)
        if order is None:
            return
        done = False
        if event.status == OrderStatus.PARTIALLY_FILLED or event.status == OrderStatus.FILLED:
            if order[0] == Side.BUY:
                self._position += event.filled_quantity
            else:
                self._position -= event.filled_quantity
            order[2] = event.remaining_quantity
            done = event.status == OrderStatus.FILLED or event.remaining_quantity == 0
        elif event.status == OrderStatus.MODIFIED:
            order[2] = event.remaining_quantity
            order[5] = 0
        elif event.status == OrderStatus.REJECTED and order[5]:
            order[5] = 0  # a modify that lost the race against a fill: the order still rests
        elif event.status == OrderStatus.CANCELED or event.status == OrderStatus.REJECTED:
            done = True
        if done:
            self._orders.pop(event.order_id, None)
            if order[4]:
                self._ioc_pending = False
            if REACT_CANCEL and event.status == OrderStatus.CANCELED and self._snap is not None:
                self.on_order_book_change(self._snap, [])
