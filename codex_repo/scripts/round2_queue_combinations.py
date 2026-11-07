"""Combine development-supported jump guards with queue-preserving inventory sizing."""
from pathlib import Path

from scripts.round2_jump_models import build_candidates,replace_once,run_study
from scripts.round2_queue_inventory import queue_inventory
from scripts.build_round2_candidates import describe


def main():
    references=build_candidates(Path('strategies/round2/round2_transfer.py').read_text())
    pause=replace_once(references['jump_pause100ms'],
        'now-self._invalid_since >= 50_000','now-self._invalid_since >= 0')
    cases={}
    for name,source,band,gain in (
        ('queue50_jump',pause,50,0),('queue25target_jump',pause,25,150),
        ('queue25_jump',pause,25,0),('queue75_jump',pause,75,0)):
        cases[name]=queue_inventory(source,band,gain)
    fixed=queue_inventory(references['robust_label1'],50,0)
    # A simple robust-count forecast is a distinct reference against learned
    # regressions contaminated by rare jumps, not a fitted price-path rule.
    fixed=replace_once(fixed,'        self._learn(now,mid)','        # Fixed causal depth-count forecast; no fitting.')
    start=fixed.index('        prediction = 0.25*spread*imbalance')
    end=fixed.index('        fair = mid + ',start)
    fixed=fixed[:start]+'        prediction=0.5*count_imbalance+0.25*depth_count\n'+fixed[end:]
    cases['queue50_fixed_counts']=fixed
    cases={n:describe(t,'Round-2 development queue/jump combination hypothesis: '+n+
                      '. Planned bounds; native overlap, latency and fees unchanged.') for n,t in cases.items()}
    run_study(cases,'logs/round2/queue_combinations',workers=2)


if __name__=='__main__':main()
