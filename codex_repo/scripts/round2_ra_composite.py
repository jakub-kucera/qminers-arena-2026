"""Bounded RA/composite integration study for the 250k local target."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import json
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json

ROOT=Path('logs/round2_ra_composite')


def build():
    source=Path('strategies/round2_composite_local.py')
    assert digest(source)=='c96141d18a50b9280539a90b160f2a1b13acb00ef96cd099a8484e12b4292877'
    base=source.read_text().replace('        self._m2_big=0','''        self._ra_flow=deque()
        self._ra_sum=0
        self._ra_anchor=0.0
        self._ra_stopped=False
        self._m2_big=0''',1)
    begin=base.index('        if net>=500:')
    end=base.index('        step=self._m2_big-self._m2_shadow_pos',begin)
    cases={}
    for window,stop,gate,fallback in ((250,0,20,'flat'),(250,3,20,'flat'),
            (250,3,20,'maker'),(250,3,0,'flat'),(150,3,20,'flat'),(0,3,20,'flat')):
        code=f'''        mid=(bid+ask)*.5
        flow=net
        if {window}>0:
            while self._ra_flow and self._ra_flow[0][0]<now-{window*1000}:
                self._ra_sum-=self._ra_flow.popleft()[1]
            if not self._ra_flow:
                self._ra_sum=0
            if net:
                self._ra_flow.append((now,net))
                self._ra_sum+=net
            flow=self._ra_sum if net else 0
        fired=1 if flow>=500 else -1 if flow<=-500 else 0
        if fired:
            if fired!=self._m2_big or self._ra_stopped:
                self._ra_anchor=mid
                self._ra_stopped=False
            self._m2_big=fired
            self._ra_flow.clear()
            self._ra_sum=0
'''
        text=base[:begin]+code+base[end:]
        text=text.replace('score-self._m2_history[0][1]>20:',f'score-self._m2_history[0][1]>{gate}:')
        # RA's stop references signal midpoint and only fires while holding real inventory.
        # Stop state is tracked continuously; maker fallback is an explicit separate hypothesis.
        anchor='        if now-self._m2_start>=60000000 and score>10'
        assert text.count(anchor)==1
        text=text.replace(anchor,f'''        if {stop}>0 and not self._ra_stopped and self._m2_big and self.inventory:
            if self._m2_big*(self._ra_anchor-mid)>={stop}:
                self._ra_stopped=True
'''+anchor,1)
        text=text.replace('            return 100*self._m2_big',f'''            if self._ra_stopped:
                return {'None' if fallback=='maker' else '0'}
            return 100*self._m2_big''',1)
        cases[f'flow{window}_stop{stop}_gate{gate}_{fallback}']=text
    return cases


def main(root=ROOT,cases=None,hypothesis='Aggregate short-window flow, consume signals, and stop adverse trends inside the existing shared-budget maker/taker composite.',goal=250000):
    ROOT=root
    m=load_manifest(Path('logs/round2_local_intake'))
    ROOT.mkdir(exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    candidates=[]
    for name,text in (build() if cases is None else cases).items():
        p=ROOT/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==text
        else:p.write_text(text)
        assert not check(p),check(p)
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p),risk='strict100'))
    protocol=dict(goal=goal,candidates=candidates,native=m['native'],
        scope='Consumed public first80%; no new holdout and no server access.',
        hypothesis=hypothesis,
        selection='Require positive minutes30-60 and60-80; maximize combined gain there; freeze one before full replay. Never select by full results.',
        reference='Frozen 167412 composite remains unchanged; no automatic promotion from prefix alone.')
    p=ROOT/'protocol.json'
    if p.exists():assert json.loads(p.read_text())==protocol
    else:write_json(p,protocol)
    p=ROOT/'results.json';results=json.loads(p.read_text()) if p.exists() else {}
    with ProcessPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(run_candidate,c,m['validation_prefix'],ROOT/c['name'],
              (m['first_us']+1800000000,m['development_cutoff_us'],m['validation_cutoff_us'])):c['name']
              for c in candidates if c['name'] not in results}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();b=r['boundary_pnl']
            r['later30']=b[str(m['development_cutoff_us'])]-b[str(m['first_us']+1800000000)]
            r['last20']=b[str(m['validation_cutoff_us'])]-b[str(m['development_cutoff_us'])]
            results[name]=r;write_json(p,results)
            print(name,r['result']['pnl'],r['later30'],r['last20'],flush=True)


if __name__=='__main__':main()
