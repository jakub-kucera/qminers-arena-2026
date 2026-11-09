"""Test quoting nearer estimated fair value during transient wider spreads."""
from pathlib import Path
from scripts.round2_structural_batch import run


def build():
    base=Path('logs/round2_structural_batch/sources/robust_labels_3.py').read_text()
    cases={}
    for width in (.5,1.5):
        code=f'''        if spread >= 3:
            buy=max(bid+1,min(ask-1,floor(fair-{width})))
            sell=min(ask-1,max(bid+1,ceil(fair+{width})))
            if buy>=sell:
                buy=sell=None
'''
        cases[f'gap_center_{str(width).replace(".","p")}']=base.replace(
            '        # Withdraw the side vulnerable',code+'        # Withdraw the side vulnerable',1)
    code='''        if spread >= 3:
            market_b=[o.price for o in snapshot.bids if o.owner=='market']
            market_a=[o.price for o in snapshot.asks if o.owner=='market']
            center=(market_b[len(market_b)//2]+market_a[len(market_a)//2])*.5
            center=max(bid+1,min(ask-1,center+prediction-skew))
            buy=max(bid+1,min(ask-1,floor(center-1)))
            sell=min(ask-1,max(bid+1,ceil(center+1)))
            if buy>=sell:
                buy=sell=None
'''
    cases['gap_book_median']=base.replace('        # Withdraw the side vulnerable',code+'        # Withdraw the side vulnerable',1)
    return cases


if __name__=='__main__':
    run(Path('logs/round2_gap_quote_batch'),build(),[
        'Quote closer to estimated fair value in spread >=3 instead of only one tick inside the touch',
        'Two fixed widths plus a robust whole-book median center',
        'No position increase: strict100 and all native execution costs retained'])
