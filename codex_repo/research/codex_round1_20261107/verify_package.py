"""Verify the published archive without loading market data or rerunning trials."""
import ast
import hashlib
import json
from pathlib import Path


def main():
    root=Path(__file__).resolve().parent
    manifest=json.loads((root/'MANIFEST.json').read_text(encoding='utf-8'))
    python_count=0
    for item in manifest['files']:
        path=root/item['path']
        assert path.is_file(),f'Missing artifact: {item["path"]}'
        raw=path.read_bytes()
        assert len(raw)==item['bytes'],f'Size mismatch: {item["path"]}'
        assert hashlib.sha256(raw).hexdigest()==item['sha256'],f'Hash mismatch: {item["path"]}'
        if path.suffix=='.py':
            compile(raw,str(path),'exec')
            python_count+=1
        elif path.suffix=='.json':
            json.loads(raw)
    strategy=root/manifest['selected_strategy']
    assert hashlib.sha256(strategy.read_bytes()).hexdigest()==manifest['selected_sha256']
    assert strategy.stat().st_size<1024**2
    tree=ast.parse(strategy.read_bytes())
    assert len([n for n in tree.body if isinstance(n,ast.ClassDef)])==1
    assert not list(root.rglob('*.npz')),'Replay arrays should remain untracked.'
    print(json.dumps(dict(verified_files=len(manifest['files']),compiled_python_files=python_count,
        strategy_sha256=manifest['selected_sha256'],strategy_bytes=strategy.stat().st_size),indent=2))


if __name__=='__main__':main()
