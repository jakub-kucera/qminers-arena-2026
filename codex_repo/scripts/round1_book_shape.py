"""Queue density, multiscale book shape, and nonlinear count responses."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT = Path('logs/round1/book_shape')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / 'sources').mkdir(exist_ok=True)
    if (ROOT / 'screening.json').exists():
        raise SystemExit('Results already exist')
    search_queue.ROOT = ROOT
    base = Path('strategies/round1_depth_nonlinear_534k.py').read_text().replace(
        'skew = 0.05 *', 'skew = 0.025 *').replace(
        'weight = min(100,order.quantity)', 'weight = min(20,order.quantity)')
    features = {
        'density': ',count_imbalance*20/max(5,bn+an),(bn-an)/20,depth_count*40/max(10,bd_n+ad_n)',
        'log_counts': ',log((bn+1)/(an+1)),log((bd_n+1)/(ad_n+1)),log((bq+1)/(aq+1))',
        'cubic_counts': ',count_imbalance**3,robust_imbalance**3,depth_count**3',
        'count_interaction': ',count_imbalance*abs(depth_count),depth_count*abs(count_imbalance)',
        'density_cubic': ',count_imbalance*20/max(5,bn+an),(bn-an)/20,count_imbalance**3,robust_imbalance**3',
    }
    candidates = {}
    for name, extra in features.items():
        source = base.replace('isfinite\n', 'isfinite, log\n')
        count = {'density': 3, 'log_counts': 3, 'cubic_counts': 3, 'count_interaction': 2, 'density_cubic': 4}[name]
        source = source.replace('FEATURE_COUNT = 15', f'FEATURE_COUNT = {15+count}')
        source = source.replace('robust_imbalance*abs(robust_imbalance))', 'robust_imbalance*abs(robust_imbalance)' + extra + ')')
        candidates[name] = source
    addition = '''        scale_b = [0,0,0]
        scale_a = [0,0,0]
        bprice = aprice = 0.0
        for orders in (snapshot.bids,snapshot.asks):
            for order in orders:
                if order.owner != 'market':
                    continue
                d = bid-order.price if order.side == Side.BUY else order.price-ask
                if d > 9:
                    break
                counts = scale_b if order.side == Side.BUY else scale_a
                if d <= 1:
                    counts[0] += 1
                if d <= 4:
                    counts[1] += 1
                counts[2] += 1
                if order.side == Side.BUY:
                    bprice += order.price
                else:
                    aprice += order.price
        shape_1 = (scale_b[0]-scale_a[0])/max(1,scale_b[0]+scale_a[0])
        shape_4 = (scale_b[1]-scale_a[1])/max(1,scale_b[1]+scale_a[1])
        shape_9 = (scale_b[2]-scale_a[2])/max(1,scale_b[2]+scale_a[2])
        center_9 = ((bprice/scale_b[2] if scale_b[2] else bid)
                    +(aprice/scale_a[2] if scale_a[2] else ask))*0.5-mid
'''
    candidates['multiscale'] = base.replace('FEATURE_COUNT = 15', 'FEATURE_COUNT = 19').replace(
        '        skew = 0.025 *', addition+'        skew = 0.025 *').replace(
        'robust_imbalance*abs(robust_imbalance))',
        'robust_imbalance*abs(robust_imbalance),shape_1,shape_4,shape_9,center_9)')
    specs = {}
    for name, source in candidates.items():
        path = ROOT / 'sources' / (name + '.py')
        path.write_text(source)
        assert source != base
        assert not check(path), check(path)
        specs[name] = dict(source_sha256=digest(path))
    (ROOT / 'specs.json').write_text(json.dumps(specs, indent=2) + '\n')
    screened = search_queue.batch(specs, 'logs/round1/screening.csv', 'screening')
    finalists = sorted(screened, key=lambda n: screened[n]['result']['pnl'], reverse=True)[:3]
    finalists = [n for n in finalists if screened[n]['result']['pnl'] > 157000]
    full = search_queue.batch(finalists, 'data/round1.csv', 'full') if finalists else {}
    winner = max(full, key=lambda n: full[n]['result']['pnl']) if full else None
    (ROOT / 'winner.json').write_text(json.dumps(dict(name=winner, result=full.get(winner),
        parameters=specs.get(winner), limitation='Tuned on already evaluated round-1 data.'), indent=2) + '\n')
    print('WINNER', winner, full[winner]['result']['pnl'] if winner else 'no prefix improvement', flush=True)


if __name__ == '__main__':
    main()
