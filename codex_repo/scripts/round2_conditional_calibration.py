"""Causal direction/spread-conditioned fill-value calibration."""
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_ra_composite import main as run_study


def build():
    p=Path('strategies/round2/round2_local_199689.py')
    assert digest(p)=='5f69e437ea77d9d494f19427162c26dab6718e76ead392bb6835cb9e19f83343'
    base=p.read_text();cases={}
    for spread_groups in (False,True):
        for blend in (.5,1.0):
            text=base.replace('        self._cal_error=0.0','''        self._cal_groups=[0.0]*4
        self._value_spread=0
        self._cal_error=0.0''',1)
            anchor='            self._cal_error*=exp(-max(0,now-self._cal_time)/300000000)'
            text=text.replace(anchor,anchor+'''
            for index in range(4):
                self._cal_groups[index]*=exp(-max(0,now-self._cal_time)/300000000)''',1)
            text=text.replace('observed,sign,price,predicted,quantity=self._cal_labels.popleft()',
                              'observed,sign,price,predicted,quantity,bucket=self._cal_labels.popleft()',1)
            anchor='                self._cal_error=max(-0.5,min(0.5,self._cal_error))'
            text=text.replace(anchor,anchor+'''
                index=(0 if sign>0 else 1)+2*bucket
                self._cal_groups[index]+=alpha*(realized-predicted-self._cal_groups[index])
                self._cal_groups[index]=max(-0.5,min(0.5,self._cal_groups[index]))''',1)
            text=text.replace('            self._value_us=now','            self._value_spread=spread\n            self._value_us=now',1)
            bucket='int(self._value_spread>=2)' if spread_groups else '0'
            anchor='predicted,event.filled_quantity))'
            assert text.count(anchor)==1
            text=text.replace(anchor,f'predicted,event.filled_quantity,{bucket}))',1)
            live_bucket='2*int(spread>=2)' if spread_groups else '0'
            for value,index in (('_bid_value',0),('_ask_value',1)):
                anchor=f'self.{value}+self._cal_error>=0.1'
                assert text.count(anchor)==1
                correction=f'({1-blend}*self._cal_error+{blend}*self._cal_groups[{index}+{live_bucket}])'
                text=text.replace(anchor,f'self.{value}+{correction}>=0.1',1)
            cases[f'side_spread{int(spread_groups)}_blend{blend}']=text
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_conditional_calibration'),build(),
        'Separate mature fill-value residuals by buy/sell side, optionally spread1 versus2+, and blend50/100percent with the existing global correction. Same400ms labels,0.03rate,0.5clip,300sdecay; no future information.')
