//! python/bots/qminers/families/room_maker.py (`LadderMakerStrategy`, family 7), line for line: the ladder maker
//! (LEVELS price levels a side from the touch, queue places kept within KEEP_DEPTH ticks, a limit counting every
//! order able to fill, TOPUP behind our touch order, SKEW / UNWIND / WIND_DOWN_S inventory rules) with the room
//! maker's knobs (SIZE_NARROW / SHRINK_NARROW, DEPLETE_LOTS / DEPLETE_SIZE, BACK_POS, FLAT_S). Its defaults are
//! candidate F3 (python/bots/qminers/candidates/round0/r0_F3_full_room.py). The same struct is
//! python/bots/qminers/families/shrink_maker.py (family 10, the strategy name `shrink_maker`), line for line too: its
//! two knobs, `DEPL_FRAC` (the depletion guard fires only on a touch shrunk below that share of its peak since it
//! became the touch) and `REACT_CANCEL` (re-run the quoting from the last snapshot when one of our cancels lands),
//! are off by default, which is room_maker.py; with its `MOM_LOTS` / `MOM_MS` hold (post nothing new on the side a
//! big aggressive order hit), off too.
//!
//! The same struct is also family 12's two files, line for line, each with its own defaults (R1-F6's cell:
//! `LEVELS` 2, `KEEP_DEPTH` 2, `SIZE_TOUCH` 65, `SIZE_DEEP` 80, `TOPUP` 1, `SESSION_S` 1e9, `SIZE_NARROW` 115,
//! `DEPLETE_LOTS` 100, `REACT_CANCEL` 1, `DEPL_FRAC` 0.06) and its knobs, off by default:
//! `alloc_maker` (python/bots/qminers/families/alloc_maker.py, no MOM hold): `ALLOC_K` (0.0), `INV_K` (0.0),
//! `ALLOC_UP` (1), `ALLOC_HI` (2.0), `ALLOC_KU` (0.0), `ALLOC_TH` (0.0), `ALLOC_DEEP` (1), `ADV_TH` (-1000.0),
//! `ADV_MIN` (2000), `ADV_MS` (1000), `ADV_SCOPE` (1); `signal_maker` (python/bots/qminers/families/signal_maker.py):
//! the shrink maker's keys and `MOM_SIZE` (-1), `IMB_TRIM` (0.0), `IMB_SIZE` (0), `MOM_BLOCK` (1), `MOM_JOIN` (0),
//! `DYING_DEEP` (0), `SIZE_SKEW` (0.0), `SKEW_TRIM` (0). A key outside the file's globals is an error.
//!
//! `take_maker` is python/bots/qminers/candidates/round1/r1_F8_take_join.py (R1-F8), line for line, at its own defaults
//! (every global of the file): signal_maker's keys at R1-F7's values, `ALLOC_K` (-0.5), `ALLOC_UP`, `ALLOC_HI`,
//! `ALLOC_DEEP` (alloc_maker's, applied before SIZE_SKEW as the file does), and its own: `TAKE_LOTS` (60),
//! `TAKE_MAX` (1000), `ANY_CLEAR` (0), `JOIN_LOTS` (0), `JOIN_MS` (200), `JOIN_OWN` (400), `TAKE_OWN` (800),
//! `TAKE_RATIO` (0.0, which reads the market's lots at each side's second price level), `TAKE_DEPLETE` (150),
//! `TAKE_MS` (250); its orders carry the time until which a take (or join) order is exempt from CANCEL_ALONE.
//!
//! Parameters: every module global of the file by its name, with its default: `LEVELS` (1), `KEEP_DEPTH` (1),
//! `SIZE_TOUCH` (200), `SIZE_DEEP` (50), `LIMIT` (100), `SKEW` (100), `SKEW_CANCEL` (1), `CANCEL_ALONE` (1),
//! `REBALANCE` (0), `IMB` (0.0), `MIN_QUEUE` (0), `INSIDE_POS` (1000), `INSIDE_SPREAD` (2), `TOPUP` (10),
//! `UNWIND` (1000), `UNWIND_TO` (50), `WIND_DOWN_S` (60), `SESSION_S` (5750), `SIZE_NARROW` (200),
//! `SHRINK_NARROW` (0), `DEPLETE_LOTS` (0), `DEPLETE_SIZE` (0), `BACK_POS` (1000), `FLAT_S` (0); shrink_maker.py's
//! `REACT_CANCEL` (0) and `DEPL_FRAC` (0.0), and `MOM_LOTS` (0) and `MOM_MS` (1000) as `shrink_maker`.

