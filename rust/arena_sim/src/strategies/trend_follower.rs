//! strategies/trend_follower.py (`TrendFollowerStrategy`): a one-lot IOC at the touch in the direction of the
//! trades since the previous callback, one order in flight, never the same side twice in a row.
//!
//! Rust-only knobs (the Python file has no globals; their defaults are the file as written): `QUANTITY` (1),
//! the order's size, and `MIN_NET` (0), trading only when |net traded| > MIN_NET.

use crate::params::Params;
use crate::sim::{Ctx, PrivateEvent, Side, Snapshot, Status, Strategy, Trade};

pub struct TrendFollower {
    quantity: i64,
    min_net: i64,
    order_in_flight: bool,
    current_order_side: Option<Side>,
}

impl TrendFollower {
    pub fn new(params: &Params) -> Result<TrendFollower, String> {
        params.check_keys(&["QUANTITY", "MIN_NET"])?;
        Ok(TrendFollower { quantity: params.int("QUANTITY", 1)?, min_net: params.int("MIN_NET", 0)?, order_in_flight: false, current_order_side: None })
    }
}

impl Strategy for TrendFollower {
    fn on_book(&mut self, snapshot: &Snapshot, trades: &[Trade], ctx: &mut Ctx) {
        if self.order_in_flight {
            return;
        }
        // side_sign = {'ask': 1, 'bid': -1}
        let total_traded: i64 = trades.iter().map(|t| if t.book_side == Side::Sell { t.quantity } else { -t.quantity }).sum();
        if total_traded.abs() <= self.min_net {
            return;
        }
        let best_price = if total_traded > 0 {
            let Some(ask) = snapshot.asks().next() else { return };
            if self.current_order_side == Some(Side::Buy) {
                return;
            }
            self.current_order_side = Some(Side::Buy);
            ask.price
        } else {
            let Some(bid) = snapshot.bids().next() else { return };
            if self.current_order_side == Some(Side::Sell) {
                return;
            }
            self.current_order_side = Some(Side::Sell);
            bid.price
        };
        ctx.send_order(self.current_order_side.unwrap(), best_price, self.quantity, true);
        self.order_in_flight = true;
    }

    fn on_private(&mut self, event: &PrivateEvent, _ctx: &mut Ctx) {
        if event.status == Status::Filled {
            self.order_in_flight = false;
        } else if event.status == Status::Rejected || event.status == Status::Canceled {
            // Side.BUY if current == Side.SELL else Side.SELL (None flips to SELL too)
            self.current_order_side = Some(if self.current_order_side == Some(Side::Sell) { Side::Buy } else { Side::Sell });
        }
    }
}
