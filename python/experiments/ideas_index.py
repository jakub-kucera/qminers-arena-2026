"""IDEAS.md's index: one line per row, with its line number, so a session reads the first 150 lines and
then only the rows it needs.

usage (from the repo root):
  uv run python -m experiments.ideas_index            # rewrite the index after editing IDEAS.md
  uv run python -m experiments.ideas_index --check    # exit 1 if it is stale (python/tests/test_ideas_index.py)

The index sits between the two markers below, after the file's title and its one-line description:
for each tested row, `- L<line> **title** — `verdict` — when to re-test it`, then the untested rows'
titles. The verdict is the first of `kept`, `dropped here`, `measured` or `open` the verdict cell names
in backticks (`mixed` if none); the re-test is the last cell, cut at its first sentence or clause.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

IDEAS = Path("IDEAS.md")
START, END = "<!-- ideas-index:start -->", "<!-- ideas-index:end -->"
VERDICTS = ("kept", "dropped here", "measured", "open")
TRIGGER = 110  # characters of the re-test cell kept


def cells(row: str) -> list[str]:
    """A table row's cells, with escaped pipes (\\|) kept inside their cell."""
    parts = re.split(r"(?<!\\)\|", row.strip())
    return [part.strip() for part in parts[1:-1]]


def title(cell: str) -> str:
    match = re.match(r"\*\*(.+?)\*\*", cell)
    return match.group(1) if match else cell


def short(text: str, limit: int = TRIGGER) -> str:
    text = re.sub(r"<br>.*", "", text).strip()
    cut = min((i for i in (text.find("; "), text.find(". ")) if i > 0), default=len(text))
    text = text[:cut].rstrip(".;")
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + " …"  # whole words


def verdict(cell: str) -> str:
    for word in re.findall(r"`([^`]+)`", cell):
        if word in VERDICTS:
            return word
    return "mixed"


def rows(lines: list[str]) -> tuple[list[tuple[int, str, str, str]], list[tuple[int, str]]]:
    """The tested rows as (line number, title, verdict, re-test) and the untested as (line number, title)."""
    tested, untested, section = [], [], None
    for number, line in enumerate(lines, 1):
        if line.startswith("## "):
            section = line[3:].strip()
        elif section == "Tested on Prosperity data" and line.startswith("| **"):
            row = cells(line)
            tested.append((number, title(row[0]), verdict(row[-2]), short(row[-1])))
        elif section == "Not yet tested" and line.startswith("| ") and not line.startswith("| Idea") and not line.startswith("|---"):
            untested.append((number, short(title(cells(line)[0]), 100)))
    return tested, untested


def strip(text: str) -> list[str]:
    """The file without its index block."""
    if START not in text:
        return text.splitlines()
    head, rest = text.split(START, 1)
    return (head.rstrip("\n") + "\n\n" + rest.split(END, 1)[1].lstrip("\n")).splitlines()


def render(text: str) -> str:
    """The file with its index rewritten: the block's own length shifts every row, so it settles in a few passes."""
    body = strip(text)
    at = 3  # after the title, the blank line and the one-line description
    block: list[str] = []
    for _ in range(10):
        offset = len(block) + 1  # the blank line before the block, and the block
        tested, untested = rows(body)
        new = [START, "## Index", "",
               f"Every row below by line (`Read IDEAS.md` at that offset). {len(tested)} tested, {len(untested)} not yet. "
               "Rebuilt by `uv run python -m experiments.ideas_index`.", ""]
        new += [f"- L{n + offset} **{t}** — `{v}` — {r}" for n, t, v, r in tested]
        new += ["", f"### Not yet tested ({len(untested)})", ""]
        new += [f"- L{n + offset} {t}" for n, t in untested]
        new += [END]
        if new == block:
            break
        block = new
    return "\n".join(body[:at] + [""] + block + body[at:]) + "\n"  # body[at] is the blank line after the block


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m experiments.ideas_index")
    parser.add_argument("--check", action="store_true", help="exit 1 if IDEAS.md's index is stale")
    parser.add_argument("--file", type=Path, default=IDEAS)
    args = parser.parse_args(argv)
    text = args.file.read_text()
    new = render(text)
    if args.check:
        if new != text:
            sys.exit(f"{args.file}'s index is stale: uv run python -m experiments.ideas_index")
        return
    args.file.write_text(new)
    print(f"{args.file}: index rewritten")


if __name__ == "__main__":
    main()
