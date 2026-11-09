"""Bounded flow freshness and directional-purity experiments."""
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_ra_composite import main as run_study


def build():
    p=Path('strategies/round2/round2_local_195721.py')
    assert digest(p)=='e2d55a7d606b1a679070bc386182c38d7bf8b35da8b5a77d6a55ae408b0118e2'
    base=p.read_text();cases={}
    for milliseconds in (250,1000,3000):
        text=base.replace('        self._ra_anchor=0.0','        self._ra_last_fire=None\n        self._ra_anchor=0.0',1)
        text=text.replace('        if fired:\n','        if fired:\n            self._ra_last_fire=now\n',1)
        anchor='            if self._ra_stopped:'
        assert text.count(anchor)==1
        text=text.replace(anchor,f'            if self._ra_stopped or self._ra_last_fire is None or now-self._ra_last_fire>{milliseconds*1000}:',1)
        cases[f'fresh{milliseconds}ms']=text
    for purity in (.25,.5):
        anchor='        fired=1 if flow>=500 else -1 if flow<=-500 else 0'
        assert base.count(anchor)==1
        text=base.replace(anchor,f'''        if abs(flow)>=500:
            gross=sum(abs(quantity) for _,quantity in self._ra_flow)
            if abs(flow)<{purity}*gross:
                flow=0
'''+anchor,1)
        cases[f'purity{purity}']=text
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_ra_flow_quality'),build(),
        'Return to the maker after250/1000/3000ms without a qualifying flow fire, or require net flow to exceed25/50percent of gross callback flow. Keep shadow and risk accounting unchanged.')
