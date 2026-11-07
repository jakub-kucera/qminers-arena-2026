//! `simulator/simulator.py`'s `OrderBook` and `ExchangeSimulator`, step for step (the run and CSV loggers and
//! the progress bar left out: this is the `--no-logs` run). Function names follow the Python's.

use std::collections::{BTreeMap, HashMap, HashSet, VecDeque};
use std::hash::{BuildHasherDefault, Hasher};

pub use crate::data::Side;
use crate::data::Row;

pub const PNL_SAMPLE_INTERVAL_US: i64 = 1_000_000;
/// Our order ids: `u000000001` is USER_BIT | 1.
pub const USER_BIT: u64 = 1 << 63;

pub fn user_order_name(id: u64) -> String {
    format!("u{:09}", id & !USER_BIT)
}

/// A multiplicative hasher for the integer order ids (the default SipHash is several times slower).
#[derive(Default)]
pub struct IdHasher(u64);
impl Hasher for IdHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for &b in bytes {
            self.0 = (self.0.rotate_left(5) ^ b as u64).wrapping_mul(0x517cc1b727220a95);
        }
    }
    fn write_u64(&mut self, x: u64) {
        self.0 = (x ^ (x >> 29)).wrapping_mul(0x9e3779b97f4a7c15);
    }
}
pub type IdMap<V> = HashMap<u64, V, BuildHasherDefault<IdHasher>>;
pub type IdSet = HashSet<u64, BuildHasherDefault<IdHasher>>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Owner {
    Market,
    User,
}

impl Owner {
    pub fn name(self) -> &'static str {
        match self {
            Owner::Market => "market",
            Owner::User => "user",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    Accepted,
    PartiallyFilled,
    Filled,
    Modified,
    Canceled,
    Rejected,
}

#[derive(Clone, Debug)]
pub struct PrivateEvent {
    pub timestamp_us: i64,
    pub order_id: u64,
    pub status: Status,
    pub filled_quantity: i64,
    pub remaining_quantity: i64,
    pub fill_price: Option<i64>,
    pub message: Option<&'static str>,
}

#[derive(Clone, Copy, Debug)]
pub struct Trade {
    pub timestamp_us: i64,
    pub price: i64,
    pub quantity: i64,
    pub taker_order_id: u64,
    pub maker_order_id: u64,
    pub taker_owner: Owner,
    pub maker_owner: Owner,
    /// the side of the book the maker rested on (Buy: "bid", Sell: "ask")
    pub book_side: Side,
}

/// One resting order as the public feed shows it.
#[derive(Clone, Copy, Debug)]
pub struct BookOrder {
    pub order_id: u64,
    pub side: Side,
    pub price: i64,
    pub quantity: i64,
    pub owner: Owner,
}

#[derive(Clone, Copy, Debug)]
struct Order {
    id: u64,
    owner: Owner,
    side: Side,
    price: i64,
    remaining: i64,
}

// ---------------------------------------------------------------------------- the book

#[derive(Default)]
pub struct OrderBook {
    slots: Vec<Order>,
    free: Vec<usize>,
    orders: IdMap<usize>,
    /// price -> FIFO of slots; index 0 bids, 1 asks
    levels: [BTreeMap<i64, VecDeque<usize>>; 2],
    user_quantity: [i64; 2],
}

impl OrderBook {
    fn get(&self, id: u64) -> Option<usize> {
        self.orders.get(&id).copied()
    }

    fn insert(&mut self, order: Order) {
        if self.orders.contains_key(&order.id) {
            panic!("ValueError: Order {} already exists", order.id);
        }
        let slot = match self.free.pop() {
            Some(s) => {
                self.slots[s] = order;
                s
            }
            None => {
                self.slots.push(order);
                self.slots.len() - 1
            }
        };
        self.orders.insert(order.id, slot);
        self.levels[order.side.index()].entry(order.price).or_default().push_back(slot);
        if order.owner == Owner::User {
            self.user_quantity[order.side.index()] += order.remaining;
        }
    }

