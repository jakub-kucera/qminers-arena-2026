"""The documents' cross-references: the front pages' relative links and doc paths, every `experiments.<name>` they
and the round tools name, the experiments README's tables, and the day's runbook against ON_THE_DAY's sections.

The day's playbook in docs/day/ and the rounds' handover notes are kept as they were used on 7-8 Nov, so their links
point at the combined repository of the time and are not checked here."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
FRONT = ["README.md", "RESULTS.md", "IDEAS.md", "CLAUDE.md", "docs/postmortem.md", "docs/tools.md", "docs/day/README.md",
         "python/experiments/README.md", "rust/README.md"]


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_every_runbook_section_name_is_in_on_the_day():
    on_the_day = text("docs/day/ON_THE_DAY.md")
    titles = re.findall(r"^#+ (.+)$", on_the_day, re.M) + re.findall(r"\*\*(.+?)\*\*", on_the_day)
    names = [" ".join(name.split()) for group in re.findall(r"\[(\"[^\]]+)\]", text("docs/day/RUNBOOK.md")) for name in re.findall(r'"([^"]+)"', group)]
    assert names
    missing = [name for name in names if not any(title.startswith(name.rstrip("?")) for title in titles)]
    assert not missing, f"RUNBOOK names sections ON_THE_DAY.md doesn't have: {missing}"


@pytest.mark.parametrize("name", FRONT)
def test_relative_links_and_doc_paths_exist(name):
    body, base = text(name), (ROOT / name).parent
    links = [link.split("#")[0] for link in re.findall(r"\]\(([^)\s]+)\)", body) if not re.match(r"(https?:|mailto:|#)", link)]
    paths = re.findall(r"(?<![\w/.])(docs/[\w./-]+\.md)", body)
    missing = [link for link in links if link and not (base / link).exists()] + [p for p in paths if not (ROOT / p).exists()]
    assert not missing, f"{name} points at files that don't exist: {missing}"


def _mentions() -> list[tuple[str, str]]:
    files = [ROOT / name for name in FRONT] + sorted((ROOT / "python" / "experiments" / "day").glob("*.py"))
    index = re.compile(r"<!-- ideas-index:start -->.*?<!-- ideas-index:end -->", re.S)  # its lines are cut short
    return [(str(f.relative_to(ROOT)), m) for f in files
            for m in re.findall(r"\bexperiments\.([a-z_]+(?:\.[a-z_]+)?)\b", index.sub("", f.read_text(encoding="utf-8")))]


def test_every_experiment_named_exists():
    base = ROOT / "python" / "experiments"

    def exists(name: str) -> bool:  # experiments.<module>[.attribute] or experiments.<folder>.<module>
        first, _, rest = name.partition(".")
        return (base / f"{first}.py").is_file() or (base / first).is_dir() and (not rest or (base / first / f"{rest}.py").is_file())

    missing = sorted({(f, m) for f, m in _mentions() if m != "py" and not exists(m)})
    assert not missing, f"experiments that don't exist here: {missing[:20]}"


def test_the_experiments_readme_lists_every_module_once():
    readme = text("python/experiments/README.md")
    base = ROOT / "python" / "experiments"
    modules = [p.stem for folder in (base, base / "day", base / "study", base / "prosperity") for p in folder.glob("*.py")]
    rows = re.findall(r"^\| `([a-z_0-9]+)/?` \|", readme, re.M)
    assert sorted(modules) == sorted(rows), "python/experiments/README.md's tables"
