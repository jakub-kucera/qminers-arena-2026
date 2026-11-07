"""Local PUBLIC-tape checks; these never evaluate the organizer's private dataset.

Commands: prepare --backtest PATH; screen; select; final. All commands accept
--output (default logs/round2). `public-check` evaluates the last public 20%;
`final` remains a compatibility alias. Server validation/private are separate.
Preparing timestamps/hashes does not make an already inspected dataset fresh.
"""
import argparse
import csv
import json
import math
import platform
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from scripts.benchmark import digest, evaluate
from scripts.check_submission import check
from scripts.search_passive import CandidateEngine
from simulator import main as cli

REPO=Path(__file__).resolve().parents[1]
REGISTRY=REPO/'strategies/round2/manifest.json'
COMPETITION_PROTOCOL={
    'source':'Organizer announcement supplied by the user on 2026-11-07',
    'public':{'downloadable':True,'purpose':'training and local diagnostics','relative_size_approx':0.5},
    'server_validation':{'feedback':['pnl'],'full_logs_available':False,'purpose':'submission feedback and selection'},
    'private':{'score_released':'after submission deadline','purpose':'competition scoring'},
    'validation_and_private_same_size':True,
    'size_metric':'Unspecified; half size does not establish half elapsed duration or doubled expected PnL.'}


def write_json(path,value):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n')
    temporary.replace(path)


def native_stamp():
    return {'python':platform.python_version(),'config':{'max_position':cli.MAX_POSITION,
        'max_potential_position':cli.MAX_POTENTIAL_POSITION,
        'position_breach_penalty_per_second':cli.POSITION_BREACH_PENALTY_PER_SECOND,
        'order_accept_delay_ms':cli.ORDER_ACCEPT_DELAY_MS,'public_depth':20},
        'source_hashes':{name:digest(REPO/'simulator'/name) for name in
                        ('simulator.py','main.py','models.py','strategy.py')},
        'evaluation_sources':{name:digest(REPO/'scripts'/name) for name in
                              ('round2_workbench.py','benchmark.py','search_passive.py')}}


def time_us(value):
    number=float(value)
    if not math.isfinite(number) or number<0:
        raise ValueError('Timestamps must be finite and nonnegative')
    return int(round(number*1000000))


def inspect_structure(path):
    """Read schema/timestamps only for splits; do not compute outcome statistics."""
    with path.open(newline='') as stream:
        reader=csv.reader(stream);header=next(reader,None)
        required=('Time','Operation','OrderId','Side','Volume','Price')
        if not header or not set(required).issubset(header) or len(header)!=len(set(header)):
            raise ValueError('Missing or duplicated CSV columns')
        columns={name:header.index(name) for name in required}
        first=last=None;count=0
        for row in reader:
            if len(row)!=len(header):raise ValueError(f'Wrong column count at row {count+2}')
            now=time_us(row[columns['Time']])
            if last is not None and now<last:raise ValueError('Market timestamps are not monotonic')
            operation=row[columns['Operation']]
            if operation not in ('Insert','Cancel'):raise ValueError(f'Unsupported operation: {operation}')
            if operation=='Insert':
                if row[columns['Side']] not in ('B','A') or any(int(row[columns[c]])<=0 for c in ('Volume','Price')):
                    raise ValueError(f'Invalid insertion at row {count+2}')
            first=now if first is None else first;last=now;count+=1
    if count<3 or last<=first:raise ValueError('Need a nonempty tape with positive duration')
    return header,first,last,count


