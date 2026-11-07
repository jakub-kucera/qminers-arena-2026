"""Read-only market diagnostics using the unchanged matching engine.

python -m scripts.profile_round --backtest data/round1.csv --output logs/round1/profile

No orders are sent. Future quotes are evaluated BEFORE a market row at the
same timestamp, matching the engine's ordering of already-due actions.
Quote round trips are one-lot screening estimates, not strategy backtests:
they omit market impact and the availability of callbacks to schedule exits.
"""

import argparse
import json
from bisect import bisect_left
from collections import Counter, deque
from math import exp, sqrt
from pathlib import Path

from scripts.benchmark import digest
from simulator.simulator import ExchangeSimulator, SimulationConfig
from simulator.strategy import BaseStrategy


BOUNDS = (0, 1, 2, 3, 5, 10, 20, 50, 100, 200, 500, 1000, 5000, 10000, 100000)
FEATURES = ('trade_flow', 'momentum', 'queue_imbalance')
DEFAULT_HORIZONS_US = (5_000, 20_000, 100_000, 500_000, 2_000_000, 5_000_000)


class Histogram:
    """Exact mean/range and approximate quantile intervals, with bounded memory."""
    def __init__(self):
        self.bins = [0.0] * (len(BOUNDS) + 1)
        self.weight = self.total = 0.0
        self.minimum = self.maximum = None

    def add(self, value, weight=1):
        if weight <= 0:
            return
        self.weight += weight
        self.total += value * weight
        self.bins[bisect_left(BOUNDS, value)] += weight
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def report(self):
        quantiles = {}
        for q in (0.5, 0.95):
            cumulative = 0.0
            interval = None
            for i, weight in enumerate(self.bins):
                cumulative += weight
                if self.weight and cumulative >= q * self.weight:
                    interval = {'lower_exclusive':BOUNDS[i-1] if i else None,
                                'upper_inclusive':BOUNDS[i] if i < len(BOUNDS) else None}
                    break
            quantiles[str(q)] = interval
        return {'weight':self.weight, 'mean':self.total/self.weight if self.weight else None,
                'min':self.minimum, 'max':self.maximum, 'quantile_intervals':quantiles}


class SignalStats:
    def __init__(self):
        self.n = 0
        self.sx = self.sy = self.sxx = self.syy = self.sxy = 0.0
        self.follow_n = self.fade_n = self.directional_n = 0
        self.follow_sum = self.fade_sum = 0.0

    def add(self, x, y, entry, future):
        self.n += 1
        self.sx += x
        self.sy += y
        self.sxx += x*x
        self.syy += y*y
        self.sxy += x*y
        if abs(x) < 1e-9:
            return
        self.directional_n += 1
        # entry: (actual bid, actual ask, buy IOC fillable, sell IOC fillable)
        long_edge = future[0] - entry[1]
        short_edge = entry[0] - future[1]
        follow_edge, fade_edge = (long_edge, short_edge) if x > 0 else (short_edge, long_edge)
        follow_ok, fade_ok = (entry[2], entry[3]) if x > 0 else (entry[3], entry[2])
        if follow_ok:
            self.follow_n += 1
            self.follow_sum += follow_edge
        if fade_ok:
            self.fade_n += 1
            self.fade_sum += fade_edge

    def report(self):
        vx = self.n*self.sxx-self.sx*self.sx
        vy = self.n*self.syy-self.sy*self.sy
        correlation = None
        if vx > 1e-12 and vy > 1e-12:
            correlation = max(-1.0,min(1.0,(self.n*self.sxy-self.sx*self.sy)/sqrt(vx*vy)))
        return {'observations':self.n, 'correlation_with_future_mid_change':correlation,
                'directional_observations':self.directional_n,
                'follow_fillable':self.follow_n, 'fade_fillable':self.fade_n,
                'follow_mean_quote_round_trip_ticks':self.follow_sum/self.follow_n if self.follow_n else None,
                'fade_mean_quote_round_trip_ticks':self.fade_sum/self.fade_n if self.fade_n else None}


def touch(orders):
    price = None
    quantity = 0
    for order in orders:
        if order.owner != 'market':
            continue
        if price is None:
            price = order.price
        if price != order.price:
            break
        quantity += order.quantity
    return price, quantity


