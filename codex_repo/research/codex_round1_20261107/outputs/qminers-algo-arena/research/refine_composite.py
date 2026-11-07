"""One bounded refinement around the screening winner; use validation only."""
import json
from run_study import ROOT,dump
from composite_study import DEST

rows=json.loads((DEST/'screen_summary.json').read_text())
eligible=[r for r in rows if r['result']['breach_penalty']==0 and r['max_reserved_exposure']<=100]
winner=max(eligible,key=lambda r:r['validation_pnl'])
assert winner['name']=='s0_full_composite',winner['name']
base=winner['params']
source=winner['source']
data=json.loads((DEST/'screen_plan.json').read_text())[0][2]
variants=[
 ('no_regime_guard',{'REGIME_GUARD':0}),
 ('linear_only',{'MODEL':'linear'}),
 ('microprice_only',{'MODEL':'microprice'}),
 ('no_forecast',{'MODEL':'none','SIZE_ALPHA':0.0,'TARGET_ALPHA':0.0}),
 ('refill5',{'MIN_REFILL':5}),
 ('more_queue_slots',{'MIN_REFILL':5,'MAX_QUOTES':8}),
 ('skew100',{'SKEW':100}),
 ('no_inventory_target',{'TARGET_ALPHA':0.0}),
 ('no_size_tilt',{'SIZE_ALPHA':0.0}),
 ('half_forecast_tilt',{'TARGET_ALPHA':40,'SIZE_ALPHA':.75}),
 ('edge05',{'EDGE_FLOOR':.05}),
 ('edge25',{'EDGE_FLOOR':.25}),
]
tasks=[['s1_'+name,source,data,dict(base,**delta),5] for name,delta in variants]
dump(DEST/'refine_plan.json',tasks)
dump(DEST/'refinement_decision.json',dict(parent=winner['name'],parent_validation_pnl=winner['validation_pnl'],
     reason='Separate forecast, risk, and queue effects; compare a small local parameter neighborhood.',
     cases=[{'name':name,'changes':delta} for name,delta in variants]))
print('Prepared',len(tasks),'predeclared refinements from',winner['name'])
