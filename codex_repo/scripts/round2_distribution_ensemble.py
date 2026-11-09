"""Equal-weight mixture of public-fill and actual/public-fill perspectives.

Identical55-feature layout and first60% training scope; fixed1/2 weights,
no fit on later public outcomes and no volatility-sizing changes.
"""
import ast
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_distribution_pricing import pricing_source
from scripts.round2_full_public_study import run_public_study


def blend(a,b):
    def constants(source):
        cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef))
        return {n.targets[0].id:ast.literal_eval(n.value) for n in cls.body if isinstance(n,ast.Assign)
                and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('TREE_BASE','TREES')}
    x=constants(a);y=constants(b)
    trees=tuple(tuple(row[:4]+(row[4]*.5,row[5]) for row in tree) for tree in x['TREES']+y['TREES'])
    lines=a.splitlines()
    for i,line in enumerate(lines):
        if line.startswith('    TREE_BASE='):lines[i]='    TREE_BASE='+repr((x['TREE_BASE']+y['TREE_BASE'])*.5)
        elif line.startswith('    TREES='):lines[i]='    TREES='+repr(trees)
    return '\n'.join(lines)+'\n'


def main():
    a=Path('strategies/round2_distribution_rich_167958.py').read_text()
    b=Path('strategies/round2_distribution_mixed_170252.py').read_text()
    source=blend(a,b)
    cases={'distribution_ensemble':source,
        'distribution_ensemble_retreat':pricing_source(source,'retreat_negative')}
    cases={n:describe(s,'Fixed equal-weight public/actual-fill ensemble. All training first60%; reused public selection; unchanged risk sizes.') for n,s in cases.items()}
    run_public_study(cases,'logs/round2/distribution_research/ensemble_replays',workers=2)


if __name__=='__main__':main()
