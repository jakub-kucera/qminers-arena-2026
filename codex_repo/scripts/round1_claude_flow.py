"""Refine the promising aggressive-order grouping, plus liquidity interactions."""
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round1_aggressor_groups import source_for

ROOT = Path('logs/round1/claude_flow')


def liquidity(base):
    extra = '''(bn-an)/20,(br-ar)/400,(bd_n-ad_n)/40,(bd_r-ad_r)/800,
                  count_imbalance*20/max(5,bn+an),
                  robust_imbalance*400/max(100,br+ar),
                  depth_count*40/max(10,bd_n+ad_n),
                  depth_imbalance*800/max(200,bd_r+ad_r)'''
    return base.replace('FEATURE_COUNT = 15','FEATURE_COUNT = 23').replace(
        'robust_imbalance*abs(robust_imbalance))',
        'robust_imbalance*abs(robust_imbalance),'+extra+')')


def main():
    base = Path('strategies/round1_claude_595k.py').read_text()
    cases = {}
    for tau in (100000, 200000, 1000000, 2000000):
        cases[f'groups_tau_{tau}'] = research.transfer_features(base, source_for(tau,100000))
    group = research.transfer_features(base, source_for(500000,100000))
    for horizon in (250000, 300000, 500000, 600000):
        cases[f'groups_h_{horizon}'] = group.replace('HORIZON_US = 400000',f'HORIZON_US = {horizon}')
    cases['liquidity'] = liquidity(base)
    cases['liquidity_low_ridge'] = cases['liquidity'].replace('0.001 * self._mass','0.0001 * self._mass')
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    specs = {}
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py')
        path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'source_sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    research.ROOT = ROOT
    screen=research.batch(cases,'logs/round1/screening.csv','screening',workers=2)
    ranked=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)
    full=research.batch(ranked[:3],'data/round1.csv','full',workers=2)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],
        limitation='Sample tuning, using only causal public observations and unchanged native fees.'),indent=2)+'\n')
    print('WINNER FLOW',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
