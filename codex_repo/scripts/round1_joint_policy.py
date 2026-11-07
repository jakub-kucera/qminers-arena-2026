"""Joint inventory-skew and signal-band tuning on already evaluated round-1 data."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/joint_policy')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/round1/target550/sources/execution_13.py').read_text()
    specs={}
    for skew in (0,.025,.05,.075):
        for band in (.025,.05,.075,.125):
            n=f'policy_{skew}_{band}'
            text=base.replace('skew = 0.05 *',f'skew = {skew} *')
            text=text.replace('abs(fair-mid) <= 0.1',f'abs(fair-mid) <= {band}')
            path=ROOT/'sources'/(n+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[n]={'skew':skew,'band':band,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>142000]
    full=search_queue.batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
