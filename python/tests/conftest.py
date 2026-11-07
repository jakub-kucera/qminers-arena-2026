import pytest

PRICES = """\
day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss
0;0;KELP;2028;1;2026;20;;;2032;20;;;;;2030.0;0.0
0;0;RAINFOREST_RESIN;9998;5;;;;;;;;;;;9998.0;0.0
0;100;KELP;2029;25;;;;;2031;25;;;;;2030.0;0.0
0;100;RAINFOREST_RESIN;9996;2;;;;;10004;2;;;;;10000.0;0.0
"""

TRADES = """\
timestamp;buyer;seller;symbol;currency;price;quantity
100;Olivia;;KELP;SEASHELLS;2030.0;3
"""


@pytest.fixture
def data_dir(tmp_path):
    """A tiny Prosperity-format data folder: round 1, days -1 and 0, two ticks each."""
    folder = tmp_path / "data" / "round1"
    folder.mkdir(parents=True)
    (folder / "prices_round_1_day_0.csv").write_text(PRICES)
    (folder / "prices_round_1_day_-1.csv").write_text(PRICES)
    (folder / "trades_round_1_day_0.csv").write_text(TRADES)
    return tmp_path / "data"
