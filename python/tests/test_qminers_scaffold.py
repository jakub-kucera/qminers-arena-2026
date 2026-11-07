"""The day's scaffold: python/arena/formats/qminers.py (registered), python/bots/qminers/template.py
and probe.py, prepared before the day. While qminers.SKELETON is set, the template's ADAPTER raises,
so the unwritten copy can never pass arena.validate by accident."""

import pytest

from arena.botfile import BotFile
from arena.cli import TEMPLATES
from arena.formats import qminers

needs_skeleton = pytest.mark.skipif(not qminers.SKELETON, reason="qminers.py is the Arena's format now")


def test_the_days_template_is_the_default_bot_for_its_format():
    assert TEMPLATES["qminers"].is_file() and (TEMPLATES["qminers"].parent / "probe.py").is_file()


@needs_skeleton
def test_the_prepared_template_loads_with_no_products_and_its_adapter_raises():
    module = BotFile(TEMPLATES["qminers"], {}).load()
    assert module.PARAMS == {}
    calls = {"to_ticks": ("api", "X", 1.0), "to_price": ("api", "X", 1), "read_book": ("api", "X"), "params_for": ("api", "X"),
             "read_trades": ("api",), "read_fills": ("api", []), "read_resting": ("api", "X")}
    for name, args in calls.items():
        with pytest.raises(NotImplementedError, match="TODO\\(day\\)"):
            getattr(module, name)(*args)