class MarketProbe(BaseStrategy):
    def __init__(self, sample_us=20_000, block_us=900_000_000, horizons=DEFAULT_HORIZONS_US):
        super().__init__()
        self.sample_us, self.block_us, self.horizons = sample_us, block_us, horizons
        self.first_us = self.last_us = None
        self.last_observation_us = None
        self.previous = None
        self.callbacks = self.observations = 0
        self.valid_time_us = self.invalid_time_us = 0
        self.market_trades = self.aggressive_rows = self.market_volume = 0
        self.buy_volume = self.sell_volume = 0
        self.net = self.volume = 0.0
        self.fast = self.slow = None
        self.feature_us = None
        self.awaiting_entry = deque()
        self.pending = {h:deque() for h in horizons}
        self.stats = {}
        self.skipped = Counter()
        self.time_hist = {name:Histogram() for name in ('spread_ticks','bid_touch_lots','ask_touch_lots')}
        self.sample_hist = {name:Histogram() for name in ('visible_bid_lots','visible_ask_lots','visible_orders')}

    def _mature(self, now):
        # previous is the book BEFORE the current market row. Using its
        # post-row replacement here would introduce a timing/lookahead error.
        previous = self.previous
        while self.awaiting_entry and self.awaiting_entry[0]['time'] + 5000 <= now:
            obs = self.awaiting_entry.popleft()
            if previous is not None:
                b, a = previous[:2]
                obs['entry'] = (b, a, a <= obs['ask'], b >= obs['bid'])
        for horizon, queue in self.pending.items():
            while queue and queue[0]['time'] + horizon <= now:
                obs = queue.popleft()
                if previous is None or obs['entry'] is None:
                    self.skipped['missing_quote'] += 1
                    continue
                end_block = (obs['time'] + horizon - self.first_us) // self.block_us
                if end_block != obs['block']:
                    self.skipped['crosses_time_block'] += 1
                    continue
                change = (previous[0]+previous[1])*0.5-obs['mid']
                for index, name in enumerate(FEATURES):
                    key = (obs['block'],horizon,name)
                    if key not in self.stats:
                        self.stats[key] = SignalStats()
                    self.stats[key].add(obs['features'][index],change,obs['entry'],previous)

    def on_order_book_change(self, snapshot, trades):
        now = snapshot.timestamp_us
        if self.first_us is None:
            self.first_us = now
        elapsed = 0 if self.last_us is None else now-self.last_us
        if elapsed < 0:
            raise ValueError('market timestamps are not monotonic')
        if self.previous is not None:
            b,a,bq,aq = self.previous
            self.valid_time_us += elapsed
            for name,value in [('spread_ticks',a-b),('bid_touch_lots',bq),('ask_touch_lots',aq)]:
                self.time_hist[name].add(value,elapsed)
        else:
            self.invalid_time_us += elapsed
        self._mature(now)
        self.callbacks += 1
        self.last_us = now
        decay = exp(-elapsed/1_000_000)
        self.net *= decay
        self.volume *= decay
        had_trade = False
        for trade in trades:
            if trade.taker_owner != 'market':
                continue
            had_trade = True
            self.market_trades += 1
            self.market_volume += trade.quantity
            sign = 1 if trade.book_side == 'ask' else -1
            self.net += sign*trade.quantity
            self.volume += trade.quantity
            if sign > 0:
                self.buy_volume += trade.quantity
            else:
                self.sell_volume += trade.quantity
        self.aggressive_rows += int(had_trade)
        bid,bq = touch(snapshot.bids)
        ask,aq = touch(snapshot.asks)
        if bid is None or ask is None or bid >= ask:
            self.previous = None
            return
        self.previous = (bid,ask,bq,aq)
        mid = (bid+ask)*0.5
        if self.feature_us is None or now-self.feature_us > 10_000_000:
            self.fast = self.slow = mid
        else:
            dt = now-self.feature_us
            self.fast += (1-exp(-dt/500_000))*(mid-self.fast)
            self.slow += (1-exp(-dt/2_000_000))*(mid-self.slow)
        self.feature_us = now
        if self.last_observation_us is not None and now-self.last_observation_us < self.sample_us:
            return
        self.last_observation_us = now
        obs = {'time':now, 'bid':bid, 'ask':ask, 'mid':mid, 'entry':None,
               'block':(now-self.first_us)//self.block_us,
               'features':(self.net/(1+self.volume), max(-5,min(5,self.fast-self.slow)), (bq-aq)/(bq+aq))}
        self.awaiting_entry.append(obs)
        for queue in self.pending.values():
            queue.append(obs)
        self.observations += 1
        self.sample_hist['visible_bid_lots'].add(sum(o.quantity for o in snapshot.bids if o.owner=='market'))
        self.sample_hist['visible_ask_lots'].add(sum(o.quantity for o in snapshot.asks if o.owner=='market'))
        self.sample_hist['visible_orders'].add(len(snapshot.bids)+len(snapshot.asks))

    def report(self):
        duration = 0 if self.first_us is None else (self.last_us-self.first_us)/1_000_000
        return {
            'duration_seconds':duration, 'market_rows':self.callbacks,
            'events_per_second':self.callbacks/duration if duration else None,
            'two_sided_time_fraction':self.valid_time_us/(duration*1_000_000) if duration else None,
            'market_matches':self.market_trades, 'aggressive_market_rows':self.aggressive_rows,
            'market_volume_lots':self.market_volume, 'aggressive_buy_lots':self.buy_volume,
            'aggressive_sell_lots':self.sell_volume, 'observations':self.observations,
            'sample_interval_ms':self.sample_us/1000, 'block_seconds':self.block_us/1_000_000,
            'time_weighted_book':{k:v.report() for k,v in self.time_hist.items()},
            'sampled_visible_book':{k:v.report() for k,v in self.sample_hist.items()},
            'unresolved_at_end_by_horizon_ms':{str(h/1000):len(q) for h,q in self.pending.items()},
            'skipped_matured_pairs':dict(self.skipped),
            'signals':[{'block':b,'horizon_ms':h/1000,'feature':f,**s.report()}
                       for (b,h,f),s in sorted(self.stats.items())],
        }


