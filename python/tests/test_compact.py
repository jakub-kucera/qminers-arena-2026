import ast
from pathlib import Path

import pytest

from arena import compact, sim
from arena.engine import run_day
from arena.formats import FORMATS

BOTS = Path(__file__).parents[1] / "bots"


@pytest.mark.parametrize("name", ["template.py", "probe.py", "drill/template.py"])
def test_a_compact_copy_is_the_same_code_without_comments_or_docstrings(name):
    source = (BOTS / name).read_text()
    out = compact.compact(source, name)
    assert len(out) < len(source) and out.startswith("# A compact copy of")
    assert '"""' not in out and "\n#" not in out  # the header is the one comment left
    assert ast.dump(ast.parse(out)) == ast.dump(compact._without_docstrings(ast.parse(source)))


def test_the_compact_template_trades_exactly_as_the_original(tmp_path):
    copy = tmp_path / "compact_template.py"
    assert compact.main([str(BOTS / "template.py"), str(copy)]) == 0
    fmt = FORMATS["prosperity"]
    for seed in (0, 1):
        day = sim.run(sim.preset_market(ticks=1500), seed).day
        original = run_day(day, fmt.load_bot(BOTS / "template.py", {}, strict=True))
        compacted = run_day(day, fmt.load_bot(copy, {}, strict=True))
        assert original.fills and compacted.fills == original.fills and compacted.pnl == original.pnl


def test_compact_wont_overwrite_the_original(tmp_path):
    bot = tmp_path / "bot.py"
    bot.write_text('"""doc"""\nx = 1  # one\n')
    with pytest.raises(SystemExit):
        compact.main([str(bot), str(bot)])
    assert compact.compact(bot.read_text(), "bot.py").splitlines()[1:] == ["x = 1"]
    assert compact.compact('def f():\n    """only a docstring"""\n', "f.py").splitlines()[1:] == ["def f():", "    pass"]
