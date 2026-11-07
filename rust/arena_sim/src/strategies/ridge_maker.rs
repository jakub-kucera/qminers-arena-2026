//! python/bots/qminers/candidates/r1_C1_codex_ridge.py (`PassiveStrategy`, round 1's candidate R1-C1), line for
//! line: an online ridge regression of the mid HORIZON_US ahead on 15 features (trade flow, the 500 ms / 2 s mid
//! EWMA gap, touch and near-touch imbalances, order counts, capped lots, signed squares), an observation every
//! OBSERVATION_INTERVAL_US, labels decayed over MODEL_MEMORY_US, refit by Gauss-Jordan once a second; quotes at
//! min(touch, floor(fair - 0.5)) / mirror, a tick inside when the edge clears INSIDE_TH, up to MAX_ORDERS orders
//! a side, the limit counting every live order, and re-quoting on a cancel landing within 5 ms.
//! The floating-point operations are in the Python's order, so the results are the same to the bit.
//!
//! Parameters, the class constants: `HORIZON_US` (100000), `OBSERVATION_INTERVAL_US` (20000), `MIN_LABELS` (200),
//! `MODEL_MEMORY_US` (300000000), `POSITION_LIMIT` (100), `QUOTE_SIZE` (200), `REQUOTE_US` (0); Rust-only knobs
//! for the file's literals: `INSIDE_TH` (0.3, the predicted edge for a tick inside), `FLOW_CUT` (1.1, the flow
//! beyond which a side is withdrawn), `SKEW_K` (0.025, the inventory skew per spread), `DEAD_ZONE` (0.1, |fair -
//! mid| at or below which fair is the mid), `MAX_ORDERS` (8, a side), `FAST_US` (500000) and `SLOW_US` (2000000),
//! the mid EWMAs, `FLOW_US` (500000, the trade flow's decay), `OFI_US` (500000, the OFI's), `RIDGE_MIN` (10.0) and
//! `RIDGE_FRAC` (0.001): ridge = max(RIDGE_MIN, RIDGE_FRAC * mass), `FIT_US` (1000000, between refits),
//! `REPLENISH_US` (5000, how long after a quote a landed cancel re-quotes), `PRED_MIX` (1.0, the model's weight in
//! fair).
//!
//! Rust-only additions from R1-F8 (python/bots/qminers/candidates/r1_F8_take_join.py, `take_maker`), off by
//! default, so the defaults are R1-C1 as written: the depletion guard, `DEPLETE_LOTS` (0: off) and `DEPL_FRAC`
//! (0.12): when the market's lots at its touch are under DEPLETE_LOTS and under DEPL_FRAC of their peak since that
//! price became the touch (DEPL_FRAC 0: the lots alone), a quote of ours at that touch moves a tick back (ours there
//! cancelled, the room posted behind); the take, `TAKE_LOTS` (0: off), `TAKE_OWN` (800), `TAKE_DEPLETE` (150),
//! `TAKE_MAX` (1000), `TAKE_MS` (250): at a one-tick spread, when the other side's touch is dying (under TAKE_DEPLETE
//! lots and under DEPL_FRAC of its peak; without both, the guard's test) with at most TAKE_MAX lots while ours holds
//! TAKE_OWN or more and we still quote our side, a limit order of TAKE_LOTS (within the limit) at the other side's
//! touch, at most one a side per TAKE_MS, exempt from the re-quote's cancels for TAKE_MS (take_maker's `take`).
//!
//! Learned-model knobs, all off by default (C1 to the bit): `PLACE` (0; 1 adds two features: the share of new market
//! orders landing at/inside the previous touch, bids minus asks, decayed over `PLACE_US1` 100000 and `PLACE_US2` 300000),
//! `DEPTH5` (5-level lots imbalance), `FLOW2` (signed flow over 0.1 s and 2 s), `LAST_AGG` (signed ln(1+lots) of the
//! last aggressive order), `STD` with `STD_US` (scale each feature by its running RMS), `BLEND_W` (0) with `H2_US`
//! (500000): a second ridge on the same features at the H2_US horizon, prediction = (1-W) p1 + W p2.
//! Rust-only additions from v2 (strategy_codex_best_v2_571k.py, 571k), off by default: `EXPOSURE` (0: the
//! POSITION_LIMIT), the lots the quoting, the skew and the withdrawal aim at, while POSITION_LIMIT stays the
//! acceptance wall (v2: POSITION_LIMIT=1000 EXPOSURE=100); `CANCEL_FREE` (0.0): the share of an order being
//! cancelled that no longer counts toward EXPOSURE (v2: 1.0, `ceil(q * (1 - CANCEL_FREE))`); `HEDGE` (0: off), an
//! IOC HEDGE_TICKS (10) through the cached touch (at most HEDGE_STALE_US, 100000, old) for |inventory| - EXPOSURE
//! whenever |inventory| > EXPOSURE, one at a time, from book updates and from private fills (v2's `_hedge`).

