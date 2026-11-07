"""Final causal quote-center filters around the audited 622920.99 candidate."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_quote_refine')


def main():
    base=Path('logs/round1/claude_final_combos/sources/group_tau1000000_cap20.py').read_text()
    cases={}
    assert 'if order.quantity<=50:' in base
    for cap in (5,20,100,200):
        cases[f'fresh_size_{cap}']=base.replace('if order.quantity<=50:',f'if order.quantity<={cap}:')
    cases['fresh_memory_2s']=base.replace('decay_new=exp(-dt/500000)','decay_new=exp(-dt/2000000)')
    for depth in (5,8):
        cases[f'fresh_depth_{depth}']=base.replace('if distance>3:',f'if distance>{depth}:').replace(
            'if abs(distance)>3:',f'if abs(distance)>{depth}:')
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
        limitation='Final parameter tuning on consumed sample; only visible current and past market information.'),indent=2)+'\n')
    print('WINNER QUOTE REFINE',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
