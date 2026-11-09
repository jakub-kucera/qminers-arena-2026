"""V2 tuning of inventory capacity reserved for wider-spread opportunities."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/sample_v2/spread_budget')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/sample_v2/target310/sources/variant_04.py').read_text()
    specs={}
    for cap in (0,25,50,75):
        for cancel in (False,True):
            n=f'spread_cap_{cap}_cancel_{cancel}'
            text=base.replace('        self._orders = {}','        self._orders = {}\n        self._active_cap = 100',1)
            text=text.replace('self.POSITION_LIMIT-sign*self.inventory-reserved','self._active_cap-sign*self.inventory-reserved')
            text=text.replace('        mid = (bid+ask)*0.5',f'        self._active_cap = {cap} if ask-bid == 1 else 100\n        mid = (bid+ask)*0.5')
            if cancel:
                text=text.replace('        changing = False','''        reserved = sum(r[2] for oid,r in current)
        if sign*self.inventory+reserved > self._active_cap:
            for oid,r in current:
                self._cancel(oid)
            return
        changing = False''')
            path=ROOT/'sources'/(n+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[n]={'one_tick_cap':cap,'cancel_excess':cancel,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/sample_v2/search/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>88000]
    full=search_queue.batch(finalists,'data/sample_v2.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Tuned on previously evaluated v2.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
