"""Evaluate paying the genuine inventory fee; never change simulator limits.

Fee = 10000 * seconds with abs(inventory)>100. The hard exposure limit is 1000.
The same previously consumed tapes are used; results are exploratory diagnostics.
"""
import argparse
import ast
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.probe_depth_advantage import replace_once
from scripts.probe_robust_augmentation import bootstrap_gate
from simulator.main import load_strategy_from_file
from simulator.models import OrderStatus, Side
from simulator.simulator import ExchangeSimulator, SimulationConfig


GUARD_QUOTE = '''    def _quote(self, now, sign, price):
        current = [(oid,r) for oid,r in self._orders.items() if r[0] == sign and oid not in self._exit_ids]
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        if self._closing:
            for oid,record in current:
                self._cancel(oid)
            return
        extra = (now >= self._cooldown_until and abs(self.inventory) <= 100
                 and sign*self.inventory >= 80 and sign*self._signal_edge >= self.BURST_EDGE)
        limit = self.POSITION_LIMIT if extra else 100
        trim = sign*self.inventory+reserved > limit
        for oid,record in current:
            if trim or price is None or record[1] != price:
                self._cancel(oid)
        if len(current) >= 8 or price is None or price <= 0:
            return
        if now-self._last_action[sign] < self.REQUOTE_US:
            return
        quantity = min(self.QUOTE_SIZE,limit-sign*self.inventory-reserved)
        if quantity <= 0:
            return
        order_id = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.LIMIT))
        self._orders[order_id] = [sign,price,quantity,False,False,now]
        self._last_action[sign] = now

    def _manage_exposure(self, now):
        if abs(self.inventory) <= 100:
            if self._breach_start is not None:
                self._cooldown_until = now+1000000
            self._breach_start = None
            self._closing = False
            return
        if self._breach_start is None:
            self._breach_start = now
        increasing = 1 if self.inventory > 0 else -1
        for oid,record in list(self._orders.items()):
            if record[0] == increasing and oid not in self._exit_ids:
                self._cancel(oid)
        if now-self._breach_start < self.HOLD_US:
            return
        self._closing = True
        for oid in list(self._orders):
            if oid not in self._exit_ids:
                self._cancel(oid)
        sign = -increasing
        reserved = sum(r[2] for r in self._orders.values() if r[0] == sign)
        exiting = sum(r[2] for oid,r in self._orders.items() if oid in self._exit_ids and r[0] == sign)
        needed = abs(self.inventory)-100-exiting
        # Outstanding opposite quotes can still fill. Reserve them before
        # adding an IOC; its combined worst-case result may not cross -/+100.
        quantity = min(needed,100-sign*self.inventory-reserved)
        if quantity <= 0 or sum(r[0] == sign for r in self._orders.values()) >= 8:
            return
        touch = self._market_bid if sign < 0 else self._market_ask
        if touch is None:
            return
        price = max(1,touch-2) if sign < 0 else touch+2
        oid = self.send_order(OrderRequest(side=Side.BUY if sign > 0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid] = [sign,price,quantity,False,False,now]
        self._exit_ids.add(oid)

'''


def guarded(source, cap, hold_us, edge):
    text = replace_once(source, 'POSITION_LIMIT = 100', f'POSITION_LIMIT = {cap}')
    text = replace_once(text, 'QUOTE_SIZE = 200', f'QUOTE_SIZE = {2*cap}\n    HOLD_US = {hold_us}\n    BURST_EDGE = {edge}')
    text = replace_once(text, 'self.inventory/self.POSITION_LIMIT', 'self.inventory/100')
    text = replace_once(text, '        self._orders = {}', '''        self._orders = {}
        self._exit_ids = set()
        self._breach_start = None
        self._closing = False
        self._cooldown_until = 0
        self._signal_edge = 0.0
        self._market_bid = self._market_ask = None''')
    start = text.index('    def _quote(')
    end = text.index('    def on_order_book_change(', start)
    text = text[:start]+GUARD_QUOTE+text[end:]
    text = replace_once(text, '        if bid is None or ask is None or bid >= ask:',
                        '        self._market_bid,self._market_ask = bid,ask\n'
                        '        self._manage_exposure(now)\n'
                        '        if bid is None or ask is None or bid >= ask:')
    text = replace_once(text, '        fair = mid +',
                        '        self._signal_edge = prediction-skew\n        fair = mid +')
    text += '''
        if event.order_id not in self._orders:
            self._exit_ids.discard(event.order_id)
        self._manage_exposure(event.timestamp_us)
'''
    return text


