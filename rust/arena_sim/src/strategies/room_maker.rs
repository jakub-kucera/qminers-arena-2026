//! python/bots/qminers/families/room_maker.py (`LadderMakerStrategy`, family 7), line for line: the ladder maker
//! (LEVELS price levels a side from the touch, queue places kept within KEEP_DEPTH ticks, a limit counting every
//! order able to fill, TOPUP behind our touch order, SKEW / UNWIND / WIND_DOWN_S inventory rules) with the room
//! maker's knobs (SIZE_NARROW / SHRINK_NARROW, DEPLETE_LOTS / DEPLETE_SIZE, BACK_POS, FLAT_S). Its defaults are
//! candidate F3 (python/bots/qminers/candidates/r0_F3_full_room.py).
//!
//! Parameters: every module global of the file by its name, with its default: `LEVELS` (1), `KEEP_DEPTH` (1),
//! `SIZE_TOUCH` (200), `SIZE_DEEP` (50), `LIMIT` (100), `SKEW` (100), `SKEW_CANCEL` (1), `CANCEL_ALONE` (1),
//! `REBALANCE` (0), `IMB` (0.0), `MIN_QUEUE` (0), `INSIDE_POS` (1000), `INSIDE_SPREAD` (2), `TOPUP` (10),
//! `UNWIND` (1000), `UNWIND_TO` (50), `WIND_DOWN_S` (60), `SESSION_S` (5750), `SIZE_NARROW` (200),
//! `SHRINK_NARROW` (0), `DEPLETE_LOTS` (0), `DEPLETE_SIZE` (0), `BACK_POS` (1000), `FLAT_S` (0).

use crate::params::Params;
use crate::sim::{Ctx, Owner, PrivateEvent, Side, Snapshot, Status, Strategy, Trade};

const KEYS: [&str; 24] = [
    "LEVELS", "KEEP_DEPTH", "SIZE_TOUCH", "SIZE_DEEP", "LIMIT", "SKEW", "SKEW_CANCEL", "CANCEL_ALONE", "REBALANCE", "IMB",
    "MIN_QUEUE", "INSIDE_POS", "INSIDE_SPREAD", "TOPUP", "UNWIND", "UNWIND_TO", "WIND_DOWN_S", "SESSION_S", "SIZE_NARROW",
    "SHRINK_NARROW", "DEPLETE_LOTS", "DEPLETE_SIZE", "BACK_POS", "FLAT_S",
];

/// The Python's `[side, price, quantity left, cancelling, is_ioc, modify target]`.
struct Order {
    id: u64,
    side: Side,
    price: i64,
    quantity: i64,
    cancelling: bool,
    ioc: bool,
    modify_to: i64,
}

pub struct RoomMaker {
    levels: i64,
    keep_depth: i64,
    size_touch: i64,
    size_deep: i64,
    limit: i64,
    skew: i64,
    skew_cancel: bool,
    cancel_alone: bool,
    rebalance: bool,
    imb: f64,
    min_queue: i64,
    inside_pos: i64,
    inside_spread: i64,
    topup: i64,
    unwind: i64,
    unwind_to: i64,
    wind_down_s: f64,
    session_s: f64,
    size_narrow: i64,
    shrink_narrow: bool,
    deplete_lots: i64,
    deplete_size: i64,
    back_pos: i64,
    flat_s: f64,
    position: i64,
    /// the insertion-ordered dict id -> order
    orders: Vec<Order>,
    start_us: Option<i64>,
    ioc_pending: bool,
    flattened: bool,
}

impl RoomMaker {
    pub fn new(params: &Params) -> Result<RoomMaker, String> {
        params.check_keys(&KEYS)?;
        let flag = |key: &str, default: i64| params.int(key, default).map(|v| v != 0);
        Ok(RoomMaker {
            levels: params.int("LEVELS", 1)?,
            keep_depth: params.int("KEEP_DEPTH", 1)?,
            size_touch: params.int("SIZE_TOUCH", 200)?,
            size_deep: params.int("SIZE_DEEP", 50)?,
            limit: params.int("LIMIT", 100)?,
            skew: params.int("SKEW", 100)?,
            skew_cancel: flag("SKEW_CANCEL", 1)?,
            cancel_alone: flag("CANCEL_ALONE", 1)?,
            rebalance: flag("REBALANCE", 0)?,
            imb: params.float("IMB", 0.0)?,
            min_queue: params.int("MIN_QUEUE", 0)?,
            inside_pos: params.int("INSIDE_POS", 1000)?,
            inside_spread: params.int("INSIDE_SPREAD", 2)?,
            topup: params.int("TOPUP", 10)?,
            unwind: params.int("UNWIND", 1000)?,
            unwind_to: params.int("UNWIND_TO", 50)?,
            wind_down_s: params.float("WIND_DOWN_S", 60.0)?,
            session_s: params.float("SESSION_S", 5750.0)?,
            size_narrow: params.int("SIZE_NARROW", 200)?,
            shrink_narrow: flag("SHRINK_NARROW", 0)?,
            deplete_lots: params.int("DEPLETE_LOTS", 0)?,
            deplete_size: params.int("DEPLETE_SIZE", 0)?,
            back_pos: params.int("BACK_POS", 1000)?,
            flat_s: params.float("FLAT_S", 0.0)?,
            position: 0,
            orders: Vec::new(),
            start_us: None,
            ioc_pending: false,
            flattened: false,
        })
    }

