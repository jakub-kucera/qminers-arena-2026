"""Predeclared structural changes to the supplied liquidity-feature taker."""
import ast
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_ra_composite import main

SOURCE=Path('research/round2_t2_liquidity_supplied_20261107/original_submission.py')


def method(source,name):
    cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef))
    node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    return '    '+ast.get_source_segment(source,node)+'\n\n'


def build():
    base=SOURCE.read_text()
    # No behavior change is expected for the existing one-lot quotes, but
    # enforce the intended all-live100 limit in every future admission path.
    base=base.replace('    POSITION_LIMIT = 1000','    POSITION_LIMIT = 100',1)
    begin=base.index('        effective=sum(');end=base.index('        quantity=min(',begin)
    base=base[:begin]+'        effective=reserved\n'+base[end:]
    h1=Path('research/round2_h1_supplied_20261107/original_submission.py').read_text()
    states=h1[h1.index('        self._flow = deque()'):h1.index('\n    def _learn')]
    biased=base.replace('\n    def _distribution_features',states+'\n    def _distribution_features',1)
    begin=biased.index('    def _take(');end=biased.index('    def _cancel(',begin)
    biased=biased[:begin]+method(h1,'_take')+method(h1,'_update_big')+biased[end:]
    biased=biased.replace('        spread = ask-bid','        spread = ask-bid\n        self._update_big(now,trades,bid,ask,mid)',1)
    knobs='\nBIAS_AGAINST=0\nAGREE_MAXSPREAD=1\nROOM_RESERVED=1\nMIN_LOTS=500\nFLOW_MS=250\nSELF_GATE=1\nGATE_TICKS=10\nSTOP=3\n'
    cases={}
    for bias in (.2,.3):
        cases[f'flow_bias{bias}']=biased.replace('\nclass PassiveStrategy',f'\nBIAS_AGREE={bias}\n'+knobs+'\nclass PassiveStrategy',1)
    cases['ridge3x']=base.replace('ridge = max(10.0, 0.001 * self._mass)','ridge = max(30.0, 0.003 * self._mass)',1)
    cases['memory1800s']=base.replace('    MODEL_MEMORY_US = 100000000000','    MODEL_MEMORY_US = 1800000000',1)
    cases['horizon800ms']=base.replace('    HORIZON_US = 400000','    HORIZON_US = 800000',1)
    extra=base.replace('    FEATURE_COUNT = 33','    FEATURE_COUNT = 36',1)
    extra=extra.replace('        self._learn(now,mid)', '''        features+=(self._distribution_frame[0][21],
                   self._distribution_frame[0][23],
                   flow*min(3.0,self._distribution_frame[1][1]))
        self._learn(now,mid)''',1)
    cases['age_concentration']=extra
    assert len(set(cases.values()))==6
    return cases


if __name__=='__main__':
    main(Path('logs/round2_t2_structural'),build(),
         'Supplied33feature liquidity taker: add H1 flow bias0.2/0.3, or independently ridge3x, memory1800s, horizon800ms, or age/concentration/liquidity interaction. Strict100, six frozen cases. Select positive30-60 and60-80 by combined gain before full. Target supplied full native net plus50000, not previous250k.',
         goal=dict(reference_audit='logs/round2_t2_liquidity_supplied/full_audit.json',reference_source_sha256=digest(SOURCE),increment=50000))