    fn remove(&mut self, id: u64) -> Option<Order> {
        let slot = self.orders.remove(&id)?;
        let order = self.slots[slot];
        let levels = &mut self.levels[order.side.index()];
        if let Some(queue) = levels.get_mut(&order.price) {
            if let Some(pos) = queue.iter().position(|&s| s == slot) {
                queue.remove(pos);
            }
            if queue.is_empty() {
                levels.remove(&order.price);
            }
        }
        if order.owner == Owner::User {
            self.user_quantity[order.side.index()] -= order.remaining;
        }
        self.free.push(slot);
        Some(order)
    }

    fn reduce_quantity(&mut self, slot: usize, amount: i64) {
        let order = &mut self.slots[slot];
        order.remaining -= amount;
        if order.owner == Owner::User {
            self.user_quantity[order.side.index()] -= amount;
        }
    }

    /// The first order a taker on `side` would match (skipping ours unless `allow_user_orders`).
    fn best_opposite_order(&self, side: Side, allow_user_orders: bool) -> Option<usize> {
        let opposite = side.opposite();
        let scan = |queue: &VecDeque<usize>| queue.iter().copied().find(|&s| allow_user_orders || self.slots[s].owner == Owner::Market);
        match opposite {
            Side::Sell => self.levels[1].values().find_map(scan),
            Side::Buy => self.levels[0].values().rev().find_map(scan),
        }
    }

    /// Live orders from the best price outwards, within `depth` ticks of the best live price (None: all).
    pub fn iter_levels(&self, side: Side, depth: Option<i64>) -> impl Iterator<Item = BookOrder> + '_ {
        let levels: Box<dyn Iterator<Item = (&i64, &VecDeque<usize>)>> = match side {
            Side::Buy => Box::new(self.levels[0].iter().rev()),
            Side::Sell => Box::new(self.levels[1].iter()),
        };
        let mut best: Option<i64> = None;
        levels
            .flat_map(move |(&price, queue)| queue.iter().map(move |&s| (price, s)))
            .filter(move |&(_, s)| self.slots[s].remaining > 0)
            .take_while(move |&(price, _)| {
                let b = *best.get_or_insert(price);
                depth.map_or(true, |d| (price - b).abs() < d)
            })
            .map(move |(_, s)| {
                let o = &self.slots[s];
                BookOrder { order_id: o.id, side: o.side, price: o.price, quantity: o.remaining, owner: o.owner }
            })
    }

    pub fn resting_user_quantity(&self, side: Side) -> i64 {
        self.user_quantity[side.index()]
    }
}

// ---------------------------------------------------------------------------- the strategy's side

/// The public book at a point in time: `bids()` and `asks()` iterate the orders within `public_depth` ticks
/// of the best price, best first (the Python snapshot's lists, without building them).
pub struct Snapshot<'a> {
    pub timestamp_us: i64,
    book: &'a OrderBook,
    depth: i64,
}

impl<'a> Snapshot<'a> {
    pub fn bids(&self) -> impl Iterator<Item = BookOrder> + 'a {
        self.book.iter_levels(Side::Buy, Some(self.depth))
    }
    pub fn asks(&self) -> impl Iterator<Item = BookOrder> + 'a {
        self.book.iter_levels(Side::Sell, Some(self.depth))
    }
    pub fn side(&self, side: Side) -> impl Iterator<Item = BookOrder> + 'a {
        self.book.iter_levels(side, Some(self.depth))
    }
}

#[derive(Clone, Copy, Debug)]
enum PendingKind {
    Order { side: Side, price: i64, quantity: i64, ioc: bool },
    Cancel,
    Modify { new_quantity: i64 },
}

#[derive(Clone, Copy, Debug)]
struct Pending {
    order_id: u64,
    ready_at_us: i64,
    kind: PendingKind,
}

/// The strategy's channel into the exchange: `send_order`, `cancel_order`, `modify_order`, `now_us`.
pub struct Ctx {
    now_us: i64,
    accept_delay_us: i64,
    user_order_seq: u64,
    pending: Vec<Pending>,
}

