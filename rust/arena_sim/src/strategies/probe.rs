//! python/tests/fixtures/qsim_probe.py (`ProbeStrategy`), line for line: random limit orders, IOCs, cancels and
//! modifies (valid or not), orders sent mid-activation, the position cap and the penalty, all driven by an LCG
//! that every trade, snapshot and private event feeds, so the parity test sees any difference in the engine.
//! Parameters: `QMAX` (40), `EVERY` (3), `SEED` (1).

use crate::params::Params;
use crate::sim::{Ctx, Owner, PrivateEvent, Side, Snapshot, Status, Strategy, Trade, USER_BIT};

pub struct Probe {
    qmax: u64,
    every: u64,
    x: u64,
    ids: Vec<u64>,
    orders: std::collections::HashMap<u64, (Side, i64)>,
    sent: u64,
}

fn status_code(s: Status) -> u64 {
    match s {
        Status::Accepted => 0,
        Status::PartiallyFilled => 1,
        Status::Filled => 2,
        Status::Modified => 3,
        Status::Canceled => 4,
        Status::Rejected => 5,
    }
}

impl Probe {
    pub fn new(params: &Params) -> Result<Probe, String> {
        params.check_keys(&["QMAX", "EVERY", "SEED"])?;
        Ok(Probe {
            qmax: params.int("QMAX", 40)? as u64,
            every: params.int("EVERY", 3)? as u64,
            x: params.int("SEED", 1)? as u64,
            ids: Vec::new(),
            orders: Default::default(),
            sent: 0,
        })
    }

    fn draw(&mut self, mix: u64) -> u64 {
        self.x = self.x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407).wrapping_add(mix);
        self.x >> 33
    }

    fn send(&mut self, side: Side, price: i64, quantity: i64, ioc: bool, ctx: &mut Ctx) {
        let id = ctx.send_order(side, price, quantity, ioc);
        self.sent += 1;
        self.ids.push(id);
        self.orders.insert(id, (side, price));
    }
}

impl Strategy for Probe {
    fn on_book(&mut self, snapshot: &Snapshot, trades: &[Trade], ctx: &mut Ctx) {
        let mut mix: u64 = 0;
        for t in trades {
            let q = t.quantity as u64 * if t.book_side == Side::Sell { 1 } else { 3 };
            mix += q + if t.taker_owner == Owner::User { 5 } else { 0 } + if t.maker_owner == Owner::User { 11 } else { 0 } + t.price as u64;
        }
        let bids: Vec<_> = snapshot.bids().collect();
        let asks: Vec<_> = snapshot.asks().collect();
        mix += 13 * bids.len() as u64 + 17 * asks.len() as u64 + bids.iter().map(|o| o.quantity as u64).sum::<u64>();
        mix += 19 * asks.iter().filter(|o| o.owner == Owner::User).count() as u64 + snapshot.timestamp_us as u64 + ctx.now_us() as u64;
        let mut r = self.draw(mix);
        if r % self.every != 0 {
            return;
        }
        r /= self.every;
        let action = r % 8;
        r /= 8;
        if action < 4 {
            let side = if action % 2 == 0 { Side::Buy } else { Side::Sell };
            let ioc = action >= 2;
            let quantity = (1 + (r / 5) % self.qmax) as i64;
            if bids.is_empty() || asks.is_empty() {
                return;
            }
            let ri = r as i64;
            let price = match (side, ioc) {
                (Side::Buy, true) => asks[0].price + ri % 3,
                (Side::Buy, false) => bids[0].price + ri % 5 - 2,
                (Side::Sell, true) => bids[0].price - ri % 3,
                (Side::Sell, false) => asks[0].price - ri % 5 + 2,
            };
            self.send(side, price.max(1), quantity, ioc, ctx);
        } else if action == 4 && !self.ids.is_empty() {
            ctx.cancel_order(self.ids[(r % self.ids.len() as u64) as usize]);
        } else if action == 5 && !self.ids.is_empty() {
            ctx.modify_order(self.ids[(r % self.ids.len() as u64) as usize], ((r / 7) % 12) as i64);
        } else if action == 6 && self.sent > 0 {
            ctx.cancel_order(USER_BIT | (1 + r % self.sent));
        } else if action == 7 && self.sent > 0 {
            ctx.modify_order(USER_BIT | (1 + r % (self.sent + 3)), (1 + r % 3) as i64);
        }
    }

    fn on_private(&mut self, event: &PrivateEvent, ctx: &mut Ctx) {
        let add = 7 * status_code(event.status)
            + 3 * event.filled_quantity as u64
            + event.remaining_quantity as u64
            + event.fill_price.unwrap_or(0) as u64
            + event.timestamp_us as u64
            + event.message.is_some() as u64;
        self.x = self.x.wrapping_add(add);
        if matches!(event.status, Status::Filled | Status::Canceled | Status::Rejected) {
            if let Some(pos) = self.ids.iter().position(|&id| id == event.order_id) {
                self.ids.remove(pos);
            }
        }
        if event.status == Status::PartiallyFilled && event.remaining_quantity > 2 && event.filled_quantity % 2 == 0 {
            ctx.modify_order(event.order_id, event.remaining_quantity / 2);
        }
        if event.status == Status::Rejected && event.message.is_none() && event.remaining_quantity == 0 {
            let (side, price) = self.orders[&event.order_id];
            if self.x % 2 == 1 {
                self.send(side, price, 1, false, ctx);
            }
        }
    }
}
