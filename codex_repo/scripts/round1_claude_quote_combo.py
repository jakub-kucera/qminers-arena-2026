"""Combine fresh passive quote centers with observed aggressive-order groups."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.round1_claude_combo import second_group
from scripts.round1_new_quote_value import source_for
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_quote_combo')


def main():
    base=Path('strategies/round1_claude_595k.py').read_text()
    cases={}
    for quote_tau,group_tau in ((100000,100000),(500000,100000),(500000,500000)):
        quote=research.transfer_features(base,source_for(quote_tau,100000))
        mixed=second_group(quote,group_tau)
        name=f'quotes{quote_tau}_groups{group_tau}'
        cases[name]=mixed
        if quote_tau==500000:
            cases[name+'_width045']=mixed.replace('floor(fair-0.5)','floor(fair-0.45)').replace(
                'ceil(fair+0.5)','ceil(fair+0.45)')
            cases[name+'_cap1']=mixed.replace('max(-20.0, min(20.0, mid - old_mid))',
                                            'max(-1.0, min(1.0, mid - old_mid))')
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
    full=research.batch(ranked[:3],'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],
        limitation='Sample tuning on already consumed round1.csv, using only currently observable features.'),indent=2)+'\n')
    print('WINNER QUOTE COMBO',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
