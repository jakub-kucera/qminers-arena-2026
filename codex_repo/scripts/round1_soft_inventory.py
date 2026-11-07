"""Forecast-dependent inventory bounds instead of changing quote prices alone."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/soft_inventory')


def source_for(mode, threshold, adverse=0, band=50):
    text=Path('strategies/round1_private_554347.py').read_text()
    text=text.replace('        self._orders = {}','        self._orders = {}\n        self._forecast = 0.0',1)
    if mode=='gated':
        body=f'''        lower,upper = -100,100
        if self._forecast > {threshold}:
            lower = -{adverse}
        elif self._forecast < -{threshold}:
            upper = {adverse}'''
    elif mode=='smooth':
        body=f'''        conviction = min(1.0,abs(self._forecast)/{threshold})
        adverse = int(100*(1-conviction))
        lower = -adverse if self._forecast > 0 else -100
        upper = adverse if self._forecast < 0 else 100'''
    else:
        body=f'''        target = max(-100,min(100,100*self._forecast/{threshold}))
        lower,upper = max(-100,int(target-{band})),min(100,int(target+{band}))'''
    helper='''    def _capacity(self, sign):
'''+body+'''
        return max(0,upper-self.inventory if sign > 0 else self.inventory-lower)

'''
    text=text.replace('    def _quote(self, now, sign, price):',helper+'    def _quote(self, now, sign, price):')
    text=text.replace('''        changing = False
        for oid,record in current:''','''        capacity = self._capacity(sign)
        excess = sum(r[2] for oid,r in current)-capacity
        if excess > 0:
            for oid,record in reversed(current):
                self._cancel(oid)
                excess -= record[2]
                if excess <= 0:
                    break
        changing = False
        for oid,record in current:''')
    text=text.replace('self.POSITION_LIMIT-sign*self.inventory-reserved','capacity-reserved')
    text=text.replace('        self._desired_buy,self._desired_sell,self._desired_time =',
                      '        self._forecast = prediction-skew\n        self._desired_buy,self._desired_sell,self._desired_time =')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;specs={}
    configs=[('gated',t,a,50) for t in (0.05,0.1,0.2) for a in (0,25,50)]
    configs += [('smooth',t,0,50) for t in (0.1,0.2,0.4)]
    configs += [('center',t,0,b) for t in (0.1,0.2) for b in (25,50)]
    for mode,threshold,adverse,band in configs:
        name=f'{mode}_{threshold}_{adverse}_{band}'
        path=ROOT/'sources'/(name+'.py');path.write_text(source_for(mode,threshold,adverse,band))
        assert not check(path),check(path)
        specs[name]=dict(mode=mode,threshold=threshold,adverse_limit=adverse,band=band,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Further tuning on consumed round1; pending cancellations retain their reservations and the hard exposure bound is 100.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
