"""Small matched-size comparison and IOC threshold probe, declared before runs."""
import json
from run_study import ROOT, OUT, dump

model=json.loads((OUT/'models_plan.json').read_text())[0][3]
own=ROOT/'strategies/research_candidate.py'
data=ROOT/'data/sample_v2.csv'
tasks=[
    ['ridge_maker_size80',str(own),str(data),dict(model,MODE='ridge_maker',SIZE=80),5],
    ['microprice_maker_size80',str(own),str(data),dict(MODE='maker',SIZE=80,SESSION_S=model['SESSION_S']),5],
    ['ridge_ioc_edge0',str(own),str(data),dict(model,MODE='ridge_ioc',EDGE=0.0),5],
    ['ridge_maker_original_sample',str(own),str(ROOT/'data/sample.csv'),dict(model,MODE='ridge_maker',SESSION_S=3599.000003),5],
]
dump(OUT/'followup_plan.json',tasks)
print('Prepared',len(tasks),'follow-up cases; these are exploratory comparisons, not a fresh holdout.')