    /// Shrinks our orders at the touch to cap lots in all, the newest (the back of the queue) first.
    fn trim(&mut self, side: Side, best: i64, cap: i64, ctx: &mut Ctx) {
        let mut mine = Vec::new();
        let mut total = 0;
        for (i, order) in self.orders.iter().enumerate() {
            if order.side == side && !order.cancelling && !order.ioc && order.price == best {
                mine.push(i);
                total += order.quantity;
            }
        }
        let mut excess = total - cap;
        for &i in mine.iter().rev() {
            if excess <= 0 {
                return;
            }
            let order = &mut self.orders[i];
            if order.modify_to != 0 {
                excess -= order.quantity - order.modify_to;
                continue;
            }
            if order.quantity <= excess {
                ctx.cancel_order(order.id);
                order.cancelling = true;
                excess -= order.quantity;
            } else {
                ctx.modify_order(order.id, order.quantity - excess);
                order.modify_to = order.quantity - excess;
                excess = 0;
            }
        }
    }

    /// Cancels this side's orders outside the ladder; posts an order on each empty level the limit has room for.
    #[allow(clippy::too_many_arguments)]
    fn ladder(&mut self, side: Side, best: i64, want: bool, cancel_all: bool, cap: i64, trim: bool, ctx: &mut Ctx) {
        let sign = if side == Side::Buy { 1 } else { -1 };
        let mut have: Vec<(i64, i64)> = Vec::new(); // ticks behind the touch -> our lots there, in insertion order
        let mut exposure = 0;
        let mut deepest: Option<usize> = None;
        let mut deepest_dist = -1;
        for (i, order) in self.orders.iter_mut().enumerate() {
            if order.side != side {
                continue;
            }
            exposure += order.quantity;
            if order.cancelling || order.ioc {
                continue;
            }
            let dist = (best - order.price) * sign;
            if cancel_all || dist >= self.keep_depth || (dist < 0 && self.cancel_alone) {
                ctx.cancel_order(order.id);
                order.cancelling = true;
                continue;
            }
            match have.iter_mut().find(|(d, _)| *d == dist) {
                Some((_, lots)) => *lots += order.quantity,
                None => have.push((dist, order.quantity)),
            }
            if dist > deepest_dist {
                deepest_dist = dist;
                deepest = Some(i);
            }
        }
        if trim {
            self.trim(side, best, cap, ctx);
        }
        if !want {
            return;
        }
        let mut room = match side {
            Side::Buy => self.limit - self.position - exposure,
            Side::Sell => self.limit + self.position - exposure,
        };
        let lots_at = |have: &Vec<(i64, i64)>, d: i64| have.iter().find(|(k, _)| *k == d).map(|(_, v)| *v);
        if self.rebalance && lots_at(&have, 0).is_none() && room < self.size_touch && deepest_dist > 0 {
            if let Some(i) = deepest {
                ctx.cancel_order(self.orders[i].id);
                self.orders[i].cancelling = true;
            }
        }
        for level in 0..self.levels.max(0) {
            let mut size = if level == 0 { cap } else { self.size_deep };
            if let Some(lots) = lots_at(&have, level) {
                if self.topup == 0 || level > 0 || size - lots < self.topup || room < self.topup {
                    continue;
                }
                size -= lots;
            }
            let quantity = size.min(room);
            if quantity <= 0 {
                return;
            }
            self.send(side, best - sign * level, quantity, false, ctx);
            room -= quantity;
        }
    }

    fn send(&mut self, side: Side, price: i64, quantity: i64, ioc: bool, ctx: &mut Ctx) {
        let id = ctx.send_order(side, price, quantity, ioc);
        self.orders.push(Order { id, side, price, quantity, cancelling: false, ioc, modify_to: 0 });
        if ioc {
            self.ioc_pending = true;
        }
    }
}

