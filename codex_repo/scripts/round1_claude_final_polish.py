"""Full-sample final parameter comparisons around the audited 622920.99 model."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_final_polish')


def main():
    base=Path('logs/round1/claude_final_combos/sources/group_tau1000000_cap20.py').read_text()
    cases={}
    for memory in (3000000000,10000000000):
        cases[f'memory_{memory}']=base.replace('MODEL_MEMORY_US = 100000000000',f'MODEL_MEMORY_US = {memory}')
    for gain in (0.8,1.2):
        cases[f'gain_{gain}']=base.replace('fair = mid + 1.0*prediction',f'fair = mid + {gain}*prediction')
    for ridge in (0.0003,0.003):
        cases[f'ridge_{ridge}']=base.replace('0.001 * self._mass',f'{ridge} * self._mass')
    cases['cap1']=base.replace('max(-20.0, min(20.0, mid - old_mid))','max(-1.0, min(1.0, mid - old_mid))')
    cases['width045']=base.replace('floor(fair-0.5)','floor(fair-0.45)').replace('ceil(fair+0.5)','ceil(fair+0.45)')
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    specs={}
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'source_sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    research.ROOT=ROOT
    full=research.batch(cases,'data/round1.csv','full',workers=4)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],
        limitation='Direct tuning on consumed full sample; native latency and inventory fees.'),indent=2)+'\n')
    print('WINNER FINAL POLISH',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
