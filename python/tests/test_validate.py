import argparse
import textwrap
from pathlib import Path

import pytest

from arena import validate

TEMPLATE = Path(__file__).parents[1] / "bots" / "template.py"


@pytest.fixture
def check(tmp_path, data_dir, capsys):
    """Runs the validator on a bot body; returns (exit code, output)."""

    def run(body=None, *args):
        path = TEMPLATE
        if body is not None:
            path = tmp_path / "bot.py"
            path.write_text(textwrap.dedent(body))
        code = validate.main([str(path), "1", "--data", str(data_dir), *args])
        return code, capsys.readouterr().out

    return run


def test_template_passes(check):
    code, out = check()
    assert code == 0, out
    assert "FAIL" not in out and "WARN" not in out


def test_exceptions_fail(check):
    code, out = check(
        """
        class Trader:
            def run(self, state):
                raise ZeroDivisionError("oops")
        """
    )
    assert code == 1
    assert "FAIL  4 errors" in out and "ZeroDivisionError: oops" in out


def test_exceptions_from_the_lenient_path_fail(check):
    # Fine with STRICT set, but its own error handling breaks once STRICT is off.
    code, out = check(
        """
        STRICT = False

        class Trader:
            def run(self, state):
                if not STRICT:
                    raise KeyError("handler bug")
                return {}, 0, ""
        """
    )
    assert code == 1
    assert "exceptions escaped the bot with STRICT off" in out and "handler bug" in out


def test_limit_breaches_fail(check):
    code, out = check(
        """
        from datamodel import Order

        class Trader:
            def run(self, state):
                return {"KELP": [Order("KELP", 1, 51)]}, 0, ""
        """
    )
    assert code == 1
    assert "FAIL  4 times orders were cancelled for breaching a position limit" in out


def test_with_a_limit_penalty_a_breach_is_a_tick_over_the_limit(tmp_path, capsys):
    folder = tmp_path / "deep" / "round1"
    folder.mkdir(parents=True)
    header = "day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss"
    rows = [f"0;{ts};KELP;2028;100;;;;;2032;100;;;;;2030.0;0.0" for ts in (0, 100, 200)]
    (folder / "prices_round_1_day_0.csv").write_text("\n".join([header, *rows]) + "\n")
    bot = tmp_path / "bot.py"
    bot.write_text("from datamodel import Order\n\nclass Trader:\n    def run(self, state):\n"
                   "        return ({'KELP': [Order('KELP', 2032, 60)]} if state.timestamp == 0 else {}), 0, ''\n")
    code = validate.main([str(bot), "1", "--data", str(tmp_path / "deep"), "--limit-penalty", "1"])
    out = capsys.readouterr().out
    assert code == 1 and "FAIL  3 ticks over a position limit (--limit-penalty charges each); first KELP on" in out


def test_imports_and_environment_are_checked(check):
    code, out = check(
        """
        import os
        import numpy

        class Trader:
            def run(self, state):
                return {}, 0, os.environ.get("X", "")
        """
    )
    assert code == 1
    assert "FAIL  imports outside the standard library: numpy" in out
    assert "WARN  uses os.environ" in out

    code, out = check(None, "--allow", "numpy")
    assert code == 0


def test_state_outside_trader_data_warns(check):
    code, out = check(
        """
        from datamodel import Order

        class Trader:
            ticks = 0

            def run(self, state):
                Trader.ticks += 1
                orders = [Order("KELP", 2100, 1)] if Trader.ticks == 2 else []
                return {"KELP": orders}, 0, ""
        """
    )
    assert code == 0
    assert "WARN  fills change when the bot is reloaded every tick" in out


def test_syntax_errors_stop_before_replaying(check):
    code, out = check("class Trader(:\n")
    assert code == 1
    assert "syntax error" in out and "errors in" not in out


def _seeds_that_order_a_set_differently(names: set[str]) -> tuple[str, str]:
    import subprocess
    import sys

    first = {}
    for seed in map(str, range(40)):
        out = subprocess.run([sys.executable, "-c", f"print(next(iter({names!r})))"], capture_output=True, text=True,
                             env={"PYTHONHASHSEED": seed})
        first.setdefault(out.stdout.strip(), seed)
        if len(first) == 2:
            return tuple(first.values())
    raise AssertionError("no two seeds order the set differently")


