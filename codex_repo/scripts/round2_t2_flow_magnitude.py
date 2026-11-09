"""Bounded causal aggressive-flow magnitude features across fixed horizons."""
from pathlib import Path
from scripts.round2_t2_structural import SOURCE
from scripts.round2_ra_composite import main
from scripts.benchmark import digest


def build():
    source=Path('strategies/round2/round2_local_296715.py')
    assert digest(source)=='33ec43e71347d9bf3ea81e7ee48c2bfd48d2310abc784a33c1ed614f5218fd55'
    base=source.read_text();cases={}
    for horizons in ((100000,),(500000,),(2000000,),(100000,500000,2000000)):
        count=33+2*len(horizons)
        text=base.replace('    FEATURE_COUNT = 33',f'    IMPACT_HORIZONS={horizons!r}\n    FEATURE_COUNT = {count}',1)
        text=text.replace('        self.inventory = 0','''        self._impact_time=None
        self._impact_net=[0.0]*len(self.IMPACT_HORIZONS)
        self._impact_volume=[0.0]*len(self.IMPACT_HORIZONS)
        self._impact_frame=()
        self.inventory = 0''',1)
        text=text.replace('    def _learn(self, now, mid):','''    def _impact_features(self,now,trades):
        elapsed=0 if self._impact_time is None else max(0,now-self._impact_time)
        self._impact_time=now
        net=volume=0
        for trade in trades:
            if trade.taker_owner=='market':
                net+=trade.quantity if trade.book_side=='ask' else -trade.quantity
                volume+=trade.quantity
        values=[]
        for i,horizon in enumerate(self.IMPACT_HORIZONS):
            decay=exp(-elapsed/horizon)
            self._impact_net[i]=self._impact_net[i]*decay+net
            self._impact_volume[i]=self._impact_volume[i]*decay+volume
            signed=self._impact_net[i];gross=self._impact_volume[i]
            values.extend((max(-3.0,min(3.0,signed/500.0)),
                signed/(1+gross)*min(9.0,gross/500.0)**0.5))
        return tuple(values)

    def _learn(self, now, mid):''',1)
        text=text.replace('        self._last_us = now','        self._last_us = now\n        self._impact_frame=self._impact_features(now,trades)',1)
        text=text.replace('        self._learn(now,mid)','        features+=self._impact_frame\n        self._learn(now,mid)',1)
        name='multiscale' if len(horizons)>1 else f'horizon{horizons[0]//1000}ms'
        cases[name]=text
    return cases


if __name__=='__main__':
    main(Path('logs/round2_t2_flow_magnitude'),build(),
         'From296715: two bounded signed magnitude features at100/500/2000ms decay or all3 horizons. Net-volume/500 clipped3 and normalized direction times sqrt gross intensity clipped3. Market takers only, past/current trades only. Four fixed cases; unchanged execution and learner settings. Reference later30-80=188941.',
         goal=dict(reference_audit='logs/round2_t2_liquidity_supplied/full_audit.json',reference_source_sha256=digest(SOURCE),increment=50000))
