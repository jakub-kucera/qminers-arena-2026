"""Causal age of visible queues: age starts at first observation, never from IDs."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/age_model')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_524k.py').read_text()
    specs = {}
    for mode, age_us in [('all', 20000), ('all', 100000), ('all', 500000),
                         ('young', 100000), ('young', 500000), ('stable', 100000)]:
        name = f'{mode}_{age_us}'
        source = base.replace('        self._previous_touch = None\n',
                              '        self._previous_touch = None\n        self._seen_at = {}\n', 1)
        source = source.replace('        bn = an = bd_n = ad_n = 0', '''        seen = {}
        young = [0,0,0,0]
        stable = [0,0,0,0]
        young_price = [0.0,0.0]
        young_count = [0,0]
        bn = an = bd_n = ad_n = 0''')
        source = source.replace('                weight = min(100,order.quantity)', f'''                first_seen = self._seen_at.get(order.order_id,now)
                seen[order.order_id] = first_seen
                side_index = 0 if order.side == Side.BUY else 1
                group = young if now-first_seen <= {age_us} else stable
                group[side_index+2] += 1
                if distance == 0:
                    group[side_index] += 1
                if now-first_seen <= {age_us}:
                    young_price[side_index] += order.price
                    young_count[side_index] += 1
                weight = min(100,order.quantity)''')
        source = source.replace('        count_imbalance = ', '''        self._seen_at = seen
        young_touch = (young[0]-young[1])/max(1,young[0]+young[1])
        stable_touch = (stable[0]-stable[1])/max(1,stable[0]+stable[1])
        young_deep = (young[2]-young[3])/max(1,young[2]+young[3])
        stable_deep = (stable[2]-stable[3])/max(1,stable[2]+stable[3])
        young_mid = ((young_price[0]/young_count[0] if young_count[0] else bid)
                     +(young_price[1]/young_count[1] if young_count[1] else ask))*0.5-mid
        count_imbalance = ''')
        extra = {'all': ',young_touch,stable_touch,young_deep,stable_deep,young_mid',
                 'young': ',young_touch,young_deep,young_mid',
                 'stable': ',stable_touch,stable_deep'}[mode]
        source = source.replace('FEATURE_COUNT = 13', f'FEATURE_COUNT = {13+extra.count(",")}')
        source = source.replace('depth_imbalance,depth_mid)', 'depth_imbalance,depth_mid' + extra + ')')
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert not check(path), check(path)
        specs[name] = dict(mode=mode, age_us=age_us, source_sha256=digest(path))
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
