"""Independent synthetic stress scenarios, not evidence about competition data.

python -m scripts.stress --output logs/stress
No strategy parameters are selected by this script.
"""

import argparse
import csv
import json
import random
from pathlib import Path

from scripts.benchmark import digest, evaluate
from strategies.arena_strategy import ArenaStrategy


def generate(path, mode, seed, seconds=600):
    rng = random.Random(seed)
    mid = 10000
    direction = 1
    with path.open('w',newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Time','Operation','OrderId','Side','Volume','Price','Lifespan'])
        for n in range(seconds * 5):
            if rng.random() < 0.08:
                direction = -direction
            behavior = mode
            if mode == 'regime_switch':
                behavior = 'continuation' if n < seconds*5//2 else 'noise'
            elif mode == 'recovery':
                behavior = 'noise' if seconds*5//3 <= n < seconds*10//3 else 'continuation'
            if behavior == 'noise':
                mid += rng.choice((-1,1))
            elif behavior != 'flat':
                mid += direction
            market_sign = -direction if behavior == 'reversal' else direction
            t = n / 5
            if n:
                writer.writerow([f'{t:.6f}','Cancel',f'b{n-1}','','','',''])
                writer.writerow([f'{t+0.000001:.6f}','Cancel',f'a{n-1}','','','',''])
            writer.writerow([f'{t+0.000002:.6f}','Insert',f'b{n}','B',rng.randint(20,60),mid-1,'G'])
            writer.writerow([f'{t+0.000003:.6f}','Insert',f'a{n}','A',rng.randint(20,60),mid+1,'G'])
            writer.writerow([f'{t+0.000004:.6f}','Insert',f't{n}',
                             'B' if market_sign > 0 else 'A',rng.randint(1,8),
                             mid+1 if market_sign > 0 else mid-1,'F'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('logs/stress'))
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    results = {}
    for mode in ('flat','noise','continuation','reversal','regime_switch'):
        for seed in (11,29,47):
            name = f'{mode}_{seed}'
            tape = args.output/(name+'.csv')
            generate(tape,mode,seed)
            summary = evaluate(ArenaStrategy(),tape,args.output/name,300)
            summary['data_sha256'] = digest(tape)
            results[name] = summary
            if summary['result']['breach_penalty'] or summary['max_potential_inventory_at_submission'] > 80:
                raise AssertionError(f'{name}: exposure/penalty failure')
            print(f'{name}: pnl={summary["result"]["pnl"]:.2f}, '
                  f'max_inventory={summary["max_abs_inventory"]}, '
                  f'drawdown={summary["max_drawdown_1s"]:.2f}')
    (args.output/'stress_results.json').write_text(json.dumps({
        'strategy_sha256':digest('strategies/arena_strategy.py'),
        'generator_sha256':digest(__file__),
        'limitation':'Artificial stress tests only; not unseen real-market validation.',
        'cases':results,
    },indent=2)+'\n')


if __name__ == '__main__':
    main()
