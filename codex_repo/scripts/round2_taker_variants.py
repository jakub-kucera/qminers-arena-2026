"""Structural taker followups to the user-supplied server-validated T2 source.

No server result is attributed to these altered files. All variants retain
strict accounting for accepted, in-flight and cancel-pending same-side lots.
"""
from pathlib import Path

from scripts.benchmark import digest
from scripts.build_round2_candidates import describe
from scripts.round2_distribution_features import augment
from scripts.round2_jump_models import replace_once
from scripts.round2_taker_audit import batch
from scripts.round2_workbench import load_manifest,write_json

BASE=Path('strategies/round2_imported/r2_T2_take_only_safe.py')
BASE_SHA='13251f09475b6248d4414d7e73d6a8ded667712d27cda09db1a50047999d37f7'


def shock_override(base):
    text=replace_once(base,'        self._orders = {}','''        self._orders = {}
        self._shock_mid=None
        self._shock_sign=0
        self._shock_until=0''')
    text=replace_once(text,'        mid = (bid+ask)*0.5','''        mid = (bid+ask)*0.5
        if self._shock_mid is not None and abs(mid-self._shock_mid)>=2:
            self._shock_sign=1 if mid>self._shock_mid else -1
            self._shock_until=now+100000
        self._shock_mid=mid''')
    return replace_once(text,'        need = self.TAKE_EDGE + 0.5*spread','''        need = self.TAKE_EDGE + 0.5*spread
        if now<self._shock_until:
            signal=self._shock_sign*(need+0.01)''')


def flow_bias(base,window_us,threshold):
    text=replace_once(base,'        self._orders = {}','''        self._orders = {}
        self._trend_flow=deque()
        self._trend_flow_sum=0
        self._trend_direction=0''')
    block=f'''        net=sum(t.quantity if t.book_side=='ask' else -t.quantity
                for t in trades if t.taker_owner=='market')
        while self._trend_flow and self._trend_flow[0][0]<now-{window_us}:
            self._trend_flow_sum-=self._trend_flow.popleft()[1]
        if net:
            self._trend_flow.append((now,net))
            self._trend_flow_sum+=net
            signal=self._trend_flow_sum if {window_us}>0 else net
            if abs(signal)>={threshold}:
                self._trend_direction=1 if signal>0 else -1
                self._trend_flow.clear()
                self._trend_flow_sum=0
'''
    text=replace_once(text,'        now = snapshot.timestamp_us','        now = snapshot.timestamp_us\n'+block)
    return replace_once(text,'        need = self.TAKE_EDGE + 0.5*spread',
        '        signal+=0.15*self._trend_direction\n        need = self.TAKE_EDGE + 0.5*spread')


def liquidity_features(base):
    text=augment(base)
    text=replace_once(text,'FEATURE_COUNT = 29','FEATURE_COUNT = 33')
    return replace_once(text,'        self._learn(now,mid)','''        young=self._distribution_frame[0][20]
        dispersion=min(3.0,self._distribution_frame[1][-1])
        features+=(young,young*dispersion,flow*dispersion,count_imbalance*dispersion)
        self._learn(now,mid)''')


def build():
    assert digest(BASE)==BASE_SHA
    base=BASE.read_text()
    cases={'t2_no_quotes':replace_once(base,'    QUOTE_SIZE = 1','    QUOTE_SIZE = 0'),
        't2_shock100':shock_override(base),
        't2_big_bias':flow_bias(base,0,500),
        't2_window_bias':flow_bias(base,125000,575),
        't2_liquidity_features':liquidity_features(base)}
    root=Path('logs/round2/taker_variants');(root/'sources').mkdir(parents=True,exist_ok=True)
    candidates=[]
    for name,text in cases.items():
        source=describe(text,'T2-derived structural taker hypothesis: '+name+
            '. Original source supplied by another session. No validation score for this alteration; strict all-live reservation accounting retained.')
        p=root/'sources'/(name+'.py')
        if p.exists():assert p.read_text()==source
        else:p.write_text(source)
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p),risk='strict100'))
    write_json(root/'hypotheses.json',dict(base_source=str(BASE),base_sha256=BASE_SHA,
        candidates=candidates,selection_scope='Five predeclared structural variants, reused public replay and later synthetic stress. No hidden scores.'))
    return candidates


def main():
    m=load_manifest(Path('logs/round2'));candidates=build()
    batch(candidates,m['data'],'logs/round2/taker_variants/public',
        (m['development_cutoff_us'],m['validation_cutoff_us']),workers=3,
        scope='Reused full PUBLIC sample. Online fitting only. No validation result for modified sources.')


if __name__=='__main__':main()