use std::collections::{HashSet, VecDeque};

use crate::params::Params;
use crate::sim::{Ctx, Owner, PrivateEvent, Side, Snapshot, Status, Strategy, Trade};

const N: usize = 15;
const NM: usize = 24;
const OBS_MAXLEN: usize = 64;

struct Record {
    id: u64,
    sign: i64,
    price: i64,
    quantity: i64,
    accepted: bool,
    cancelling: bool,
    /// a take order: not cancelled by the quoting before this time
    exempt_until: i64,
}

/// CPython 3.12's `sum()` of floats, start 0 (rust/src/support/py.rs `sum`).
fn py_sum(xs: impl IntoIterator<Item = f64>) -> f64 {
    let mut it = xs.into_iter();
    let Some(first) = it.next() else { return 0.0 };
    let mut f = 0.0 + first;
    let mut c = 0.0f64;
    for x in it {
        let t = f + x;
        if f.abs() >= x.abs() {
            c += (f - t) + x;
        } else {
            c += (x - t) + f;
        }
        f = t;
    }
    if c != 0.0 && c.is_finite() {
        f += c;
    }
    f
}

/// Python's max(lo, min(hi, x)) on floats (equal values keep the first, which is the same number).
fn clamp(x: f64, lo: f64, hi: f64) -> f64 {
    let m = if x < hi { x } else { hi };
    if m > lo {
        m
    } else {
        lo
    }
}

struct Model {
    horizon_us: i64,
    observations: VecDeque<(i64, f64, [f64; NM])>,
    last_fit_us: Option<i64>,
    last_label_us: Option<i64>,
    labels: i64,
    mass: f64,
    xx: [[f64; NM]; NM],
    xy: [f64; NM],
    weights: [f64; NM],
}

impl Model {
    fn new(horizon_us: i64) -> Model {
        Model {
            horizon_us,
            observations: VecDeque::with_capacity(OBS_MAXLEN),
            last_fit_us: None,
            last_label_us: None,
            labels: 0,
            mass: 0.0,
            xx: [[0.0; NM]; NM],
            xy: [0.0; NM],
            weights: [0.0; NM],
        }
    }
}

pub struct RidgeMaker {
    horizon_us: i64,
    observation_interval_us: i64,
    min_labels: i64,
    model_memory_us: i64,
    position_limit: i64,
    quote_size: i64,
    requote_us: i64,
    inside_th: f64,
    flow_cut: f64,
    skew_k: f64,
    dead_zone: f64,
    max_orders: usize,
    fast_us: i64,
    slow_us: i64,
    flow_us: i64,
    ofi_us: i64,
    ridge_min: f64,
    ridge_frac: f64,
    fit_us: i64,
    replenish_us: i64,
    pred_mix: f64,
    deplete_lots: i64,
    depl_frac: f64,
    take_lots: i64,
    take_own: i64,
    take_deplete: i64,
    take_max: i64,
    take_ms: i64,
    take_block: [i64; 2],
    exposure: i64,
    cancel_free: f64,
    hedge: bool,
    hedge_ticks: i64,
    hedge_stale_us: i64,
    hedge_id: Option<u64>,
    cached: Option<(i64, i64, i64)>,
    /// per side (bid, ask): [touch price, the market's lots there at their most since]
    peak: [Option<(i64, i64)>; 2],

    inventory: i64,
    orders: Vec<Record>,
    desired_buy: Option<i64>,
    desired_sell: Option<i64>,
    desired_time: Option<i64>,
    m1: Model,
    m2: Model,
    n: usize,
    last_observation_us: i64,
    place: i64,
    place_us1: i64,
    place_us2: i64,
    depth5: i64,
    flow2: i64,
    last_agg: i64,
    std_on: i64,
    std_us: i64,
    blend_w: f64,
    seen: HashSet<u64>,
    seen_next: HashSet<u64>,
    /// per tau: [bid at/inside, bid all, ask at/inside, ask all]
    place_acc: [[f64; 4]; 2],
    flow_fast: (f64, f64),
    flow_slow: (f64, f64),
    last_agg_value: f64,
    std_m2: [f64; NM],
    std_mass: f64,
    fast_mid: f64,
    slow_mid: f64,
    model_time: Option<i64>,
    ofi: f64,
    ofi_time: Option<i64>,
    previous_touch: Option<(i64, i64, i64, i64)>,
    last_action: [i64; 2],
    last_us: Option<i64>,
    net: f64,
    volume: f64,
    invalid_since: Option<i64>,
}

