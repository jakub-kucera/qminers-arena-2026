"""Separate liquidity by observed order size instead of treating every order alike."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/size_cohorts')


def source_for(cutoff, filter_volume=True, minimum=False):
    text=Path('strategies/round1_private_554347.py').read_text()
    text=text.replace('        bn = an = bd_n = ad_n = 0','        bf = af = 0\n        bn = an = bd_n = ad_n = 0')
    operator='<' if minimum else '>'
    text=text.replace('                weight = min(20,order.quantity)',f'''                if order.quantity {operator} {cutoff}:
                    continue
                weight = min(20,order.quantity)''')
    text=text.replace('                        br += weight','                        br += weight\n                        bf += order.quantity')
    text=text.replace('                        ar += weight','                        ar += weight\n                        af += order.quantity')
    if filter_volume:
        text=text.replace('        count_imbalance = ','''        bq,aq = max(1,bf),max(1,af)
        imbalance = (bq-aq)/(bq+aq)
        count_imbalance = ''')
    text=text.replace('bd_value/max(1,bd_r)','(bd_value/bd_r if bd_r else bid)').replace(
        'ad_value/max(1,ad_r)','(ad_value/ad_r if ad_r else ask)')
    return text


def bucket_source():
    text=Path('strategies/round1_private_554347.py').read_text().replace('FEATURE_COUNT = 15','FEATURE_COUNT = 23')
    text=text.replace('        bn = an = bd_n = ad_n = 0', '''        bucket_b = [0,0,0,0]
        bucket_a = [0,0,0,0]
        bucket_db = [0,0,0,0]
        bucket_da = [0,0,0,0]
        bn = an = bd_n = ad_n = 0''')
    text=text.replace('                weight = min(20,order.quantity)', '''                bucket = 0 if order.quantity <= 5 else 1 if order.quantity <= 20 else 2 if order.quantity <= 100 else 3
                if order.side == Side.BUY:
                    bucket_db[bucket] += 1
                    if distance == 0:
                        bucket_b[bucket] += 1
                else:
                    bucket_da[bucket] += 1
                    if distance == 0:
                        bucket_a[bucket] += 1
                weight = min(20,order.quantity)''')
    text=text.replace('robust_imbalance*abs(robust_imbalance))', '''robust_imbalance*abs(robust_imbalance))+tuple(
                  (b-a)/max(1,b+a) for b,a in zip(bucket_b,bucket_a))+tuple(
                  (b-a)/max(1,b+a) for b,a in zip(bucket_db,bucket_da))''')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;candidates={}
    for cutoff in (5,20,50,100,200):
        candidates[f'maximum_{cutoff}']=source_for(cutoff)
    for cutoff in (20,50,100):
        candidates[f'counts_maximum_{cutoff}']=source_for(cutoff,False)
    for cutoff in (5,20,50):
        candidates[f'minimum_{cutoff}']=source_for(cutoff,True,True)
    candidates['size_buckets']=bucket_source()
    specs={}
    for name,text in candidates.items():
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]=dict(source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Further tuning on previously evaluated round-1 data; every feature uses only public past/current observations.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
