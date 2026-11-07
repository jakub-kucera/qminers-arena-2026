"""H1 forecast execution plus calibrated maker under a shared strict budget."""
import ast
from pathlib import Path
from scripts.round2_h1_refine import build as h1_build
from scripts.round2_ra_composite import main


def build():
    base=h1_build()['strict_base']
    ref=Path('strategies/round2/round2_local_222966.py').read_text()
    cls=next(n for n in ast.parse(ref).body if isinstance(n,ast.ClassDef))
    tree=next(n for n in cls.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TREES' for t in n.targets))
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_fill_value')
    base=base.replace('    FEATURE_COUNT = 29','    '+ast.get_source_segment(ref,tree)+'\n\n    '+ast.get_source_segment(ref,method)+'\n\n    FEATURE_COUNT = 29',1)
    anchor='        self._bias = 0\n'
    assert base.count(anchor)==1
    base=base.replace(anchor,anchor+'''        self._cal_error=0.0
        self._cal_groups=[0.0]*4
        self._cal_time=None
        self._cal_labels=deque(maxlen=4096)
        self._value_us=None
        self._bid_value=self._ask_value=0.0
        self._value_spread=1
''',1)
    begin=ref.index('        if self._cal_time is not None:')
    end=ref.index('        self._learn(now,mid)',begin)
    base=base.replace('        self._learn(now,mid)',ref[begin:end]+'        self._learn(now,mid)',1)
    begin=ref.index('        if self._value_us is None or now-self._value_us >= 20000:')
    end=ref.index('        # Withdraw the side',begin)
    gating=ref[begin:end]
    base=base.replace('        # Withdraw the side',gating+'        # Withdraw the side',1)
    anchor='        if event.status == OrderStatus.ACCEPTED:'
    assert base.count(anchor)==1
    base=base.replace(anchor,'''        if event.status in (OrderStatus.FILLED,OrderStatus.PARTIALLY_FILLED) and self._value_us is not None and record[6]==0 and event.order_id!=self._hedge_id:
            if 0<=event.timestamp_us-self._value_us<=100000:
                predicted=self._bid_value if record[0]>0 else self._ask_value
                self._cal_labels.append((event.timestamp_us,record[0],event.fill_price,predicted,event.filled_quantity,int(self._value_spread>=2)))
'''+anchor,1)
    base=base.replace('    KEEP_LOTS = 20','    KEEP_LOTS = 0',1)
    cases={}
    for size,mode in ((25,'wide'),(100,'wide'),(25,'inactive'),(100,'inactive')):
        text=base.replace('    QUOTE_SIZE = 1\n',f'    QUOTE_SIZE = {size}\n',1)
        # Suppress maker quotes while a forecast take is actionable, even if the
        # IOC pacing gate temporarily prevents sending it. Wide-only isolates
        # the maker to spreads outside H1's IOC gate.
        condition='spread < 2' if mode=='wide' else '''(spread<=1 and ((prediction-skew)>self.TAKE_EDGE+0.5*spread-(BIAS_AGREE if self._bias>0 else 0)+(BIAS_AGAINST if self._bias<0 else 0) or (prediction-skew)<-(self.TAKE_EDGE+0.5*spread-(BIAS_AGREE if self._bias<0 else 0)+(BIAS_AGAINST if self._bias>0 else 0))))'''
        anchor='        self._desired_buy,self._desired_sell,self._desired_time = buy,sell,now'
        text=text.replace(anchor,f'        if {condition}:\n            buy=sell=None\n'+anchor,1)
        cases[f'maker{size}_{mode}']=text
    return cases


if __name__=='__main__':
    main(Path('logs/round2_h1_maker'),build(),
         'Fixed H1 strict baseline bias0.3 plus reference calibrated maker; quote25/100, wide-spread-only or forecast-inactive. Shared strict100 reservations, no independent strategy accounts, IOC fills excluded from maker calibration. Fixed four cases; reused public tree; consumed data only.')
