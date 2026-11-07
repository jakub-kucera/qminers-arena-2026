"""Writes a compact copy of a bot file: the same code, without comments or docstrings.

    uv run python -m arena.compact python/bots/template.py submit/template.py

For an upload over the portal's size cap (arena.validate --max-size; the template's 49 KB come down
to about 26 KB). The copy is the file's syntax tree printed back (ast.unparse) without its
docstrings, so it runs exactly as the original: after writing it, this parses the copy again and
checks that its tree is the original's without the docstrings. Validate the copy, not the original,
before uploading it, and keep the original for editing.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

HEADER = "# A compact copy of {name} (python -m arena.compact): its comments and docstrings removed. Edit the original.\n"


def compact(source: str, name: str) -> str:
    """The source without comments or docstrings, behind a one-line header. Raises ValueError if the
    copy's syntax tree isn't the original's without the docstrings."""
    tree = _without_docstrings(ast.parse(source))
    out = HEADER.format(name=name) + ast.unparse(tree) + "\n"
    if ast.dump(ast.parse(out)) != ast.dump(tree):
        raise ValueError(f"the compact copy of {name} doesn't parse back to the same code")
    return out


def _without_docstrings(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.compact", description="Write a bot file without comments or docstrings.")
    parser.add_argument("bot", type=Path, help="the bot file")
    parser.add_argument("out", type=Path, help="where to write the copy (not the bot file itself)")
    args = parser.parse_args(argv)
    if args.out.resolve() == args.bot.resolve():
        parser.error("write the copy to another file: the original keeps the comments")
    try:
        source = args.bot.read_text(encoding="utf-8")
        out = compact(source, args.bot.name)
    except (OSError, SyntaxError, ValueError) as error:
        parser.error(str(error))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(out, encoding="utf-8")
    print(f"{args.out}: {len(out.encode()):,} bytes, from {len(source.encode()):,} ({args.bot}); the same code, checked")
    from arena.validate import gray_area

    marked = gray_area(ast.parse(source))
    if marked is not None:
        print(f"!!! GRAY AREA BOT: {marked}. Don't upload it without an organiser's yes (arena.validate FAILs it) !!!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
