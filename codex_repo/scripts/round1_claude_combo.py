"""Combine independently promising features and execution settings; native scoring."""
import difflib
import json
from pathlib import Path

from scripts import round1_claude_improvements as research
from scripts.benchmark import digest
from scripts.check_submission import check
from scripts.round1_aggressor_groups import source_for
from scripts.round1_size_cohorts import bucket_source

ROOT = Path('logs/round1/claude_combo')


def second_group(text, tau):
    dimensions=int(text.split('FEATURE_COUNT = ')[1].splitlines()[0])
    old = research.OLD.read_text().splitlines(keepends=True)
    generated = source_for(tau,100000).replace('_group_', '_second_group_').replace(
        '_rest_count', '_second_rest_count').replace('group_decay', 'second_group_decay')
    new = generated.splitlines(keepends=True)
    for tag,a,b,c,d in difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes():
        if tag=='equal':
            continue
        before,after=''.join(old[a:b]),''.join(new[c:d])
        if 'FEATURE_COUNT' in before:
            continue
        if 'robust_imbalance*abs(robust_imbalance))' in before:
            extra = after.split('robust_imbalance*abs(robust_imbalance),',1)[1].rstrip()[:-1]
            text=text.replace('        self._learn(now,mid)',
                              '        features += ('+extra+')\n        self._learn(now,mid)',1)
            continue
        if not before:
            before=old[a]
            after+=before
        assert text.count(before)==1,(before,text.count(before))
        text=text.replace(before,after,1)
    return text.replace(f'FEATURE_COUNT = {dimensions}',f'FEATURE_COUNT = {dimensions+8}',1)


def generate():
    base = Path('strategies/round1_claude_595k.py').read_text()
    g100=research.transfer_features(base,source_for(100000,100000))
    g500=research.transfer_features(base,source_for(500000,100000))
    bucket=research.transfer_features(base,bucket_source())
    cases={
        'buckets_groups100':research.transfer_features(bucket,source_for(100000,100000)),
        'buckets_groups500':research.transfer_features(bucket,source_for(500000,100000)),
        'groups100_500':second_group(g100,500000),
        'groups100_cap1':g100.replace('max(-20.0, min(20.0, mid - old_mid))','max(-1.0, min(1.0, mid - old_mid))'),
        'groups500_cap1':g500.replace('max(-20.0, min(20.0, mid - old_mid))','max(-1.0, min(1.0, mid - old_mid))'),
        'groups100_gain08':g100.replace('fair = mid + 1.0*prediction','fair = mid + 0.8*prediction'),
        'groups500_gain08':g500.replace('fair = mid + 1.0*prediction','fair = mid + 0.8*prediction'),
        'groups100_band022':g100.replace('abs(fair-mid) <= 0.18','abs(fair-mid) <= 0.22'),
        'groups500_band022':g500.replace('abs(fair-mid) <= 0.18','abs(fair-mid) <= 0.22'),
    }
    (ROOT/'sources').mkdir(parents=True,exist_ok=True)
    specs={}
    for name,text in cases.items():
        path=ROOT/'sources'/(name+'.py')
        if path.exists():assert path.read_text()==text
        path.write_text(text)
        assert not check(path),check(path)
        specs[name]={'source_sha256':digest(path)}
    (ROOT/'specs.json').write_text(json.dumps(specs,indent=2)+'\n')
    return list(cases)


def main():
    names=generate()
    research.ROOT=ROOT
    screen=research.batch(names,'logs/round1/screening.csv','screening',workers=2)
    ranked=sorted(screen,key=lambda n:screen[n]['result']['pnl'],reverse=True)
    full=research.batch(ranked[:4],'data/round1.csv','full',workers=2)
    winner=max(full,key=lambda n:full[n]['result']['pnl'])
    (ROOT/'winner.json').write_text(json.dumps(dict(name=winner,result=full[winner],
        limitation='Sample tuning. All features and labels are causal; native latency and risk fees.'),indent=2)+'\n')
    print('WINNER COMBO',winner,full[winner]['result']['pnl'],flush=True)


if __name__=='__main__':main()
