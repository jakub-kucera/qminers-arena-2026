//! python/bots/qminers/candidates/r0_F1_fallback.py (`FallbackMakerStrategy`): QUOTE lots a side at, or a tick
//! inside, the market's touch; a quote kept while its price is wanted; every order that can still fill counted
//! against LIMIT; only the reducing side quoted in the last WIND_DOWN_S of SESSION_S.
//!
//! Parameters: the file's globals `QUOTE` (5), `LIMIT` (50), `SKEW` (20), `WIND_DOWN_S` (60), `SESSION_S`
//! (3600); Rust-only `INSIDE_SPREAD` (3), the spread from which it quotes a tick inside (a literal in the file).

use crate::params::Params;
use crate::sim::{Ctx, Owner, PrivateEvent, Side, Snapshot, Status, Strategy, Trade};

struct Quote {
    id: u64,
    side: Side,
    price: i64,
    quantity: i64,
    cancelling: bool,
}

pub struct FallbackMaker {
    quote: i64,
    limit: i64,
    skew: i64,
    wind_down_s: f64,
    session_s: f64,
    inside_spread: i64,
    position: i64,
    /// the Python's insertion-ordered dict id -> [side, price, quantity left, cancelling]
    orders: Vec<Quote>,
    start_us: Option<i64>,
}

impl FallbackMaker {
    pub fn new(params: &Params) -> Result<FallbackMaker, String> {
        params.check_keys(&["QUOTE", "LIMIT", "SKEW", "WIND_DOWN_S", "SESSION_S", "INSIDE_SPREAD"])?;
        Ok(FallbackMaker {
            quote: params.int("QUOTE", 5)?,
            limit: params.int("LIMIT", 50)?,
            skew: params.int("SKEW", 20)?,
            wind_down_s: params.float("WIND_DOWN_S", 60.0)?,
            session_s: params.float("SESSION_S", 3600.0)?,
            inside_spread: params.int("INSIDE_SPREAD", 3)?,
            position: 0,
            orders: Vec::new(),
            start_us: None,
        })
    }

    /// Cancels this side's quotes at any other price; posts one at `price` if none is there and the limit allows.
    fn keep_one(&mut self, side: Side, price: Option<i64>, ctx: &mut Ctx) {
        let mut have = false;
        for order in self.orders.iter_mut() {
            if order.side != side || order.cancelling {
                continue;
            }
            if price.is_some() && Some(order.price) == price && !have {
                have = true;
            } else {
                ctx.cancel_order(order.id);
                order.cancelling = true;
            }
        }
        let Some(price) = price else { return };
        if have {
            return;
        }
        let exposure: i64 = self.orders.iter().filter(|o| o.side == side).map(|o| o.quantity).sum();
        let room = match side {
            Side::Buy => self.limit - self.position - exposure,
            Side::Sell => self.limit + self.position - exposure,
        };
        let quantity = self.quote.min(room);
        if quantity <= 0 {
            return;
        }
        let id = ctx.send_order(side, price, quantity, false);
        self.orders.push(Quote { id, side, price, quantity, cancelling: false });
    }
}

impl Strategy for FallbackMaker {
    fn on_book(&mut self, snapshot: &Snapshot, _trades: &[Trade], ctx: &mut Ctx) {
        let start = *self.start_us.get_or_insert(snapshot.timestamp_us);
        let Some(bid) = snapshot.bids().find(|o| o.owner == Owner::Market) else { return };
        let Some(ask) = snapshot.asks().find(|o| o.owner == Owner::Market) else { return };
        let (best_bid, best_ask) = (bid.price, ask.price);
        let (bid_price, ask_price) =
            if best_ask - best_bid >= self.inside_spread { (best_bid + 1, best_ask - 1) } else { (best_bid, best_ask) };
        let elapsed_s = (snapshot.timestamp_us - start) as f64 / 1_000_000.0;
        let winding_down = elapsed_s > self.session_s - self.wind_down_s;
        let want_bid = self.position < self.skew && !(winding_down && self.position >= 0);
        let want_ask = self.position > -self.skew && !(winding_down && self.position <= 0);
        self.keep_one(Side::Buy, want_bid.then_some(bid_price), ctx);
        self.keep_one(Side::Sell, want_ask.then_some(ask_price), ctx);
    }

    /// Counts fills into the position; forgets orders that are done.
    fn on_private(&mut self, event: &PrivateEvent, _ctx: &mut Ctx) {
        let Some(index) = self.orders.iter().position(|o| o.id == event.order_id) else { return };
        match event.status {
            Status::PartiallyFilled | Status::Filled => {
                let order = &mut self.orders[index];
                if order.side == Side::Buy {
                    self.position += event.filled_quantity;
                } else {
                    self.position -= event.filled_quantity;
                }
                order.quantity = event.remaining_quantity;
                if event.status == Status::Filled || event.remaining_quantity == 0 {
                    self.orders.remove(index);
                }
            }
            Status::Canceled | Status::Rejected => {
                self.orders.remove(index);
            }
            _ => {}
        }
    }
}
