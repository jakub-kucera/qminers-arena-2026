"""Predeclared combination of two independently tested improvements."""
from pathlib import Path
from scripts.round2_residual_ridge import build as original_build
from scripts.round2_ra_composite import main as run_study


def build():
    original=original_build();cases={}
    for ridge,blend in ((5,.25),(5,.5),(5,.75),(25,.5)):
        text=original[f'ridge{ridge}_blend0.5']
        maturity='self._cal_labels[0][0]+400000<=now'
        stale='now-observed<=1400000'
        assert text.count(maturity)==1 and text.count(stale)==1
        text=text.replace(maturity,'self._cal_labels[0][0]+200000<=now',1)
        text=text.replace(stale,'now-observed<=1200000',1)
        assert text.count('0.5*self._cal_groups[')==2
        assert text.count('0.5*self._res_predict(')==2
        text=text.replace('0.5*self._cal_groups[',f'{1-blend}*self._cal_groups[')
        text=text.replace('0.5*self._res_predict(',f'{blend}*self._res_predict(')
        cases[f'h200_ridge{ridge}_blend{blend}']=text
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_residual_horizon_combo'),build(),
        'Combine200ms fill-label maturity with residual ridge5 blended25/50/75percent or ridge25 blended50percent. Same causal stored features and native risk. Reference222966 first80=189889,later50=150423. No assumed additive gain.')
