"""The Arena's format, registered as `--format qminers`: the source checks only, no loader.

The day's bot, python/bots/qminers/template.py (`ArenaBot`, a BaseStrategy subclass), and every file in
python/bots/qminers/ run on the organisers' own simulator (`uv run exchange-simulator`; grids with arena.qgrid
and arena.qsim_rust), so this plug-in serves arena.validate's source checks alone: check_source (one
BaseStrategy subclass), PROVIDED_MODULES (the import check) and SANDBOX (validate.sandbox_bans). REPLAY = False
makes `arena.validate BOT all --format qminers` stop after them (no --data); the loader hooks the FORMATS
registry names raise. Its snapshots-loader half (a copy of snapshots.py, unused since 7 Nov) is in the history.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROVIDED_MODULES = {"simulator", "numpy", "pandas", "scipy", "sklearn"}  # what a submission may import besides the standard library (STARTER.md)
REPLAY = False  # no loader here: arena.validate runs the source checks and stops (replay: run exchange-simulator)
BASE = "BaseStrategy"  # the class a submission subclasses (simulator.strategy.BaseStrategy)
SANDBOX = {  # what their sandbox rejects before a bot runs (STARTER.md, "Writing a strategy"; the site's info page; arena.validate.sandbox_bans)
    "modules": {"os", "sys", "subprocess", "socket", "io", "pathlib", "threading", "importlib", "inspect", "gc"},
    "private_modules": True,  # a module name starting with an underscore
    "builtins": {"open", "getattr", "type", "eval", "exec"},
    "dunders": True,  # dunder attributes and names
    "str_format": True,
    "no_except_pass": True,  # a warning: their static analysis ran a linter that rejected `except ...: pass` until they turned it off (7 Nov)
    "allow": {"__future__", "__init__"},  # their own examples use `from __future__ import annotations` and `super().__init__()`
    "public": {"simulator.models": "*", "simulator.strategy": {"BaseStrategy"}},  # module: its public names ("*": any without an underscore)
}
NO_LOADER = "the Arena's data and bots run on their simulator: `uv run exchange-simulator` (or arena.qgrid), not --format qminers"


def check_source(tree: ast.Module) -> list[str]:
    """Exactly one top-level class subclassing BaseStrategy (`BaseStrategy` or `x.BaseStrategy`)."""
    found = [node.name for node in tree.body if isinstance(node, ast.ClassDef)
             and any((b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else None) == BASE for b in node.bases)]
    if not found:
        return [f"no top-level class subclassing {BASE}"]
    if len(found) > 1:
        return [f"{len(found)} classes subclass {BASE} ({', '.join(found)}): their loader runs the alphabetically first, {sorted(found)[0]}"]
    return []


def resolve_data_dir(arg: str) -> Path:
    raise ValueError(NO_LOADER)


def load_days(data_dir: Path, specs: list[str]):
    raise ValueError(NO_LOADER)


def load_bot(path: Path, overrides: dict[str, object], strict: bool, fresh_each_tick: bool = False):
    raise ValueError(NO_LOADER)
