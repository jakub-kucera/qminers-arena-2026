"""Bounded search on development data; freezes a shortlist before tail evaluation."""
import csv
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from scripts.benchmark import AuditedSimulator, digest, evaluate
from scripts.check_submission import check
from simulator.main import load_strategy_from_file

ROOT=Path('logs/sample_v2/search')


class CandidateEngine(AuditedSimulator):
    def _private_notify(self,event):
        super()._private_notify(event)
        s=self.strategy
        if s.inventory!=self._inventory or s.cash!=self._cash:
            raise AssertionError('candidate ledger mismatch')
        if abs(self._inventory)>s.POSITION_LIMIT:
            raise AssertionError('candidate position bound violated')


def run(source,data,out):
    source,data,out=Path(source),Path(data),Path(out)
    result=evaluate(load_strategy_from_file(source),data,out,600,CandidateEngine)
    result['source']=str(source)
    result['source_sha256']=digest(source)
    if result['result']['breach_penalty'] or result['max_potential_inventory_at_submission']>100:
        raise AssertionError('candidate risk failure')
    return result


def batch(specs,data,stage):
    results={}
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(run,ROOT/'sources'/(name+'.py'),data,ROOT/stage/name):name for name in specs}
        for future in as_completed(futures):
            name=futures[future]
            results[name]=future.result()
            r=results[name]
            print(stage,name,'pnl',r['result']['pnl'],'dd',r['max_drawdown_1s'],flush=True)
    (ROOT/(stage+'.json')).write_text(json.dumps(results,indent=2)+'\n')
    return results


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    if (ROOT/'shortlist.json').exists():
        raise SystemExit('Shortlist already frozen; use its saved sources/results rather than repeat selection.')
    (ROOT/'sources').mkdir(exist_ok=True)
    manifest=json.loads(Path('logs/sample_v2/manifest.json').read_text())
    cutoff=manifest['first_time_s']+0.3*manifest['duration_s']
    screening=ROOT/'screening.csv'
    with Path(manifest['development_file']).open() as file,screening.open('w',newline='') as target:
        reader=csv.reader(file); writer=csv.writer(target); writer.writerow(next(reader))
        for row in reader:
            if float(row[0])>=cutoff: break
            writer.writerow(row)
    specs={'original':dict(size=5,cap=60,skew=1.0,alpha=.25,veto=.6,improve=None)}
    for size in (10,30,60):
        for skew in (.25,1.0):
            for veto in (.6,1.1):
                name=f'join_q{size}_s{skew}_f{veto}'
                specs[name]=dict(size=size,cap=90,skew=skew,alpha=.25,veto=veto,improve=None)
    for alpha in (.5,1.0):
        for threshold in (.15,.4):
            name=f'improve_a{alpha}_t{threshold}'
            specs[name]=dict(size=30,cap=90,skew=1.0,alpha=alpha,veto=1.1,improve=threshold)
    specs['conservative']=dict(size=20,cap=60,skew=1.0,alpha=.5,veto=1.1,improve=None)
    specs['large']=dict(size=90,cap=90,skew=1.0,alpha=.25,veto=1.1,improve=None)
    template=Path('strategies/passive_strategy.py').read_text()
    for name,params in specs.items():
        text=template.replace('POSITION_LIMIT = 60',f'POSITION_LIMIT = {params["cap"]}')
        text=text.replace('QUOTE_SIZE = 5',f'QUOTE_SIZE = {params["size"]}')
        text=text.replace('skew = self.inventory/self.POSITION_LIMIT',f'skew = {params["skew"]} * self.inventory/self.POSITION_LIMIT')
        text=text.replace('fair = mid + 0.25*spread*imbalance',f'fair = mid + {params["alpha"]}*spread*imbalance')
        text=text.replace('flow < -0.6',f'flow < -{params["veto"]}').replace('flow > 0.6',f'flow > {params["veto"]}')
        if params['improve'] is not None:
            text=text.replace('        # Withdraw the side',f'''        if spread >= 2:
            if imbalance > {params['improve']}:
                buy = min(ask-1, bid+1)
            elif imbalance < -{params['improve']}:
                sell = max(bid+1, ask-1)
        # Withdraw the side''')
        path=ROOT/'sources'/(name+'.py'); path.write_text(text)
        if check(path): raise AssertionError(check(path))
    (ROOT/'specifications.json').write_text(json.dumps(specs,indent=2)+'\n')
    screened=batch(specs,screening,'screening')
    ranked=sorted(screened,key=lambda name:screened[name]['result']['pnl'],reverse=True)
    # Carry the four strongest short-prefix candidates plus a lower-size reference.
    promoted=list(dict.fromkeys(ranked[:4]+['conservative','original']))
    developed=batch(promoted,manifest['development_file'],'development')
    ranked=sorted((n for n in developed if n!='original'),key=lambda n:developed[n]['result']['pnl'],reverse=True)
    finalists=list(dict.fromkeys(ranked[:2]+['conservative']))
    frozen={'names':finalists,'reference':'original','specs':{n:specs[n] for n in finalists},
            'source_hashes':{n:digest(ROOT/'sources'/(n+'.py')) for n in finalists},
            'selection':'Ranked by development PnL, with a lower-size reference; no tail results observed before freezing.'}
    (ROOT/'shortlist.json').write_text(json.dumps(frozen,indent=2)+'\n')
    print('FROZEN SHORTLIST',finalists,flush=True)
    # Full replay preserves queue, positions and model history at the split.
    for name in finalists+['original']:
        result=run(ROOT/'sources'/(name+'.py'),manifest['path'],ROOT/'validation'/name)
        pnl_path=ROOT/'validation'/name/'pnl.csv'
        boundary=manifest['development_cutoff_s']-manifest['first_time_s']
        baseline=None
        with pnl_path.open() as file:
            for row in csv.DictReader(file):
                if float(row['elapsed_s'])>boundary: break
                baseline=float(row['pnl'])
        # One-second sampling can precede the split by <1 second; state is continuous.
        result['tail_pnl_increment']=result['result']['pnl']-baseline
        result['tail_boundary_sample_pnl']=baseline
        result['split_elapsed_s']=boundary
        (ROOT/'validation'/name/'selection_result.json').write_text(json.dumps(result,indent=2)+'\n')
        print('VALIDATION',name,'full',result['result']['pnl'],'tail',result['tail_pnl_increment'],flush=True)


if __name__=='__main__':
    main()