use std::collections::VecDeque;

use crate::params::{Params, Value};
use crate::sim::{Ctx, Owner, PrivateEvent, Side, Snapshot, Status, Strategy, Trade};

const KEYS: [&str; 26] = [
    "LEVELS", "KEEP_DEPTH", "SIZE_TOUCH", "SIZE_DEEP", "LIMIT", "SKEW", "SKEW_CANCEL", "CANCEL_ALONE", "REBALANCE", "IMB",
    "MIN_QUEUE", "INSIDE_POS", "INSIDE_SPREAD", "TOPUP", "UNWIND", "UNWIND_TO", "WIND_DOWN_S", "SESSION_S", "SIZE_NARROW",
    "SHRINK_NARROW", "DEPLETE_LOTS", "DEPLETE_SIZE", "BACK_POS", "FLAT_S", "REACT_CANCEL", "DEPL_FRAC",
];
/// shrink_maker.py's hold (and signal_maker.py's)
const MOM_KEYS: [&str; 2] = ["MOM_LOTS", "MOM_MS"];
const ALLOC_KEYS: [&str; 11] = [
    "ALLOC_K", "INV_K", "ALLOC_UP", "ALLOC_HI", "ALLOC_KU", "ALLOC_TH", "ALLOC_DEEP", "ADV_TH", "ADV_MIN", "ADV_MS", "ADV_SCOPE",
];
const SIGNAL_KEYS: [&str; 8] = ["MOM_SIZE", "IMB_TRIM", "IMB_SIZE", "MOM_BLOCK", "MOM_JOIN", "DYING_DEEP", "SIZE_SKEW", "SKEW_TRIM"];
/// r1_F8_take_join.py's globals beyond signal_maker.py's
const TAKE_KEYS: [&str; 14] = [
    "ALLOC_K", "ALLOC_UP", "ALLOC_HI", "ALLOC_DEEP", "TAKE_LOTS", "TAKE_MAX", "ANY_CLEAR", "JOIN_LOTS", "JOIN_MS", "JOIN_OWN",
    "TAKE_OWN", "TAKE_RATIO", "TAKE_DEPLETE", "TAKE_MS",
];
/// r1_F8_take_join.py's defaults over family 12's
const F8_DEFAULTS: [(&str, Value); 13] = [
    ("MOM_LOTS", Value::Int(400)),
    ("MOM_MS", Value::Int(50)),
    ("MOM_BLOCK", Value::Int(0)),
    ("MOM_JOIN", Value::Int(1)),
    ("DYING_DEEP", Value::Int(80)),
    ("DEPL_FRAC", Value::Float(0.12)),
    ("ALLOC_K", Value::Float(-0.5)),
    ("TAKE_LOTS", Value::Int(60)),
    ("TAKE_MAX", Value::Int(1000)),
    ("JOIN_OWN", Value::Int(400)),
    ("TAKE_OWN", Value::Int(800)),
    ("TAKE_DEPLETE", Value::Int(150)),
    ("TAKE_MS", Value::Int(250)),
];
/// family 12's defaults over room_maker.py's: R1-F6's cell
const F6_DEFAULTS: [(&str, Value); 10] = [
    ("LEVELS", Value::Int(2)),
    ("KEEP_DEPTH", Value::Int(2)),
    ("SIZE_TOUCH", Value::Int(65)),
    ("SIZE_DEEP", Value::Int(80)),
    ("TOPUP", Value::Int(1)),
    ("SESSION_S", Value::Int(1_000_000_000)),
    ("SIZE_NARROW", Value::Int(115)),
    ("DEPLETE_LOTS", Value::Int(100)),
    ("REACT_CANCEL", Value::Int(1)),
    ("DEPL_FRAC", Value::Float(0.06)),
];

