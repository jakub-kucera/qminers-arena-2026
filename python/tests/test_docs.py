"""The docs' cross-references: what a fresh session follows on the day must lead somewhere. RUNBOOK's
bracketed section names, the relative links and doc paths, every `experiments.<name>` the docs and
usage strings name, the experiments README's tables, and the sizes that keep the day's files a read or two."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
DAY_DOCS = ["CLAUDE.md", "RUNBOOK.md", "ON_THE_DAY.md", "KICKOFF_PROMPT.md", "README.md", "ARCHITECTURE.md", "IDEAS.md", "TODO.md"]
DOCS = DAY_DOCS + sorted(str(p.relative_to(ROOT)) for p in (ROOT / "docs").glob("*.md"))
SIZES = {"CLAUDE.md": 10_240, "RUNBOOK.md": 8_192, "ON_THE_DAY.md": 105_000}
# ON_THE_DAY is read by section (RUNBOOK names them; the kickoff says so), but stays within two Reads: a Read stops at
# 25,000 tokens and this prose runs about 2.2 bytes a token (measured 2026-10-28: 57,116 bytes to the cut at line 263),
# so about 110 KB in two. It is 80 KB before the day; the cap leaves about 25 KB for the answers written in under its
# items over four rounds (the audit's round 8, R6), longer reasoning going to the round's HANDOVER.md.


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_every_runbook_section_name_is_in_on_the_day():
    on_the_day = text("ON_THE_DAY.md")
    titles = re.findall(r"^#+ (.+)$", on_the_day, re.M) + re.findall(r"\*\*(.+?)\*\*", on_the_day)
    names = [" ".join(name.split()) for group in re.findall(r"\[(\"[^\]]+)\]", text("RUNBOOK.md")) for name in re.findall(r'"([^"]+)"', group)]
    assert names
    missing = [name for name in names if not any(title.startswith(name.rstrip("?")) for title in titles)]
    assert not missing, f"RUNBOOK names sections ON_THE_DAY.md doesn't have: {missing}"


@pytest.mark.parametrize("name", DOCS)
def test_relative_links_and_doc_paths_exist(name):
    body, base = text(name), (ROOT / name).parent
    links = [link.split("#")[0] for link in re.findall(r"\]\(([^)\s]+)\)", body) if not re.match(r"(https?:|mailto:|#)", link)]
    paths = re.findall(r"(?<![\w/.])(docs/[\w.-]+\.md)", body)
    missing = [link for link in links if link and not (base / link).exists()] + [p for p in paths if not (ROOT / p).exists()]
    assert not missing, f"{name} points at files that don't exist: {missing}"
    moved = re.findall(r"(?<![\w/.])(?:TODO_DONE|MANUAL_TODO)\.md", body)
    assert name.startswith("docs/") or not moved, f"{name}: TODO_DONE.md and MANUAL_TODO.md live in docs/"


def _mentions() -> list[tuple[str, str]]:
    files = [ROOT / name for name in DOCS] + [ROOT / "rust" / "README.md", ROOT / "python" / "experiments" / "README.md"]
    files += sorted((ROOT / "python").rglob("*.py")) + sorted((ROOT / "references" / "wiki").rglob("*.md"))
    skip = ("mock_round/results", "mock_round/round2/results", "mock_round/round3/results", "wiki/log.md", "/zoo/chatgpt/", "/zoo/claude/", "/zoo/gemini/", "/zoo/other/")
    index = re.compile(r"<!-- ideas-index:start -->.*?<!-- ideas-index:end -->", re.S)  # its lines are cut short
    return [(str(f.relative_to(ROOT)), m) for f in files if not any(s in str(f) for s in skip)
            for m in re.findall(r"\bexperiments\.([a-z_]+(?:\.[a-z_]+)?)\b", index.sub("", f.read_text(encoding="utf-8")))]


def test_every_experiment_named_exists():
    base = ROOT / "python" / "experiments"
    def exists(name: str) -> bool:  # experiments.<module>[.attribute] or experiments.<folder>.<module>
        first, _, rest = name.partition(".")
        return (base / f"{first}.py").is_file() or (base / first).is_dir() and (not rest or (base / first / f"{rest}.py").is_file())

    missing = sorted({(f, m) for f, m in _mentions() if m != "py" and not exists(m)})  # "experiments.py" is a file name
    assert not missing, f"experiments that don't exist (moved to day/ or study/?): {missing[:20]}"


def test_the_experiments_readme_lists_every_module_once():
    readme = text("python/experiments/README.md")
    base = ROOT / "python" / "experiments"
    modules = [p.stem for folder in (base, base / "day", base / "study") for p in folder.glob("*.py")]
    rows = re.findall(r"^\| `([a-z_0-9]+)/?` \|", readme, re.M)
    assert sorted(m for m in modules) == sorted(r for r in rows if r != "mock_round"), "python/experiments/README.md's tables"


@pytest.mark.parametrize("name,limit", SIZES.items())
def test_the_days_files_stay_small(name, limit):
    assert len(text(name).encode()) <= limit, f"{name} grew past {limit:,} bytes: move evidence to its IDEAS.md row"
