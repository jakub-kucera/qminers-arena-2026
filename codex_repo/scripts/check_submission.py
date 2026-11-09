"""Conservative local checks for documented submission restrictions.

This checks the subset used by our strategies, not the unavailable server
checker. Usage: python scripts/check_submission.py strategies/arena_strategy.py
"""

import argparse
import ast
from pathlib import Path


ALLOWED_IMPORTS = {
    '__future__', 'math', 'collections', 'statistics', 'bisect',
    'heapq', 'itertools', 'functools', 'typing', 'enum', 'dataclasses',
    'numpy', 'pandas', 'scipy', 'sklearn', 'simulator.models', 'simulator.strategy',
}
FORBIDDEN_NAMES = {
    'open', 'eval', 'exec', 'getattr', 'setattr', 'delattr', 'type',
    'globals', 'locals', 'vars', 'dir', 'compile', '__import__', 'input',
    'breakpoint', 'help',
}


def check(path):
    tree = ast.parse(Path(path).read_text(), filename=str(path))
    issues = []
    strategies = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or '']
            for module in modules:
                root = module.split('.')[0]
                if module not in ALLOWED_IMPORTS and root not in {'numpy', 'pandas', 'scipy', 'sklearn'}:
                    issues.append((node.lineno, f'import outside local allowlist: {module}'))
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    issues.append((node.lineno, 'relative import'))
                if node.module == 'simulator.strategy' and any(a.name != 'BaseStrategy' for a in node.names):
                    issues.append((node.lineno, 'only BaseStrategy may be imported from simulator.strategy'))
            if any(a.name == '*' for a in node.names):
                issues.append((node.lineno, 'wildcard import'))
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            issues.append((node.lineno, f'forbidden name: {node.id}'))
        if isinstance(node, ast.Attribute):
            if (node.attr.startswith('__') and node.attr != '__init__') or node.attr == 'format':
                issues.append((node.lineno, f'forbidden attribute: {node.attr}'))
        if isinstance(node, ast.ClassDef) and any(isinstance(b, ast.Name) and b.id == 'BaseStrategy' for b in node.bases):
            strategies.append(node)
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == '__init__':
                    args = child.args
                    if len(args.posonlyargs + args.args) != 1 or args.kwonlyargs or args.vararg or args.kwarg:
                        issues.append((child.lineno, 'constructor must take only self'))
    if len(strategies) != 1:
        issues.append((1, 'expected exactly one direct BaseStrategy subclass'))
    return sorted(set(issues))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('strategy', type=Path)
    args = parser.parse_args()
    issues = check(args.strategy)
    for line, message in issues:
        print(f'{args.strategy}:{line}: {message}')
    if issues:
        raise SystemExit(1)
    print(f'{args.strategy}: local submission checks passed (server checker not included)')


if __name__ == '__main__':
    main()
