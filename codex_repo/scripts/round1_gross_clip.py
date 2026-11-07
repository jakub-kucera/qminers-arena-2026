"""Cap total same-side resting size to separate closing from opening inventory."""
import json
from pathlib import Path
from scripts import search_queue
from scripts.check_submission import check
from scripts.benchmark import digest

ROOT=Path('logs/round1/gross_clip')


def main():
    ROOT.mkdir(parents=True,exist_ok=True);(ROOT/'sources').mkdir(exist_ok=True)
    if (ROOT/'screening.json').exists():raise SystemExit('Results already exist')
    search_queue.ROOT=ROOT;base=Path('strategies/round1_private_554347.py').read_text();specs={}
    for gross in (25,50,75,100,125,150,175):
        name=f'gross_{gross}'
        text=base.replace('QUOTE_SIZE = 200',f'QUOTE_SIZE = {gross}')
        text=text.replace('quantity = min(self.QUOTE_SIZE, self.POSITION_LIMIT-sign*self.inventory-reserved)',
                          'quantity = min(self.QUOTE_SIZE-reserved, self.POSITION_LIMIT-sign*self.inventory-reserved)')
        path=ROOT/'sources'/(name+'.py');path.write_text(text)
        assert not check(path),check(path)
        specs[name]=dict(gross_resting_limit=gross,source_sha256=digest(path))
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    screen=search_queue.batch(specs,'logs/round1/screening.csv','screening',workers=3)
    finalists=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)[:3]
    full=search_queue.batch(finalists,'data/round1.csv','full',workers=3)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],parameters=specs[winner],
        limitation='Sample tuning. Gross resting cap differs from per-order size; hard potential inventory remains 100.'),indent=2)+'\n')
    print('WINNER GROSS CLIP',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
