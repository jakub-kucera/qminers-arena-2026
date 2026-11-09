"""Native-fee burst probe; does not change the simulator or scoring rules."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import json
from scripts.benchmark import digest,evaluate
from scripts.check_submission import check
from scripts.round2_workbench import BoundaryMarkEngine,load_manifest,write_json
from simulator.main import load_strategy_from_file

ROOT=Path('logs/round2_burst_revisit')


def build():
    p=Path('strategies/round2/round2_local_199689.py')
    assert digest(p)=='5f69e437ea77d9d494f19427162c26dab6718e76ead392bb6835cb9e19f83343'
    base=p.read_text();cases={}
    for cap,hold in ((250,0),(250,20),(1000,0),(1000,20)):
        text=base.replace('POSITION_LIMIT = 100',f'POSITION_LIMIT = {cap}',1)
        text=text.replace('QUOTE_SIZE = 200',f'QUOTE_SIZE = {cap}',1)
        text=text.replace('        self.inventory = 0','''        self._burst_start=None
        self._burst_closing=False
        self._burst_cooldown=0
        self._burst_prediction=0.0
        self._burst_spread=0
        self.inventory = 0''',1)
        start=text.index('    def _hedge(self, now):')
        end=text.index('    def _cancel(self, order_id):',start)
        text=text[:start]+f'''    def _hedge(self,now):
        if abs(self.inventory)<=100:
            if self._burst_start is not None:
                self._burst_cooldown=now+1000000
            self._burst_start=None
            self._burst_closing=False
            return
        if self._burst_start is None:
            self._burst_start=now
        increasing=1 if self.inventory>0 else -1
        for oid,record in list(self._orders.items()):
            if record[0]==increasing and oid!=self._hedge_id:
                self._cancel(oid)
        if now-self._burst_start<{hold*1000}:
            return
        self._burst_closing=True
        for oid in list(self._orders):
            if oid!=self._hedge_id:
                self._cancel(oid)
        if self._hedge_id is not None:
            return
        if self._cached_time is None or now-self._cached_time>100000:
            return
        sign=-increasing
        reserved=sum(r[2] for r in self._orders.values() if r[0]==sign)
        quantity=min(abs(self.inventory)-100,max(0,self.POSITION_LIMIT-sign*self.inventory-reserved))
        if quantity<=0:
            return
        price=self._cached_ask+10 if sign>0 else max(1,self._cached_bid-10)
        oid=self.send_order(OrderRequest(side=Side.BUY if sign>0 else Side.SELL,
            price=price,quantity=quantity,order_type=OrderType.IOC))
        self._orders[oid]=[sign,price,quantity,False,False,now]
        self._hedge_id=oid

'''+text[end:]
        anchor='    def _quote(self, now, sign, price):'
        text=text.replace(anchor,anchor+'''
        if self._burst_closing or self._hedge_id is not None:
            return''',1)
        anchor='        budget=100-sign*self.inventory if allowed else max(0,-sign*self.inventory)'
        assert text.count(anchor)==1
        text=text.replace(anchor,'''        extra=(allowed and now>=self._burst_cooldown and abs(self.inventory)<=100
               and sign*self.inventory>=0 and self._burst_spread>=4
               and sign*self._burst_prediction>=0.5)
        limit=self.POSITION_LIMIT if extra else 100
        budget=limit-sign*self.inventory if allowed else max(0,-sign*self.inventory)''',1)
        anchor='    def _m2_trade(self,now,target,bid,ask):'
        text=text.replace(anchor,anchor+'''
        if self._burst_start is not None or self._hedge_id is not None:
            return''',1)
        anchor='        self._cached_bid,self._cached_ask,self._cached_time = bid,ask,now'
        assert text.count(anchor)==1
        text=text.replace(anchor,'''        self._burst_prediction=prediction
        self._burst_spread=spread
'''+anchor,1)
        cases[f'cap{cap}_hold{hold}ms']=text
    return cases


class BurstAudit(BoundaryMarkEngine):
    def __init__(self,strategy,config):
        super().__init__(strategy,config)
        self.bursts=[];self.open_burst=None

    def _private_notify(self,event):
        super()._private_notify(event)
        if abs(self._inventory)>100:
            if self.open_burst is None:
                self.open_burst=dict(start_us=self.current_ts_us,peak=abs(self._inventory))
            self.open_burst['peak']=max(self.open_burst['peak'],abs(self._inventory))
        elif self.open_burst is not None:
            self._close_burst()

    def _close_burst(self):
        row=self.open_burst
        row['end_us']=self.current_ts_us
        row['duration_us']=row['end_us']-row['start_us']
        self.bursts.append(row);self.open_burst=None

    def run(self,path):
        result=super().run(path)
        if self.open_burst is not None:self._close_burst()
        expected=sum(r['duration_us'] for r in self.bursts)*.01
        assert abs(expected-result.breach_penalty)<1e-5,'Breach duration/fee mismatch'
        self.strategy._burst_audit=self.bursts
        return result


def run(candidate,full=False):
    m=load_manifest(Path('logs/round2_local_intake'))
    BurstAudit.boundaries=(m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us'])
    bot=load_strategy_from_file(candidate['file'])
    data_key='data' if full else 'validation_prefix'
    destination=ROOT/'full_audit' if full else ROOT/candidate['name']
    r=evaluate(bot,Path(m[data_key]),destination,600,BurstAudit)
    assert r['max_potential_inventory_at_submission']<=bot.POSITION_LIMIT<=1000
    b=r['boundary_pnl'];bursts=bot._burst_audit
    r.update(source_sha256=digest(candidate['file']),data_sha256=m[data_key+'_sha256'],
        later30=b[str(m['development_cutoff_us'])]-b[str(m['first_us']+1800000000)],
        last20=b[str(m['validation_cutoff_us'])]-b[str(m['development_cutoff_us'])],
        gross_pnl=r['result']['pnl']+r['result']['breach_penalty'],
        breach_count=len(bursts),breach_time_us=sum(x['duration_us'] for x in bursts),
        max_breach_us=max((x['duration_us'] for x in bursts),default=0),
        bursts_reaching900=sum(x['peak']>=900 for x in bursts))
    if full:
        r['first80']=b[str(m['validation_cutoff_us'])]
        r['final20']=r['result']['pnl']-r['first80']
    write_json(destination/'breaches.json',bursts)
    return r


def full_check():
    protocol=json.loads((ROOT/'protocol.json').read_text())
    results=json.loads((ROOT/'results.json').read_text())
    assert len(results)==len(protocol['candidates'])
    eligible=[c for c in protocol['candidates'] if results[c['name']]['later30']>0
        and results[c['name']]['last20']>0 and results[c['name']]['result']['pnl']>176875
        and results[c['name']]['later30']+results[c['name']]['last20']>141049]
    if not eligible:
        print('No candidate passed the predeclared net-PnL gate');return
    winner=max(eligible,key=lambda c:results[c['name']]['later30']+results[c['name']]['last20'])
    selection=dict(candidate=winner,selection_rule=protocol['selection'],goal=250000,scope=protocol['scope'])
    p=ROOT/'full_selection.json'
    if p.exists():assert json.loads(p.read_text())==selection
    else:write_json(p,selection)
    print('Frozen',winner['name'],flush=True)
    p=ROOT/'full_audit.json'
    if p.exists():print('Preserving completed full audit');return
    r=run(winner,True);write_json(p,r)
    print(r['result'],'final20',r['final20'],flush=True)


def main():
    m=load_manifest(Path('logs/round2_local_intake'))
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    candidates=[]
    for name,text in build().items():
        p=ROOT/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==text
        else:p.write_text(text)
        assert not check(p),check(p)
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p)))
    protocol=dict(goal=250000,candidates=candidates,native=m['native'],
        scope='Consumed public first80%; local-only native-fee experiment.',
        hypothesis='Allow250/1000 potential lots only with spread>=4, aligned inventory and prediction>=0.5; withdraw increasing orders on breach, force recovery after0/20ms, cooldown1s.',
        selection='Require positive later30 and last20 and beat the199689 reference first80 net176875 and later50 net141049. Compare net after native fees; freeze before full replay.',
        caveat='Recovery trigger is not a guaranteed exit time. No rules or fee changes.')
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    p=ROOT/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run,c):c['name'] for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();results[name]=r;write_json(p,results)
            print(name,'net',r['result']['pnl'],'fee',r['result']['breach_penalty'],
                  'peak',r['max_abs_inventory'],'bursts',r['breach_count'],flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--full',action='store_true')
    args=parser.parse_args()
    full_check() if args.full else main()
