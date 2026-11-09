"""Fill-value margins, latency responsiveness and quote-alpha combination.

The pretrained tree weights and every volatility-sizing parameter stay fixed.
These are reused-public model-selection comparisons, not fresh validation.
"""
import argparse
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once
from scripts.round2_fresh_quote_alpha import fast_quotes
from scripts.round2_full_public_study import run_public_study


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    base=Path('strategies/round2_fill_value_162253.py').read_text()
    cases={}
    assert base.count('))<0.0)')==2
    for threshold in (.1,.2):
        cases[f'fill_value_margin{threshold}']=base.replace('))<0.0)',f'))<{threshold})')
    cases['fill_value_fast_refresh']=replace_once(base,
        'now-self._tree_time>=20000','now-self._tree_time>=5000')
    cases['fill_value_fresh_quote100ms']=fast_quotes(base,100000)
    cases={n:describe(t,'Reused-public conditional-fill-value follow-up: '+n+
        '. Original pretrained weights and volatility sizing fixed; first60% training overlap remains.') for n,t in cases.items()}
    run_public_study(cases,'logs/round2/fill_value_followups',workers=args.workers)


if __name__=='__main__':main()
