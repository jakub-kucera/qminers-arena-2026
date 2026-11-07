"""Loads a single-file bot as a fresh module, the way a competition would run it."""

from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path
from types import ModuleType


class OverrideError(Exception):
    """A --set override doesn't match the bot."""


class BotFile:
    """A bot source file that can be loaded as a fresh module any number of times.

    provided_modules are made importable under the given names first (e.g. Prosperity's
    `datamodel`). In strict mode, a module-level STRICT flag is set to True so the bot raises
    errors instead of swallowing them. overrides set bot globals after loading
    (see parse_override).
    """

    def __init__(
        self,
        path: Path,
        provided_modules: dict[str, ModuleType],
        overrides: dict[str, object] | None = None,
        strict: bool = True,
    ):
        self.path = Path(path)
        self.provided_modules = provided_modules
        self.overrides = overrides or {}
        self.strict = strict
        self._code = compile(self.path.read_text(encoding="utf-8"), str(self.path), "exec")

    def load(self, overrides: dict[str, object] | None = None) -> ModuleType:
        """A fresh module, with `overrides` instead of the file's own when given."""
        sys.modules.update(self.provided_modules)
        name = f"arena_bot_{self.path.stem}"
        module = ModuleType(name)
        module.__file__ = str(self.path)
        # Registered before running so dataclasses and pickling inside the bot can find it.
        sys.modules[name] = module
        exec(self._code, module.__dict__)
        if self.strict and hasattr(module, "STRICT"):
            module.STRICT = True
        for target, value in (self.overrides if overrides is None else overrides).items():
            _apply_override(module, target, value)
        return module


def parse_override(text: str) -> tuple[str, object]:
    """Parses `PATH=VALUE`, e.g. `PARAMS.KELP.make_edge=2`.

    PATH is a bot global followed by dict keys. VALUE is a Python literal or a bare word (see
    parse_value).
    """
    target, sep, raw = text.partition("=")
    if not sep or not target.strip():
        raise ValueError(f"expected PATH=VALUE, got {text!r}")
    return target.strip(), parse_value(raw)


def parse_value(raw: str) -> object:
    """A Python literal, or a bare word such as `wall_mid`, taken as a string.

    Anything else is an error, so a dict with an expression in it (`10**6`) fails here instead of
    reaching the bot as a string.
    """
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        word = raw.strip()
        if word and all(c.isalnum() or c in "_-." for c in word):
            return word
        raise ValueError(f"{raw!r} is not a Python literal or a bare word (write 1000000, not 10**6)") from None


def _apply_override(module: ModuleType, target: str, value: object) -> None:
    name, *keys = target.split(".")
    value = copy.deepcopy(value)  # a dict value is shared by every load: a deeper override mustn't change it
    if not hasattr(module, name):
        raise OverrideError(f"--set {target}: the bot has no global named {name!r}")
    if not keys:
        setattr(module, name, value)
        return
    container, path = getattr(module, name), name
    for depth, key in enumerate(keys):
        if not isinstance(container, dict):
            raise OverrideError(f"--set {target}: {path} is not a dict (it's a {type(container).__name__})")
        if depth == len(keys) - 1:
            container[key] = value
        elif key not in container:
            raise OverrideError(f"--set {target}: {key!r} not found")
        else:
            container, path = container[key], f"{path}.{key}"
