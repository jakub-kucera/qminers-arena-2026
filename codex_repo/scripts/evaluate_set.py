"""Parallel audited replay of explicit standalone candidates on an explicit prefix."""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from scripts.search_passive import run
from scripts.benchmark import digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backtest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--strategy',type=Path,action='append',required=True)
    p.add_argument('--workers',type=int,default=3)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    names=[s.stem for s in a.strategy]
    if len(names)!=len(set(names)):p.error('Candidate file stems must be unique')
    results={}
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        jobs={pool.submit(run,s,a.backtest,a.output/s.stem):s.stem for s in a.strategy}
        for job in as_completed(jobs):
            n=jobs[job];r=job.result();results[n]=r
            print(n,'pnl',r['result']['pnl'],'dd',r['max_drawdown_1s'],
                  'inventory',r['max_abs_inventory'],'blocks',[b['pnl_increment'] for b in r['blocks']],flush=True)
    (a.output/'comparison.json').write_text(json.dumps({'data':str(a.backtest),
        'sha256':digest(a.backtest),'results':results},indent=2)+'\n')


if __name__=='__main__':main()
