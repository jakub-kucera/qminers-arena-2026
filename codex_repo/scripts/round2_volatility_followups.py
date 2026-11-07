"""Predeclared development checks of faster absolute-volatility adaptation."""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import build_candidates,replace_once,run_study
from scripts.round2_volatility_exposure import volatility_model


def main():
    base=build_candidates(Path('strategies/round2/round2_transfer.py').read_text())['jump_pause100ms']
    base=replace_once(base,'now-self._invalid_since >= 50_000','now-self._invalid_since >= 0')
    cases={}
    for tau,budget in ((1,100),(3,100),(3,150),(10,75)):
        name=f'absolute_vol_tau{tau}_risk{budget}'
        cases[name]=describe(volatility_model(base,tau,budget,1),
            'Round-2 faster absolute-volatility exposure development hypothesis: '+name+
            '. Causal regular-sample sigma; native fees and latency unchanged.')
    run_study(cases,'logs/round2/absolute_vol_followups',workers=2)


if __name__=='__main__':main()
