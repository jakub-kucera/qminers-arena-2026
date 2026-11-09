"""Frozen development-only probes; no later-period evaluation or selection."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest, run_candidate, write_json

ROOT = Path('logs/round2_structural_batch')


def build():
    base = Path('strategies/round2/round2_strict100.py').read_text()
    cases = {}
    for clip in (1, 3):
        cases[f'robust_labels_{clip}'] = base.replace(
            'response = max(-20.0, min(20.0, mid - old_mid))',
            f'response = max(-{clip}.0, min({clip}.0, mid - old_mid))')
    for size in (10, 25):
        cases[f'replenish_{size}'] = base.replace('QUOTE_SIZE = 200', f'QUOTE_SIZE = {size}')
    for horizon in (2_000_000, 5_000_000):
        text = base.replace('HORIZON_US = 400000', f'HORIZON_US = {horizon}')
        text = text.replace('deque(maxlen=64)', 'deque(maxlen=512)')
        text = text.replace('MODEL_MEMORY_US = 100000000000', 'MODEL_MEMORY_US = 300000000')
        text = text.replace('REQUOTE_US = 0', 'REQUOTE_US = 20000')
        text = text.replace('self.inventory = 0', 'self.inventory = 0\n        self._target_position = 0', 1)
        text = text.replace('max(-2.0,min(2.0,sum(w*x', 'max(-10.0,min(10.0,sum(w*x')
        text = text.replace('100-sign*self.inventory-effective',
                            'max(0,sign*(self._target_position-self.inventory))-effective')
        text = text.replace('quantity=quantity, order_type=OrderType.LIMIT',
                            'quantity=quantity, order_type=OrderType.IOC')
        begin = text.index('        fair = mid +')
        end = text.index('        self._cached_bid,self._cached_ask', begin)
        text = text[:begin] + '''        # Entry pays for both crossings; weak favorable alpha retains inventory.
        if abs(prediction) > spread + 0.5:
            self._target_position = 100 if prediction > 0 else -100
        elif self.inventory*prediction > 0 and abs(prediction) > 0.25:
            self._target_position = self.inventory
        else:
            self._target_position = 0
        buy = ask if self._target_position > self.inventory else None
        sell = bid if self._target_position < self.inventory else None
''' + text[end:]
        cases[f'selective_ioc_{horizon//1000000}s'] = text
    return cases


def run(root, cases, hypotheses):
    ROOT = root
    intake = load_manifest(Path('logs/round2_local_intake'))
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT/'sources').mkdir(exist_ok=True)
    candidates = []
    for name, text in cases.items():
        path = ROOT/'sources'/(name+'.py')
        if path.exists():
            assert path.read_text() == text, 'Frozen source changed'
        else:
            path.write_text(text)
        assert not check(path), check(path)
        candidates.append(dict(name=name, file=str(path), source_sha256=digest(path), risk='strict100'))
    protocol = dict(scope='Development first 60% only; no final selection.',
                    hypotheses=hypotheses,
                    candidates=candidates, data_sha256=intake['development_sha256'],
                    native=intake['native'], target_full_public_net=100000)
    frozen = ROOT/'protocol.json'
    if frozen.exists():
        assert json.loads(frozen.read_text()) == protocol
    else:
        write_json(frozen, protocol)
    destination = ROOT/'results.json'
    results = json.loads(destination.read_text()) if destination.exists() else {}
    for candidate in candidates:
        if candidate['name'] in results:
            cached = results[candidate['name']]
            assert cached['source_sha256'] == candidate['source_sha256']
            assert cached['data_sha256'] == intake['development_sha256']
    with ProcessPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(run_candidate, c, intake['development'], ROOT/c['name'],
                            (intake['development_cutoff_us'],)):c['name']
                for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name = jobs[job]
            results[name] = job.result()
            write_json(destination, results)
            print(name, 'net', results[name]['result']['pnl'], flush=True)


if __name__ == '__main__':
    run(ROOT, build(), ['Clipped response limits jump influence',
                       'Smaller child orders replenish without canceling equal-price orders',
                       'Rich-feature longer-horizon IOC entry with explicit spread hurdle'])