def generate(source):
    variants = {'baseline': source, 'guard_disabled': guarded(source, 100, 0, 999)}
    specs = {'baseline': {'kind': 'control', 'cap': 100},
             'guard_disabled': {'kind': 'control', 'cap': 100}}
    for cap in (101, 250, 1000):
        name = f'continuous_{cap}'
        text = replace_once(source, 'POSITION_LIMIT = 100', f'POSITION_LIMIT = {cap}')
        text = replace_once(text, 'QUOTE_SIZE = 200', f'QUOTE_SIZE = {2*cap}')
        text = replace_once(text, 'self.inventory/self.POSITION_LIMIT', 'self.inventory/100')
        variants[name] = text
        specs[name] = {'kind': 'continuous', 'cap': cap}
    for cap, hold, edge in [(125, 0, .5), (250, 0, .5), (500, 0, .5), (1000, 0, .5),
                            (500, 20000, .5), (1000, 20000, 1.0)]:
        name = f'burst_{cap}_hold{hold//1000}_edge{str(edge).replace(".", "p")}'
        variants[name] = guarded(source, cap, hold, edge)
        specs[name] = {'kind': 'burst', 'cap': cap, 'hold_us': hold, 'edge': edge}
    return variants, specs


def activation_variants(source):
    variants, specs = {}, {}
    for cap, hold, edge in [(500,0,0.0),(1000,0,0.0),(500,20000,0.0),
                            (1000,20000,0.0),(1000,100000,0.3)]:
        name=f'active_{cap}_hold{hold//1000}_edge{str(edge).replace(".","p")}'
        text=guarded(source,cap,hold,edge)
        text=replace_once(text,'sign*self.inventory >= 80','sign*self.inventory >= 0')
        variants[name]=text
        specs[name]={'kind':'burst_active','cap':cap,'hold_us':hold,'edge':edge,'minimum_aligned_inventory':0}
    return variants,specs


def prepare_activation(root):
    path=root/'activation_protocol.json'
    if path.exists() or (root/'selection.json').exists():
        raise FileExistsError('Activation cohort is already frozen or selection has occurred')
    original=json.loads((root/'protocol.json').read_text())
    source=Path(original['sources']['baseline']['source']).read_text()
    variants,specs=activation_variants(source)
    for name,text in variants.items():
        file=root/'sources'/(name+'.py')
        assert not file.exists()
        file.write_text(text,encoding='utf-8',newline='\n')
        assert not check(file),check(file)
        specs[name].update(source=str(file),sha256=digest(file))
    amendment={'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
               'original_protocol_sha256':digest(root/'protocol.json'),'sources':specs,
               'reason':('Initial guarded variants posted only a few extra orders and incurred no '
                         'breaches in the first completed screens. Their unchanged PnL cannot '
                         'evaluate the economics of paying a fee. Add five activation probes, '
                         'lowering the admission threshold and allowing aligned inventory from zero; '
                         'also include a 100ms hold aligned with the forecasting horizon.'),
               'selection_amendment':('Keep all original numerical gates, but correct over all '
                                      'fourteen candidates together. Freeze this extra cohort before '
                                      'its replays. No further additions. If no model passes, choose '
                                      'the best-lower-bound guarded variant with realized breaches '
                                      'for diagnostic confirmation only; inactive variants are not '
                                      'evidence for a profitable penalty tradeoff.'),
               'limitation':'Adaptive exploratory extension on already consumed data; no fresh holdout.'}
    path.write_text(json.dumps(amendment,indent=2)+'\n')
    print('FROZEN five activation probes; combined family = fourteen trials',flush=True)


def load_protocol(root):
    original=json.loads((root/'protocol.json').read_text())
    extra=root/'activation_protocol.json'
    if extra.exists():
        amendment=json.loads(extra.read_text())
        assert digest(root/'protocol.json')==amendment['original_protocol_sha256']
        original['sources'].update(amendment['sources'])
    return original