pub const KEYS: [&str; 43] = [
    "HORIZON_US", "OBSERVATION_INTERVAL_US", "MIN_LABELS", "MODEL_MEMORY_US", "POSITION_LIMIT", "QUOTE_SIZE",
    "REQUOTE_US", "INSIDE_TH", "FLOW_CUT", "SKEW_K", "DEAD_ZONE", "MAX_ORDERS", "FAST_US", "SLOW_US", "FLOW_US",
    "OFI_US", "RIDGE_MIN", "RIDGE_FRAC", "FIT_US", "REPLENISH_US", "PRED_MIX",
    "DEPLETE_LOTS", "DEPL_FRAC", "TAKE_LOTS", "TAKE_OWN", "TAKE_DEPLETE", "TAKE_MAX", "TAKE_MS",
    "PLACE", "PLACE_US1", "PLACE_US2", "DEPTH5", "FLOW2", "LAST_AGG", "STD", "STD_US", "BLEND_W", "H2_US",
    "EXPOSURE", "CANCEL_FREE", "HEDGE", "HEDGE_TICKS", "HEDGE_STALE_US",
];

fn side_index(sign: i64) -> usize {
    if sign > 0 {
        0
    } else {
        1
    }
}

impl RidgeMaker {
    pub fn new(params: &Params) -> Result<RidgeMaker, String> {
        params.check_keys(&KEYS)?;
        let position_limit = params.int("POSITION_LIMIT", 100)?;
        let exposure = params.int("EXPOSURE", 0)?;
        Ok(RidgeMaker {
            exposure: if exposure > 0 { exposure } else { position_limit },
            cancel_free: params.float("CANCEL_FREE", 0.0)?,
            hedge: params.int("HEDGE", 0)? != 0,
            hedge_ticks: params.int("HEDGE_TICKS", 10)?,
            hedge_stale_us: params.int("HEDGE_STALE_US", 100_000)?,
            hedge_id: None,
            cached: None,
            horizon_us: params.int("HORIZON_US", 100_000)?,
            observation_interval_us: params.int("OBSERVATION_INTERVAL_US", 20_000)?,
            min_labels: params.int("MIN_LABELS", 200)?,
            model_memory_us: params.int("MODEL_MEMORY_US", 300_000_000)?,
            position_limit,
            quote_size: params.int("QUOTE_SIZE", 200)?,
            requote_us: params.int("REQUOTE_US", 0)?,
            inside_th: params.float("INSIDE_TH", 0.3)?,
            flow_cut: params.float("FLOW_CUT", 1.1)?,
            skew_k: params.float("SKEW_K", 0.025)?,
            dead_zone: params.float("DEAD_ZONE", 0.1)?,
            max_orders: params.int("MAX_ORDERS", 8)? as usize,
            fast_us: params.int("FAST_US", 500_000)?,
            slow_us: params.int("SLOW_US", 2_000_000)?,
            flow_us: params.int("FLOW_US", 500_000)?,
            ofi_us: params.int("OFI_US", 500_000)?,
            ridge_min: params.float("RIDGE_MIN", 10.0)?,
            ridge_frac: params.float("RIDGE_FRAC", 0.001)?,
            fit_us: params.int("FIT_US", 1_000_000)?,
            replenish_us: params.int("REPLENISH_US", 5000)?,
            pred_mix: params.float("PRED_MIX", 1.0)?,
            deplete_lots: params.int("DEPLETE_LOTS", 0)?,
            depl_frac: params.float("DEPL_FRAC", 0.12)?,
            take_lots: params.int("TAKE_LOTS", 0)?,
            take_own: params.int("TAKE_OWN", 800)?,
            take_deplete: params.int("TAKE_DEPLETE", 150)?,
            take_max: params.int("TAKE_MAX", 1000)?,
            take_ms: params.int("TAKE_MS", 250)?,
            take_block: [0, 0],
            peak: [None, None],
            inventory: 0,
            orders: Vec::new(),
            desired_buy: None,
            desired_sell: None,
            desired_time: None,
            m1: Model::new(params.int("HORIZON_US", 100_000)?),
            m2: Model::new(params.int("H2_US", 500_000)?),
            n: N + if params.int("PLACE", 0)? > 0 { 2 } else { 0 }
                + if params.int("DEPTH5", 0)? > 0 { 1 } else { 0 }
                + if params.int("FLOW2", 0)? > 0 { 2 } else { 0 }
                + if params.int("LAST_AGG", 0)? > 0 { 1 } else { 0 },
            last_observation_us: -100_000,
            place: params.int("PLACE", 0)?,
            place_us1: params.int("PLACE_US1", 100_000)?,
            place_us2: params.int("PLACE_US2", 300_000)?,
            depth5: params.int("DEPTH5", 0)?,
            flow2: params.int("FLOW2", 0)?,
            last_agg: params.int("LAST_AGG", 0)?,
            std_on: params.int("STD", 0)?,
            std_us: params.int("STD_US", 60_000_000)?,
            blend_w: params.float("BLEND_W", 0.0)?,
            seen: HashSet::new(),
            seen_next: HashSet::new(),
            place_acc: [[0.0; 4]; 2],
            flow_fast: (0.0, 0.0),
            flow_slow: (0.0, 0.0),
            last_agg_value: 0.0,
            std_m2: [0.0; NM],
            std_mass: 0.0,
            fast_mid: 0.0,
            slow_mid: 0.0,
            model_time: None,
            ofi: 0.0,
            ofi_time: None,
            previous_touch: None,
            last_action: [-5000, -5000],
            last_us: None,
            net: 0.0,
            volume: 0.0,
            invalid_since: None,
        })
    }