impl Ctx {
    pub fn now_us(&self) -> i64 {
        self.now_us
    }
    /// Queues an order; it activates 5 ms from now. Returns its id (USER_BIT | sequence).
    pub fn send_order(&mut self, side: Side, price: i64, quantity: i64, ioc: bool) -> u64 {
        assert!(price > 0 && quantity > 0, "OrderRequest needs a positive price and quantity (pydantic raises)");
        self.user_order_seq += 1;
        let order_id = USER_BIT | self.user_order_seq;
        self.pending.push(Pending { order_id, ready_at_us: self.now_us + self.accept_delay_us, kind: PendingKind::Order { side, price, quantity, ioc } });
        order_id
    }
    pub fn cancel_order(&mut self, order_id: u64) {
        self.pending.push(Pending { order_id, ready_at_us: self.now_us + self.accept_delay_us, kind: PendingKind::Cancel });
    }
    pub fn modify_order(&mut self, order_id: u64, new_quantity: i64) {
        self.pending.push(Pending { order_id, ready_at_us: self.now_us + self.accept_delay_us, kind: PendingKind::Modify { new_quantity } });
    }
}

pub trait Strategy {
    /// After every market event: the public book and every trade since the previous call.
    fn on_book(&mut self, snapshot: &Snapshot, trades: &[Trade], ctx: &mut Ctx);
    /// Every state change of our own orders, synchronously during matching.
    fn on_private(&mut self, event: &PrivateEvent, ctx: &mut Ctx);
}

// ---------------------------------------------------------------------------- the simulator

#[derive(Clone, Debug)]
pub struct Config {
    pub order_accept_delay_ms: i64,
    pub public_depth: i64,
    pub max_position: Option<i64>,
    pub max_potential_position: Option<i64>,
    pub position_breach_penalty_per_second: f64,
}

impl Default for Config {
    /// simulator.main's constants: the rules.
    fn default() -> Config {
        Config { order_accept_delay_ms: 5, public_depth: 20, max_position: Some(100), max_potential_position: Some(1000), position_breach_penalty_per_second: 10_000.0 }
    }
}

/// `SimulationResult`, plus the PnL curve (`pnl_curve`) and the rejects arena.qgrid counts.
#[derive(Clone, Debug)]
pub struct Outcome {
    pub fills: usize,
    pub traded_volume: i64,
    pub inventory: i64,
    pub cash: f64,
    pub mark_price: f64,
    pub breach_penalty: f64,
    pub pnl: f64,
    pub pnl_se: Option<f64>,
    pub abs_inventory_q50: i64,
    pub abs_inventory_q68: i64,
    pub abs_inventory_q95: i64,
    pub abs_inventory_q997: i64,
    pub curve: Vec<(i64, f64)>,
    /// orders refused at activation (the potential-position cap)
    pub rejected: u64,
    /// cancels and modifies rejected (no resting order, or a modify that doesn't shrink)
    pub cancel_rejected: u64,
}

struct Taker {
    id: u64,
    owner: Owner,
    side: Side,
    price: i64,
    remaining: i64,
    ioc: bool,
}

pub struct ExchangeSimulator {
    config: Config,
    book: OrderBook,
    ctx: Ctx,
    last_event_us: Option<i64>,
    trades: Vec<Trade>,
    filled_order_ids: IdSet,
    user_traded_volume: i64,
    inventory: i64,
    cash: f64,
    breach_penalty: f64,
    last_trade_price: Option<f64>,
    next_pnl_sample_us: Option<i64>,
    pnl_sample_times_us: Vec<i64>,
    pnl_samples: Vec<f64>,
    abs_inventory_time_us: Vec<i64>,
    rejected: u64,
    cancel_rejected: u64,
}

impl ExchangeSimulator {
    pub fn new(config: Config) -> ExchangeSimulator {
        if let Some(potential) = config.max_potential_position {
            let max = config.max_position.expect("max_potential_position requires max_position to be set");
            assert!(potential >= max, "max_potential_position must be >= max_position");
        }
        let delay = config.order_accept_delay_ms * 1_000;
        ExchangeSimulator {
            config,
            book: OrderBook::default(),
            ctx: Ctx { now_us: 0, accept_delay_us: delay, user_order_seq: 0, pending: Vec::new() },
            last_event_us: None,
            trades: Vec::new(),
            filled_order_ids: IdSet::default(),
            user_traded_volume: 0,
            inventory: 0,
            cash: 0.0,
            breach_penalty: 0.0,
            last_trade_price: None,
            next_pnl_sample_us: None,
            pnl_sample_times_us: Vec::new(),
            pnl_samples: Vec::new(),
            abs_inventory_time_us: Vec::new(),
            rejected: 0,
            cancel_rejected: 0,
        }
    }

