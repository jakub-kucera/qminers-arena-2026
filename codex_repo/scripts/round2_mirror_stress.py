"""Synthetic directional symmetry probe; never an unseen validation tape."""
import argparse
import csv
import json
from pathlib import Path
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json


def mirror_row(row):
    mirrored=dict(row)
    if row['Side'] in ('B','A'):mirrored['Side']='A' if row['Side']=='B' else 'B'
    if row['Price'] and int(row['Price'])>0:
        price=20000-int(row['Price'])
        if price<=0:raise ValueError('Mirror anchor incompatible with price range')
        mirrored['Price']=str(price)
    return mirrored


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();assert not check(args.source)
    m=load_manifest(Path('logs/round2_local_intake'))
    root=Path('logs/round2_mirror_stress');root.mkdir(exist_ok=True)
    data=root/'mirrored.csv';meta=root/'data.json'
    if meta.exists():
        record=json.loads(meta.read_text());assert record['original_sha256']==m['data_sha256']
        assert digest(data)==record['mirrored_sha256']
    else:
        assert not data.exists(),'Unfinished mirror must be reviewed before reuse'
        with Path(m['data']).open(newline='') as src,data.open('w',newline='') as dst:
            reader=csv.DictReader(src);writer=csv.DictWriter(dst,fieldnames=reader.fieldnames);writer.writeheader()
            count=0
            for row in reader:writer.writerow(mirror_row(row));count+=1
        record=dict(original_sha256=m['data_sha256'],mirrored_sha256=digest(data),rows=count,
            transform='Price=20000-original for positive prices; B/A swapped; other fields unchanged',
            limitation='Synthetic transform of consumed tape, not independent holdout')
        write_json(meta,record)
    candidate=dict(name=args.source.stem,file=str(args.source),source_sha256=digest(args.source),risk='strict100')
    args.output.mkdir(parents=True,exist_ok=True)
    write_json(args.output/'protocol.json',dict(candidate=candidate,data=record,native=m['native']))
    r=run_candidate(candidate,data,args.output/'audit')
    write_json(args.output/'result.json',r)
    print(r['result'],flush=True)


if __name__=='__main__':main()