def test_a_bot_that_depends_on_the_hash_seed_warns(check, monkeypatch):
    # Which product comes first out of a set of strings changes with PYTHONHASHSEED, so a rerun in
    # another process (the organisers') trades another product.
    monkeypatch.setattr(validate, "HASH_SEEDS", _seeds_that_order_a_set_differently({"KELP", "RAINFOREST_RESIN"}))
    code, out = check(
        """
        from datamodel import Order

        class Trader:
            def run(self, state):
                first = next(iter(set(state.order_depths)))
                asks = state.order_depths[first].sell_orders
                return {first: [Order(first, min(asks), 1)]} if asks else {}, 0, ""
        """
    )
    assert code == 0
    assert "WARN  fills differ between Python processes with other hash seeds" in out
    assert "PASS  same fills when r1d-1 is replayed again" in out  # one process can't see it


def test_settings_that_cant_matter_warn(check, tmp_path):
    source = TEMPLATE.read_text().replace('"KELP": {"limit": 50, "fair": "sized_mid", "make_edge": 0.5, "stop_loss": 1200},',
                                          '"KELP": {"limit": 50, "fair": "sized_mid", "make_edge": 0.5, "stop_loss": 1200, "level": 2030, "jump_min": 4},')
    assert source != TEMPLATE.read_text()
    code, out = check(source)
    assert code == 0
    assert "WARN  settings that can't matter: KELP: level sets the target, so jump_min is ignored" in out


def test_a_limit_unlike_the_datas_warns(check):
    kelp = '"KELP": {"limit": 50, "fair": "sized_mid", "make_edge": 0.5, "stop_loss": 1200},'
    wrong = TEMPLATE.read_text().replace(kelp, kelp.replace('"limit": 50', '"limit": 20'))
    code, out = check(wrong)
    assert code == 0 and "WARN  position limits differ from the data's: KELP 20, the data's 50" in out
    missing = TEMPLATE.read_text().replace(kelp, kelp.replace('"limit": 50, ', "")).replace('"limit": 50,  # position', '"limit": 80,  # position')
    code, out = check(missing)
    assert code == 1 and "FAIL  no limit in PARAMS for KELP (the data's 50)" in out


def test_a_wall_size_above_the_market_makers_warns(check):
    # The fixture's KELP walls hold 20-25 lots; a wall_size of 30 leaves sized_mid on the plain mid.
    kelp = '"KELP": {"limit": 50, "fair": "sized_mid", "make_edge": 0.5, "stop_loss": 1200},'
    code, out = check(TEMPLATE.read_text().replace(kelp, kelp.replace('"make_edge": 0.5', '"make_edge": 0.5, "wall_size": 30')))
    assert code == 0 and "WARN  sized_mid falls back to the plain mid" in out and "KELP on 100% of book sides" in out


@pytest.mark.parametrize("text, size", [("102400", 102400), ("100KB", 99950), ("100 kB", 99950), ("100KiB", 102348),
                                        ("100k", 99950), ("1.5MB", 1450000), ("1 MB", 950000), ("1MiB", 996147)])
def test_max_size_reads_the_dashboards_figure_at_the_least_it_could_be(text, size):
    assert validate.max_size(text) == size  # 100 kB is anything from 99.95 kB, decimal unless it says KiB: 99,950 bytes


@pytest.mark.parametrize("text", ["abc", "KB", "-5", "0", "10 GB"])
def test_max_size_rejects_what_isnt_a_size(text):
    with pytest.raises(argparse.ArgumentTypeError):
        validate.max_size(text)


def test_the_file_checks_are_the_upload_forms(tmp_path):
    def statuses(path, size, limit):
        return [(c.status, c.message.split(",")[0]) for c in validate.file_checks(path, size, limit)]

    assert statuses(Path("bot.py"), 10, None) == [("INFO", "file size 10 bytes; pass the dashboard's cap as --max-size to check it")]
    assert statuses(Path("bot.PY"), 10, 10) == [("PASS", "file size 10 bytes")]
    assert statuses(Path("bot.txt"), 0, 10) == [("FAIL", "bot.txt: the portal takes only a .py file"), ("FAIL", "the file is empty"),
                                                 ("PASS", "file size 0 bytes")]
    assert statuses(Path("bot.py"), 11, 10)[0][0] == "FAIL"


def test_a_file_over_max_size_fails_and_names_the_compact_command(check):
    code, out = check(None, "--max-size", "10KB")
    assert code == 1 and "over the cap of 9,950: upload a compact copy (uv run python -m arena.compact" in out
    code, out = check(None, "--max-size", "1MB")
    assert code == 0 and "PASS  file size" in out


def test_a_state_over_max_state_warns(check):
    code, out = check(None, "--max-state", "10")
    assert code == 0 and "is over --max-state 10: the exchange may cut it" in out
    code, out = check(None, "--max-state", "50000")
    assert "WARN" not in out


