"""Faster signed flow and count-based OFI alongside robust depth features."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/microflow')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_524k.py').read_text()
    specs = {}
    for mode, period in [('all', 20000), ('all', 100000), ('all', 500000),
                         ('flow', 20000), ('flow', 100000), ('count_ofi', 100000)]:
        name = f'{mode}_{period}'
        source = base.replace('        self._previous_touch = None\n', '''        self._previous_touch = None
        self._previous_count_touch = None
        self._count_ofi = 0.0
        self._fast_net = self._fast_volume = 0.0
        self._taker_net = self._taker_mass = 0.0
''', 1)
        source = source.replace('        decay = exp(-elapsed/500_000)', f'''        fast_decay = exp(-elapsed/{period})
        self._fast_net *= fast_decay
        self._fast_volume *= fast_decay
        self._taker_net *= fast_decay
        self._taker_mass *= fast_decay
        self._count_ofi *= fast_decay
        last_taker = None
        decay = exp(-elapsed/500_000)''')
        source = source.replace('                self._net += ', '''                direction = 1 if trade.book_side == 'ask' else -1
                self._fast_net += direction*trade.quantity
                self._fast_volume += trade.quantity
                if trade.taker_order_id != last_taker:
                    self._taker_net += direction
                    self._taker_mass += 1
                    last_taker = trade.taker_order_id
                self._net += ''')
        source = source.replace('        count_imbalance = ', '''        if self._previous_count_touch is not None:
            pb,pa,pbn,pan = self._previous_count_touch
            count_change = (bn if bid >= pb else 0)-(pbn if bid <= pb else 0)
            count_change -= an if ask <= pa else 0
            count_change += pan if ask >= pa else 0
            self._count_ofi += count_change/max(1,bn+an,pbn+pan)
        self._previous_count_touch = (bid,ask,bn,an)
        count_imbalance = ''')
        extra = {'all': ',self._fast_net/(1+self._fast_volume),self._taker_net/(1+self._taker_mass),max(-3,min(3,self._count_ofi))',
                 'flow': ',self._fast_net/(1+self._fast_volume),self._taker_net/(1+self._taker_mass)',
                 'count_ofi': ',max(-3,min(3,self._count_ofi))'}[mode]
        count = {'all': 16, 'flow': 15, 'count_ofi': 14}[mode]
        source = source.replace('FEATURE_COUNT = 13', f'FEATURE_COUNT = {count}')
        source = source.replace('depth_imbalance,depth_mid)', 'depth_imbalance,depth_mid' + extra + ')')
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert not check(path), check(path)
        specs[name] = dict(mode=mode, period_us=period, source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    screened = search_queue.batch(specs, 'logs/round1/screening.csv', 'screening')
    finalists = sorted(screened, key=lambda n: screened[n]['result']['pnl'], reverse=True)[:2]
    finalists = [n for n in finalists if screened[n]['result']['pnl'] > 152000]
    full = search_queue.batch(finalists, 'data/round1.csv', 'full') if finalists else {}
    winner = max(full, key=lambda n: full[n]['result']['pnl']) if full else None
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full.get(winner),
        parameters=specs.get(winner), limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'] if winner else 'no prefix improvement', flush=True)


if __name__ == '__main__':
    main()
