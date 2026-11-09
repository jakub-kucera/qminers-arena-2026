"""Ablate correlated flow features and test depth-normalized impact."""
from pathlib import Path
from scripts.round2_t2_flow_magnitude import build as magnitude
from scripts.round2_ra_composite import main


def build():
    base=magnitude()['horizon500ms'];cases={}
    anchor='        features+=self._impact_frame'
    assert base.count(anchor)==1 and base.count('    FEATURE_COUNT = 35')==1
    depth='max(-3.0,min(3.0,self._impact_net[0]/(1+(aq if self._impact_net[0]>=0 else bq))))'
    for name,expression,count in (
        ('net_only','(self._impact_frame[0],)',34),
        ('sqrt_only','(self._impact_frame[1],)',34),
        ('depth_only',f'({depth},)',34),
        ('magnitude_and_depth',f'self._impact_frame+({depth},)',36)):
        cases[name]=base.replace('    FEATURE_COUNT = 35',f'    FEATURE_COUNT = {count}',1).replace(anchor,'        features+='+expression,1)
    return cases


if __name__=='__main__':
    main(Path('logs/round2_t2_impact_ablation'),build(),
         'New user goal main plus>=10k, main36a041a audited bestactive-6116/control0. Stronger fixed local-cycle guard306715=296715+10000. Ablate500ms net vs sqrt magnitude; or net/opposite touch depth, alone or with both. Four cases, no crash-time gates or directional bias. Current304476 later30-80=196983, full gain7761.',
         goal=306715)
