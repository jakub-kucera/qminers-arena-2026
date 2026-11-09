"""Integrate the newly published F4 execution improvements into a frozen v2 policy."""
import hashlib
import json
import shutil
from run_study import ROOT,TEAM,dump
from composite_study import DEST

source=(ROOT/'strategies/composite_template.py').read_text(encoding='utf-8')
source=source.replace("FEATURE_US = 100_000\n", "FEATURE_US = 100_000\nSTEP_INSIDE = 1\nDEPLETE_LOTS = 0\nBACK_POS = 1000\n")
old='''        bid = ask = 0
        for order in snapshot.bids:
            if order.owner == 'market':
                bid = order.price
                break
        for order in snapshot.asks:
            if order.owner == 'market':
                ask = order.price
                break
'''
new='''        bid = ask = 0
        bid_lots = ask_lots = 0
        for order in snapshot.bids:
            if order.owner == 'market':
                if bid == 0:
                    bid = order.price
                elif order.price != bid:
                    break
                bid_lots += order.quantity
        for order in snapshot.asks:
            if order.owner == 'market':
                if ask == 0:
                    ask = order.price
                elif order.price != ask:
                    break
                ask_lots += order.quantity
'''
assert old in source
source=source.replace(old,new)
source=source.replace("if ask - bid >= 3 else (bid, ask)","if STEP_INSIDE and ask - bid >= 3 else (bid, ask)")
source=source.replace('        inventory_error = self.position - target\n',
'''        inventory_error = self.position - target
        if inventory_error >= BACK_POS:
            bp = bid - 1
        if inventory_error <= -BACK_POS:
            ap = ask + 1
''')
source=source.replace('        if REGIME_GUARD:\n',
'''        if DEPLETE_LOTS and bid_lots < DEPLETE_LOTS:
            want_buy = False
        if DEPLETE_LOTS and ask_lots < DEPLETE_LOTS:
            want_sell = False
        if REGIME_GUARD:
''')
path=ROOT/'strategies/composite_room_template.py'
path.write_text('# Adds the execution ideas in team F4 at commit 5003a35; independent composite implementation.\n'+source,encoding='utf-8')
reference=ROOT/'research/reference_strategies/r0_F4_depletion_guard.py'
shutil.copy2(TEAM/'python/bots/qminers/candidates/r0_F4_depletion_guard.py',reference)
params=json.loads((DEST/'model_params.json').read_text())
base=dict(params,QUOTE=200,SKEW=100,TOPUP=1,MIN_REFILL=10,MAX_QUOTES=200,INVENTORY_SIZE=0,
          STEP_INSIDE=0,DEPLETE_LOTS=20,BACK_POS=95,WIND_DOWN_S=30)
variants=[
 ('control',{}),
 ('ensemble_edge15',{'MODEL':'ensemble','EDGE_FLOOR':.15}),
 ('linear_edge15',{'MODEL':'linear','EDGE_FLOOR':.15}),
 ('ensemble_edge35',{'MODEL':'ensemble','EDGE_FLOOR':.35}),
 ('ensemble_target20',{'MODEL':'ensemble','EDGE_FLOOR':.15,'TARGET_ALPHA':20}),
 ('ensemble_target40',{'MODEL':'ensemble','EDGE_FLOOR':.15,'TARGET_ALPHA':40}),
 ('ensemble_refill5',{'MODEL':'ensemble','EDGE_FLOOR':.15,'MIN_REFILL':5}),
 ('ensemble_sizing',{'MODEL':'ensemble','EDGE_FLOOR':.15,'TARGET_ALPHA':40,'SIZE_ALPHA':.75}),
]
data=json.loads((DEST/'screen_plan.json').read_text())[0][2]
tasks=[['r0_F4',str(reference),data,{},5]]
tasks.extend(['r0_'+name,str(path),data,dict(base,**delta),5] for name,delta in variants)
dump(DEST/'room_plan.json',tasks)
dump(DEST/'latest_team_reference.json',dict(commit='5003a35',source=str(reference),
    source_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),reported_full_pnl=264616,
    note='New team source discovered after initial screen. Reported full/tail results are prior research, not independent test evidence. Local comparison still selects policies on the 50-75% segment only.'))
print('Prepared',len(tasks),'new F4/composite comparisons.')
