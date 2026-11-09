"""Two distinct followups to the frozen 269920 liquidity forecast.

Reused public selection only; no inherited server score for altered sources.
"""
import argparse
from pathlib import Path

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once
from scripts.round2_taker_audit import batch
from scripts.round2_workbench import load_manifest,write_json

BASE=Path('strategies/round2_taker_liquidity_269920.py')
BASE_SHA='154504db3b2b6919e485a406a3be52c8ecb056a7dd7d342e2b59d6487529b6a5'
ROOT=Path('logs/round2/taker_extensions')


def large_flow(base):
    text=replace_once(base,'FEATURE_COUNT = 33','FEATURE_COUNT = 37')
    text=replace_once(text,'        self._orders = {}','''        self._orders = {}
        self._tail_time=None
        self._tail_net=self._tail_mass=self._tail_value=0.0''')
    text=replace_once(text,'    def _learn(self, now, mid):','''    def _large_flow(self,now,trades):
        dt=0 if self._tail_time is None else max(0,now-self._tail_time)
        self._tail_time=now
        decay=exp(-dt/500000)
        self._tail_net*=decay
        self._tail_mass*=decay
        self._tail_value*=decay
        # Aggregate fills of each external aggressor before applying the
        # size threshold; a sweep may match many small resting orders.
        groups={}
        for trade in trades:
            if trade.taker_owner!='market':
                continue
            row=groups.setdefault(trade.taker_order_id,
                [1 if trade.book_side=='ask' else -1,0,0.0])
            row[1]+=trade.quantity
            row[2]+=trade.quantity*trade.price
        for direction,quantity,value in groups.values():
            if quantity<500:
                continue
            weight=min(4.0,quantity/500.0)
            self._tail_net+=direction*weight
            self._tail_mass+=weight
            self._tail_value+=weight*value/quantity

    def _learn(self, now, mid):''')
    text=replace_once(text,'        now = snapshot.timestamp_us',
        '        now = snapshot.timestamp_us\n        self._large_flow(now,trades)')
    return replace_once(text,'        self._learn(now,mid)','''        tail=self._tail_net/(1+self._tail_mass)
        tail_center=max(-5.0,min(5.0,(self._tail_value-mid*self._tail_mass)/(1+self._tail_mass)))
        features+=(tail,tail_center,tail*dispersion,young*self._tail_mass/(1+self._tail_mass))
        self._learn(now,mid)''')


def build():
    assert digest(BASE)==BASE_SHA
    base=BASE.read_text()
    cases={'liquidity_no_probes':replace_once(base,'    QUOTE_SIZE = 1','    QUOTE_SIZE = 0'),
           'liquidity_large_flow':large_flow(base)}
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    candidates=[]
    for name,text in cases.items():
        source=describe(text,'Structural liquidity-taker followup: '+name+
            '. Fixed100-lot exposure and strict all-live reservations. Altered source has no server score.')
        p=ROOT/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==source
        else:p.write_text(source)
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p),risk='strict100'))
    write_json(ROOT/'hypotheses.json',dict(base_source=str(BASE),base_sha256=BASE_SHA,
        candidates=candidates,selection_scope='Two predeclared structural changes on reused public data. No volatility sizing search or server query.'))
    return candidates


def main():
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=2);args=p.parse_args()
    m=load_manifest(Path('logs/round2'))
    report=batch(build(),m['data'],ROOT/'public',
        (m['development_cutoff_us'],m['validation_cutoff_us']),workers=args.workers,
        scope='Two new structural followups; all public data reused for selection, no server result.')
    write_json(Path('results/round2_taker_extensions_public.json'),report)


if __name__=='__main__':main()
