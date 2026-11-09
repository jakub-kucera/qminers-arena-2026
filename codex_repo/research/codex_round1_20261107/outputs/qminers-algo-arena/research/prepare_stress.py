"""Fixed sensitivity cases, not a parameter search."""
import json
from run_study import ROOT, OUT, REFS, dump

data=ROOT/'data/sample_v2.csv'
old=ROOT/'data/sample.csv'
maker=REFS/'r0_F2_maker_v2.py'
momentum=REFS/'r0_M2_runner_safe.py'
own=ROOT/'strategies/research_candidate.py'
duration=json.loads((OUT/'dataset_profile.json').read_text())['duration_s']
tasks=[
    ['F2_delay20ms',str(maker),str(data),{},20],
    ['F2_delay50ms',str(maker),str(data),{},50],
    ['F2_cap50',str(maker),str(data),{'QUOTE':50,'LIMIT':50,'SKEW':30},5],
    ['F2_original_sample',str(maker),str(old),{'SESSION_S':3599.000003},5],
    ['M2_original_sample',str(momentum),str(old),{'SESSION_S':3599.000003},5],
    ['microprice_original_sample',str(own),str(old),{'MODE':'maker','SESSION_S':3599.000003},5],
]
dump(OUT/'stress_plan.json',tasks)
print('Prepared',len(tasks),'fixed sensitivity cases.')
