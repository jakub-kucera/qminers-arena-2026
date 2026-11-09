"""Two final ablations of the validation winner, before opening its final tail."""
import json
from run_study import dump
from composite_study import DEST

rows=json.loads((DEST/'room_summary.json').read_text())
winner=max(rows,key=lambda r:r['validation_pnl'])
assert winner['name']=='r0_ensemble_target40'
prefix=json.loads((DEST/'room_plan.json').read_text())[0][2]
variants=[('matched_linear',{'MODEL':'linear'}),('without_edge_filter',{'EDGE_FLOOR':-100.0})]
tasks=[['a0_'+name,winner['source'],prefix,dict(winner['params'],**delta),5] for name,delta in variants]
dump(DEST/'confirm_plan.json',tasks)
print('Prepared final matched-policy ablations; no later tuning on the diagnostic tail.')
