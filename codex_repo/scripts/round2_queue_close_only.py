"""On slow queues, allow closing capacity without planning a position reversal."""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_jump_models import replace_once,run_study
from scripts.round2_queue_wait import queue_wait


def close_only_queue(base,wait):
    text=queue_wait(base,wait)
    text=replace_once(text,'        if price is not None and sign*self.inventory>=0:',
        '        slow_queue=False\n        if price is not None:')
    text=replace_once(text,f'            if ahead/max(100,rate)>{wait}:',
        f'            slow_queue=ahead/max(100,rate)>{wait}\n            if slow_queue and sign*self.inventory>=0:')
    text=replace_once(text,'        budget=max(0,limit-sign*self.inventory)',
        '''        budget=max(0,limit-sign*self.inventory)
        if slow_queue:
            budget=min(budget,max(0,-sign*self.inventory))''')
    return text


def main():
    base=Path('strategies/round2_research/round2_absolute_variance_112379.py').read_text()
    cases={}
    for wait in (.1,.25):
        name=f'queue_slow_close_only_{wait}'
        cases[name]=describe(close_only_queue(base,wait),
            'Development-only queue gate with closing-only slow-queue budget: '+name+
            '. Native modify/cancel overlap remains; saved volatility parameters unchanged.')
    run_study(cases,'logs/round2/queue_close_only',workers=2)


if __name__=='__main__':main()
