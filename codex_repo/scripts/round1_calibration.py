"""Round-1 sample tuning of model stability, memory and calibration windows."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/calibration')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/round1/target550/sources/execution_13.py').read_text()
    configs=[{'memory':m} for m in (30000000,100000000,1000000000,3000000000)]
    configs += [{'refit':v} for v in (5000000,30000000)]
    configs += [{'memory':1000000000,'refit':5000000}]
    configs += [{'smooth':v} for v in (.1,.3)]
    configs += [{'freeze':v} for v in (300000000,900000000,1800000000)]
    configs += [{'ridge':v} for v in (.001,.05)]
    specs={}
    for index,params in enumerate(configs):
        n=f'calibration_{index:02d}'
        text=base.replace('MODEL_MEMORY_US = 300000000',f'MODEL_MEMORY_US = {params.get("memory",300000000)}')
        text=text.replace('now - self._last_fit_us < 1_000_000',f'now - self._last_fit_us < {params.get("refit",1000000)}')
        text=text.replace('0.01 * self._mass',f'{params.get("ridge",.01)} * self._mass')
        if 'smooth' in params:
            text=text.replace('            self._weights = weights',f'            self._weights = [{1-params["smooth"]}*old + {params["smooth"]}*new for old,new in zip(self._weights,weights)]')
        if 'freeze' in params:
            text=text.replace('        self._orders = {}','        self._orders = {}\n        self._calibration_start = None',1)
            text=text.replace('    def _learn(self, now, mid):',f'''    def _learn(self, now, mid):
        if self._calibration_start is None:
            self._calibration_start = now
        if now-self._calibration_start > {params['freeze']}:
            return''')
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={**params,'sha256':digest(path)}
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screened=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screened,key=lambda n:screened[n]['result']['pnl'],reverse=True)[:3]
    finalists=[n for n in finalists if screened[n]['result']['pnl']>141000]
    full=search_queue.batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
