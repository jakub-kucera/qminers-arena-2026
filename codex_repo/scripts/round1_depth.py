"""Robust order-count and multi-level depth predictors for round-1 quoting."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/depth_model')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT
    base=Path('logs/round1/nonlinear/sources/nonlinear_8_0.001_100000.py').read_text()
    specs={}
    for mode in ('touch','depth','all','replace50','replace100'):
        n='depth_'+mode
        cap=50 if mode=='replace50' else 100
        addition=f'''        bn = an = bd_n = ad_n = 0
        br = ar = bd_r = ad_r = 0
        bd_value = ad_value = 0
        for orders in (snapshot.bids,snapshot.asks):
            for order in orders:
                if order.owner != 'market':
                    continue
                distance = bid-order.price if order.side == Side.BUY else order.price-ask
                if distance > 2:
                    break
                weight = min({cap},order.quantity)
                if order.side == Side.BUY:
                    bd_n += 1
                    bd_r += weight
                    bd_value += weight*order.price
                    if distance == 0:
                        bn += 1
                        br += weight
                else:
                    ad_n += 1
                    ad_r += weight
                    ad_value += weight*order.price
                    if distance == 0:
                        an += 1
                        ar += weight
        count_imbalance = (bn-an)/max(1,bn+an)
        robust_imbalance = (br-ar)/max(1,br+ar)
        depth_count = (bd_n-ad_n)/max(1,bd_n+ad_n)
        depth_imbalance = (bd_r-ad_r)/max(1,bd_r+ad_r)
        depth_mid = (bd_value/max(1,bd_r)+ad_value/max(1,ad_r))*0.5-mid
'''
        text=base.replace('        imbalance = (bq-aq)/(bq+aq)','        imbalance = (bq-aq)/(bq+aq)\n'+addition)
        if mode.startswith('replace'):
            text=text.replace('        skew = 0.05 *','        imbalance = robust_imbalance\n        skew = 0.05 *')
            # Source may still carry the original skew spelling; assert insertion below.
            if 'imbalance = robust_imbalance' not in text:
                text=text.replace('        skew = 0.1 *','        imbalance = robust_imbalance\n        skew = 0.1 *')
            dimensions=8
        else:
            extra={'touch':',count_imbalance,robust_imbalance',
                   'depth':',depth_count,depth_imbalance,depth_mid',
                   'all':',count_imbalance,robust_imbalance,depth_count,depth_imbalance,depth_mid'}[mode]
            dimensions={'touch':10,'depth':11,'all':13}[mode]
            text=text.replace('ofi*abs(ofi))','ofi*abs(ofi)'+extra+')')
        text=text.replace('FEATURE_COUNT = 8',f'FEATURE_COUNT = {dimensions}')
        path=ROOT/'sources'/(n+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[n]={'mode':mode,'order_volume_cap':cap,'dimensions':dimensions,'sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening')
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:2]
    finalists=[n for n in finalists if screen[n]['result']['pnl']>147000]
    full=search_queue.batch(finalists,'data/round1.csv','full') if finalists else {}
    winner=max(full,key=lambda n:full[n]['result']['pnl']) if full else None
    (ROOT/'winner.json').write_text(json.dumps({'name':winner,'parameters':specs.get(winner),
        'result':full.get(winner),'limitation':'Further tuning on already evaluated round-1 data.'},indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'] if winner else 'no prefix improvement',flush=True)


if __name__=='__main__':main()