class PenaltyAudit(ExchangeSimulator):
    """Observe cash, independent reservations, exact fee time and boundary PnL."""
    def __init__(self, strategy, config, boundaries=()):
        super().__init__(strategy, config)
        self.reservations = {}
        self.status_counts = Counter()
        self.max_inventory = self.max_potential = 0
        self.new_order_rejections = 0
        self.breach_us = 0
        self.excess_lot_us = 0
        self.episode_start = None
        self.episode_peak = 0
        self.episodes = []
        self.boundaries = deque(sorted(boundaries))
        self.marks = {}

    def risk(self):
        buys = sum(r[1] for r in self.reservations.values() if r[0] > 0)
        sells = sum(r[1] for r in self.reservations.values() if r[0] < 0)
        potential = max(abs(self._inventory+buys), abs(self._inventory-sells))
        self.max_inventory = max(self.max_inventory, abs(self._inventory))
        self.max_potential = max(self.max_potential, potential)
        assert potential <= 1000, ('hard reservation bound', self.current_ts_us, potential)

    def submit_order(self, request):
        oid = super().submit_order(request)
        self.reservations[oid] = [1 if request.side == Side.BUY else -1, request.quantity, False]
        self.risk()
        return oid

    def _private_notify(self, event):
        self.status_counts[event.status.value] += 1
        r = self.reservations.get(event.order_id)
        if r is not None:
            if event.status == OrderStatus.ACCEPTED:
                r[2] = True
            elif event.status == OrderStatus.PARTIALLY_FILLED:
                r[1] = event.remaining_quantity
            elif event.status in (OrderStatus.FILLED, OrderStatus.CANCELED):
                del self.reservations[event.order_id]
            elif event.status == OrderStatus.REJECTED and not r[2]:
                self.new_order_rejections += 1
                del self.reservations[event.order_id]
        self.risk()
        now = event.timestamp_us
        if abs(self._inventory) > 100:
            if self.episode_start is None:
                self.episode_start = now
                self.episode_peak = 0
            self.episode_peak = max(self.episode_peak, abs(self._inventory))
        elif self.episode_start is not None:
            self.episodes.append({'start_us': self.episode_start, 'end_us': now,
                                  'duration_us': now-self.episode_start, 'peak': self.episode_peak})
            self.episode_start = None
        super()._private_notify(event)
        s = self.strategy
        assert s.inventory == self._inventory and s.cash == self._cash, 'cash/inventory mismatch'
        assert {oid: (r[0], r[2]) for oid, r in s._orders.items()} == {
            oid: (r[0], r[1]) for oid, r in self.reservations.items()}, 'reservation ledger mismatch'
        self.risk()

    def _advance_measured(self, timestamp_us):
        elapsed = max(0, timestamp_us-self.current_ts_us)
        if abs(self._inventory) > 100:
            self.breach_us += elapsed
            self.excess_lot_us += elapsed*(abs(self._inventory)-100)
        super()._advance_time(timestamp_us)

    def _advance_time(self, timestamp_us):
        while self.boundaries and self.boundaries[0] <= timestamp_us:
            boundary = self.boundaries.popleft()
            if boundary > self.current_ts_us:
                self._advance_measured(boundary)
                self.marks[str(boundary)] = {'net': self._mark_to_market_pnl(),
                                             'penalty': self._breach_penalty,
                                             'breach_us': self.breach_us}
        self._advance_measured(timestamp_us)


