"""Reproduce the supplied 595K strategy and test causal feature extensions.

Every replay uses native position fees and latency. This is sample tuning,
not an independent holdout. Sources and incremental results are preserved.
"""
import argparse
import difflib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round1_aggressor_groups import source_for as group_source
from scripts.round1_new_quote_value import source_for as quote_source
from scripts.round1_size_cohorts import bucket_source
from scripts.round1_standing_liquidity import run

ROOT = Path('logs/round1/claude_improvements')
BASE = Path('strategies/round1_claude_595k.py')
OLD = Path('strategies/round1_private_554347.py')


def transfer_features(text, generated):
    """Apply only the old generator's feature edits to the supplied model."""
    old = OLD.read_text().splitlines(keepends=True)
    new = generated.splitlines(keepends=True)
    dimension = int(text.split('FEATURE_COUNT = ')[1].splitlines()[0])
    extra = int(generated.split('FEATURE_COUNT = ')[1].splitlines()[0]) - 15
    for tag, a, b, c, d in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        before, after = ''.join(old[a:b]), ''.join(new[c:d])
        if 'FEATURE_COUNT = ' in before:
            continue
        if not before:
            before = old[a]
            after += before
        assert before and text.count(before) == 1, (before, text.count(before))
        text = text.replace(before, after, 1)
    return text.replace(f'FEATURE_COUNT = {dimension}', f'FEATURE_COUNT = {dimension + extra}', 1)


def batch(names, data, stage, workers=4):
    destination = ROOT / (stage + '.json')
    results = json.loads(destination.read_text()) if destination.exists() else {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(run, ROOT/'sources'/(n+'.py'), data, ROOT/stage/n): n
                   for n in names if n not in results}
        for job in as_completed(pending):
            name = pending[job]
            results[name] = job.result()
            destination.write_text(json.dumps(results, indent=2)+'\n')
            r = results[name]['result']
            print(stage, name, 'NET', r['pnl'], 'penalty', r['breach_penalty'], flush=True)
    return results


def generate():
    original = BASE.read_text()
    candidates = {'baseline': original}
    for h in (200000, 300000, 600000, 800000, 1200000):
        candidates[f'horizon_{h}'] = original.replace('HORIZON_US = 400000', f'HORIZON_US = {h}').replace(
            'deque(maxlen=64)', f'deque(maxlen={max(64, h//20000+32)})')
    for m in (1000000000, 3000000000, 10000000000, 1000000000000):
        candidates[f'memory_{m}'] = original.replace('MODEL_MEMORY_US = 100000000000', f'MODEL_MEMORY_US = {m}')
    variants = {
        'buckets': bucket_source(),
        'groups_fast': group_source(50000, 100000),
        'groups_slow': group_source(500000, 100000),
        'new_quotes': quote_source(500000, 100000),
    }
    for name, source in variants.items():
        augmented = transfer_features(original, source)
        candidates[name] = augmented
        candidates[name+'_h800'] = augmented.replace('HORIZON_US = 400000', 'HORIZON_US = 800000')
    (ROOT/'sources').mkdir(parents=True, exist_ok=True)
    specs = {}
    for name, text in candidates.items():
        path = ROOT/'sources'/(name+'.py')
        if path.exists():
            assert path.read_text() == text
        else:
            path.write_text(text)
        assert not check(path), check(path)
        specs[name] = {'source_sha256': digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs, indent=2)+'\n')
    return list(candidates)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    names = generate()
    screen = batch(names, 'logs/round1/screening.csv', 'screening', args.workers)
    ranked = sorted(screen, key=lambda n: screen[n]['result']['pnl'], reverse=True)
    finalists = list(dict.fromkeys(['baseline'] + ranked[:5]))
    full = batch(finalists, 'data/round1.csv', 'full', args.workers)
    winner = max(full, key=lambda n: full[n]['result']['pnl'])
    record = dict(name=winner, result=full[winner],
                  limitation='Sample tuning on previously evaluated round1.csv; full native fees and latency.')
    (ROOT/'winner.json').write_text(json.dumps(record, indent=2)+'\n')
    print('WINNER', winner, full[winner]['result']['pnl'], flush=True)


if __name__ == '__main__':
    main()
