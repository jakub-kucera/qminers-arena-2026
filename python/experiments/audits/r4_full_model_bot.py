"""Replay-only F5 wrapper for r4_full_model_probe; not an upload candidate.

R4_BASE names an unchanged F5 source file. R4_MODEL names a frozen model fitted
strictly before its start_us. Only the current prediction is replaced; execution,
features, matured labels and the online learning state remain F5's code.
"""

import ast
import hashlib
import json
import os
from pathlib import Path
import types

from experiments.audits.r4_full_model_probe import Predictor


_path = Path(os.environ["R4_BASE"])
_model = json.loads(Path(os.environ["R4_MODEL"]).read_text())
assert hashlib.sha256(_path.read_bytes()).hexdigest() == _model["base_sha256"]
_tree = ast.parse(_path.read_text())
_changed = 0
for _node in ast.walk(_tree):
    if (isinstance(_node, ast.Assign) and len(_node.targets) == 1
            and isinstance(_node.targets[0], ast.Name) and _node.targets[0].id == "prediction"
            and isinstance(_node.value, ast.Call) and isinstance(_node.value.func, ast.Name)
            and _node.value.func.id == "max"):
        _node.value = ast.Call(func=ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()),
            attr="_r4_prediction", ctx=ast.Load()), args=[ast.Name(id="now", ctx=ast.Load()),
            ast.Name(id="features", ctx=ast.Load()), _node.value], keywords=[])
        _changed += 1
assert _changed == 1, "F5 prediction site changed; re-audit before running"
_base = types.ModuleType("r4_full_model_base")
exec(compile(ast.fix_missing_locations(_tree), str(_path), "exec"), _base.__dict__)


class AFullModelProbe(_base.PassiveStrategy):
    def __init__(self):
        super().__init__()
        assert self.FEATURE_COUNT == _model["feature_count"]
        self._r4_model = Predictor(_model)

    def _r4_prediction(self, now, features, online):
        if now < _model["start_us"]:
            return online
        frozen = max(-2.0, min(2.0, self._r4_model.one(features)))
        weight = _model["blend"]
        return weight*frozen + (1-weight)*online
