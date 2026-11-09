"""One-factor selector and stop alternatives around the verified 195721 hybrid."""
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_ra_composite import main as run_study


def build():
    p=Path('strategies/round2/round2_local_195721.py')
    assert digest(p)=='e2d55a7d606b1a679070bc386182c38d7bf8b35da8b5a77d6a55ae408b0118e2'
    base=p.read_text();cases={}
    for gate in (10,40):
        anchor='score-self._m2_history[0][1]>20:'
        assert base.count(anchor)==1
        cases[f'gate{gate}']=base.replace(anchor,f'score-self._m2_history[0][1]>{gate}:')
    for seconds in (30,120):
        text=base.replace('boundary=now-60000000',f'boundary=now-{seconds*1000000}')
        text=text.replace('now-self._m2_start>=60000000',f'now-self._m2_start>={seconds*1000000}')
        cases[f'window{seconds}']=text
    for stop in (2,5):
        anchor='self._m2_big*(self._ra_anchor-mid)>=3:'
        assert base.count(anchor)==1
        cases[f'stop{stop}']=base.replace(anchor,f'self._m2_big*(self._ra_anchor-mid)>={stop}:')
    return cases


if __name__=='__main__':
    run_study(Path('logs/round2_ra_selector'),build(),
        'One-factor variations around verified195721: recent-profit hurdle10/40, lookback30/120seconds, stop2/5ticks. All other parameters fixed.')
