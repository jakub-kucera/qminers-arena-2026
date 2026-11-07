"""Full replays around the strongest one-second count-flow screening candidate."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_count_polish')


def main():
    base=Path('logs/round1/claude_count_refine/sources/count_tau_1000000.py').read_text()
    cases={}
    for memory in (1000000000,3000000000,10000000000):
        cases[f'memory_{memory}']=base.replace('MODEL_MEMORY_US = 100000000000',f'MODEL_MEMORY_US = {memory}')
    cases['width045']=base.replace('floor(fair-0.5)','floor(fair-0.45)').replace('ceil(fair+0.5)','ceil(fair+0.45)')
    cases['cap1']=base.replace('max(-20.0, min(20.0, mid - old_mid))','max(-1.0, min(1.0, mid - old_mid))')
    for horizon in (300000,500000):
        cases[f'horizon_{horizon}']=base.replace('HORIZON_US = 400000',f'HORIZON_US = {horizon}')
    for band in (0.14,0.22):
        cases[f'band_{band}']=base.replace('abs(fair-mid) <= 0.18',f'abs(fair-mid) <= {band}')
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    specs={}
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'source_sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    research.ROOT=ROOT
    full=research.batch(cases,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],
        limitation='Direct tuning on consumed full sample; no fresh holdout. Native fees and 5ms action delay retained.'),indent=2)+'\n')
    print('WINNER COUNT POLISH',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
