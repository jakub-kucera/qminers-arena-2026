"""FIFO-aware quote retention and private-confirmation replenishment."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/queue_position')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_queue_545k.py').read_text()
    candidates = {}
    for ahead in (50, 200, 500):
        for edge in (0.1, 0.25, 0.4):
            name = f'keep_ahead_{ahead}_edge_{edge}'
            source = base.replace('        self._previous_touch = None\n',
                '        self._previous_touch = None\n        self._fair_reference = 0.0\n        self._market_touch = {}\n', 1)
            source = source.replace('        self._quote(now,1,buy)', '''        self._fair_reference = mid+prediction-skew
        self._market_touch = {1:bid,-1:ask}
        self._quote(now,1,buy)''')
            source = source.replace('''            if price is None or record[1] != price:
                self._cancel(oid)
                changing = True''', f'''            if price is None or record[1] != price:
                keep = (price is not None and record[3] and not record[4]
                        and record[1] == self._market_touch.get(sign)
                        and self.queue_ahead.get(oid,1000000) <= {ahead}
                        and sign*(self._fair_reference-record[1]) >= {edge})
                if not keep:
                    self._cancel(oid)
                    changing = True''')
            candidates[name] = source
    for mode in ('cancel', 'all'):
        for age in (2000, 5000, 20000):
            source = base.replace('        self._orders = {}', '''        self._orders = {}
        self._desired_buy = self._desired_sell = None
        self._desired_time = None''', 1)
            source = source.replace('            self._previous_touch = None\n',
                '            self._previous_touch = None\n            self._desired_time = None\n')
            source = source.replace('        self._quote(now,1,buy)', '''        self._desired_buy,self._desired_sell,self._desired_time = buy,sell,now
        self._quote(now,1,buy)''')
            statuses = '(OrderStatus.CANCELED,)' if mode == 'cancel' else '(OrderStatus.CANCELED,OrderStatus.PARTIALLY_FILLED,OrderStatus.FILLED)'
            source += f'''
        if (self._desired_time is not None and 0 <= event.timestamp_us-self._desired_time <= {age}
                and event.status in {statuses}):
            self._quote(event.timestamp_us,1,self._desired_buy)
            self._quote(event.timestamp_us,-1,self._desired_sell)
'''
            candidates[f'private_{mode}_{age}'] = source
    specs = {}
    for name, source in candidates.items():
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert source != base
        assert not check(path), check(path)
        specs[name] = dict(source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    screened = search_queue.batch(specs, 'logs/round1/screening.csv', 'screening', workers=6)
    finalists = sorted(screened, key=lambda n: screened[n]['result']['pnl'], reverse=True)[:4]
    full = search_queue.batch(finalists, 'data/round1.csv', 'full', workers=4)
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full[winner],
        parameters=specs[winner], limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
