"""Inventory-conditioned forecast thresholds with unchanged100-lot risk."""
from pathlib import Path
from scripts.round2_t2_structural import SOURCE
from scripts.round2_ra_composite import main
from scripts.benchmark import digest


def build():
    p=Path('strategies/round2/round2_local_294098.py')
    assert digest(p)=='06acfa3b209a6a3ccbf7beb08ec0715774c87bf98becdeae07f52465c3380f09'
    base=p.read_text();assert base.count('    SKEW_K = 0.025')==1
    return {f'skew{k}':base.replace('    SKEW_K = 0.025',f'    SKEW_K = {k}',1)
            for k in (.1,.25,.5,.75)}


if __name__=='__main__':
    main(Path('logs/round2_t2_inventory_response'),build(),
         'Four coarse inventory skew strengths0.1/0.25/0.5/0.75 from no-passive294098, versus0.025. Same model/execution pace/spread gate and hard100. Stronger skew makes reducing/reversing exposure easier; no independent time exits or larger limits. Reference later30-80=185349.',
         goal=dict(reference_audit='logs/round2_t2_liquidity_supplied/full_audit.json',reference_source_sha256=digest(SOURCE),increment=50000))
