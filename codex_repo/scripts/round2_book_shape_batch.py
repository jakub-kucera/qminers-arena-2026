"""Development-only latent-price and size-cohort feature hypotheses."""
from pathlib import Path
from scripts.round2_structural_batch import run


def build():
    base=Path('logs/round2_structural_batch/sources/robust_labels_3.py').read_text()
    common='''        shape_b=[o for o in snapshot.bids if o.owner=='market']
        shape_a=[o for o in snapshot.asks if o.owner=='market']
        shape_mean=(sum(o.price for o in shape_b)/len(shape_b)+sum(o.price for o in shape_a)/len(shape_a))*.5-mid
        shape_median=(shape_b[len(shape_b)//2].price+shape_a[len(shape_a)//2].price)*.5-mid
        small_b=sum(o.quantity<=20 for o in shape_b)
        small_a=sum(o.quantity<=20 for o in shape_a)
        large_b=sum(o.quantity>=100 for o in shape_b)
        large_a=sum(o.quantity>=100 for o in shape_a)
'''
    groups={'centers':['max(-5,min(5,shape_mean))','max(-5,min(5,shape_median))'],
            'cohorts':['(small_b-small_a)/max(1,small_b+small_a)',
                       '(large_b-large_a)/max(1,large_b+large_a)']}
    groups['combined']=groups['centers']+groups['cohorts']
    cases={}
    for name,features in groups.items():
        text=base.replace('FEATURE_COUNT = 29',f'FEATURE_COUNT = {29+len(features)}',1)
        text=text.replace('        self._learn(now,mid)',common+
                          '        features += ('+','.join(features)+',)\n        self._learn(now,mid)',1)
        cases['shape_'+name]=text
    cases['shape_combined_adapt']=cases['shape_combined'].replace(
        'MODEL_MEMORY_US = 100000000000','MODEL_MEMORY_US = 300000000')
    return cases


if __name__=='__main__':
    run(Path('logs/round2_book_shape_batch'),build(),[
        'All-visible-order mean and median centers estimate latent fair price beyond near-touch depth',
        'Small and large visible size cohorts may contain different information',
        'Robust 400ms labels, unchanged strict execution, one shorter-memory comparison'])
