"""Full round-1 replay of combinations; no new holdout claim."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/combine_depth')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'full.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_nonlinear_534k.py').read_text()
    configurations = [(skew, distance, cap) for skew in (0.025, 0.05)
                      for distance in (2, 9) for cap in (20, 100)
                      if (skew, distance, cap) != (0.05, 2, 100)]
    configurations += [(0.015, 2, 100), (0.035, 2, 100)]
    specs = {}
    for skew, distance, cap in configurations:
        name = f'skew_{skew}_distance_{distance}_cap_{cap}'
        source = base.replace('skew = 0.05 *', f'skew = {skew} *').replace(
            'distance > 2:', f'distance > {distance}:').replace(
            'weight = min(100,order.quantity)', f'weight = min({cap},order.quantity)')
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert not check(path), check(path)
        specs[name] = dict(skew=skew, distance=distance, cap=cap, source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    full = search_queue.batch(specs, 'data/round1.csv', 'full')
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        parameters=specs[winner], limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
