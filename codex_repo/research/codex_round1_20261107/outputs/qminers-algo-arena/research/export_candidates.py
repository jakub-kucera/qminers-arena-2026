"""Export tested parameters into standalone files and run local source checks."""
import ast
import hashlib
import json
import shutil
import sys
from pathlib import Path
from run_study import ROOT, OUT, TEAM, dump, load_bot


def source_check(tree):
    """Conservative local check of published bans, not the remote validator."""
    banned_modules={'os','sys','subprocess','socket','io','pathlib','threading','importlib','inspect','gc'}
    banned_names={'open','getattr','type','eval','exec'}
    fails=[]
    for node in ast.walk(tree):
        names=[]
        if isinstance(node,ast.Import):
            names=[a.name for a in node.names]
        elif isinstance(node,ast.ImportFrom):
            names=[node.module or '']
            if node.module=='simulator.strategy' and any(a.name!='BaseStrategy' for a in node.names):
                fails.append('Nonpublic simulator.strategy import')
        for name in names:
            if name.split('.')[0] in banned_modules:
                fails.append('Banned import: '+name)
            if name.startswith('simulator') and name not in ('simulator.models','simulator.strategy'):
                fails.append('Nonpublic simulator import: '+name)
            if name!='__future__' and any(p.startswith('_') for p in name.split('.')):
                fails.append('Private module: '+name)
        if isinstance(node,ast.Name) and node.id in banned_names:
            fails.append('Banned name: '+node.id)
        if isinstance(node,ast.Attribute):
            if node.attr=='format' or (node.attr.startswith('__') and node.attr.endswith('__') and node.attr!='__init__'):
                fails.append('Banned attribute: '+node.attr)
    return fails,[]


def render(source, overrides):
    lines=source.splitlines(keepends=True)
    found=set()
    for node in ast.parse(source).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            key=node.targets[0].id
            if key in overrides:
                assert node.lineno==node.end_lineno
                lines[node.lineno-1]=key+' = '+repr(overrides[key])+'\n'
                found.add(key)
    assert found==set(overrides),set(overrides)-found
    return ''.join(lines)


def main():
    exported=[]
    for case,filename in [('team_F2','team_f2_v2.py'),('team_F2_cap80','team_f2_cap80_v2.py'),
                           ('ridge_maker','ridge_maker_v2.py')]:
        result=json.loads((OUT/(case+'.json')).read_text())
        source_path=Path(result['source'])
        if not source_path.exists() or hashlib.sha256(source_path.read_bytes()).hexdigest()!=result['source_sha256']:
            choices=[ROOT/'research/reference_strategies'/source_path.name,ROOT/'strategies'/source_path.name]
            source_path=next(p for p in choices if p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==result['source_sha256'])
        source=source_path.read_text(encoding='utf-8')
        rendered=render(source,result['params'])
        header='# Local export of '+case+'; tested on sample_v2.csv.\n'
        header+='# Original source SHA256: '+result['source_sha256']+'\n'
        if case.startswith('team'):
            header+='# Based on jakub-kucera/qminers-arena-hachathon at 6ca459e966bb1f9e767258ef5ae0ef0bce979c3f.\n'
        path=ROOT/'strategies'/filename
        path.write_text(header+rendered,encoding='utf-8')
        tree=ast.parse(path.read_text(encoding='utf-8'))
        compile(tree,str(path),'exec')
        subclasses=[n.name for n in tree.body if isinstance(n,ast.ClassDef) and any(isinstance(b,ast.Name) and b.id=='BaseStrategy' for b in n.bases)]
        assert len(subclasses)==1
        assert path.stat().st_size<=1048576
        fails,warns=source_check(tree)
        assert not fails,fails
        load_bot(path,{})
        exported.append(dict(case=case,file=str(path),bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),subclasses=subclasses,
            local_static_fails=fails,local_static_warnings=warns,
            expected_pnl=result['result']['pnl']))
    refs=ROOT/'research/reference_strategies'
    refs.mkdir(exist_ok=True)
    for rel in ['candidates/r0_F2_maker_v2.py','candidates/r0_M2_runner_safe.py','families/protected_maker.py']:
        if not (refs/Path(rel).name).exists() and (TEAM/'python/bots/qminers'/rel).exists():
            shutil.copy2(TEAM/'python/bots/qminers'/rel,refs/Path(rel).name)
    (refs/'SOURCE.txt').write_text('Local research snapshots from the authorized team repository\nhttps://github.com/jakub-kucera/qminers-arena-hachathon\nCommit 6ca459e966bb1f9e767258ef5ae0ef0bce979c3f\nThese files have not been published or pushed by this research task.\n',encoding='utf-8')
    dump(OUT/'exports.json',exported)
    print(json.dumps(exported,indent=2))


if __name__=='__main__':
    main()