def run_case(source, data, destination, boundaries, delay=5):
    destination = Path(destination)
    if (destination/'evaluation.json').exists():
        raise FileExistsError(destination)
    strategy = load_strategy_from_file(Path(source))
    config = SimulationConfig(max_position=100, max_potential_position=1000,
                              position_breach_penalty_per_second=10000,
                              order_accept_delay_ms=delay, public_depth=20)
    engine = PenaltyAudit(strategy, config, boundaries)
    cpu, wall = time.process_time(), time.perf_counter()
    result = engine.run(Path(data))
    seconds, elapsed = time.process_time()-cpu, time.perf_counter()-wall
    assert len(engine.marks) == len(boundaries)
    assert abs(result.breach_penalty-engine.breach_us/1000000*10000) < 1e-4
    assert engine.new_order_rejections == 0
    episodes = engine.episodes[:]
    if engine.episode_start is not None:
        episodes.append({'start_us': engine.episode_start, 'end_us': engine.current_ts_us,
                         'duration_us': engine.current_ts_us-engine.episode_start,
                         'peak': engine.episode_peak, 'open_at_end': True})
    assert sum(e['duration_us'] for e in episodes) == engine.breach_us
    curve = engine.pnl_curve(result.pnl)
    peak = drawdown = 0.0
    for _, value in curve:
        peak = max(peak, value)
        drawdown = max(drawdown, peak-value)
    blocks, previous = [], 0.0
    for stamp, mark in engine.marks.items():
        blocks.append({'end_us': int(stamp), 'pnl': mark['net']-previous})
        previous = mark['net']
    durations = [e['duration_us']/1000 for e in episodes]
    report = {'source_sha256': digest(source), 'data_sha256': digest(data),
              'result': result.model_dump(mode='json'),
              'gross_pnl': result.pnl+result.breach_penalty, 'marks': engine.marks,
              'boundary_pnl': {k: v['net'] for k, v in engine.marks.items()}, 'blocks': blocks,
              'breach_seconds': engine.breach_us/1000000,
              'breach_time_percent': 100*engine.breach_us/max(1, engine.current_ts_us),
              'excess_lot_seconds': engine.excess_lot_us/1000000,
              'breach_episodes': len(episodes),
              'duration_ms_p50_p95_max': ([float(np.median(durations)), float(np.quantile(durations,.95)), max(durations)] if durations else [0,0,0]),
              'max_abs_inventory': engine.max_inventory, 'max_potential_inventory': engine.max_potential,
              'max_drawdown_1s': drawdown, 'new_order_rejections': engine.new_order_rejections,
              'status_counts': dict(engine.status_counts), 'submissions': engine._user_order_seq,
              'cpu_seconds': seconds, 'wall_seconds': elapsed,
              'config': config.model_dump(mode='json'),
              'curve_sha256': hashlib.sha256(json.dumps(curve).encode()).hexdigest()}
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'evaluation.json').write_text(json.dumps(report, indent=2)+'\n')
    (destination/'episodes.json').write_text(json.dumps(episodes)+'\n')
    (destination/'pnl.json').write_text(json.dumps(curve)+'\n')
    return report


