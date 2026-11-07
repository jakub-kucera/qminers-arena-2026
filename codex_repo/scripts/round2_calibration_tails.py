"""Tail-aware fill labels; no hardcoded direction-specific rule."""
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_ra_composite import main as run_study


def build():
    p=Path('strategies/round2/round2_local_209795.py')
    assert digest(p)=='df93cf43167894a1fe00a67b459f32d655ecbc8a5d5a2e4f036f54645e05af90'
    base=p.read_text();anchor='realized=max(-3,min(3,sign*(mid-price)))'
    assert base.count(anchor)==1
    expressions={'clip6':'max(-6,min(6,sign*(mid-price)))',
                 'clip12':'max(-12,min(12,sign*(mid-price)))',
                 'downside6_upside3':'max(-6,min(3,sign*(mid-price)))',
                 'unclipped':'sign*(mid-price)'}
    return {name:base.replace(anchor,'realized='+expression,1) for name,expression in expressions.items()}


if __name__=='__main__':
    run_study(Path('logs/round2_calibration_tails'),build(),
        'Reference diagnostics show clipping can hide adverse tail markouts. Test symmetric6/12, downside6-upside3, and unclipped calibration targets on both trade directions. Keep correction bounded0.5, rate0.01, horizon400ms and price-learner labels unchanged. All data consumed.')
