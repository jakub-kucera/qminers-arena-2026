"""Execution sensitivity without changing supplied T2's learned forecast."""
from pathlib import Path
from scripts.round2_t2_structural import SOURCE
from scripts.round2_ra_composite import main
from scripts.benchmark import digest


def build():
    base=SOURCE.read_text().replace('    POSITION_LIMIT = 1000','    POSITION_LIMIT = 100',1)
    begin=base.index('        effective=sum(');end=base.index('        quantity=min(',begin)
    base=base[:begin]+'        effective=reserved\n'+base[end:]
    cases={}
    for gap in (10,25,100):
        cases[f'gap{gap}ms']=base.replace('    TAKE_GAP_MS = 50',f'    TAKE_GAP_MS = {gap}',1)
    for edge in (0.0,0.3):
        cases[f'edge{edge}']=base.replace('    TAKE_EDGE = 0.15',f'    TAKE_EDGE = {edge}',1)
    cases['no_passive']=base.replace('    QUOTE_SIZE = 1','    QUOTE_SIZE = 0',1)
    assert len(set(cases.values()))==6
    return cases


if __name__=='__main__':
    main(Path('logs/round2_t2_execution'),build(),
         'Execution sensitivity from supplied liquidity model, no structural-study winner reuse: gap10/25/100ms versus50, edge0/0.3 versus0.15, or disable one-lot passive quotes. Same 33feature causal learner and spread1 gate. Six fixed cases, strict100. Baseline first80=209280,later30-80=174033,full269920. Target319920.',
         goal=dict(reference_audit='logs/round2_t2_liquidity_supplied/full_audit.json',reference_source_sha256=digest(SOURCE),increment=50000))
