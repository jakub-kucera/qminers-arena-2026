"""Round-1 development only. Validation and final evaluation are separate steps."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/search')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    specs={}
    for features in (3,5):
        template=Path('strategies/round1_linear_base.py' if features==3 else 'strategies/round1_ofi_base.py').read_text()
        for horizon in (100000,500000,2000000):
            for blend in (.5,1.0):
                for ridge in ((.01,.05) if features==3 else (.01,)):
                    n=f'f{features}_h{horizon}_b{blend}_r{ridge}'
                    text=template.replace('HORIZON_US = 500000',f'HORIZON_US = {horizon}')
                    text=text.replace('0.01 * self._mass',f'{ridge} * self._mass')
                    text=text.replace('0.5*prediction + 0.5*0.25*spread*imbalance',f'{blend}*prediction + {1-blend}*0.25*spread*imbalance')
                    path=ROOT/'sources'/(n+'.py');path.write_text(text)
                    assert not check(path),check(path)
                    specs[n]={'features':features,'horizon_us':horizon,'model_blend':blend,'ridge':ridge,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screened=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    # Retain feature-family diversity alongside the strongest early results.
    ranked=sorted(screened,key=lambda n:screened[n]['result']['pnl'],reverse=True)
    best5=max((n for n in specs if specs[n]['features']==5),key=lambda n:screened[n]['result']['pnl'])
    promoted=list(dict.fromkeys(ranked[:5]+[best5]))
    developed=search_queue.batch(promoted,'logs/round1/development.csv','development')
    ranked=sorted(developed,key=lambda n:developed[n]['result']['pnl'],reverse=True)
    frozen={'names':ranked[:3],'sources':{n:str(ROOT/'sources'/(n+'.py')) for n in ranked[:3]},
            'hashes':{n:digest(ROOT/'sources'/(n+'.py')) for n in ranked[:3]},
            'selection':'Ranked on first 60% only. Next 20% and final 20% remain unevaluated.'}
    (ROOT/'shortlist.json').write_text(json.dumps(frozen,indent=2)+'\n')
    print('DEVELOPMENT SHORTLIST',frozen['names'],flush=True)


if __name__=='__main__':main()
