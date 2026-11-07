"""Round-1 sample tuning after its original held-out segment was evaluated."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/target550')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('strategies/round1_best.py').read_text()
    configs=[]
    for close in (0,25,50,75):
        configs.append({'close':close,'band':.1,'size':200,'skew':.1})
    for band in (0,.05,.15,.2,.3):
        configs.append({'close':None,'band':band,'size':200,'skew':.1})
    for size in (40,60,100):
        configs.append({'close':0,'band':.1,'size':size,'skew':.1})
    for skew in (0,.05,.25,.5):
        configs.append({'close':None,'band':.1,'size':200,'skew':skew})
    specs={}
    for i,params in enumerate(configs):
        n=f'execution_{i:02d}'
        text=base.replace('QUOTE_SIZE = 200',f'QUOTE_SIZE = {params["size"]}')
        text=text.replace('abs(fair-mid) <= 0.1',f'abs(fair-mid) <= {params["band"]}')
        text=text.replace('skew = 0.1 *',f'skew = {params["skew"]} *')
        if params['close'] is not None:
            text=text.replace('        # Withdraw the side',f'''        if self.inventory > {params['close']}:
            sell = ask
        elif self.inventory < -{params['close']}:
            buy = bid
        # Withdraw the side''')
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={**params,'sha256':digest(path)}
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screened=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screened,key=lambda n:screened[n]['result']['pnl'],reverse=True)[:3]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=search_queue.batch(finalists,'data/round1.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Further tuning on the already evaluated round-1 file.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
