"""Causal fast price-reversion, jump-age and slower reference-price features."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/fast_price')


def augment(text,base_count,mode='all'):
    count={'fast':6,'slow':4,'all':10}[mode]
    text=text.replace(f'FEATURE_COUNT = {base_count}',f'FEATURE_COUNT = {base_count+count}')
    text=text.replace('isfinite\n','isfinite, sqrt\n').replace('isfinite, log\n','isfinite, log, sqrt\n')
    text=text.replace('        self._orders = {}', '''        self._orders = {}
        self._extra_time = None
        self._extra_mid = self._extra_anchor = None
        self._extra_emas = None
        self._extra_move = 0.0
        self._extra_jump = 0
        self._extra_var = 0.0''',1)
    tail={'fast':'fast','slow':'slow','all':'fast+slow'}[mode]
    helper='''    def _extra_features(self, now, mid, count_imbalance):
        if self._extra_time is None:
            self._extra_mid = self._extra_anchor = mid
            self._extra_emas = [mid]*5
            self._extra_jump = now
        dt=0 if self._extra_time is None else max(0,now-self._extra_time)
        for i,tau in enumerate((20000,100000,10000000,30000000,100000000)):
            self._extra_emas[i]+=(1-exp(-dt/tau))*(mid-self._extra_emas[i])
        change=mid-self._extra_mid
        self._extra_var=self._extra_var*exp(-dt/500000)+change*change
        if change:
            self._extra_move=change
            self._extra_jump=now
        self._extra_mid,self._extra_time=mid,now
        age=max(0,now-self._extra_jump)
        volatility=sqrt(max(0,self._extra_var))
        fast=(max(-5,min(5,mid-self._extra_emas[0])),
              max(-5,min(5,mid-self._extra_emas[1])),
              self._extra_move*exp(-age/50000),age/(age+100000),
              volatility,count_imbalance*volatility)
        slow=((mid-self._extra_emas[2])/5,(mid-self._extra_emas[3])/10,
              (mid-self._extra_emas[4])/20,(mid-self._extra_anchor)/20)
        return '''+tail+'\n\n'
    text=text.replace('    def _cancel(self, order_id):',helper+'    def _cancel(self, order_id):')
    if base_count==15:
        old='robust_imbalance*abs(robust_imbalance))'
    else:
        old='(bq/max(1,bn)-aq/max(1,an))/max(1,bq/max(1,bn)+aq/max(1,an)))'
    assert old in text
    text=text.replace(old,old+'+self._extra_features(now,mid,count_imbalance)')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;base=Path('strategies/round1_private_554347.py').read_text();specs={}
    for mode in ('fast','all'):
        for horizon in (100000,500000):
            for gain in (0.75,1.25):
                name=f'{mode}_{horizon}_gain_{gain}'
                text=augment(base,15,mode).replace('HORIZON_US = 100000',f'HORIZON_US = {horizon}')
                text=text.replace('        fair = mid + ',f'        prediction *= {gain}\n        fair = mid + ')
                path=ROOT/'sources'/(name+'.py');path.write_text(text)
                assert not check(path),check(path)
                specs[name]=dict(mode=mode,horizon=horizon,gain=gain,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning; every added feature is updated only from observed midpoints and elapsed public-feed time.'),indent=2)+'\n')
    print('WINNER FAST PRICE',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
