"""Full replays combining the strongest fresh-quote and capped-flow families."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_final_combos')


def main():
    base=Path('logs/round1/claude_count_refine/sources/count500_newquotes.py').read_text()
    cases={}
    for tau,cap in ((1000000,1),(1000000,5),(1000000,20),(1000000,100),(500000,5),(500000,100)):
        text=base.replace('second_group_decay=exp(-elapsed/500000)',f'second_group_decay=exp(-elapsed/{tau})')
        text=text.replace('weight=min(1,quantity)',f'weight=min({cap},quantity)').replace(
            'weight=min(1,own)',f'weight=min({cap},own)')
        cases[f'group_tau{tau}_cap{cap}']=text
    for cap in (1,20):
        cases[f'group1s_quote1s_cap{cap}']=cases[f'group_tau1000000_cap{cap}'].replace(
            'decay_new=exp(-dt/500000)','decay_new=exp(-dt/1000000)')
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
        limitation='Direct tuning on consumed full sample, with causal features and unchanged organizer engine.'),indent=2)+'\n')
    print('WINNER FINAL COMBOS',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
