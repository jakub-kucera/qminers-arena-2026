"""Small predeclared inverse-absolute-variance exposure mechanism checks."""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import build_candidates,replace_once,run_study
from scripts.round2_volatility_exposure import volatility_model


def main():
    base=build_candidates(Path('strategies/round2/round2_transfer.py').read_text())['jump_pause100ms']
    base=replace_once(base,'now-self._invalid_since >= 50_000','now-self._invalid_since >= 0')
    cases={}
    for tau,budget in ((1,200),(3,200),(10,100)):
        name=f'absolute_variance_tau{tau}_risk{budget}'
        cases[name]=volatility_model(base,tau,budget,2)
    pause=replace_once(base,'self._pause_until=now+100000','self._pause_until=now+500000')
    cases['absolute_variance_tau10_pause500']=volatility_model(pause,10,200,2)
    cases={n:describe(t,'Round-2 inverse-absolute-variance development hypothesis: '+n+
                      '. Causal regular samples and original native rules.') for n,t in cases.items()}
    run_study(cases,'logs/round2/absolute_variance_followups',workers=2)


if __name__=='__main__':main()
