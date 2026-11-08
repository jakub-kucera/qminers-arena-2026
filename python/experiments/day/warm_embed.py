"""The ridge's warm start (R4-W1) embedded in a bot file: reads a stats file the Rust ridge_maker wrote (env var
RIDGE_DUMP) and writes a copy of BOT.py with model 0's statistics as module constants (WARM_MASS, WARM_XX, WARM_XY)
and PRIOR_MASS, between BOT.py's `# WARM START BEGIN` / `# WARM START END` lines
(python/bots/qminers/candidates/r4_W1_warm.py has them). The numbers keep the file's text (Rust's shortest round-trip
repr of each f64), so the bot reads the values ridge_maker's RIDGE_WARM reads, and the bot scales them as load_warm
does: X'X and X'y times PRIOR_MASS / WARM_MASS, the mass PRIOR_MASS, the label count MIN_LABELS (it fits on its first
book). Standard library only.

    uv run python -m experiments.day.warm_embed STATS.txt BOT.py OUT.py --prior-mass 1000

Round 4: once the round's public tape is saved (F5's line from
`uv run python -c "import sys; sys.path.insert(0,'python'); from experiments.day.family_rust import F5; print(F5)"`):

    RIDGE_DUMP=data/arena/round4/r4_stats.txt uv run python -m arena.qsim_rust ridge_maker data/arena/round4/round4_public.csv <F5 line> --threads 1
    uv run python -m experiments.day.warm_embed data/arena/round4/r4_stats.txt python/bots/qminers/candidates/r4_W1_warm.py OUT.py --prior-mass 1000

and the Rust twin of OUT.py on any tape: `RIDGE_WARM=data/arena/round4/r4_stats.txt uv run python -m arena.qsim_rust
ridge_maker TAPE <F5 line> --set PRIOR_MASS=1000 --threads 1` (the same PnL to the unit; IDEAS.md, "R4-W1").

The stats file, per model with labels: `M <index> <n> <mass> <labels>`, n rows of X'X, one row of X'y.
"""

import argparse
import ast
import math
import re
import sys
from pathlib import Path

BEGIN, END = "# WARM START BEGIN\n", "# WARM START END\n"
LITERAL = re.compile(r"-?(\d+\.\d*|\d+)(e[-+]?\d+)?\Z")  # a float Rust's {:?} writes, also a Python literal


def number(token: str) -> str:
    """The token itself, once it is a finite float literal Python reads to the same value."""
    if not LITERAL.match(token) or not math.isfinite(float(token)):
        raise ValueError(f"not a finite float literal: {token!r}")
    return token


def read_stats(path: Path) -> dict[int, dict]:
    """Every model in a RIDGE_DUMP file, by index, as text tokens: n, mass, labels, xx (n x n), xy (n)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    models, k = {}, 0
    while k < len(lines):
        if not lines[k].strip():
            k += 1
            continue
        head = lines[k].split()
        if head[0] != "M" or len(head) != 5:
            raise ValueError(f"{path}:{k + 1}: expected 'M index n mass labels', got {lines[k]!r}")
        index, n = int(head[1]), int(head[2])
        rows = [[number(t) for t in lines[k + 1 + r].split()] for r in range(n + 1)]
        if any(len(row) != n for row in rows):
            raise ValueError(f"{path}: model {index}: rows of {n} numbers expected")
        models[index] = {"n": n, "mass": number(head[3]), "labels": int(head[4]), "xx": rows[:n], "xy": rows[n]}
        k += n + 2
    return models


def block(model: dict, prior_mass: float, source: str, index: int) -> str:
    rows = "".join(f"    ({', '.join(row)},),\n" for row in model["xx"])
    return (f"# from {source}: model {index}, n {model['n']}, mass {model['mass']}, labels {model['labels']}\n"
            f"PRIOR_MASS = {prior_mass!r}\n"
            f"WARM_MASS = {model['mass']}\n"
            f"WARM_XX = (\n{rows})\n"
            f"WARM_XY = ({', '.join(model['xy'])},)\n")


def embed(source: str, text: str) -> str:
    start, stop = source.find(BEGIN), source.find(END)
    if start < 0 or stop < start:
        raise ValueError(f"the bot has no '{BEGIN.strip()}' ... '{END.strip()}' block")
    return source[:start + len(BEGIN)] + text + source[stop:]


def check(out: str, model: dict, prior_mass: float) -> None:
    """The written constants read back to the stats file's values, bit for bit."""
    values = {}
    for node in ast.parse(out).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("PRIOR_MASS", "WARM_MASS", "WARM_XX", "WARM_XY"):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    want = {"PRIOR_MASS": prior_mass, "WARM_MASS": float(model["mass"]),
            "WARM_XX": tuple(tuple(float(t) for t in row) for row in model["xx"]),
            "WARM_XY": tuple(float(t) for t in model["xy"])}
    for name, value in want.items():
        if name not in values or repr(values[name]) != repr(value):
            raise ValueError(f"{name} does not read back to the stats file's values")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stats", type=Path, help="a RIDGE_DUMP file from the Rust ridge_maker")
    parser.add_argument("bot", type=Path, help="a bot with the WARM START block (r4_W1_warm.py)")
    parser.add_argument("out", type=Path, help="the copy to write")
    parser.add_argument("--prior-mass", type=float, required=True, help="the labels the saved statistics count as (0: off)")
    parser.add_argument("--model", type=int, default=0, help="the model index in the stats file (default 0, the first ridge)")
    args = parser.parse_args(argv)
    models = read_stats(args.stats)
    if args.model not in models:
        parser.error(f"{args.stats} has no model {args.model} (has {sorted(models)})")
    model = models[args.model]
    out = embed(args.bot.read_text(encoding="utf-8"), block(model, args.prior_mass, args.stats.name, args.model))
    check(out, model, args.prior_mass)
    args.out.write_text(out, encoding="utf-8")
    print(f"{args.out}: model {args.model} (n {model['n']}, mass {model['mass']}, labels {model['labels']}) at PRIOR_MASS "
          f"{args.prior_mass!r}, {len(out.encode()):,} bytes; the bot loads it only if its FEATURE_COUNT is {model['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
