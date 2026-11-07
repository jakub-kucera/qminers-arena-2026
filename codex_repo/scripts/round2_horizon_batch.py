"""Second bounded development batch; prior public outcomes informed these hypotheses."""
from pathlib import Path
from scripts.round2_structural_batch import run


def build():
    old = Path('strategies/round1_robust_candidate.py').read_text()
    base = Path('strategies/round2/round2_strict100.py').read_text()
    cases = {'prior_15_features':old}
    anchor = 'response = max(-20.0, min(20.0, mid - old_mid))'
    assert anchor in old and anchor in base
    cases['prior_15_clip3'] = old.replace(anchor, 'response = max(-3.0, min(3.0, mid - old_mid))')
    for clip in (1, 3):
        cases[f'short100_clip{clip}'] = base.replace('HORIZON_US = 400000', 'HORIZON_US = 100000').replace(
            anchor, f'response = max(-{clip}.0, min({clip}.0, mid - old_mid))')
    cases['short100_clip3_adapt'] = cases['short100_clip3'].replace(
        'MODEL_MEMORY_US = 100000000000', 'MODEL_MEMORY_US = 300000000')
    cases['horizon1s_clip3'] = base.replace('HORIZON_US = 400000', 'HORIZON_US = 1000000').replace(
        anchor, 'response = max(-3.0, min(3.0, mid - old_mid))').replace('deque(maxlen=64)', 'deque(maxlen=128)')
    return cases


if __name__ == '__main__':
    run(Path('logs/round2_horizon_batch'), build(), [
        'Earlier 15-feature short-horizon maker may adapt better to the new regime',
        'Shorter robust forecast reduces jump contamination',
        'Compare five-minute adaptation and one-second prediction with controls'])
