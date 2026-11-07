"""Separate passive reduction quotes from opening forecasts, development only."""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    anchor='        if self._last_mid is not None and abs(mid-self._last_mid)>=2:'
    cases={}
    for name,condition_long,condition_short in (
        ('reduce_at_touch','self.inventory>0','self.inventory<0'),
        ('reduce_large_at_touch','self.inventory>=50','self.inventory<=-50'),
        ('reduce_weak_forecast_at_touch','self.inventory>0 and prediction<0.5',
         'self.inventory<0 and prediction> -0.5')):
        block=f'''        if {condition_long}:
            sell=ask
        elif {condition_short}:
            buy=bid
'''
        cases[name]=replace_once(base,anchor,block+anchor)
    cases['capacity_normalized_skew']=replace_once(base,
        'skew = 0.025 * self.inventory/100 * max(1.0,spread)',
        'skew = 0.25 * self.inventory/max(10,self._upper_target) * max(1.0,spread)')
    cases={n:describe(t,'Development-only passive inventory-reduction hypothesis: '+n+
        '. Uses absolute-volatility sizing; jump guards, native latency and fees unchanged.') for n,t in cases.items()}
    run_study(cases,'logs/round2/inventory_exit_quotes',workers=3)


if __name__=='__main__':main()
