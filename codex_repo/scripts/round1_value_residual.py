"""Use shadow execution values as a residual on the proven online fair-price model."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/value_residual')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;base=Path('strategies/round1_private_554347.py').read_text();specs={}
    models={'early':'value_0.6_128_15_0.0','full':'value_1.0_128_31_0.0'}
    for label,model_name in models.items():
        model_source=Path('logs/round1/shadow_value/sources')/(model_name+'.py')
        learned=model_source.read_text();start=learned.index('    def _value(');end=learned.index('    def _cancel(',start)
        helper=learned[start:end]
        for gain in ((0.0,1.0,5.0,15.0,30.0) if label=='early' else (1.0,5.0,15.0,30.0)):
            name=f'value_{label}_gain_{gain}'
            text=base.replace('isfinite\n','isfinite, log\n')
            text=text.replace('        self._orders = {}', '''        self._orders = {}
        self._value_time = None
        self._value_touch = None
        self._value_bias = 0.0''',1)
            text=text.replace('    def _cancel(self, order_id):',helper+'    def _cancel(self, order_id):')
            addition=f'''        if self._value_time is None or now-self._value_time>=5000 or self._value_touch!=(bid,ask):
            value_features=features+(spread,(bn+an)/20,(bd_n+ad_n)/40,log(1+bq+aq)/10,
                (bq/max(1,bn)-aq/max(1,an))/max(1,bq/max(1,bn)+aq/max(1,an)))
            buy_value=self._value(self._frame(value_features,1,bid,mid,bq,0))
            sell_value=self._value(self._frame(value_features,-1,ask,mid,aq,0))
            self._value_bias=max(-0.5,min(0.5,{gain}*(buy_value-sell_value)))
            self._value_time,self._value_touch=now,(bid,ask)
        prediction=max(-2.0,min(2.0,prediction+self._value_bias))
'''
            text=text.replace('        fair = mid + ',addition+'        fair = mid + ')
            path=ROOT/'sources'/(name+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[name]=dict(model_training_fraction=0.6 if label=='early' else 1.0,gain=gain,
                learned_model_source_sha256=digest(model_source),source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    assert screen['value_early_gain_0.0']['result']['pnl']==162623
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Fixed shadow models have the stated training overlap; residual gain tuned on consumed sample.'),indent=2)+'\n')
    print('WINNER VALUE RESIDUAL',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