    fn learn(&mut self, which: usize, now: i64, mid: f64) {
        let n = self.n;
        let (min_labels, memory, fit_us, ridge_min, ridge_frac) =
            (self.min_labels, self.model_memory_us, self.fit_us, self.ridge_min, self.ridge_frac);
        let m = if which == 0 { &mut self.m1 } else { &mut self.m2 };
        while let Some(&(observed_us, old_mid, features)) = m.observations.front() {
            if observed_us + m.horizon_us > now {
                break;
            }
            m.observations.pop_front();
            if now - observed_us > m.horizon_us + 1_000_000 {
                continue;
            }
            let elapsed = match m.last_label_us {
                None => 0,
                Some(t) => now - t,
            };
            let decay = ((-(elapsed.max(0))) as f64 / memory as f64).exp();
            m.last_label_us = Some(now);
            let response = clamp(mid - old_mid, -20.0, 20.0);
            m.mass = m.mass * decay + 1.0;
            for i in 0..n {
                m.xy[i] = m.xy[i] * decay + features[i] * response;
                for j in 0..n {
                    m.xx[i][j] = m.xx[i][j] * decay + features[i] * features[j];
                }
            }
            m.labels += 1;
        }
        if m.labels < min_labels {
            return;
        }
        if let Some(t) = m.last_fit_us {
            if now - t < fit_us {
                return;
            }
        }
        m.last_fit_us = Some(now);
        let r = ridge_frac * m.mass;
        let ridge = if r > ridge_min { r } else { ridge_min };
        let mut matrix = [[0.0f64; NM + 1]; NM];
        for i in 0..n {
            matrix[i][..n].copy_from_slice(&m.xx[i][..n]);
            matrix[i][n] = m.xy[i];
        }
        for i in 0..n {
            matrix[i][i] += ridge;
        }
        for col in 0..n {
            let pivot = matrix[col][col];
            if !pivot.is_finite() || pivot <= 1e-12 {
                return;
            }
            for j in col..=n {
                matrix[col][j] /= pivot;
            }
            for i in 0..n {
                if i == col {
                    continue;
                }
                let factor = matrix[i][col];
                for j in col..=n {
                    matrix[i][j] -= factor * matrix[col][j];
                }
            }
        }
        let mut weights = [0.0; NM];
        for i in 0..n {
            weights[i] = matrix[i][n];
        }
        if weights.iter().all(|w| w.is_finite()) {
            m.weights = weights;
        }
    }

    fn cancel(&mut self, index: usize, ctx: &mut Ctx) {
        let record = &mut self.orders[index];
        if record.accepted && !record.cancelling {
            record.cancelling = true;
            ctx.cancel_order(record.id);
        }
    }

