"""Standalone inference and replay helpers for the frozen robustness experiment."""
import ast
import json
from pathlib import Path

import numpy as np

import ml_round1_common as previous
import run_study
from export_candidates import render, source_check
from run_study import ROOT, dump

DEST = ROOT / 'research/robust_ml_results'
SOURCES = DEST / 'sources'
PREFIX = ROOT.parents[1] / 'work/ml-round1/round1_first75.csv'
PREVIOUS = ROOT / 'research/ml_round1_results'
HORIZON = .25


def runtime_source():
    source = previous.runtime_source()
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'predict')
    replacement = '''    def component(self, x, numeric, model):
        kind = model['kind']
        if kind == 'linear':
            return model['base'] + sum(a * b for a, b in zip(model['coef'], x))
        if kind == 'logit':
            z = [(b + sum(w * v for w, v in zip(row, x))) / model['temperature']
                 for row, b in zip(model['coef'], model['base'])]
            top = max(z)
            p = [exp(v - top) for v in z]
            return sum(a * b for a, b in zip(p, model['class_values'])) / sum(p)
        value = 0.0
        if kind == 'cat':
            for splits, leaves in model['trees']:
                index = 0
                for level, split in enumerate(splits):
                    if numeric[split[0]] > split[1]:
                        index += 1 << level
                value += leaves[index]
            return model['base'] + model['scale'] * value
        for tree in model['trees']:
            node = 0
            while tree[node][0] >= 0:
                f, threshold, left, right, leaf = tree[node]
                node = left if numeric[f] <= threshold else right
            value += tree[node][4]
        return value / len(model['trees'])

    def predict(self, x):
        numeric = unpack('f' * len(x), pack('f' * len(x), *x))
        values = [self.component(x, numeric, m) for m in ROBUST_MODELS]
        center = sum(w * v for w, v in zip(ROBUST_WEIGHTS, values))
        if ROBUST_GUARD:
            spread = sum(w * (v - center) ** 2 for w, v in zip(ROBUST_WEIGHTS, values)) ** .5
            magnitude = max(0.0, abs(center) - ROBUST_GUARD * spread)
            return magnitude if center >= 0 else -magnitude
        return center

'''
    lines = source.splitlines(keepends=True)
    lines[fn.lineno - 1:fn.end_lineno] = [replacement]
    source = ''.join(lines)
    return source.replace('\n\nclass CompositeStrategy',
        '\nROBUST_MODELS = []\nROBUST_WEIGHTS = []\nROBUST_GUARD = 0.0\n\nclass CompositeStrategy', 1)


def export(name, models, weights=None, guard=0.0):
    SOURCES.mkdir(parents=True, exist_ok=True)
    weights = weights if weights is not None else [1 / len(models)] * len(models)
    assert abs(sum(weights) - 1) < 1e-12 and min(weights) >= 0
    source = render(runtime_source(), dict(previous.EXECUTION, TARGET_ALPHA=40.0,
        EDGE_FLOOR=.15, ML_KIND='robust', ML_HISTORY=True, ROBUST_MODELS=models,
        ROBUST_WEIGHTS=weights, ROBUST_GUARD=guard))
    compile(source, name, 'exec')
    failures, warnings = source_check(ast.parse(source))
    assert not failures, failures
    path = SOURCES / f'{name}.py'
    path.write_text(source, encoding='utf-8')
    assert path.stat().st_size < 1024 ** 2
    return path


def at(curve, seconds):
    i = max(0, np.searchsorted(curve[:, 0], seconds * 1e6, side='right') - 1)
    return float(curve[i, 1])


def enrich(result, directory=DEST):
    if result['data'] != 'round1.csv' and result['data'] != 'round1_first75.csv':
        result.update(validation_blocks=None, validation_pnl=None, training_pnl=None,
            tail_pnl=None, outside_fit_pnl=None)
        return result
    curve = np.load(directory / f"{result['name']}_trace.npz")['curve']
    prefix = curve[-1, 0] <= 9000e6
    end = float(result['result']['pnl']) if prefix else at(curve, 9000)
    points = [at(curve, s) for s in (6000, 7000, 8000)] + [end]
    result['validation_blocks'] = np.diff(points).tolist()
    result['validation_pnl'] = end - points[0]
    result['training_pnl'] = points[0]
    result['tail_pnl'] = None if prefix else float(result['result']['pnl']) - end
    result['outside_fit_pnl'] = float(result['result']['pnl']) - points[0]
    return result


def run_case(case):
    run_study.OUT = DEST
    result = enrich(run_study.run_case(case))
    dump(DEST / f'{case[0]}.json', result)
    return result


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))
