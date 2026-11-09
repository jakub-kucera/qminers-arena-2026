"""Tune passive quote policy for the preserved robust-depth predictor."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/depth_policy')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_524k.py').read_text()
    specs = {}
    for skew in (0, 0.025, 0.075, 0.1):
        for band in (0.075, 0.1, 0.15):
            name = f'skew_{skew}_band_{band}'
            source = base.replace('skew = 0.05 *', f'skew = {skew} *').replace('abs(fair-mid) <= 0.1', f'abs(fair-mid) <= {band}')
            path = ROOT / 'sources' / (name + '.py')
            path.write_text(source)
            assert not check(path), check(path)
            specs[name] = dict(skew=skew, band=band, source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    screened = search_queue.batch(specs, 'logs/round1/screening.csv', 'screening')
    finalists = sorted(screened, key=lambda n: screened[n]['result']['pnl'], reverse=True)[:3]
    full = search_queue.batch(finalists, 'data/round1.csv', 'full')
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        parameters=specs[winner], limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
