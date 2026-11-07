"""Online first-passage direction labels instead of fixed-horizon midpoint returns."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.benchmark import digest
from scripts.check_submission import check

ROOT=Path('logs/round1/barrier')


def source_for(barrier, lag, gain):
    text=Path('strategies/round1_submission.py').read_text()
    text=text.replace('deque(maxlen=64)','deque(maxlen=256)')
    old='''        while self._observations and self._observations[0][0] + self.HORIZON_US <= now:
            observed_us, old_mid, features = self._observations.popleft()
            if now - observed_us > self.HORIZON_US + 1_000_000:
                continue'''
    new=f'''        ready = []
        waiting = deque(maxlen=256)
        while self._observations:
            observation = self._observations.popleft()
            stamp,origin,frame = observation
            if now-stamp >= {lag} and abs(mid-origin) >= {barrier}:
                ready.append(observation)
            elif now-stamp <= 2000000:
                waiting.append(observation)
        self._observations = waiting
        for observed_us, old_mid, features in ready:'''
    assert old in text
    text=text.replace(old,new).replace('response = max(-20.0, min(20.0, mid - old_mid))',
                                       f'response = {barrier} if mid > old_mid else -{barrier}')
    text=text.replace('        fair = mid + ',f'        prediction *= {gain}\n        fair = mid + ')
    return text


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;specs={}
    for barrier in (0.5,1.0):
        for lag in (5000,20000):
            for gain in (0.25,0.5,1.0):
                name=f'barrier_{barrier}_lag_{lag}_gain_{gain}'
                path=ROOT/'sources'/(name+'.py');path.write_text(source_for(barrier,lag,gain))
                assert not check(path),check(path)
                specs[name]=dict(barrier=barrier,min_lag_us=lag,gain=gain,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=4)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning; first-passage labels mature only after the observable barrier event.'),indent=2)+'\n')
    print('WINNER',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