    fn quote(&mut self, now: i64, sign: i64, price: Option<i64>, ctx: &mut Ctx) {
        let mut current = 0usize;
        for index in 0..self.orders.len() {
            if self.orders[index].sign != sign {
                continue;
            }
            current += 1;
            if (price.is_none() || Some(self.orders[index].price) != price) && now >= self.orders[index].exempt_until {
                self.cancel(index, ctx);
            }
        }
        if current >= self.max_orders {
            return;
        }
        let Some(price) = price else { return };
        if price <= 0 || now - self.last_action[side_index(sign)] < self.requote_us {
            return;
        }
        let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
        let effective: i64 = self
            .orders
            .iter()
            .filter(|r| r.sign == sign)
            .map(|r| if r.cancelling { (r.quantity as f64 * (1.0 - self.cancel_free)).ceil() as i64 } else { r.quantity })
            .sum();
        let quantity = self
            .quote_size
            .min(self.exposure - sign * self.inventory - effective)
            .min(self.position_limit - sign * self.inventory - reserved);
        if quantity <= 0 {
            return;
        }
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, false);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: 0 });
        self.last_action[side_index(sign)] = now;
    }

    /// v2's `_hedge`: an IOC for |inventory| - EXPOSURE, HEDGE_TICKS through the cached touch, one at a time.
    fn hedge(&mut self, now: i64, ctx: &mut Ctx) {
        if !self.hedge || self.inventory.abs() <= self.exposure || self.hedge_id.is_some() {
            return;
        }
        let Some((bid, ask, time)) = self.cached else { return };
        if now - time > self.hedge_stale_us {
            return;
        }
        let sign = if self.inventory > 0 { -1 } else { 1 };
        let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
        let quantity = (self.inventory.abs() - self.exposure).min(0i64.max(self.position_limit - sign * self.inventory - reserved));
        if quantity <= 0 {
            return;
        }
        let price = if sign > 0 { ask + self.hedge_ticks } else { 1i64.max(bid - self.hedge_ticks) };
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, true);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: 0 });
        self.hedge_id = Some(id);
    }

    /// take_maker's `take`: TAKE_LOTS (within the limit) at `price`, one a side per TAKE_MS, exempt that long.
    fn take(&mut self, now: i64, sign: i64, price: i64, ctx: &mut Ctx) {
        let key = side_index(sign);
        if now < self.take_block[key] {
            return;
        }
        let reserved: i64 = self.orders.iter().filter(|r| r.sign == sign).map(|r| r.quantity).sum();
        let quantity = self.take_lots.min(self.position_limit - sign * self.inventory - reserved);
        if quantity <= 0 || price <= 0 {
            return;
        }
        let until = now + self.take_ms * 1000;
        self.take_block[key] = until;
        let id = ctx.send_order(if sign > 0 { Side::Buy } else { Side::Sell }, price, quantity, false);
        self.orders.push(Record { id, sign, price, quantity, accepted: false, cancelling: false, exempt_until: until });
    }
}

