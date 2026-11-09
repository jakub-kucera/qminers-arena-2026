"""Development-only state-dependent inventory policies under unchanged native rules.

These planned targets do not impose strict inventory bands: cancel-in-flight
overlap can breach the free 100-lot threshold, and all native fees are charged.
"""
import json
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.check_submission import check
from scripts.round2_workbench import load_manifest,run_candidate,write_json

ROOT=Path('logs/round2/inventory_probes')
DESTINATION=Path('strategies/round2_research')


def build_candidates(base):
    common=base.replace('        self._orders = {}','''        self._orders = {}
        self._upper_target=100
        self._lower_target=-100''',1)
    common=common.replace('        changing = False','''        limit=self._upper_target if sign>0 else -self._lower_target
        active=sum(r[2] for _,r in current if not r[4])
        excessive=active>max(0,limit-sign*self.inventory)
        changing = False''',1)
    common=common.replace('if price is None or record[1] != price:',
                          'if price is None or record[1] != price or excessive:',1)
    common=common.replace('100-sign*self.inventory-effective','limit-sign*self.inventory-effective',1)
    assert common!=base and 'quantity=min(self.QUOTE_SIZE,limit-' in common
    cases={}
    for band in (10,25):
        block=f'''        target=max(-75,min(75,int(150*prediction)))
        self._upper_target=min(100,target+{band})
        self._lower_target=max(-100,target-{band})
'''
        name=f'round2_target_band{band}'
        cases[name]=common.replace('        # Withdraw the side',block+'        # Withdraw the side',1)
    selective='''        self._upper_target=100 if prediction>0.3 else 0
        self._lower_target=-100 if prediction< -0.3 else 0
'''
    cases['round2_selective_entry']=common.replace('        # Withdraw the side',selective+'        # Withdraw the side',1)
    exit_block='''        if spread<=2:
            if self.inventory>self._upper_target+25 and prediction< -0.3:
                sell=bid
            elif self.inventory<self._lower_target-25 and prediction>0.3:
                buy=ask
'''
    cases['round2_target_with_exit']=cases['round2_target_band25'].replace(
        '        # Withdraw the side',exit_block+'        # Withdraw the side',1)
    return {name:describe(text,'Round-2 development inventory-policy hypothesis: '+name+
        '. Planned targets only; charged cancellation overlap remains.') for name,text in cases.items()}


def main():
    manifest=load_manifest(Path('logs/round2'))
    reference=next(c for c in manifest['candidates'] if c['name']=='round2_transfer')
    cases=build_candidates(Path(reference['file']).read_text())
    DESTINATION.mkdir(exist_ok=True);ROOT.mkdir(parents=True,exist_ok=True)
    candidates=[]
    for name,text in cases.items():
        path=DESTINATION/(name+'.py')
        if path.exists():assert path.read_text()==text
        else:path.write_text(text)
        assert not check(path),check(path)
        candidates.append({'name':name,'file':str(path),'source_sha256':digest(path),'risk':'native'})
    report_path=ROOT/'results.json'
    result=json.loads(report_path.read_text()) if report_path.exists() else {
        'scope':'Round-2 public development only. No validation/private selection.',
        'data_sha256':manifest['development_sha256'],'results':{}}
    assert result['data_sha256']==manifest['development_sha256']
    for c in candidates:
        if c['name'] in result['results']:
            assert result['results'][c['name']]['source_sha256']==c['source_sha256']
    with ProcessPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(run_candidate,c,manifest['development'],ROOT/c['name'],
                          (manifest['development_cutoff_us'],)):c['name']
              for c in candidates if c['name'] not in result['results']}
        for job in as_completed(jobs):
            name=jobs[job];r=job.result();result['results'][name]=r
            write_json(report_path,result)
            print(name,'NET',r['result']['pnl'],'fee',r['result']['breach_penalty'],
                  'medianI',r['result']['abs_inventory_q50'],flush=True)


if __name__=='__main__':main()