    pub fn run(mut self, rows: &[Row], strategy: &mut dyn Strategy) -> Outcome {
        for row in rows {
            self.last_event_us = Some(row.ts);
            if !self.ctx.pending.is_empty() {
                self.activate_pending_orders_up_to(Some(row.ts), strategy);
            }
            self.advance_time(row.ts);
            self.process_market_event(row, strategy);
            // _emit_public_snapshot
            let snapshot = Snapshot { timestamp_us: self.ctx.now_us, book: &self.book, depth: self.config.public_depth };
            strategy.on_book(&snapshot, &self.trades, &mut self.ctx);
            self.trades.clear();
        }
        self.activate_pending_orders_up_to(None, strategy);

        let mark_price = self.mark_price();
        let pnl = self.mark_to_market_pnl();
        let curve = self.pnl_curve(pnl);
        Outcome {
            fills: self.filled_order_ids.len(),
            traded_volume: self.user_traded_volume,
            inventory: self.inventory,
            cash: self.cash,
            mark_price,
            breach_penalty: self.breach_penalty,
            pnl,
            pnl_se: self.pnl_standard_error(),
            abs_inventory_q50: self.abs_inventory_quantile(0.5),
            abs_inventory_q68: self.abs_inventory_quantile(0.68),
            abs_inventory_q95: self.abs_inventory_quantile(0.95),
            abs_inventory_q997: self.abs_inventory_quantile(0.997),
            curve,
            rejected: self.rejected,
            cancel_rejected: self.cancel_rejected,
        }
    }

    fn process_market_event(&mut self, row: &Row, strategy: &mut dyn Strategy) {
        if row.insert {
            let mut taker = Taker { id: row.id, owner: Owner::Market, side: row.side, price: row.price, remaining: row.volume, ioc: row.ioc };
            self.execute_taker(&mut taker, strategy);
            if !taker.ioc && taker.remaining > 0 {
                self.book.insert(Order { id: taker.id, owner: Owner::Market, side: taker.side, price: taker.price, remaining: taker.remaining });
            }
        } else {
            self.book.remove(row.id);
        }
    }

    /// Activates every pending item due by `timestamp_us` (all of them when None), in ready order. Items the
    /// strategy queues meanwhile wait for the next call, as in the Python (it iterates a sorted copy).
    fn activate_pending_orders_up_to(&mut self, timestamp_us: Option<i64>, strategy: &mut dyn Strategy) {
        let mut pending = std::mem::take(&mut self.ctx.pending);
        pending.sort_by_key(|item| item.ready_at_us); // stable, as sorted()
        for item in pending {
            if let Some(t) = timestamp_us {
                if item.ready_at_us > t {
                    self.ctx.pending.push(item);
                    continue;
                }
            }
            self.advance_time(self.ctx.now_us.max(item.ready_at_us));
            match item.kind {
                PendingKind::Order { side, price, quantity, ioc } => self.activate_order(item.order_id, side, price, quantity, ioc, strategy),
                PendingKind::Cancel => self.activate_cancel(item.order_id, strategy),
                PendingKind::Modify { new_quantity } => self.activate_modify(item.order_id, new_quantity, strategy),
            }
        }
    }

    fn event(&self, order_id: u64, status: Status, remaining_quantity: i64) -> PrivateEvent {
        PrivateEvent { timestamp_us: self.ctx.now_us, order_id, status, filled_quantity: 0, remaining_quantity, fill_price: None, message: None }
    }

    fn activate_order(&mut self, order_id: u64, side: Side, price: i64, quantity: i64, ioc: bool, strategy: &mut dyn Strategy) {
        if self.exceeds_position_limit(side, quantity) {
            self.rejected += 1;
            let event = self.event(order_id, Status::Rejected, 0);
            self.private_notify(&event, strategy);
            return;
        }
        let event = self.event(order_id, Status::Accepted, quantity);
        self.private_notify(&event, strategy);
        let mut taker = Taker { id: order_id, owner: Owner::User, side, price, remaining: quantity, ioc };
        self.execute_taker(&mut taker, strategy);
        if taker.ioc || taker.remaining == 0 {
            return;
        }
        self.book.insert(Order { id: order_id, owner: Owner::User, side, price, remaining: taker.remaining });
    }