/// What the quoting reads of a snapshot: its time, each side's market touch (price, lots), and the market's lots at
/// each side's second price level (bid, ask; read only for TAKE_RATIO, else 0).
type Touches = (i64, Option<(i64, i64)>, Option<(i64, i64)>, (i64, i64));

/// The Python's `[side, price, quantity left, cancelling, is_ioc, modify target, (r1_F8's) exempt from CANCEL_ALONE until]`.
struct Order {
    id: u64,
    side: Side,
    price: i64,
    quantity: i64,
    cancelling: bool,
    ioc: bool,
    modify_to: i64,
    exempt_until: i64,
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
    react_cancel: bool,
    depl_frac: f64,
    mom_lots: i64,
    mom_ms: i64,
    // alloc_maker.py
    alloc_k: f64,
    inv_k: f64,
    alloc_up: bool,
    alloc_hi: f64,
    alloc_ku: f64,
    alloc_th: f64,
    alloc_deep: bool,
    adv_th: f64,
    adv_min: i64,
    adv_ms: i64,
    adv_scope: i64,
    // signal_maker.py
    mom_size: i64,
    imb_trim: f64,
    imb_size: i64,
    mom_block: bool,
    mom_join: bool,
    dying_deep: i64,
    size_skew: f64,
    skew_trim: i64,
    // r1_F8_take_join.py
    take_lots: i64,
    take_max: i64,
    any_clear: bool,
    join_lots: i64,
    join_ms: i64,
    join_own: i64,
    take_own: i64,
    take_ratio: f64,
    take_deplete: i64,
    take_ms: i64,
    /// `_take_block`, `_join_block`: per our order's side (buy, sell), the time until which no such order goes out
    take_block: [i64; 2],
    join_block: [i64; 2],
    /// `_prev_touch`: the previous snapshot's market touches (bid, ask), for ANY_CLEAR
    prev_touch: Option<(i64, i64)>,
    /// `_now_us`: the current snapshot's time
    now_us: i64,
    position: i64,
    /// the insertion-ordered dict id -> order
    orders: Vec<Order>,
    start_us: Option<i64>,
    ioc_pending: bool,
    flattened: bool,
    /// the Python's `_snap`: the last snapshot's touches, for REACT_CANCEL
    snap: Option<Touches>,
    /// the Python's `_peak`: per side (bid, ask), [touch price, the market lots there at their most since]
    peak: [Option<(i64, i64)>; 2],
    /// the Python's `_hold_until`: per book side (bid, ask), the time until which nothing new is posted there
    hold_until: [i64; 2],
    /// alloc_maker.py's `_pending`: (due us, sign, price, lots, state) per fill, for its markout
    pending: VecDeque<(i64, f64, i64, i64, usize)>,
    adv_sum: [f64; 6],
    adv_lots: [i64; 6],
    bstate: usize,
    astate: usize,
}

