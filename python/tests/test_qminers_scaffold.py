"""The day's scaffold: python/arena/formats/qminers.py (registered, source checks only) and
python/bots/qminers/template.py with probe.py, the default bot for --format qminers."""

from arena.cli import TEMPLATES


def test_the_days_template_is_the_default_bot_for_its_format():
    assert TEMPLATES["qminers"].is_file() and (TEMPLATES["qminers"].parent / "probe.py").is_file()
