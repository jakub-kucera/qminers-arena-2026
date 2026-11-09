"""Test longer forecasts with rescaled quote strength and sufficient label buffers."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_horizon_scale')


def main():
    base=Path('logs/round1/claude_count_refine/sources/count500_newquotes.py').read_text()
    cases={}
    for horizon,gain in ((800000,0.5),(800000,0.75),(1200000,1/3),(1200000,0.5),(2000000,0.2),(2000000,0.4)):
        text=base.replace('HORIZON_US = 400000',f'HORIZON_US = {horizon}')
        text=text.replace('deque(maxlen=64)',f'deque(maxlen={horizon//20000+32})')
        old='prediction = max(-2.0,min(2.0,sum(w*x for w,x in zip(self._weights,features))))'
        assert old in text
        cap=2*horizon/400000
        text=text.replace(old,f'prediction = max(-{cap},min({cap},sum(w*x for w,x in zip(self._weights,features))))')
        text=text.replace('        fair = mid + ',f'        prediction=max(-2.0,min(2.0,{gain}*prediction))\n        fair = mid + ',1)
        cases[f'horizon{horizon}_gain{gain}']=text
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
        limitation='Direct sample tuning, causal matured labels and original organizer fees and latency.'),indent=2)+'\n')
    print('WINNER HORIZON SCALE',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
