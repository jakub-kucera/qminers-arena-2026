"""Refine count-weighted taker flow and combine it with orthogonal book signals."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.round1_claude_combo import second_group
from scripts.round1_claude_flow_anchors import count_block
from scripts.round1_aggressor_groups import source_for
from scripts.round1_new_quote_value import source_for as quote_source
from scripts.round1_size_cohorts import bucket_source
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/claude_count_refine')


def count_source(base,tau):
    text=research.transfer_features(base,source_for(tau,100000))
    start=text.index('        group_decay=')
    end=text.index('        decay = exp(-elapsed/500_000)',start)
    return text[:start]+count_block(tau,1)+text[end:]


def main():
    base=Path('strategies/round1_claude_595k.py').read_text()
    count=count_source(base,500000)
    cases={f'count_tau_{tau}':count_source(base,tau) for tau in (300000,800000,1000000,2000000)}
    cases['count500_raw100']=second_group(count,100000)
    cases['count500_raw500']=second_group(count,500000)
    cases['count500_buckets']=count_source(research.transfer_features(base,bucket_source()),500000)
    quote=research.transfer_features(base,quote_source(500000,100000))
    mixed=second_group(quote,500000)
    start=mixed.index('        second_group_decay=')
    end=mixed.index('        decay = exp(-elapsed/500_000)',start)
    replacement=count_block(500000,1).replace('_group_','_second_group_').replace(
        '_rest_count','_second_rest_count').replace('group_decay','second_group_decay')
    cases['count500_newquotes']=mixed[:start]+replacement+mixed[end:]
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
        limitation='Sample tuning; only currently observed features and fully matured labels, with native fees.'),indent=2)+'\n')
    print('WINNER COUNT REFINE',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