/// The Python's loop over a side of the snapshot: the first market order's price and the market's lots at it, ours
/// skipped. The engine's `Snapshot::market_touch` gives the same, several times faster; this stays as its check.
#[allow(dead_code)]
fn touch(orders: impl Iterator<Item = crate::sim::BookOrder>) -> Option<(i64, i64)> {
    let mut best = None;
    let mut lots = 0;
    for order in orders {
        if order.owner == Owner::Market {
            match best {
                None => best = Some(order.price),
                Some(b) if order.price != b => break,
                _ => {}
            }
            lots += order.quantity;
        }
    }
    best.map(|b| (b, lots))
}

impl Strategy for RoomMaker {
    fn on_book(&mut self, snapshot: &Snapshot, _trades: &[Trade], ctx: &mut Ctx) {
        let start = *self.start_us.get_or_insert(snapshot.timestamp_us);
        let bid = snapshot.market_touch(Side::Buy);
        let ask = snapshot.market_touch(Side::Sell);
        debug_assert_eq!(bid, touch(snapshot.bids()));
        debug_assert_eq!(ask, touch(snapshot.asks()));
        let (Some((best_bid, bid_lots)), Some((best_ask, ask_lots))) = (bid, ask) else { return };
        let bid_ok = bid_lots >= self.min_queue && bid_lots as f64 >= self.imb * ask_lots as f64;
        let ask_ok = ask_lots >= self.min_queue && ask_lots as f64 >= self.imb * bid_lots as f64;

        let elapsed_s = (snapshot.timestamp_us - start) as f64 / 1_000_000.0;
        let winding_down = elapsed_s > self.session_s - self.wind_down_s;
        let position = self.position;
        if self.flat_s != 0.0 && !self.flattened && !self.ioc_pending && elapsed_s > self.session_s - self.flat_s {
            self.flattened = true;
            if position > 0 {
                self.send(Side::Sell, best_bid, position, true, ctx);
            } else if position < 0 {
                self.send(Side::Buy, best_ask, -position, true, ctx);
            }
        }
        if !self.ioc_pending && position > self.unwind {
            self.send(Side::Sell, best_bid, position - self.unwind_to, true, ctx);
        } else if !self.ioc_pending && position < -self.unwind {
            self.send(Side::Buy, best_ask, -position - self.unwind_to, true, ctx);
        }
        let want_bid = position < self.skew && !(winding_down && position >= 0) && bid_ok;
        let want_ask = position > -self.skew && !(winding_down && position <= 0) && ask_ok;
        let cancel_bid = (winding_down && position >= 0) || (self.skew_cancel && position >= self.skew) || !bid_ok;
        let cancel_ask = (winding_down && position <= 0) || (self.skew_cancel && position <= -self.skew) || !ask_ok;
        let spread = best_ask - best_bid;
        let mut bid_anchor = if position <= -self.inside_pos && spread >= self.inside_spread { best_bid + 1 } else { best_bid };
        let mut ask_anchor = if position >= self.inside_pos && spread >= self.inside_spread { best_ask - 1 } else { best_ask };
        if position >= self.back_pos {
            bid_anchor = best_bid - 1;
        }
        if position <= -self.back_pos {
            ask_anchor = best_ask + 1;
        }
        let mut bid_cap = if spread >= 2 { self.size_touch } else { self.size_narrow };
        let mut ask_cap = bid_cap;
        let mut bid_trim = self.shrink_narrow && spread < 2;
        let mut ask_trim = bid_trim;
        if bid_lots < self.deplete_lots {
            bid_cap = bid_cap.min(self.deplete_size);
            bid_trim = true;
        }
        if ask_lots < self.deplete_lots {
            ask_cap = ask_cap.min(self.deplete_size);
            ask_trim = true;
        }
        self.ladder(Side::Buy, bid_anchor, want_bid, cancel_bid, bid_cap, bid_trim, ctx);
        self.ladder(Side::Sell, ask_anchor, want_ask, cancel_ask, ask_cap, ask_trim, ctx);
    }

    /// Counts fills into the position; forgets orders that are done.
    fn on_private(&mut self, event: &PrivateEvent, _ctx: &mut Ctx) {
        let Some(index) = self.orders.iter().position(|o| o.id == event.order_id) else { return };
        let order = &mut self.orders[index];
        let mut done = false;
        match event.status {
            Status::PartiallyFilled | Status::Filled => {
                if order.side == Side::Buy {
                    self.position += event.filled_quantity;
                } else {
                    self.position -= event.filled_quantity;
                }
                order.quantity = event.remaining_quantity;
                done = event.status == Status::Filled || event.remaining_quantity == 0;
            }
            Status::Modified => {
                order.quantity = event.remaining_quantity;
                order.modify_to = 0;
            }
            Status::Rejected if order.modify_to != 0 => order.modify_to = 0,
            Status::Canceled | Status::Rejected => done = true,
            Status::Accepted => {}
        }
        if done {
            let order = self.orders.remove(index);
            if order.ioc {
                self.ioc_pending = false;
            }
        }
    }
}