class ProfileSimulator(ExchangeSimulator):
    def __init__(self,strategy,config):
        super().__init__(strategy,config)
        self.operations = Counter()
        self.bucket = None
        self.bucket_count = self.max_bucket_count = 0

    @staticmethod
    def iter_backtest(path):
        previous = None
        for event in ExchangeSimulator.iter_backtest(path):
            if previous is not None and event.timestamp_us < previous:
                raise ValueError(f'market time moved backwards at order {event.order_id}')
            previous = event.timestamp_us
            yield event

    def _process_market_event(self,event):
        kind = event.operation.value
        if event.order_type is not None:
            kind += ':'+event.order_type.value
        self.operations[kind] += 1
        bucket = event.timestamp_us//5000
        if bucket != self.bucket:
            self.bucket, self.bucket_count = bucket, 0
        self.bucket_count += 1
        self.max_bucket_count = max(self.max_bucket_count,self.bucket_count)
        super()._process_market_event(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backtest',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=Path('logs/round_profile'))
    parser.add_argument('--sample-ms',type=int,default=20)
    parser.add_argument('--block-seconds',type=int,default=900)
    args = parser.parse_args()
    if args.sample_ms <= 0 or args.block_seconds <= 5:
        parser.error('sample interval must be positive; blocks must exceed the 5s horizon')
    probe = MarketProbe(args.sample_ms*1000,args.block_seconds*1_000_000)
    engine = ProfileSimulator(probe,SimulationConfig(public_depth=20))
    result = engine.run(args.backtest)
    assert result.traded_volume == 0 and result.pnl == 0
    report = probe.report()
    report.update({
        'backtest':str(args.backtest.resolve()), 'backtest_sha256':digest(args.backtest),
        'profiler_sha256':digest(__file__), 'engine_sha256':digest('simulator/simulator.py'),
        'operations':dict(engine.operations), 'max_events_in_aligned_5ms_bucket':engine.max_bucket_count,
        'limitations':[
            'Descriptive statistics, not a fitted strategy or out-of-sample evaluation.',
            'Quote round trips assume one lot, zero impact, and an exit at the horizon. Actual callback scheduling, latency on an exit decision, and changed liquidity require simulator validation.',
            'Conditional means exclude entries whose original touch limit is no longer executable after 5ms. Fillable counts must be considered alongside means.',
            'Labels overlap; correlations do not imply statistical significance or trading profitability.',
            'Observations with horizons crossing a chronological block are excluded. Unresolved end-of-file labels are censored.',
            'Book quantile intervals use fixed histogram bins; means and ranges are exact for their stated weighting.',
        ],
    })
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'profile.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['duration_seconds','market_rows','events_per_second',
                     'two_sided_time_fraction','market_matches','market_volume_lots',
                     'max_events_in_aligned_5ms_bucket','time_weighted_book']},indent=2))
    print(f'Full diagnostics: {args.output / "profile.json"}')


if __name__ == '__main__':
    main()
