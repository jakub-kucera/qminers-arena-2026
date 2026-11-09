"""Public-fill conditional alpha with the saved volatility sizing held fixed."""
from pathlib import Path

from scripts.round2_conditional_market_fills import conditional_model
from scripts.round2_jump_models import run_study
from scripts.build_round2_candidates import describe


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    cases={}
    for horizon,mode in ((100000,'gate'),(400000,'gate'),(400000,'shade')):
        name=f'fixed_risk_conditional_{horizon}_{mode}'
        text=conditional_model(base,horizon,mode)
        text=text.replace('if self.inventory>=0 and self._conditional_edge(1,buy,',
                          'if buy is not None and self.inventory>=0 and self._conditional_edge(1,buy,')
        text=text.replace('if self.inventory<=0 and self._conditional_edge(-1,sell,',
                          'if sell is not None and self.inventory<=0 and self._conditional_edge(-1,sell,')
        cases[name]=describe(text,
            'Development-only public-fill conditional forecast: '+name+
            '. Absolute-volatility parameters held fixed; preceding features and matured markouts.')
    run_study(cases,'logs/round2/fixed_risk_conditional',workers=2)


if __name__=='__main__':main()