impl RoomMaker {
    /// The strategy `name`'s file: room_maker, shrink_maker, alloc_maker or signal_maker (its keys and defaults).
    pub fn new(name: &str, params: &Params) -> Result<RoomMaker, String> {
        let mut known: Vec<&str> = KEYS.to_vec();
        match name {
            "room_maker" => {}
            "shrink_maker" => known.extend(MOM_KEYS),
            "alloc_maker" => known.extend(ALLOC_KEYS),
            "signal_maker" => known.extend(MOM_KEYS.iter().chain(SIGNAL_KEYS.iter())),
            "take_maker" => known.extend(MOM_KEYS.iter().chain(SIGNAL_KEYS.iter()).chain(TAKE_KEYS.iter())),
            _ => return Err(format!("{name:?} is not a room maker")),
        }
        params.check_keys(&known)?;
        let mut merged = Params::default();
        if name == "alloc_maker" || name == "signal_maker" || name == "take_maker" {
            for (key, value) in F6_DEFAULTS {
                merged.0.insert(key.to_string(), value);
            }
        }
        if name == "take_maker" {
            for (key, value) in F8_DEFAULTS {
                merged.0.insert(key.to_string(), value);
            }
        }
        merged.0.extend(params.0.iter().map(|(k, v)| (k.clone(), v.clone())));
        let params = &merged;
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
            react_cancel: flag("REACT_CANCEL", 0)?,
            depl_frac: params.float("DEPL_FRAC", 0.0)?,
            mom_lots: params.int("MOM_LOTS", 0)?,
            mom_ms: params.int("MOM_MS", 1000)?,
            alloc_k: params.float("ALLOC_K", 0.0)?,
            inv_k: params.float("INV_K", 0.0)?,
            alloc_up: flag("ALLOC_UP", 1)?,
            alloc_hi: params.float("ALLOC_HI", 2.0)?,
            alloc_ku: params.float("ALLOC_KU", 0.0)?,
            alloc_th: params.float("ALLOC_TH", 0.0)?,
            alloc_deep: flag("ALLOC_DEEP", 1)?,
            adv_th: params.float("ADV_TH", -1000.0)?,
            adv_min: params.int("ADV_MIN", 2000)?,
            adv_ms: params.int("ADV_MS", 1000)?,
            adv_scope: params.int("ADV_SCOPE", 1)?,
            mom_size: params.int("MOM_SIZE", -1)?,
            imb_trim: params.float("IMB_TRIM", 0.0)?,
            imb_size: params.int("IMB_SIZE", 0)?,
            mom_block: flag("MOM_BLOCK", 1)?,
            mom_join: flag("MOM_JOIN", 0)?,
            dying_deep: params.int("DYING_DEEP", 0)?,
            size_skew: params.float("SIZE_SKEW", 0.0)?,
            skew_trim: params.int("SKEW_TRIM", 0)?,
            take_lots: params.int("TAKE_LOTS", 0)?,
            take_max: params.int("TAKE_MAX", 1000)?,
            any_clear: flag("ANY_CLEAR", 0)?,
            join_lots: params.int("JOIN_LOTS", 0)?,
            join_ms: params.int("JOIN_MS", 200)?,
            join_own: params.int("JOIN_OWN", 0)?,
            take_own: params.int("TAKE_OWN", 0)?,
            take_ratio: params.float("TAKE_RATIO", 0.0)?,
            take_deplete: params.int("TAKE_DEPLETE", 0)?,
            take_ms: params.int("TAKE_MS", 250)?,
            take_block: [0, 0],
            join_block: [0, 0],
            prev_touch: None,
            now_us: 0,
            position: 0,
            orders: Vec::new(),
            start_us: None,
            ioc_pending: false,
            flattened: false,
            snap: None,
            peak: [None, None],
            hold_until: [0, 0],
            pending: VecDeque::new(),
            adv_sum: [0.0; 6],
            adv_lots: [0; 6],
            bstate: 1,
            astate: 4,
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
    /// `deep`: the lots behind the touch (both family-12 files'); `skip_touch`: signal_maker.py's (a dying touch's room
    /// goes behind it, that order topped up); `top_ok`: alloc_maker.py's (false: no top-up; with ADV_SCOPE 2 no touch order).
    fn ladder(
        &mut self, side: Side, best: i64, want: bool, cancel_all: bool, cap: i64, trim: bool, deep: i64, skip_touch: bool,
        top_ok: bool, ctx: &mut Ctx,
    ) {
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
            if cancel_all || dist >= self.keep_depth || (dist < 0 && self.cancel_alone && self.now_us >= order.exempt_until) {
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
            let mut size = if level == 0 { cap } else { deep };
            let held = lots_at(&have, level);
            if level == 0 && !top_ok && (self.adv_scope == 2 || held.is_some()) {
                continue;
            }
            if let Some(lots) = held {
                let deep_topup = skip_touch && level == 1;
                if self.topup == 0 || (level > 0 && !deep_topup) || size - lots < self.topup || room < self.topup {
                    continue;
                }
                size -= lots;
            }
            let quantity = size.min(room);
            if quantity <= 0 {
                if skip_touch && level == 0 {
                    continue;
                }
                return;
            }
            self.send(side, best - sign * level, quantity, false, ctx);
            room -= quantity;
        }
    }

    fn send(&mut self, side: Side, price: i64, quantity: i64, ioc: bool, ctx: &mut Ctx) {
        let id = ctx.send_order(side, price, quantity, ioc);
        self.orders.push(Order { id, side, price, quantity, cancelling: false, ioc, modify_to: 0, exempt_until: 0 });
        if ioc {
            self.ioc_pending = true;
        }
    }

    /// r1_F8_take_join.py's `_take`: an extra limit order at `price` (a dying touch's last lots, or one tick inside
    /// after a sweep), exempt from the alone-cancel for `ms`; at most one a side per `ms`, the ladder's orders untouched.
    /// `join`: the join orders' block, else the takes'.
    fn take(&mut self, side: Side, price: i64, lots: i64, ms: i64, join: bool, ctx: &mut Ctx) {
        let key = if side == Side::Buy { 0 } else { 1 };
        let block = if join { self.join_block[key] } else { self.take_block[key] };
        if self.now_us < block {
            return;
        }
        let exposure: i64 = self.orders.iter().filter(|o| o.side == side).map(|o| o.quantity).sum();
        let room = match side {
            Side::Buy => self.limit - self.position - exposure,
            Side::Sell => self.limit + self.position - exposure,
        };
        let quantity = lots.min(room);
        if quantity <= 0 {
            return;
        }
        let until = self.now_us + ms * 1000;
        if join {
            self.join_block[key] = until;
        } else {
            self.take_block[key] = until;
        }
        self.send(side, price, quantity, false, ctx);
        self.orders.last_mut().expect("just sent").exempt_until = until;
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

/// r1_F8_take_join.py's loop over a side: the market's lots at its second market price level (0 if none).
fn second_lots(orders: impl Iterator<Item = crate::sim::BookOrder>) -> i64 {
    let mut best = None;
    let mut second = None;
    let mut lots = 0;
    for order in orders {
        if order.owner == Owner::Market {
            match best {
                None => best = Some(order.price),
                Some(b) if order.price != b => {
                    match second {
                        None => second = Some(order.price),
                        Some(p) if order.price != p => break,
                        _ => {}
                    }
                    lots += order.quantity;
                }
                _ => {}
            }
        }
    }
    lots
}

impl RoomMaker {
    /// The Python's `on_order_book_change` from the snapshot's touches (also its REACT_CANCEL re-run).
    fn quote(&mut self, touches: Touches, trades: &[Trade], ctx: &mut Ctx) {
        self.snap = Some(touches);
        let (timestamp_us, bid, ask, (bid_lots2, ask_lots2)) = touches;
        self.now_us = timestamp_us;
        let start = *self.start_us.get_or_insert(timestamp_us);
        let (Some((best_bid, bid_lots)), Some((best_ask, ask_lots))) = (bid, ask) else { return };
        let bid_ok = bid_lots >= self.min_queue && bid_lots as f64 >= self.imb * ask_lots as f64;
        let ask_ok = ask_lots >= self.min_queue && ask_lots as f64 >= self.imb * bid_lots as f64;

        let elapsed_s = (timestamp_us - start) as f64 / 1_000_000.0;
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
        if self.mom_lots > 0 && !trades.is_empty() {
            let mut swept: Vec<((u64, Side), i64)> = Vec::new();
            for trade in trades {
                if trade.taker_owner == Owner::Market {
                    let key = (trade.taker_order_id, trade.book_side);
                    match swept.iter_mut().find(|(k, _)| *k == key) {
                        Some((_, lots)) => *lots += trade.quantity,
                        None => swept.push((key, trade.quantity)),
                    }
                }
            }
            for ((_, book_side), lots) in swept {
                if lots >= self.mom_lots {
                    self.hold_until[if book_side == Side::Buy { 0 } else { 1 }] = timestamp_us + self.mom_ms * 1000;
                }
            }
        }
        if self.any_clear {
            if let Some((prev_bid, prev_ask)) = self.prev_touch {
                if best_ask > prev_ask {
                    self.hold_until[1] = timestamp_us + self.mom_ms * 1000;
                }
                if best_bid < prev_bid {
                    self.hold_until[0] = timestamp_us + self.mom_ms * 1000;
                }
            }
            self.prev_touch = Some((best_bid, best_ask));
        }
        let hold_bid = timestamp_us < self.hold_until[0];
        let hold_ask = timestamp_us < self.hold_until[1];
        let want_bid = position < self.skew && !(winding_down && position >= 0) && bid_ok && !(hold_bid && self.mom_block);
        let want_ask = position > -self.skew && !(winding_down && position <= 0) && ask_ok && !(hold_ask && self.mom_block);
        let cancel_bid = (winding_down && position >= 0) || (self.skew_cancel && position >= self.skew) || !bid_ok;
        let cancel_ask = (winding_down && position <= 0) || (self.skew_cancel && position <= -self.skew) || !ask_ok;
        let spread = best_ask - best_bid;
        let mut bid_anchor = if position <= -self.inside_pos && spread >= self.inside_spread { best_bid + 1 } else { best_bid };
        let mut ask_anchor = if position >= self.inside_pos && spread >= self.inside_spread { best_ask - 1 } else { best_ask };
        if self.mom_join && spread >= 2 && hold_ask && !hold_bid && bid_lots >= self.join_own {
            bid_anchor = best_bid + 1;
        }
        if self.mom_join && spread >= 2 && hold_bid && !hold_ask && ask_lots >= self.join_own {
            ask_anchor = best_ask - 1;
        }
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
        let mut bid_dying = bid_lots < self.deplete_lots;
        let mut ask_dying = ask_lots < self.deplete_lots;
        if self.depl_frac > 0.0 {
            for (key, price, lots) in [(0, best_bid, bid_lots), (1, best_ask, ask_lots)] {
                match &mut self.peak[key] {
                    Some((p, most)) if *p == price => *most = (*most).max(lots),
                    slot => *slot = Some((price, lots)),
                }
            }
            let peak = |key: usize| self.peak[key].map_or(0, |(_, most)| most) as f64;
            bid_dying = bid_dying && (bid_lots as f64) < self.depl_frac * peak(0);
            ask_dying = ask_dying && (ask_lots as f64) < self.depl_frac * peak(1);
        }
        if bid_dying {
            bid_cap = bid_cap.min(self.deplete_size);
            bid_trim = true;
        }
        if ask_dying {
            ask_cap = ask_cap.min(self.deplete_size);
            ask_trim = true;
        }
        // signal_maker.py's caps and deep sizes (off in the other files)
        if self.mom_size >= 0 && hold_bid {
            bid_cap = bid_cap.min(self.mom_size);
            bid_trim = true;
        }
        if self.mom_size >= 0 && hold_ask {
            ask_cap = ask_cap.min(self.mom_size);
            ask_trim = true;
        }
        if self.imb_trim > 0.0 {
            if (bid_lots as f64) < self.imb_trim * ask_lots as f64 {
                bid_cap = bid_cap.min(self.imb_size);
                bid_trim = true;
            }
            if (ask_lots as f64) < self.imb_trim * bid_lots as f64 {
                ask_cap = ask_cap.min(self.imb_size);
                ask_trim = true;
            }
        }
        let mut bid_deep = self.size_deep;
        let mut ask_deep = self.size_deep;
        let bid_skip = self.dying_deep > 0 && bid_dying;
        let ask_skip = self.dying_deep > 0 && ask_dying;
        if bid_skip {
            bid_deep = self.dying_deep;
        }
        if ask_skip {
            ask_deep = self.dying_deep;
        }
        // alloc_maker.py's allocation and adverse table (off in the other files)
        if self.alloc_k != 0.0 || self.inv_k != 0.0 {
            let mut imb = (bid_lots - ask_lots) as f64 / (bid_lots + ask_lots) as f64;
            if -self.alloc_th <= imb && imb <= self.alloc_th {
                imb = 0.0;
            }
            let inv = self.inv_k * position as f64 / self.limit as f64;
            let shift = self.alloc_k * imb - inv;
            let hi = if self.alloc_up { self.alloc_hi } else { 1.0 };
            if !bid_dying {
                let mut factor = 1.0 + shift;
                if self.alloc_ku != 0.0 && factor > 1.0 {
                    factor = 1.0 + self.alloc_ku * imb - inv;
                }
                let new = (bid_cap as f64 * py_min(hi, py_max(0.0, factor)) + 0.5) as i64;
                if new < bid_cap && self.alloc_deep {
                    bid_deep += bid_cap - new;
                }
                bid_cap = new;
            }
            if !ask_dying {
                let mut factor = 1.0 - shift;
                if self.alloc_ku != 0.0 && factor > 1.0 {
                    factor = 1.0 - self.alloc_ku * imb + inv;
                }
                let new = (ask_cap as f64 * py_min(hi, py_max(0.0, factor)) + 0.5) as i64;
                if new < ask_cap && self.alloc_deep {
                    ask_deep += ask_cap - new;
                }
                ask_cap = new;
            }
        }
        // signal_maker.py's size skew, after the allocation as r1_F8_take_join.py has it (the other files have one or neither)
        if self.size_skew > 0.0 && position != 0 {
            let factor = py_max(0.0, 1.0 - self.size_skew * position.abs() as f64 / self.limit as f64);
            if position > 0 {
                bid_cap = (bid_cap as f64 * factor) as i64;
                bid_deep = (self.size_deep as f64 * factor) as i64;
                bid_trim = bid_trim || self.skew_trim == 1;
            } else {
                ask_cap = (ask_cap as f64 * factor) as i64;
                ask_deep = (self.size_deep as f64 * factor) as i64;
                ask_trim = ask_trim || self.skew_trim == 1;
            }
        }
        let mut bid_top = true;
        let mut ask_top = true;
        if self.adv_th > -1000.0 {
            let mid = (best_bid + best_ask) as f64 / 2.0;
            while let Some(&(due, sign, price, lots, state)) = self.pending.front() {
                if due > timestamp_us {
                    break;
                }
                self.pending.pop_front();
                self.adv_sum[state] += sign * (mid - price as f64) * lots as f64;
                self.adv_lots[state] += lots;
            }
            let imb = (bid_lots - ask_lots) as f64 / (bid_lots + ask_lots) as f64;
            let wide = if spread >= 2 { 3 } else { 0 };
            let third = 1.0 / 3.0;
            self.bstate = wide + if imb < -third { 0 } else if imb > third { 2 } else { 1 };
            self.astate = wide + if imb > third { 0 } else if imb < -third { 2 } else { 1 };
            let n = self.adv_lots[self.bstate];
            bid_top = n < self.adv_min || self.adv_sum[self.bstate] >= self.adv_th * n as f64;
            let n = self.adv_lots[self.astate];
            ask_top = n < self.adv_min || self.adv_sum[self.astate] >= self.adv_th * n as f64;
        }
        // r1_F8_take_join.py's join and take orders (off in the other files)
        if self.join_lots > 0 && spread >= 2 {
            if hold_ask && !hold_bid && want_bid && bid_lots >= self.join_own {
                self.take(Side::Buy, best_bid + 1, self.join_lots, self.join_ms, true, ctx);
            }
            if hold_bid && !hold_ask && want_ask && ask_lots >= self.join_own {
                self.take(Side::Sell, best_ask - 1, self.join_lots, self.join_ms, true, ctx);
            }
        }
        if self.take_lots > 0 && spread == 1 {
            let mut ask_take = ask_dying;
            let mut bid_take = bid_dying;
            if self.take_deplete > 0 && self.depl_frac > 0.0 {
                let peak = |key: usize| self.peak[key].map_or(0, |(_, most)| most) as f64;
                ask_take = ask_lots < self.take_deplete && (ask_lots as f64) < self.depl_frac * peak(1);
                bid_take = bid_lots < self.take_deplete && (bid_lots as f64) < self.depl_frac * peak(0);
            }
            if ask_take
                && ask_lots <= self.take_max
                && want_bid
                && bid_lots >= self.take_own
                && bid_lots as f64 >= self.take_ratio * ask_lots2.max(1) as f64
            {
                self.take(Side::Buy, best_ask, self.take_lots, self.take_ms, false, ctx);
            }
            if bid_take
                && bid_lots <= self.take_max
                && want_ask
                && ask_lots >= self.take_own
                && ask_lots as f64 >= self.take_ratio * bid_lots2.max(1) as f64
            {
                self.take(Side::Sell, best_bid, self.take_lots, self.take_ms, false, ctx);
            }
        }
        self.ladder(Side::Buy, bid_anchor, want_bid, cancel_bid, bid_cap, bid_trim, bid_deep, bid_skip, bid_top, ctx);
        self.ladder(Side::Sell, ask_anchor, want_ask, cancel_ask, ask_cap, ask_trim, ask_deep, ask_skip, ask_top, ctx);
    }
}

/// Python's `min(a, b)` and `max(a, b)` on floats: the first argument unless the second is strictly beyond it.
fn py_min(a: f64, b: f64) -> f64 {
    if b < a { b } else { a }
}

fn py_max(a: f64, b: f64) -> f64 {
    if b > a { b } else { a }
}

impl Strategy for RoomMaker {
    fn on_book(&mut self, snapshot: &Snapshot, trades: &[Trade], ctx: &mut Ctx) {
        let bid = snapshot.market_touch(Side::Buy);
        let ask = snapshot.market_touch(Side::Sell);
        debug_assert_eq!(bid, touch(snapshot.bids()));
        debug_assert_eq!(ask, touch(snapshot.asks()));
        let lots2 =
            if self.take_ratio > 0.0 { (second_lots(snapshot.bids()), second_lots(snapshot.asks())) } else { (0, 0) };
        self.quote((snapshot.timestamp_us, bid, ask, lots2), trades, ctx);
    }

    /// Counts fills into the position; forgets orders that are done.
    fn on_private(&mut self, event: &PrivateEvent, ctx: &mut Ctx) {
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
                if self.adv_th > -1000.0 && !order.ioc {
                    if let Some(price) = event.fill_price {
                        let buy = order.side == Side::Buy;
                        self.pending.push_back((
                            event.timestamp_us + self.adv_ms * 1000,
                            if buy { 1.0 } else { -1.0 },
                            price,
                            event.filled_quantity,
                            if buy { self.bstate } else { self.astate },
                        ));
                    }
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
            if self.react_cancel && event.status == Status::Canceled {
                if let Some(touches) = self.snap {
                    self.quote(touches, &[], ctx);
                }
            }
        }
    }
}
