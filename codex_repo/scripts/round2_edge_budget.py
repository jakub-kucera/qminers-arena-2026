"""Spend at most one extra execution tick, only when forecast edge covers it.

Adaptive third followup after the no-probe and large-flow comparisons.
It starts from frozen269920, not from their public-selected winner.
"""
from pathlib import Path

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once
from scripts.round2_taker_audit import batch
from scripts.round2_taker_extensions import BASE,BASE_SHA
from scripts.round2_workbench import load_manifest,write_json


def edge_budget(base):
    return replace_once(base,
        '        price = ask+self.TAKE_THRU if sign > 0 else max(1,bid-self.TAKE_THRU)',
        '''        # Retain the original edge margin after paying extra ticks.
        crossing=min(1,max(0,int(abs(signal)-need)))
        price = ask+crossing if sign > 0 else max(1,bid-crossing)''')


def main():
    assert digest(BASE)==BASE_SHA
    root=Path('logs/round2/edge_budget');root.mkdir(exist_ok=True,parents=True)
    p=root/'liquidity_edge_budget.py'
    source=describe(edge_budget(BASE.read_text()),
        'Taker with forecast-budgeted one-tick execution. Same strict100 accounting. No server result.')
    if p.exists():assert p.read_text()==source
    else:p.write_text(source)
    candidates=[dict(name='liquidity_edge_budget',file=str(p),source_sha256=digest(p),risk='strict100')]
    write_json(root/'specs.json',dict(base_source=str(BASE),base_sha256=BASE_SHA,candidates=candidates,
        scope='Adaptive structural followup on reused public data; forecast must pay extra execution cost.'))
    m=load_manifest(Path('logs/round2'))
    report=batch(candidates,m['data'],root/'public',(m['development_cutoff_us'],m['validation_cutoff_us']),1,
        scope='Reused public data. Dynamic IOC limit price; no increased position limit.')
    write_json(Path('results/round2_edge_budget_public.json'),report)


if __name__=='__main__':main()