impl Strategy for RidgeMaker {
    fn on_book(&mut self, snapshot: &Snapshot, trades: &[Trade], ctx: &mut Ctx) {
        let now = snapshot.timestamp_us;
        let elapsed = match self.last_us {
            None => 0,
            Some(t) => (now - t).max(0),
        };
        self.last_us = Some(now);
        let decay = ((-elapsed) as f64 / self.flow_us as f64).exp();
        self.net *= decay;
        self.volume *= decay;
        for trade in trades {
            if trade.taker_owner == Owner::Market {
                self.net += if trade.book_side == Side::Sell { trade.quantity as f64 } else { -(trade.quantity as f64) };
                self.volume += trade.quantity as f64;
            }
        }
        if self.flow2 > 0 {
            let df = ((-elapsed) as f64 / 100_000.0).exp();
            let ds = ((-elapsed) as f64 / 2_000_000.0).exp();
            self.flow_fast.0 *= df;
            self.flow_fast.1 *= df;
            self.flow_slow.0 *= ds;
            self.flow_slow.1 *= ds;
            for trade in trades {
                if trade.taker_owner == Owner::Market {
                    let q = trade.quantity as f64;
                    let signed = if trade.book_side == Side::Sell { q } else { -q };
                    self.flow_fast.0 += signed;
                    self.flow_fast.1 += q;
                    self.flow_slow.0 += signed;
                    self.flow_slow.1 += q;
                }
            }
        }
        if self.last_agg > 0 {
            let mut last: Option<(u64, f64, f64)> = None;
            for trade in trades {
                if trade.taker_owner != Owner::Market {
                    continue;
                }
                let sign = if trade.book_side == Side::Sell { 1.0 } else { -1.0 };
                match &mut last {
                    Some((id, _, q)) if *id == trade.taker_order_id => *q += trade.quantity as f64,
                    slot => *slot = Some((trade.taker_order_id, sign, trade.quantity as f64)),
                }
            }
            if let Some((_, sign, q)) = last {
                self.last_agg_value = sign * (1.0 + q).ln();
            }
        }
        let touch_bid = snapshot.market_touch(Side::Buy);
        let touch_ask = snapshot.market_touch(Side::Sell);
        let (bid, bq, ask, aq) = match (touch_bid, touch_ask) {
            (Some((b, bq)), Some((a, aq))) if b < a => (b, bq, a, aq),
            _ => {
                self.previous_touch = None;
                self.desired_time = None;
                let since = *self.invalid_since.get_or_insert(now);
                if now - since >= 50_000 {
                    for index in 0..self.orders.len() {
                        self.cancel(index, ctx);
                    }
                }
                return;
            }
        };
        self.invalid_since = None;
        let mid = (bid + ask) as f64 * 0.5;
        let spread = ask - bid;
        let flow = self.net / (1.0 + self.volume);
        let imbalance = (bq - aq) as f64 / (bq + aq) as f64;
        let (mut bn, mut an, mut bd_n, mut ad_n) = (0i64, 0i64, 0i64, 0i64);
        let (mut br, mut ar, mut bd_r, mut ad_r) = (0i64, 0i64, 0i64, 0i64);
        let (mut bd_value, mut ad_value) = (0i64, 0i64);
        for side in [Side::Buy, Side::Sell] {
            for order in snapshot.side(side) {
                if order.owner != Owner::Market {
                    continue;
                }
                let distance = if order.side == Side::Buy { bid - order.price } else { order.price - ask };
                if distance > 2 {
                    break;
                }
                let weight = order.quantity.min(20);
                if order.side == Side::Buy {
                    bd_n += 1;
                    bd_r += weight;
                    bd_value += weight * order.price;
                    if distance == 0 {
                        bn += 1;
                        br += weight;
                    }
                } else {
                    ad_n += 1;
                    ad_r += weight;
                    ad_value += weight * order.price;
                    if distance == 0 {
                        an += 1;
                        ar += weight;
                    }
                }
            }
        }
        let ratio = |a: i64, b: i64| (a - b) as f64 / (a + b).max(1) as f64;
        let count_imbalance = ratio(bn, an);
        let robust_imbalance = ratio(br, ar);
        let depth_count = ratio(bd_n, ad_n);
        let depth_imbalance = ratio(bd_r, ad_r);
        let depth_mid =
            (bd_value as f64 / bd_r.max(1) as f64 + ad_value as f64 / ad_r.max(1) as f64) * 0.5 - mid;

        let mut place_feat = [0.0f64; 2];
        if self.place > 0 {
            let (ref_bid, ref_ask) = match self.previous_touch {
                Some((ob, oa, _, _)) => (ob, oa),
                None => (bid, ask),
            };
            let mut add = [0.0f64; 4];
            self.seen_next.clear();
            for side in [Side::Buy, Side::Sell] {
                for order in snapshot.side(side) {
                    if order.owner != Owner::Market {
                        continue;
                    }
                    self.seen_next.insert(order.order_id);
                    if self.seen.contains(&order.order_id) {
                        continue;
                    }
                    if order.side == Side::Buy {
                        add[1] += 1.0;
                        if order.price >= ref_bid {
                            add[0] += 1.0;
                        }
                    } else {
                        add[3] += 1.0;
                        if order.price <= ref_ask {
                            add[2] += 1.0;
                        }
                    }
                }
            }
            std::mem::swap(&mut self.seen, &mut self.seen_next);
            for (k, tau) in [self.place_us1, self.place_us2].into_iter().enumerate() {
                let d = ((-elapsed) as f64 / tau as f64).exp();
                for q in 0..4 {
                    self.place_acc[k][q] = self.place_acc[k][q] * d + add[q];
                }
                let acc = self.place_acc[k];
                let sb = if acc[1] > 1e-9 { acc[0] / acc[1] } else { 0.5 };
                let sa = if acc[3] > 1e-9 { acc[2] / acc[3] } else { 0.5 };
                place_feat[k] = sb - sa;
            }
        }
        let mut depth5_feat = 0.0f64;
        if self.depth5 > 0 {
            let mut tot = [0i64; 2];
            for (k, side) in [Side::Buy, Side::Sell].into_iter().enumerate() {
                let mut levels = 0;
                let mut last_price = i64::MIN;
                for order in snapshot.side(side) {
                    if order.price != last_price {
                        levels += 1;
                        last_price = order.price;
                        if levels > 5 {
                            break;
                        }
                    }
                    if order.owner == Owner::Market {
                        tot[k] += order.quantity;
                    }
                }
            }
            depth5_feat = ratio(tot[0], tot[1]);
        }

        let spread_f = spread as f64;
        let skew = self.skew_k * self.inventory as f64 / self.exposure as f64 * spread_f.max(1.0);
        match self.model_time {
            Some(t) if now - t <= 10_000_000 => {
                let dt = (now - t).max(0) as f64;
                self.fast_mid += (1.0 - (-dt / self.fast_us as f64).exp()) * (mid - self.fast_mid);
                self.slow_mid += (1.0 - (-dt / self.slow_us as f64).exp()) * (mid - self.slow_mid);
            }
            _ => {
                self.fast_mid = mid;
                self.slow_mid = mid;
                self.m1.observations.clear();
                self.m2.observations.clear();
            }
        }
        self.model_time = Some(now);
        let dt = match self.ofi_time {
            None => 0,
            Some(t) => (now - t).max(0),
        };
        self.ofi_time = Some(now);
        self.ofi *= ((-dt) as f64 / self.ofi_us as f64).exp();
        if let Some((old_bid, old_ask, old_bq, old_aq)) = self.previous_touch {
            let mut change = (if bid >= old_bid { bq } else { 0 }) - (if bid <= old_bid { old_bq } else { 0 });
            change -= if ask <= old_ask { aq } else { 0 };
            change += if ask >= old_ask { old_aq } else { 0 };
            self.ofi += change as f64 / 1i64.max(bq + aq).max(old_bq + old_aq) as f64;
        }
        self.previous_touch = Some((bid, ask, bq, aq));
        let ofi = clamp(self.ofi, -3.0, 3.0);
        let base: [f64; N] = [
            flow,
            clamp(self.fast_mid - self.slow_mid, -5.0, 5.0),
            imbalance,
            ofi,
            spread_f * imbalance,
            flow * flow.abs(),
            imbalance * imbalance.abs(),
            ofi * ofi.abs(),
            count_imbalance,
            robust_imbalance,
            depth_count,
            depth_imbalance,
            depth_mid,
            count_imbalance * count_imbalance.abs(),
            robust_imbalance * robust_imbalance.abs(),
        ];
        let mut features = [0.0f64; NM];
        features[..N].copy_from_slice(&base);
        let mut k = N;
        if self.place > 0 {
            features[k] = place_feat[0];
            features[k + 1] = place_feat[1];
            k += 2;
        }
        if self.depth5 > 0 {
            features[k] = depth5_feat;
            k += 1;
        }
        if self.flow2 > 0 {
            features[k] = self.flow_fast.0 / (1.0 + self.flow_fast.1);
            features[k + 1] = self.flow_slow.0 / (1.0 + self.flow_slow.1);
            k += 2;
        }
        if self.last_agg > 0 {
            features[k] = self.last_agg_value;
        }
        let n = self.n;
        if self.std_on > 0 {
            let d = ((-elapsed) as f64 / self.std_us as f64).exp();
            self.std_mass = self.std_mass * d + 1.0;
            for i in 0..n {
                self.std_m2[i] = self.std_m2[i] * d + features[i] * features[i];
                features[i] /= (self.std_m2[i] / self.std_mass).sqrt() + 1e-9;
            }
        }
        self.learn(0, now, mid);
        if self.blend_w > 0.0 {
            self.learn(1, now, mid);
        }
        if now - self.last_observation_us >= self.observation_interval_us {
            if self.m1.observations.len() == OBS_MAXLEN {
                self.m1.observations.pop_front();
            }
            self.m1.observations.push_back((now, mid, features));
            if self.blend_w > 0.0 {
                if self.m2.observations.len() == OBS_MAXLEN {
                    self.m2.observations.pop_front();
                }
                self.m2.observations.push_back((now, mid, features));
            }
            self.last_observation_us = now;
        }
        let mut prediction = 0.25 * spread_f * imbalance;
        if self.m1.labels >= self.min_labels {
            prediction =
                clamp(py_sum(self.m1.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0);
            if self.blend_w > 0.0 && self.m2.labels >= self.min_labels {
                let p2 =
                    clamp(py_sum(self.m2.weights[..n].iter().zip(features[..n].iter()).map(|(w, x)| w * x)), -2.0, 2.0);
                prediction = (1.0 - self.blend_w) * prediction + self.blend_w * p2;
            }
        }
        let mut fair = mid + self.pred_mix * prediction + 0.0 * 0.25 * spread_f * imbalance - skew;
        if (fair - mid).abs() <= self.dead_zone {
            fair = mid;
        }
        let mut buy = Some(bid.min((fair - 0.5).floor() as i64));
        let mut sell = Some(ask.max((fair + 0.5).ceil() as i64));
        if spread >= 2 {
            if prediction - skew > self.inside_th {
                buy = Some((ask - 1).min(bid + 1));
            } else if prediction - skew < -self.inside_th {
                sell = Some((bid + 1).max(ask - 1));
            }
        }
        if flow < -self.flow_cut || self.inventory >= self.exposure {
            buy = None;
        }
        if flow > self.flow_cut || self.inventory <= -self.exposure {
            sell = None;
        }
        if self.deplete_lots > 0 || self.take_lots > 0 {
            for (key, price, lots) in [(0, bid, bq), (1, ask, aq)] {
                match &mut self.peak[key] {
                    Some((p, most)) if *p == price => *most = (*most).max(lots),
                    slot => *slot = Some((price, lots)),
                }
            }
            let peak = |key: usize| self.peak[key].map_or(0, |(_, most)| most) as f64;
            let mut bid_dying = bq < self.deplete_lots;
            let mut ask_dying = aq < self.deplete_lots;
            if self.depl_frac > 0.0 {
                bid_dying = bid_dying && (bq as f64) < self.depl_frac * peak(0);
                ask_dying = ask_dying && (aq as f64) < self.depl_frac * peak(1);
            }
            if self.take_lots > 0 && spread == 1 {
                let (mut ask_take, mut bid_take) = (ask_dying, bid_dying);
                if self.take_deplete > 0 && self.depl_frac > 0.0 {
                    ask_take = aq < self.take_deplete && (aq as f64) < self.depl_frac * peak(1);
                    bid_take = bq < self.take_deplete && (bq as f64) < self.depl_frac * peak(0);
                }
                if ask_take && aq <= self.take_max && buy.is_some() && bq >= self.take_own {
                    self.take(now, 1, ask, ctx);
                }
                if bid_take && bq <= self.take_max && sell.is_some() && aq >= self.take_own {
                    self.take(now, -1, bid, ctx);
                }
            }
            if bid_dying && buy == Some(bid) {
                buy = Some(bid - 1);
            }
            if ask_dying && sell == Some(ask) {
                sell = Some(ask + 1);
            }
        }
        self.cached = Some((bid, ask, now));
        self.hedge(now, ctx);
        self.desired_buy = buy;
        self.desired_sell = sell;
        self.desired_time = Some(now);
        self.quote(now, 1, buy, ctx);
        self.quote(now, -1, sell, ctx);
    }

    fn on_private(&mut self, event: &PrivateEvent, ctx: &mut Ctx) {
        let Some(index) = self.orders.iter().position(|r| r.id == event.order_id) else { return };
        match event.status {
            Status::Accepted => self.orders[index].accepted = true,
            Status::Filled | Status::PartiallyFilled => {
                let record = &mut self.orders[index];
                self.inventory += record.sign * event.filled_quantity;
                record.quantity = event.remaining_quantity;
                if event.status == Status::Filled {
                    self.orders.remove(index);
                }
            }
            Status::Canceled => {
                self.orders.remove(index);
            }
            Status::Rejected => {
                if !self.orders[index].accepted {
                    self.orders.remove(index);
                } else {
                    self.orders[index].cancelling = false;
                }
            }
            Status::Modified => {}
        }
        let was_hedge = self.hedge_id == Some(event.order_id);
        if was_hedge && matches!(event.status, Status::Filled | Status::Canceled | Status::Rejected) {
            self.hedge_id = None;
        }
        if let Some(t) = self.desired_time {
            let d = event.timestamp_us - t;
            if !was_hedge && 0 <= d && d <= self.replenish_us && event.status == Status::Canceled {
                let (buy, sell) = (self.desired_buy, self.desired_sell);
                self.quote(event.timestamp_us, 1, buy, ctx);
                self.quote(event.timestamp_us, -1, sell, ctx);
            }
        }
        if was_hedge || matches!(event.status, Status::Filled | Status::PartiallyFilled) {
            self.hedge(event.timestamp_us, ctx);
        }
    }
}