def prepare(root, source, data, prefix, transfer):
    root.mkdir(parents=True, exist_ok=True)
    if (root/'protocol.json').exists():
        raise FileExistsError('Protocol already frozen')
    (root/'sources').mkdir(exist_ok=True)
    variants, specs = generate(source.read_text())
    for name, text in variants.items():
        path = root/'sources'/(name+'.py')
        if name == 'baseline':
            shutil.copyfile(source, path)
        else:
            path.write_text(text, encoding='utf-8', newline='\n')
        ast.parse(text)
        assert not check(path), (name, check(path))
        specs[name].update(source=str(path), sha256=digest(path))
    protocol = {'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'git_head': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
                'engine_sha256': digest('simulator/simulator.py'),
                'data_sha256': digest(data), 'prefix_sha256': digest(prefix),
                'transfer_sha256': digest(transfer), 'sources': specs,
                'economics': 'Official fee = 10000 per second with abs(inventory)>100, independent of excess size. Hard potential limit=1000. No simulator/rule changes.',
                'controller': ('Guarded extra exposure requires same-direction inventory >=80 and '
                               'forecast-after-skew >=edge. On breach cancel risk-increasing orders; '
                               'after hold time cancel normal quotes and IOC excess back toward 100, '
                               'reserving all pending/canceling orders. IOC price allows two ticks '
                               'through the last visible market touch. One-second cooldown. No '
                               'guarantee of instant exit: callbacks, latency and liquidity can delay it.'),
                'selection': ('Freeze nine candidates, plus baseline and disabled-controller control. '
                              'Screen from tape start through prefix; exact 300-second blocks ending '
                              'at 5990 seconds before EOF drain. Disabled control must match baseline. '
                              'Require >=1% net-after-penalty improvement, positive gain in both halves, '
                              '>=12/20 positive blocks and positive simultaneous one-sided 95% max-T '
                              'bootstrap lower bound across all nine trials, 20000 circular paired '
                              'draws of two blocks within each half, seed 2026110703. Hard exposure '
                              'must stay <=1000 with no new-order rejections. Select greatest lower '
                              'bound, cap as tie-breaker; freeze before later data. No retuning.'),
                'confirmation': ('Require positive after-fee gains in both later 5990-9000 and '
                                 '9000-end segments and >=1% full gain. Net PnL on sample_v2 and '
                                 '20/50ms stress must each be >=99% of the corresponding penalty-free '
                                 'baseline. Otherwise keep baseline. If no candidate passes screening, '
                                 'run only the best-lower-bound guarded candidate as a diagnostic; '
                                 'it cannot be promoted afterwards.'),
                'baseline_reuse': ('Verified baseline full/sample/20/50ms results from '
                                   'logs/robust_augmentation are reused only after matching baseline '
                                   'source, data and engine hashes, and exact prefix parity.'),
                'limitation': 'All tapes were previously examined; tests do not create a fresh holdout.'}
    (root/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    print('FROZEN', len(specs)-2, 'penalty candidates and two controls', flush=True)


def select(root):
    path = root/'selection.json'
    if path.exists():
        raise FileExistsError(path)
    protocol = load_protocol(root)
    screen = json.loads((root/'screen.json').read_text())
    if (root/'activation_protocol.json').exists():
        screen.update(json.loads((root/'activation_screen.json').read_text()))
    baseline = screen['baseline']
    for key in ('result','boundary_pnl','curve_sha256'):
        assert baseline[key] == screen['guard_disabled'][key], ('disabled controller differs',key)
    names = [n for n,s in protocol['sources'].items() if s['kind'] != 'control']
    gains = np.array([[b['pnl']-a['pnl'] for a,b in zip(baseline['blocks'],screen[n]['blocks'])]
                      for n in names]).T
    lower, errors, critical = bootstrap_gate(gains, seed=2026110703)
    baseline_total = baseline['boundary_pnl']['5990000000']
    scores = {}
    for i,name in enumerate(names):
        d = gains[:,i]
        halves = [float(d[:10].sum()),float(d[10:].sum())]
        gain = float(d.sum())
        ok = gain >= baseline_total*.01 and min(halves)>0 and (d>0).sum()>=12 and lower[i]>0
        scores[name] = {'eligible': bool(ok), 'net_gain':gain,'half_gains':halves,
                        'positive_blocks':int((d>0).sum()),'lower_bound':float(lower[i]),
                        'bootstrap_error':float(errors[i]),'block_gains':d.tolist()}
    ranking = sorted(names,key=lambda n:(-scores[n]['lower_bound'],protocol['sources'][n]['cap'],n))
    selected = next((n for n in ranking if scores[n]['eligible']),None)
    diagnostic = selected or next(n for n in ranking
                                  if protocol['sources'][n]['kind'].startswith('burst')
                                  and screen[n]['breach_seconds']>0)
    result = {'selected':selected,'confirmation_candidate':diagnostic,
              'diagnostic_only':selected is None,'scores':scores,'bootstrap_critical':critical,
              'source':protocol['sources'][diagnostic],
              'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)


def batch(root,data,names,stage,workers,delay):
    protocol = load_protocol(root)
    boundaries = list(range(300000000,5700000001,300000000))+[5990000000]
    expected = protocol['prefix_sha256']
    if stage.startswith('full'):
        boundaries += list(range(6000000000,11700000001,300000000))
        expected = protocol['data_sha256']
    elif stage.startswith('sample'):
        boundaries = list(range(300000000,5400000001,300000000))
        expected = protocol['transfer_sha256']
    assert digest(data)==expected
    assert digest('simulator/simulator.py')==protocol['engine_sha256']
    results = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs = {}
        for name in names:
            source = Path(protocol['sources'][name]['source'])
            assert digest(source)==protocol['sources'][name]['sha256']
            jobs[pool.submit(run_case,source,data,root/stage/name,boundaries,delay)] = name
        for future in as_completed(jobs):
            name = jobs[future]
            value = future.result()
            results[name] = value
            print(stage,name,'net',round(value['result']['pnl'],3),
                  'gross',round(value['gross_pnl'],3),'fee',round(value['result']['breach_penalty'],3),
                  'breach_s',round(value['breach_seconds'],4),'maxI',value['max_abs_inventory'],flush=True)
    (root/(stage+'.json')).write_text(json.dumps(results,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('logs/penalty_tradeoff'))
    p.add_argument('--prepare',action='store_true');p.add_argument('--select',action='store_true')
    p.add_argument('--prepare-activation',action='store_true')
    p.add_argument('--source',type=Path,default=Path('strategies/round1_robust_candidate.py'))
    p.add_argument('--data',type=Path);p.add_argument('--prefix',type=Path);p.add_argument('--transfer',type=Path)
    p.add_argument('--stage',default='screen');p.add_argument('--names',nargs='+')
    p.add_argument('--workers',type=int,default=8);p.add_argument('--delay',type=int,default=5)
    a=p.parse_args()
    if a.prepare:prepare(a.root,a.source,a.data,a.prefix,a.transfer)
    elif a.prepare_activation:prepare_activation(a.root)
    elif a.select:select(a.root)
    else:batch(a.root,a.data,a.names or list(json.loads((a.root/'protocol.json').read_text())['sources']),a.stage,a.workers,a.delay)


if __name__=='__main__':main()