    fn activate_cancel(&mut self, order_id: u64, strategy: &mut dyn Strategy) {
        let ours = self.book.get(order_id).map_or(false, |slot| self.book.slots[slot].owner == Owner::User);
        if !ours {
            self.cancel_rejected += 1;
            let mut event = self.event(order_id, Status::Rejected, 0);
            event.message = Some("cancel rejected: no resting order with this id");
            self.private_notify(&event, strategy);
            return;
        }
        let removed = self.book.remove(order_id).unwrap();
        let event = self.event(order_id, Status::Canceled, removed.remaining);
        self.private_notify(&event, strategy);
    }

    fn activate_modify(&mut self, order_id: u64, new_quantity: i64, strategy: &mut dyn Strategy) {
        let slot = match self.book.get(order_id) {
            Some(slot) if self.book.slots[slot].owner == Owner::User => slot,
            _ => return, // a modify of an unknown id is silently ignored
        };
        let remaining = self.book.slots[slot].remaining;
        if !(0 < new_quantity && new_quantity < remaining) {
            self.cancel_rejected += 1;
            let event = self.event(order_id, Status::Rejected, remaining);
            self.private_notify(&event, strategy);
            return;
        }
        self.book.reduce_quantity(slot, remaining - new_quantity);
        let event = self.event(order_id, Status::Modified, self.book.slots[slot].remaining);
        self.private_notify(&event, strategy);
    }

    fn execute_taker(&mut self, taker: &mut Taker, strategy: &mut dyn Strategy) {
        while taker.remaining > 0 {
            let Some(slot) = self.book.best_opposite_order(taker.side, taker.owner == Owner::Market) else { break };
            let maker = self.book.slots[slot];
            let crosses = match taker.side {
                Side::Buy => taker.price >= maker.price,
                Side::Sell => taker.price <= maker.price,
            };
            if !crosses {
                break;
            }
            let traded = taker.remaining.min(maker.remaining);
            taker.remaining -= traded;
            self.book.reduce_quantity(slot, traded);
            let maker_remaining = self.book.slots[slot].remaining;
            self.trades.push(Trade {
                timestamp_us: self.ctx.now_us,
                price: maker.price,
                quantity: traded,
                taker_order_id: taker.id,
                maker_order_id: maker.id,
                taker_owner: taker.owner,
                maker_owner: maker.owner,
                book_side: maker.side,
            });
            if taker.owner == Owner::User || maker.owner == Owner::User {
                self.user_traded_volume += traded;
            }
            self.last_trade_price = Some(maker.price as f64);
            for (owner, side) in [(taker.owner, taker.side), (maker.owner, maker.side)] {
                if owner != Owner::User {
                    continue;
                }
                let sign = side.sign();
                self.inventory += sign * traded;
                self.cash -= (sign * traded * maker.price) as f64;
            }
            if maker.owner == Owner::User {
                self.notify_fill(maker.id, maker_remaining, traded, maker.price, strategy);
            }
            if taker.owner == Owner::User {
                self.notify_fill(taker.id, taker.remaining, traded, maker.price, strategy);
            }
            if maker_remaining == 0 {
                self.book.remove(maker.id);
            }
        }
        if taker.owner == Owner::User && taker.ioc && taker.remaining > 0 {
            let event = self.event(taker.id, Status::Canceled, taker.remaining);
            self.private_notify(&event, strategy);
        }
    }

    fn notify_fill(&mut self, order_id: u64, remaining: i64, quantity: i64, price: i64, strategy: &mut dyn Strategy) {
        let status = if remaining == 0 { Status::Filled } else { Status::PartiallyFilled };
        let event = PrivateEvent { timestamp_us: self.ctx.now_us, order_id, status, filled_quantity: quantity, remaining_quantity: remaining, fill_price: Some(price), message: None };
        self.private_notify(&event, strategy);
    }

    fn private_notify(&mut self, event: &PrivateEvent, strategy: &mut dyn Strategy) {
        if matches!(event.status, Status::Filled | Status::PartiallyFilled) {
            self.filled_order_ids.insert(event.order_id);
        }
        strategy.on_private(event, &mut self.ctx);
    }

