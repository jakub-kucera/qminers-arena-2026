"""Online binned response surfaces with a regularized linear-model fallback."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/histogram')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_524k.py').read_text()
    specs = {}
    for bins in (5, 9):
        for prior in (5, 20):
            for blend in (0.5, 1.0):
                name = f'bins_{bins}_prior_{prior}_blend_{blend}'
                source = base.replace('        self._previous_touch = None\n',
                    '        self._previous_touch = None\n        self._histogram = {}\n', 1)
                source = source.replace('            self._mass = self._mass * decay + 1.0', '''            self._mass = self._mass * decay + 1.0
            for pair, (i,j) in enumerate(((0,8),(0,9),(8,10),(3,9))):
                x = features[i]/3 if i == 3 else features[i]
                y = features[j]
                key = (pair, self._bin(x), self._bin(y))
                count,total,stamp = self._histogram.get(key,(0.0,0.0,now))
                retention = exp(-max(0,now-stamp)/self.MODEL_MEMORY_US)
                self._histogram[key] = (count*retention+1,total*retention+response,now)''')
                methods = f'''    def _bin(self, value):
        return max(0,min({bins-1},floor((value+1)*{bins}*0.5)))

    def _surface(self, now, features, linear):
        estimates = []
        for pair, (i,j) in enumerate(((0,8),(0,9),(8,10),(3,9))):
            x = features[i]/3 if i == 3 else features[i]
            y = features[j]
            key = (pair,self._bin(x),self._bin(y))
            count,total,stamp = self._histogram.get(key,(0.0,0.0,now))
            retention = exp(-max(0,now-stamp)/self.MODEL_MEMORY_US)
            count *= retention
            total *= retention
            estimates.append((total+{prior}*linear)/(count+{prior}))
        return {1-blend}*linear+{blend}*sum(estimates)/len(estimates)

'''
                source = source.replace('    def _cancel(self, order_id):', methods + '    def _cancel(self, order_id):')
                source = source.replace('        fair = mid + ', '''        if self._labels >= self.MIN_LABELS:
            prediction = max(-2.0,min(2.0,self._surface(now,features,prediction)))
        fair = mid + ''')
                path = ROOT / 'sources' / (name + '.py')
                path.write_text(source)
                assert not check(path), check(path)
                specs[name] = dict(bins=bins, prior=prior, blend=blend, source_sha256=digest(path))
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