def test_an_order_cap_fails_once_and_the_busiest_tick_counts_what_the_bot_sent(check):
    code, out = check(None)
    busiest = int(out.split("most orders in a tick ")[1].split(" ")[0])
    assert busiest >= 2
    code, out = check(None, "--max-orders", "1")
    assert code == 1 and "order cap:" in out
    assert "exceptions escaped" not in out  # dropped orders are the engine's, not the bot's
    assert f"most orders in a tick {busiest} " in out  # what the bot sent, not the cap


def test_the_action_and_resting_caps_fail_once_and_the_counts_are_what_the_bot_sent(check):
    # The 2026-10-28 rehearsal: "most orders in a tick 15" counted the orders kept from earlier ticks, read like a
    # breach of a 10-action cap and wasn't one. Now actions count new orders and cancels, before any cap.
    code, out = check(None, "--resting")
    actions = int(out.split("most actions in a tick ")[1].split(" ")[0])
    working = int(out.split("most orders working a product ")[1].split(" ")[0])
    assert actions >= 2 and working >= 2
    code, out = check(None, "--resting", "--max-actions", "1")
    assert code == 1 and "action cap:" in out and "exceptions escaped" not in out
    assert int(out.split("most actions in a tick ")[1].split(" ")[0]) > 1  # what the bot sent, not the cap (its runs differ once capped)
    code, out = check(None, "--resting", "--max-resting", "1")
    assert code == 1 and "resting cap:" in out and "exceptions escaped" not in out


def test_a_garbage_collection_inside_a_call_is_left_out_of_the_slowest_tick(check):
    # The 2026-10-28 rehearsal: one call a session took 70-91 ms, a full collection over the backtester's own
    # objects, and failed a 50 ms limit the bot's own work never came near. Here the collection is forced inside
    # a call that otherwise does nothing; the check times the call without it, and says so.
    code, out = check(
        """
        import gc

        HEAP = [[i] for i in range(300_000)]  # tracked objects the collector has to walk
        CALLS = [0]

        class Trader:
            def run(self, state):
                CALLS[0] += 1
                if CALLS[0] == 2:
                    gc.collect()
                return {}, 0, ""
        """,
        "--time-limit-ms", "5",
    )
    line = next(l for l in out.splitlines() if "slowest tick" in l)
    assert "PASS" in line and "with the backtester's garbage collections, left out" in line, line
    assert "WARN  a tick took" in out and "their clock may count them" in out  # the raw figure is still over the limit


def test_a_bot_that_reposts_what_it_cant_see_yet_fails_one_step_late(tmp_path, capsys):
    # The 2026-10-30 rehearsal: the rules didn't say orders arrive a step late, validate passed both bots, and
    # both uploads lost to their re-posts. The late replay fails them; DELAY passes it; --late 0 leaves it out.
    from arena import sim

    sim.write_day(sim.run(sim.preset_market(ticks=600), 7), tmp_path, 1, 0)
    def run(*args):
        code = validate.main([str(TEMPLATE), "1", "--data", str(tmp_path), "--resting", "--max-resting", "3", "--set", "MAX_RESTING=3", *args])
        return code, capsys.readouterr().out

    code, out = run()
    assert code == 1 and "FAIL  r1d0 with orders 1 step late (--delay 1): " in out and "resting cap:" in out and "set the bot's DELAY" in out
    assert "PASS  no errors in" in out  # on time it is fine
    code, out = run("--set", "DELAY=1", "--set", "ORDERS_REST=True")
    assert "PASS  r1d0 with orders 1 step late (--delay 1): no errors or breaches" in out
    code, out = run("--late", "0")
    assert code == 0 and "step late" not in out
    code, out = run("--delay", "1")  # the run itself is late: nothing more to replay
    assert "step late" not in out


def test_a_gray_area_bot_fails_unless_allowed_and_compact_warns(check, tmp_path, capsys):
    from arena import compact

    gray = TEMPLATE.read_text() + '\nGRAY_AREA = "spoofs Kelp\'s book"\n'
    code, out = check(gray)
    assert code == 1 and "FAIL  GRAY AREA: spoofs Kelp's book. THIS BOT GAMES" in out and "!!! GRAY AREA BOT" in out
    code, out = check(gray.replace('GRAY_AREA = "', 'GRAY_AREA: str = "'))  # annotated, as the audit's round 8 found (R7)
    assert code == 1 and "FAIL  GRAY AREA: spoofs Kelp's book" in out
    code, out = check(gray, "--allow-gray-area")
    assert code == 0 and "WARN  GRAY AREA, ALLOWED" in out
    path = tmp_path / "gray.py"
    path.write_text(gray)
    assert compact.main([str(path), str(tmp_path / "out.py")]) == 0
    assert "!!! GRAY AREA BOT: spoofs Kelp's book" in capsys.readouterr().out
