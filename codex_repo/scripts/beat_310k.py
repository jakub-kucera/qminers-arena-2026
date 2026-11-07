"""Further v2 sample tuning; all inventory including pending cancels is reserved."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/target310')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('strategies/passive_v2_champion.py').read_text()
    configs=[]
    for layers in (4,8,16):
        for cooldown in (0,5000):
            for minimum in (1,10):
                configs.append(dict(layers=layers,cooldown=cooldown,minimum=minimum,skew=.1))
    for skew in (.25,.5,1.0):
        configs.append(dict(layers=8,cooldown=0,minimum=1,skew=skew))
    for keep in (.2,.3):
        configs.append(dict(layers=8,cooldown=0,minimum=1,skew=.1,keep=keep))
    for threshold in (25,50,75):
        configs.append(dict(layers=8,cooldown=0,minimum=1,skew=.1,exit=threshold))
    specs={}
    for index,params in enumerate(configs):
        name=f'variant_{index:02d}'
        text=base.replace('if len(current) >= 4:',f'if len(current) >= {params["layers"]}:')
        text=text.replace('REQUOTE_US = 5000',f'REQUOTE_US = {params["cooldown"]}')
        text=text.replace('quantity < 10',f'quantity < {params["minimum"]}')
        text=text.replace('skew = 0.1 *',f'skew = {params["skew"]} *')
        text=text.replace('At most 4 orders',f'At most {params["layers"]} orders')
        if 'keep' in params:
            text=text.replace('        # Withdraw the side',f'''        if abs(fair-mid) < {params['keep']}:
            if any(r[0] == 1 and r[1] == bid and not r[4] for r in self._orders.values()):
                buy = bid
            if any(r[0] == -1 and r[1] == ask and not r[4] for r in self._orders.values()):
                sell = ask
        # Withdraw the side''')
        if 'exit' in params:
            text=text.replace('        self.queue_ahead = {}','        self.queue_ahead = {}\n        self._exit_side = 0',1)
            text=text.replace('        if quantity <= 0 or (current and quantity <', '''        if self._exit_side == sign:
            quantity = min(quantity,max(0,-sign*self.inventory-reserved))
        if quantity <= 0 or (current and quantity <''')
            text=text.replace('        # Withdraw the side',f'''        self._exit_side = 0
        if spread >= 2 and self.inventory > {params['exit']}:
            sell = ask-1
            self._exit_side = -1
        elif spread >= 2 and self.inventory < -{params['exit']}:
            buy = bid+1
            self._exit_side = 1
        # Withdraw the side''')
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]={**params,'sha256':digest(path)}
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    (ROOT/'finalists.json').write_text(json.dumps(finalists,indent=2)+'\n')
    full=search_queue.batch(finalists,'data/sample_v2.csv','full')
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs[winner],
        'result':full[winner],'limitation':'Tuned on previously evaluated v2 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
