"""Selective inside quotes plus bounded-age private confirmation replenishment."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/private_inside')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'full.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_inside_551k.py').read_text()
    specs = {}
    configurations = [('cancel',2000,0.25),('cancel',5000,0.25),('cancel',20000,0.25),
                      ('all',5000,0.25),('cancel',5000,0.3),('cancel',5000,0.35)]
    for mode, age, threshold in configurations:
        name = f'{mode}_{age}_inside_{threshold}'
        source = base.replace('        self._orders = {}', '''        self._orders = {}
        self._desired_buy = self._desired_sell = None
        self._desired_time = None''', 1)
        source = source.replace('            self._previous_touch = None\n',
            '            self._previous_touch = None\n            self._desired_time = None\n')
        source = source.replace('        self._quote(now,1,buy)', '''        self._desired_buy,self._desired_sell,self._desired_time = buy,sell,now
        self._quote(now,1,buy)''')
        source = source.replace('prediction-skew > 0.25:', f'prediction-skew > {threshold}:').replace(
            'prediction-skew < -0.25:', f'prediction-skew < -{threshold}:')
        statuses = '(OrderStatus.CANCELED,)' if mode == 'cancel' else '(OrderStatus.CANCELED,OrderStatus.PARTIALLY_FILLED,OrderStatus.FILLED)'
        source += f'''
        if (self._desired_time is not None and 0 <= event.timestamp_us-self._desired_time <= {age}
                and event.status in {statuses}):
            self._quote(event.timestamp_us,1,self._desired_buy)
            self._quote(event.timestamp_us,-1,self._desired_sell)
'''
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert not check(path), check(path)
        specs[name] = dict(mode=mode, age_us=age, inside_threshold=threshold, source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    full = search_queue.batch(specs, 'data/round1.csv', 'full', workers=4)
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        parameters=specs[winner], limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
