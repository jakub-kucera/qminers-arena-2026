"""Small predeclared H1 study; unchanged native matching and penalties."""
from pathlib import Path
from scripts.round2_ra_composite import main


def build():
    source=Path('research/round2_h1_supplied_20261107/original_submission.py').read_text()
    assert source.count('    POSITION_LIMIT = 1000')==1
    base=source.replace('    POSITION_LIMIT = 1000','    POSITION_LIMIT = 100',1)
    base=base.replace('    CANCEL_FREE = 1.0','    CANCEL_FREE = 0.0',1)
    # Reserve original quantities until cancellation/modification is confirmed.
    begin=base.index('        effective=sum(')
    end=base.index('        quantity=min(',begin)
    base=base[:begin]+'        effective=reserved\n'+base[end:]
    cases={'strict_base':base}
    for clip in (3,6):
        cases[f'clip{clip}']=base.replace('max(-20.0, min(20.0, mid - old_mid))',f'max(-{clip}.0, min({clip}.0, mid - old_mid))',1)
    cases['horizon200']=base.replace('    HORIZON_US = 400000','    HORIZON_US = 200000',1)
    cases['edge005']=base.replace('    TAKE_EDGE = 0.15','    TAKE_EDGE = 0.05',1)
    cases['bias020']=base.replace('BIAS_AGREE = 0.3','BIAS_AGREE = 0.2',1)
    assert len(set(cases.values()))==6
    return cases


if __name__=='__main__':
    main(Path('logs/round2_h1_refine'),build(),
         'H1 strict100 pending reservations baseline; separately clip3/6, 200ms price horizon, edge0.05, or flow bias0.2. Six cases frozen before replay; no combined parameter search. Compare later30-80 gain against H1 129691 and reference222966 150423. Full winner may underperform; public evidence only.')
