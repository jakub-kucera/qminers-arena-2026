"""One-time selection validation, followed by final evaluation of the frozen winner."""
import argparse
import json
import shutil
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from scripts.benchmark import digest,evaluate
from scripts.search_passive import CandidateEngine
from scripts.check_submission import check
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round1')


def final_timestamp_us(path):
    with Path(path).open('rb') as file:
        file.seek(max(0,Path(path).stat().st_size-4096))
        line=file.read().splitlines()[-1]
    return round(float(line.split(b',',1)[0])*1e6)


class BoundaryEngine(CandidateEngine):
    boundaries=()

    def __init__(self,strategy,config):
        super().__init__(strategy,config)
        self.boundary_pnl={str(t):None for t in self.boundaries}

    def _advance_time(self,timestamp_us):
        for boundary in self.boundaries:
            if self.boundary_pnl[str(boundary)] is None and self.current_ts_us < boundary <= timestamp_us:
                super()._advance_time(boundary)
                self.boundary_pnl[str(boundary)]=self._mark_to_market_pnl()
        super()._advance_time(timestamp_us)


def run(source,data,output,boundaries):
    BoundaryEngine.boundaries=tuple(sorted(boundaries))
    r=evaluate(load_strategy_from_file(source),Path(data),Path(output),600,BoundaryEngine)
    r['source_sha256']=digest(source)
    assert r['result']['breach_penalty']==0
    assert r['max_potential_inventory_at_submission']<=100
    assert all(v is not None for v in r['boundary_pnl'].values())
    return r


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--final',action='store_true');a=p.parse_args()
    m=json.loads((ROOT/'manifest.json').read_text())
    cut60=round(m['development_cutoff']*1e6);cut80=round(m['validation_cutoff']*1e6)
    if not a.final:
        if (ROOT/'selection.json').exists():raise SystemExit('Selection already frozen')
        frozen=json.loads((ROOT/'search/shortlist.json').read_text());results={}
        end_us=final_timestamp_us('logs/round1/validation_prefix.csv')
        with ProcessPoolExecutor(max_workers=3) as pool:
            jobs={pool.submit(run,frozen['sources'][n],'logs/round1/validation_prefix.csv',ROOT/'validation'/n,[cut60,end_us]):n for n in frozen['names']}
            for job in as_completed(jobs):
                n=jobs[job];r=job.result()
                assert r['source_sha256']==frozen['hashes'][n]
                r['validation_pnl']=r['boundary_pnl'][str(end_us)]-r['boundary_pnl'][str(cut60)]
                r['validation_end_us']=end_us
                results[n]=r
                print('VALIDATION',n,'increment',r['validation_pnl'],'prefix pnl',r['result']['pnl'],flush=True)
        winner=max(results,key=lambda n:(results[n]['validation_pnl'],-results[n]['max_drawdown_1s']))
        source=Path(frozen['sources'][winner]);target=Path('strategies/round1_best.py')
        if target.exists():raise SystemExit('Refusing to overwrite round1_best.py')
        shutil.copy2(source,target);assert not check(target)
        report={'name':winner,'file':str(target),'source_sha256':digest(target),'results':results,
                'criterion':'Highest PnL increment in the next 20%, lower sampled drawdown as tie-break. Final 20% not inspected.'}
        (ROOT/'selection.json').write_text(json.dumps(report,indent=2)+'\n')
        print('SELECTED',winner,flush=True)
    else:
        if (ROOT/'final_evaluation.json').exists():raise SystemExit('Final evaluation already completed')
        selection=json.loads((ROOT/'selection.json').read_text())
        source=Path(selection['file']);assert digest(source)==selection['source_sha256']
        r=run(source,m['path'],ROOT/'final',[cut60,cut80])
        r['final_segment_pnl']=r['result']['pnl']-r['boundary_pnl'][str(cut80)]
        r['validation_segment_pnl']=r['boundary_pnl'][str(cut80)]-r['boundary_pnl'][str(cut60)]
        r['data_sha256']=m['sha256']
        (ROOT/'final_evaluation.json').write_text(json.dumps(r,indent=2)+'\n')
        print('FINAL',r['result'],'final segment',r['final_segment_pnl'],flush=True)


if __name__=='__main__':main()
