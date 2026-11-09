"""Cold-start diagnostic on the already-consumed later40% of public data.

This is not a new holdout. Native book starts empty; unobserved orders born
before the cut are not reconstructed. Time is rebased exactly in microseconds.
It tests dependence on first-hour online state, not hidden-data performance.
"""
import argparse
import csv
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path

from scripts.benchmark import digest
from scripts.round2_workbench import load_manifest,run_candidate,native_stamp,write_json

ROOT=Path('logs/round2/distribution_research/restarted')


def prepare():
    m=load_manifest(Path('logs/round2'));cut=m['development_cutoff_us'];ROOT.mkdir(exist_ok=True)
    target=ROOT/'later40_rebased.csv';meta=ROOT/'data.json'
    if not target.exists():
        count=0
        with Path(m['data']).open(newline='') as src,target.open('w',newline='') as dst:
            reader=csv.reader(src);writer=csv.writer(dst,lineterminator='\n');writer.writerow(next(reader))
            for row in reader:
                t=int(round(float(row[0])*1000000))
                if t>=cut:
                    rebased=t-cut;row[0]=f'{rebased//1000000}.{rebased%1000000:06d}'
                    writer.writerow(row);count+=1
        write_json(meta,dict(original_data_sha256=m['data_sha256'],cutoff_us=cut,
            data_sha256=digest(target),rows=count))
    saved=json.loads(meta.read_text())
    assert saved['original_data_sha256']==m['data_sha256'] and saved['cutoff_us']==cut
    assert saved['data_sha256']==digest(target)
    return target


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);a=p.parse_args()
    target=prepare();candidates=[]
    for name,source in [('baseline162253',Path('strategies/round2_fill_value_162253.py')),('candidate',a.candidate)]:
        candidates.append(dict(name=name,file=str(source),source_sha256=digest(source),risk='native'))
    tag=digest(a.candidate)[:12];out=ROOT/tag;out.mkdir(exist_ok=True)
    report=dict(scope=__doc__,native=native_stamp(),data_sha256=digest(target),results={})
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(run_candidate,c,target,out/c['name']):c['name'] for c in candidates}
        for job in as_completed(futures):
            name=futures[job];result=job.result();report['results'][name]=result
            write_json(out/'results.json',report)
            print('RESTARTED LATER40',name,result['result']['pnl'],flush=True)


if __name__=='__main__':main()
