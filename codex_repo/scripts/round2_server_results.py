"""Record operator-reported server PnL against immutable source snapshots.

This does not submit to the website or verify which file the server executed.
Validation feedback and post-deadline private results remain separate records.
"""
import argparse
import json
import math
from datetime import datetime,timezone
from pathlib import Path

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import COMPETITION_PROTOCOL,REPO,write_json

DEFAULT=REPO/'results/round2_server_results.json'


def load(ledger):
    ledger=Path(ledger)
    result=json.loads(ledger.read_text()) if ledger.exists() else {
        'round':2,'protocol':COMPETITION_PROTOCOL,'entries':[]}
    if result['round']!=2:raise ValueError('This ledger is for round 2')
    for entry in result['entries']:
        if entry['dataset'] not in ('validation','private'):raise ValueError('Unknown server dataset')
        snapshot=ledger.parent/entry['source_snapshot']
        if digest(snapshot)!=entry['source_sha256']:raise ValueError('Server-score source snapshot changed')
    return result


def record(ledger,source,pnl,dataset,submission_id=None,notes='',duration_seconds=None):
    ledger=Path(ledger);source=Path(source)
    if dataset not in ('validation','private'):raise ValueError('Use validation or private; local public PnL is not server feedback')
    if not math.isfinite(pnl):raise ValueError('PnL must be finite')
    if duration_seconds is not None and (not math.isfinite(duration_seconds) or duration_seconds<=0):
        raise ValueError('Supply a positive observed duration, not a guessed size multiplier')
    issues=check(source)
    if issues:raise ValueError(f'Invalid submission source: {issues}')
    result=load(ledger)
    sha=digest(source)
    if submission_id and any(e['dataset']==dataset and e['submission_id']==submission_id for e in result['entries']):
        raise ValueError('This dataset/submission ID is already recorded')
    if submission_id and any(e['submission_id']==submission_id and e['source_sha256']!=sha for e in result['entries']):
        raise ValueError('Submission ID is already bound to another source')
    folder=ledger.parent/'round2_server_sources';folder.mkdir(parents=True,exist_ok=True)
    snapshot=folder/(sha+'.py')
    if snapshot.exists():
        if digest(snapshot)!=sha:raise ValueError('Source snapshot collision or corruption')
    else:snapshot.write_bytes(source.read_bytes())
    if digest(snapshot)!=sha:raise ValueError('Source changed while being captured')
    entry={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'dataset':dataset,
        'submission_id':submission_id,'pnl':pnl,'source_sha256':sha,
        'source_snapshot':str(snapshot.relative_to(ledger.parent)),'original_source':str(source.resolve()),
        'provenance':'operator-reported server PnL; operator must match this file to the actual upload',
        'duration_seconds':duration_seconds,'net_pnl_per_minute':pnl*60/duration_seconds if duration_seconds else None,
        'notes':notes}
    result['entries'].append(entry);write_json(ledger,result)
    return entry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('record','show'))
    parser.add_argument('--ledger',type=Path,default=DEFAULT)
    parser.add_argument('--strategy',type=Path)
    parser.add_argument('--dataset',choices=('validation','private'))
    parser.add_argument('--pnl',type=float)
    parser.add_argument('--submission-id')
    parser.add_argument('--duration-seconds',type=float)
    parser.add_argument('--notes',default='')
    args=parser.parse_args()
    if args.command=='record':
        if args.strategy is None or args.dataset is None or args.pnl is None:
            parser.error('record requires --strategy, --dataset and --pnl')
        value=record(args.ledger,args.strategy,args.pnl,args.dataset,args.submission_id,args.notes,args.duration_seconds)
    else:value=load(args.ledger)
    print(json.dumps(value,indent=2))


if __name__=='__main__':main()
