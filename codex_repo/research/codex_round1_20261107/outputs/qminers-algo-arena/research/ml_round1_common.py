"""Causal feature construction and standalone model export for round-one ML."""
import ast
import hashlib
import json
from pathlib import Path

import numpy as np
from export_candidates import render, source_check
from run_study import ROOT, dump

DEST = ROOT / 'research/ml_round1_results'
SOURCES = DEST / 'sources'
WORK = ROOT.parents[1] / 'work/ml-round1'
LAGS = (250_000, 1_000_000, 5_000_000)
HISTORY_COLUMNS = (1, 2, 3, 8)
FIT_END, MODEL_VALID_END, POLICY_END = 4800.0, 6000.0, 9000.0
EXECUTION = dict(CAP=100, QUOTE=200, SKEW=100, SESSION_S=12000.0,
    WIND_DOWN_S=30, MODEL='learned', TOPUP=1, MIN_REFILL=10, MAX_QUOTES=200,
    INVENTORY_SIZE=0, STEP_INSIDE=0, DEPLETE_LOTS=20, BACK_POS=95,
    SIZE_ALPHA=0.0, REGIME_GUARD=0, INSIDE_MODE='off')


def load_features():
    f = np.load(ROOT / 'research/round1_results/record_trace.npz')['features']
    f = f[f[:, 0] <= POLICY_END * 1e6]
    t, current = f[:, 0], f[:, 5:]
    mid = (f[:, 1] + f[:, 2]) / 2
    parts = [current]
    for lag in LAGS:
        index = np.maximum(0, np.searchsorted(t, t - lag, side='right') - 1)
        parts += [current[:, HISTORY_COLUMNS] - current[index][:, HISTORY_COLUMNS],
                  (mid - mid[index])[:, None]]
    history = np.column_stack(parts)
    assert current.shape[1] == 9 and history.shape[1] == 24
    return f, current, history


def future_change(f, horizon_s):
    t = f[:, 0]
    mid = (f[:, 1] + f[:, 2]) / 2
    index = np.minimum(len(t) - 1, np.searchsorted(t, t + horizon_s * 1e6, side='right') - 1)
    return mid[index] - mid


def runtime_source():
    source = (ROOT / 'strategies/composite_room_template.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    strategy = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    predict = next(n for n in strategy.body if isinstance(n, ast.FunctionDef) and n.name == 'predict')
    lines = source.splitlines(keepends=True)
    replacement = '''    def expand_features(self, now, mid, current):
        if not ML_HISTORY:
            return current
        self.feature_history.append((now, mid, current[:]))
        cutoff = now - 5_000_000
        while len(self.feature_history) > 1 and self.feature_history[1][0] <= cutoff:
            self.feature_history.pop(0)
        result = current[:]
        for lag in (250_000, 1_000_000, 5_000_000):
            chosen = self.feature_history[0]
            for row in self.feature_history:
                if row[0] > now - lag:
                    break
                chosen = row
            for index in (1, 2, 3, 8):
                result.append(current[index] - chosen[2][index])
            result.append(mid - chosen[1])
        return result

    def predict(self, x):
        if ML_KIND == 'none':
            return 0.0
        if ML_KIND == 'microprice':
            return x[8]
        if ML_KIND == 'ridge':
            return ML_BASE + sum(a * b for a, b in zip(ML_COEF, x))
        if ML_KIND == 'mlp':
            value = [(a - b) / c for a, b, c in zip(x, ML_MEAN, ML_STD)]
            for layer in range(len(ML_W)):
                value = [bias + sum(w * v for w, v in zip(weights, value))
                         for weights, bias in zip(ML_W[layer], ML_B[layer])]
                if layer < len(ML_W) - 1:
                    value = [max(0.0, v) for v in value]
            return value[0]
        form = 'f' * len(x)
        numeric = unpack(form, pack(form, *x))
        value = 0.0
        for splits, leaves in ML_TREES:
            index = 0
            for level, split in enumerate(splits):
                if numeric[split[0]] > split[1]:
                    index += 1 << level
            value += leaves[index]
        return ML_BASE + ML_CB_SCALE * value

'''
    lines[predict.lineno - 1:predict.end_lineno] = [replacement]
    source = ''.join(lines)
    source = source.replace('from math import exp, log1p\n', 'from math import exp, log1p\nfrom struct import pack, unpack\n', 1)
    source = source.replace('        self.alpha = 0.0\n',
        '        self.alpha = 0.0\n        self.feature_history = []\n        self.bid_edge = 0.0\n        self.ask_edge = 0.0\n', 1)
    old = "        self.alpha = self.predict(self.features) if MODEL != 'none' else 0.0\n"
    assert old in source
    source = source.replace(old, '''        values = self.expand_features(now, mid, self.features)
        if ML_KIND == 'fillcat':
            self.bid_edge = self.predict(values + [1.0])
            self.ask_edge = self.predict(values + [-1.0])
            self.alpha = max(-2.0, min(2.0, (self.bid_edge - self.ask_edge) / 2))
        else:
            self.alpha = max(-2.0, min(2.0, self.predict(values)))
''')
    source = source.replace('        if mid - bp + self.alpha < EDGE_FLOOR:',
        "        buy_edge = self.bid_edge + bid - bp if ML_KIND == 'fillcat' else mid - bp + self.alpha\n        if buy_edge < EDGE_FLOOR:")
    source = source.replace('        if ap - mid - self.alpha < EDGE_FLOOR:',
        "        sell_edge = self.ask_edge + ap - ask if ML_KIND == 'fillcat' else ap - mid - self.alpha\n        if sell_edge < EDGE_FLOOR:")
    declarations = "\nML_KIND = 'none'\nML_HISTORY = False\nML_BASE = 0.0\nML_COEF = []\nML_MEAN = []\nML_STD = []\nML_W = []\nML_B = []\nML_TREES = []\nML_CB_SCALE = 1.0\n"
    source = source.replace('\n\nclass CompositeStrategy', declarations + '\n\nclass CompositeStrategy', 1)
    return source


def export(name, parameters, target=40.0, edge=.15):
    SOURCES.mkdir(parents=True, exist_ok=True)
    overrides = dict(EXECUTION, TARGET_ALPHA=target, EDGE_FLOOR=edge, **parameters)
    if parameters['ML_KIND'] == 'none':
        overrides.update(MODEL='none', TARGET_ALPHA=0.0, EDGE_FLOOR=-100.0)
    source = render(runtime_source(), overrides)
    compile(source, name, 'exec')
    fails, warnings = source_check(ast.parse(source))
    assert not fails, fails
    output = SOURCES / f'{name}.py'
    output.write_text(source, encoding='utf-8')
    assert output.stat().st_size < 1024 ** 2
    return output


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