    fn exceeds_position_limit(&self, side: Side, quantity: i64) -> bool {
        let Some(limit) = self.config.max_potential_position.or(self.config.max_position) else { return false };
        let worst_case = self.inventory + side.sign() * (self.book.resting_user_quantity(side) + quantity);
        worst_case.abs() > limit
    }

    fn advance_time(&mut self, timestamp_us: i64) {
        let Some(mut next) = self.next_pnl_sample_us else {
            self.ctx.now_us = timestamp_us;
            self.pnl_sample_times_us.push(timestamp_us);
            let pnl = self.mark_to_market_pnl();
            self.pnl_samples.push(pnl);
            self.next_pnl_sample_us = Some(timestamp_us + PNL_SAMPLE_INTERVAL_US);
            return;
        };
        if timestamp_us > self.ctx.now_us {
            let level = self.inventory.unsigned_abs() as usize;
            if self.abs_inventory_time_us.len() <= level {
                self.abs_inventory_time_us.resize(level + 1, 0);
            }
            self.abs_inventory_time_us[level] += timestamp_us - self.ctx.now_us;
            while next <= timestamp_us {
                self.accrue_breach_penalty(next);
                self.pnl_sample_times_us.push(next);
                let pnl = self.mark_to_market_pnl();
                self.pnl_samples.push(pnl);
                next += PNL_SAMPLE_INTERVAL_US;
            }
            self.next_pnl_sample_us = Some(next);
            self.accrue_breach_penalty(timestamp_us);
        }
    }

    fn accrue_breach_penalty(&mut self, timestamp_us: i64) {
        if let Some(limit) = self.config.max_position {
            if self.inventory.abs() > limit {
                let elapsed_s = (timestamp_us - self.ctx.now_us) as f64 / 1_000_000.0;
                self.breach_penalty += elapsed_s * self.config.position_breach_penalty_per_second;
            }
        }
        self.ctx.now_us = timestamp_us;
    }

    fn pnl_curve(&self, final_pnl: f64) -> Vec<(i64, f64)> {
        let Some(end_us) = self.last_event_us else { return vec![(self.ctx.now_us, final_pnl)] };
        let mut out: Vec<(i64, f64)> =
            self.pnl_sample_times_us.iter().zip(&self.pnl_samples).filter(|(&ts, _)| ts < end_us).map(|(&ts, &pnl)| (ts, pnl)).collect();
        out.push((end_us, final_pnl));
        out
    }

    fn mark_to_market_pnl(&self) -> f64 {
        self.cash + self.mark_out_value() - self.breach_penalty
    }

    fn pnl_standard_error(&self) -> Option<f64> {
        let increments: Vec<f64> = self.pnl_samples.windows(2).map(|w| w[1] - w[0]).collect();
        if increments.len() < 2 {
            return None;
        }
        Some(crate::py::stdev(&increments) * (increments.len() as f64).sqrt())
    }

    fn abs_inventory_quantile(&self, quantile: f64) -> i64 {
        let total_us: i64 = self.abs_inventory_time_us.iter().sum();
        let threshold = quantile * total_us as f64;
        let mut held_us = 0i64;
        for (level, &time) in self.abs_inventory_time_us.iter().enumerate() {
            if time == 0 {
                continue; // no such key in the Python's defaultdict
            }
            held_us += time;
            if held_us as f64 >= threshold {
                return level as i64;
            }
        }
        0
    }

    fn mark_out_value(&self) -> f64 {
        if self.inventory == 0 {
            return 0.0;
        }
        let mut remaining = self.inventory.abs();
        let mut last_price = self.last_trade_price.expect("inventory without a trade");
        let mut value = 0.0f64;
        let side = if self.inventory > 0 { Side::Buy } else { Side::Sell };
        for order in self.book.iter_levels(side, None) {
            if order.owner != Owner::Market {
                continue;
            }
            let filled = remaining.min(order.quantity);
            value += (filled * order.price) as f64;
            last_price = order.price as f64;
            remaining -= filled;
            if remaining == 0 {
                break;
            }
        }
        value += remaining as f64 * last_price;
        if self.inventory > 0 {
            value
        } else {
            -value
        }
    }

    fn mark_price(&self) -> f64 {
        if self.inventory == 0 {
            return self.last_trade_price.unwrap_or(0.0);
        }
        self.mark_out_value() / self.inventory as f64
    }
}
