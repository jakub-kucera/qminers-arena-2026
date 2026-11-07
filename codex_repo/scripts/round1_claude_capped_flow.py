"""Clip unusually large aggressive orders instead of letting them dominate flow."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.round1_claude_flow_anchors import count_block
from scripts.round1_aggressor_groups import source_for
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_capped_flow')


def source(tau,cap):
    base=Path('strategies/round1_claude_595k.py').read_text()
    text=research.transfer_features(base,source_for(tau,100000))
    start=text.index('        group_decay=')
    end=text.index('        decay = exp(-elapsed/500_000)',start)
    return text[:start]+count_block(tau,cap)+text[end:]


def main():
    cases={f'cap_{cap}_tau_{tau}':source(tau,cap)
           for tau in (250000,500000,1000000) for cap in (5,10,20,50)}
    cases['cap20_tau500_allflow']=source(500000,20).replace('flow = self._net/(1+self._volume)',
        'flow = (self._group_net[0]+self._group_net[1])/(1+self._group_volume[0]+self._group_volume[1])')
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    specs={}
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'source_sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    research.ROOT=ROOT
    screen=research.batch(cases,'logs/round1/screening.csv','screening',workers=3)
    ranked=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)
    full=research.batch(ranked[:4],'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],
        limitation='Sample-tuned size clipping. No future inputs, runtime files or altered simulator configuration.'),indent=2)+'\n')
    print('WINNER CAPPED FLOW',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
