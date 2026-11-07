"""Execution spread is independent of fair-value forecast calibration."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/quote_width')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;base=Path('strategies/round1_private_554347.py').read_text();specs={}
    for width in (0.55,0.6,0.7,0.75,1.0,1.5):
        for inside in (False,True):
            name=f'width_{width}_inside_{inside}'
            text=base.replace('fair-0.5',f'fair-{width}').replace('fair+0.5',f'fair+{width}')
            if not inside:
                text=text.replace('prediction-skew > 0.3','prediction-skew > 2.1').replace('prediction-skew < -0.3','prediction-skew < -2.1')
            path=ROOT/'sources'/(name+'.py');path.write_text(text)
            assert not check(path),check(path)
            specs[name]=dict(half_width=width,inside=inside,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:4]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=4)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Execution widths tuned on consumed round1; all hard exposure and latency settings unchanged.'),indent=2)+'\n')
    print('WINNER WIDTH',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
