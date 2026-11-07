"""IDEAS.md's index (experiments.ideas_index) matches the rows, and the parser keeps escaped pipes and
five-cell rows apart."""

import textwrap
from pathlib import Path

from experiments import ideas_index

ROOT = Path(__file__).parents[2]


def test_the_committed_index_is_current():
    text = (ROOT / "IDEAS.md").read_text()
    assert ideas_index.render(text) == text, "uv run python -m experiments.ideas_index"


def test_rows_with_escaped_pipes_and_five_cells():
    text = textwrap.dedent("""\
        # Ideas

        One line.

        Some text.

        ## Tested on Prosperity data

        | Idea | Result | Verdict | Re-test |
        |---|---|---|---|
        | **A \\| B** (more) | 1,000 | `kept`: yes | On every round; then more |
        | **Five cells** | x | y | `dropped here` | If shared. Then more |

        ## Not yet tested

        | Idea | Where | Test |
        |---|---|---|
        | Untested one | here | later |
    """)
    rendered = ideas_index.render(text)
    lines = rendered.splitlines()
    assert ideas_index.render(rendered) == rendered  # stable
    index = [line for line in lines if line.startswith("- L")]
    assert index[0].endswith("**A \\| B** — `kept` — On every round") and "**Five cells** — `dropped here` — If shared" in index[1]
    for line in index:
        number = int(line[3:].split(" ", 1)[0])
        assert lines[number - 1].startswith("| ")  # each points at its row
    assert ideas_index.strip(rendered) == text.splitlines()