def prepare(data,output,sources=None):
    data=Path(data).resolve();output=Path(output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('Output is not empty; choose a new experiment directory')
    stamp=digest(data);header,first,last,rows=inspect_structure(data)
    cut60=first+round((last-first)*0.6);cut80=first+round((last-first)*0.8)
    if not first<cut60<cut80<last:raise ValueError('Tape is too short for distinct chronological boundaries')
    registry=json.loads(REGISTRY.read_text())['candidates']
    known={str((REPO/c['file']).resolve()):c for c in registry}
    requested=[Path(s).resolve() for s in sources] if sources else [REPO/c['file'] for c in registry]
    if len({p.stem for p in requested})!=len(requested):raise ValueError('Candidate file stems must be unique')
    for source in requested:
        issues=check(source)
        if issues:raise ValueError(f'{source}: {issues}')
        if str(source) in known and digest(source)!=known[str(source)]['source_sha256']:
            raise ValueError('Registered source changed; rebuild/review the registry before preparing')
    output.mkdir(parents=True,exist_ok=True);(output/'sources').mkdir()
    candidates=[]
    for source in requested:
        target=output/'sources'/source.name;shutil.copy2(source,target)
        metadata=known.get(str(source),{})
        candidates.append({'name':source.stem,'file':str(target),'original_file':str(source),
            'source_sha256':digest(target),'risk':metadata.get('risk','native'),
            'intent':metadata.get('intent','Explicit custom candidate')})
    dev=output/'development.csv';validation=output/'validation_prefix.csv';counts=[0,0]
    with data.open(newline='') as src,dev.open('w',newline='') as a,validation.open('w',newline='') as b:
        reader=csv.reader(src);next(reader);wa=csv.writer(a);wb=csv.writer(b)
        wa.writerow(header);wb.writerow(header);index=header.index('Time')
        for row in reader:
            now=time_us(row[index])
            if now<cut60:wa.writerow(row);counts[0]+=1
            if now<cut80:wb.writerow(row);counts[1]+=1
    if not 0<counts[0]<counts[1]<rows:raise ValueError('Chronological segments must each contain rows')
    if digest(data)!=stamp:raise ValueError('Input changed during preparation')
    manifest={'data':str(data),'data_sha256':stamp,'first_us':first,'last_us':last,'rows':rows,
        'dataset_role':'public','competition_protocol':COMPETITION_PROTOCOL,
        'development_cutoff_us':cut60,'validation_cutoff_us':cut80,
        'development':str(dev),'development_sha256':digest(dev),'development_rows':counts[0],
        'validation_prefix':str(validation),'validation_prefix_sha256':digest(validation),
        'validation_prefix_rows':counts[1],'candidates':candidates,'native':native_stamp(),
        'protocol':'Local PUBLIC 60/20/20 diagnostic; organizer server validation and private backtests are distinct datasets.',
        'limitation':'The last public 20% is only a local chronological check, never the organizer private backtest. Freshness requires no earlier inspection.'}
    write_json(output/'manifest.json',manifest)
    return manifest


def load_manifest(output):
    manifest=json.loads((output/'manifest.json').read_text())
    if manifest['native']!=native_stamp():raise ValueError('Native engine/config changed since preparation')
    for key in ('data','development','validation_prefix'):
        if digest(manifest[key])!=manifest[key+'_sha256']:raise ValueError(f'{key} data changed')
    for candidate in manifest['candidates']:
        if digest(candidate['file'])!=candidate['source_sha256']:raise ValueError('Candidate snapshot changed')
    return manifest


class BoundaryMarkEngine(CandidateEngine):
    """Read a boundary mark without advancing or changing the native engine clock."""
    boundaries=()

    def __init__(self,strategy,config):
        super().__init__(strategy,config)
        self.boundary_pnl={str(t):None for t in self.boundaries}

    def _boundary_value(self,boundary):
        value=self._mark_to_market_pnl()
        if self._max_position is not None and abs(self._inventory)>self._max_position:
            value-=(boundary-self.current_ts_us)/1000000*self._penalty_per_second
        return value

    def run(self,path):
        result=super().run(path)
        # Prefixes contain all events strictly before a known split. If their
        # pending queue finishes before that split, carry the final book and
        # inventory to the split virtually, charging any remaining breach time.
        # This does not modify native clocks, samples, results, or callbacks.
        for boundary in self.boundaries:
            if self.boundary_pnl[str(boundary)] is None and boundary>=self.current_ts_us:
                self.boundary_pnl[str(boundary)]=self._boundary_value(boundary)
        return result

    def _advance_time(self,timestamp_us):
        for boundary in self.boundaries:
            key=str(boundary)
            if self.boundary_pnl[key] is None and self.current_ts_us<boundary<=timestamp_us:
                self.boundary_pnl[key]=self._boundary_value(boundary)
        super()._advance_time(timestamp_us)


def run_candidate(candidate,data,output,boundaries=()):
    if digest(candidate['file'])!=candidate['source_sha256']:raise ValueError('Candidate snapshot changed')
    BoundaryMarkEngine.boundaries=tuple(sorted(boundaries))
    strategy=cli.load_strategy_from_file(candidate['file'])
    r=evaluate(strategy,Path(data),Path(output),600,BoundaryMarkEngine)
    if any(v is None for v in r['boundary_pnl'].values()):raise ValueError('A requested boundary was not reached')
    if r['max_potential_inventory_at_submission']>cli.MAX_POTENTIAL_POSITION:
        raise AssertionError('Native potential-position wall exceeded')
    strict={'strict100':100,'strict80':80}.get(candidate['risk'])
    if strict is not None and (r['result']['breach_penalty'] or
        r['max_abs_inventory']>strict or r['max_potential_inventory_at_submission']>strict):
        raise AssertionError('Declared strict exposure contract failed')
    r.update(source=candidate['file'],source_sha256=candidate['source_sha256'],data_sha256=digest(data))
    r['strategy_state']={name:getattr(strategy,name) for name in
        ('_labels','_mass','_fast_mix','_fast_loss','_long_loss','_guard_scale','_guard_score')
        if hasattr(strategy,name)}
    duration=r['blocks'][-1]['end_s'] if r['blocks'] else 0
    r['rates']={'observed_duration_seconds':duration,
        'net_pnl_per_minute':r['result']['pnl']*60/duration if duration>0 else None,
        'volume_per_minute':r['result']['traded_volume']*60/duration if duration>0 else None,
        'limitation':'Observed-tape diagnostics, not a projection for a larger or different dataset.'}
    return r


def batch(manifest,output,stage,workers):
    report_path=output/(stage+'.json')
    results=json.loads(report_path.read_text())['results'] if report_path.exists() else {}
    if not set(results).issubset({c['name'] for c in manifest['candidates']}):
        raise ValueError('Cached results contain unknown candidates')
    data=manifest['development'] if stage=='development' else manifest['validation_prefix']
    boundaries=(manifest['development_cutoff_us'],) if stage=='development' else \
        (manifest['development_cutoff_us'],manifest['validation_cutoff_us'])
    for candidate in manifest['candidates']:
        if candidate['name'] in results:
            r=results[candidate['name']]
            if r['source_sha256']!=candidate['source_sha256'] or r['data_sha256']!=digest(data):
                raise ValueError('Cached result provenance mismatch')
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs={pool.submit(run_candidate,c,data,output/stage/c['name'],boundaries):c['name']
              for c in manifest['candidates'] if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result()
            r['development_window_pnl']=r['boundary_pnl'][str(manifest['development_cutoff_us'])]
            if stage=='validation':
                r['validation_pnl_increment']=r['boundary_pnl'][str(manifest['validation_cutoff_us'])]-r['development_window_pnl']
            results[name]=r
            write_json(report_path,{'data_sha256':digest(data),'results':results})
            print(stage,name,'net',r['result']['pnl'],'validation',r.get('validation_pnl_increment'),flush=True)
    return results


def validate_selection(manifest,selected):
    original=next((c for c in manifest['candidates'] if c['name']==selected['name']),None)
    if original is None or selected['source_sha256']!=original['source_sha256'] or \
        selected['risk']!=original['risk'] or selected['data_sha256']!=manifest['data_sha256']:
        raise ValueError('Frozen selection provenance mismatch')
    if digest(selected['frozen_file'])!=selected['source_sha256']:
        raise ValueError('Frozen winner changed')


def select(manifest,output,workers):
    path=output/'selection.json'
    if path.exists():
        report=json.loads(path.read_text())
        validate_selection(manifest,report)
        return report
    screen=output/'development.json'
    if not screen.exists() or len(json.loads(screen.read_text())['results'])!=len(manifest['candidates']):
        raise ValueError('Finish screen before selecting')
    results=batch(manifest,output,'validation',workers)
    winner=max(results,key=lambda n:(results[n]['validation_pnl_increment'],-results[n]['max_drawdown_1s']))
    candidate=next(c for c in manifest['candidates'] if c['name']==winner)
    frozen=output/'frozen_submission.py';shutil.copy2(candidate['file'],frozen)
    assert digest(frozen)==candidate['source_sha256']
    report={'name':winner,'frozen_file':str(frozen),'source_sha256':candidate['source_sha256'],
        'evaluation_scope':'local_public_only','organizer_private_evaluated':False,
        'risk':candidate['risk'],'criterion':'Highest next-20% net PnL increment; lower sampled drawdown breaks ties.',
        'data_sha256':manifest['data_sha256'],'final_segment_inspected':False}
    write_json(path,report)
    return report


def final(manifest,output):
    selected=json.loads((output/'selection.json').read_text())
    validate_selection(manifest,selected)
    source=Path(selected['frozen_file'])
    if digest(source)!=selected['source_sha256']:raise ValueError('Frozen source changed; final evaluation refused')
    report_path=output/'final_report.json'
    if report_path.exists():
        report=json.loads(report_path.read_text())
        if report['source_sha256']!=selected['source_sha256'] or report['data_sha256']!=manifest['data_sha256']:
            raise ValueError('Final report provenance mismatch')
        return report
    candidate=dict(name=selected['name'],file=str(source),source_sha256=selected['source_sha256'],risk=selected['risk'])
    audit_path=output/'final_audit.json'
    if audit_path.exists():
        audit=json.loads(audit_path.read_text())
        if audit['source_sha256']!=selected['source_sha256'] or audit['data_sha256']!=manifest['data_sha256']:
            raise ValueError('Final audit provenance mismatch')
    else:
        audit=run_candidate(candidate,manifest['data'],output/'final_audit',
                            (manifest['development_cutoff_us'],manifest['validation_cutoff_us']))
        write_json(audit_path,audit)
    official=output/'official_final'
    subprocess.run([sys.executable,'-m','simulator.main','--backtest',manifest['data'],
        '--strategy',str(source),'--log-dir',str(official),'--no-logs'],cwd=REPO,check=True)
    actual=json.loads((official/'result.json').read_text())
    if actual!=audit['result']:raise AssertionError('Unmodified CLI disagrees with audited result')
    report={'selection':selected,'result':audit,'official_cli_match':True,
        'evaluation_scope':'local_public_only','organizer_private_evaluated':False,
        'final_segment_evaluated':True,
        'source_sha256':digest(source),'data_sha256':manifest['data_sha256'],
        'final_segment_pnl_increment':actual['pnl']-audit['boundary_pnl'][str(manifest['validation_cutoff_us'])],
        'limitation':'This is only the PUBLIC tape. Its last 20% is an internal chronological check if not previously inspected. It is not the organizer private backtest; server validation feedback and post-deadline private scoring are separate.'}
    write_json(report_path,report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','screen','select','public-check','final'))
    parser.add_argument('--backtest',type=Path)
    parser.add_argument('--strategy',type=Path,action='append')
    parser.add_argument('--output',type=Path,default=REPO/'logs/round2')
    parser.add_argument('--workers',type=int,default=3)
    args=parser.parse_args();output=args.output.resolve()
    if args.workers<1:parser.error('--workers must be positive')
    if args.command=='prepare':
        if args.backtest is None:parser.error('prepare requires --backtest')
        report=prepare(args.backtest,output,args.strategy)
        print('Prepared',report['rows'],'rows and',len(report['candidates']),'snapshots; no final-period replay.')
        return
    if args.backtest is not None or args.strategy is not None:parser.error('Data and candidates are fixed during prepare')
    manifest=load_manifest(output)
    if args.command=='screen':batch(manifest,output,'development',args.workers)
    elif args.command=='select':print(json.dumps(select(manifest,output,args.workers),indent=2))
    else:print(json.dumps(final(manifest,output),indent=2))


if __name__=='__main__':main()
