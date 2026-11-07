"""arena.qgrid: a grid on the Arena's own simulator, end to end on a tiny synthetic backtest."""

import csv
import random
from pathlib import Path

import pytest

from arena import qgrid
from arena.botfile import BotFile, OverrideError, parse_override

ROOT = Path(__file__).resolve().parents[2]
BOT = ROOT / "python" / "bots" / "qminers" / "template.py"
BASE = ['--set', 'PARAMS.ASSET={"fair": "mid"}']


def write_backtest(path: Path, seconds: int = 60, seed: int = 1) -> Path:
    """The starter's format: each second the market maker requotes around a random-walk mid, and every
    other second a fill-and-kill order hits one side (about 200 rows for 60 seconds)."""
    rng = random.Random(seed)
    rows, next_id, live, mid = [], 1_000_001, [], 10_000
    for second in range(seconds):
        t = float(second)
        for order_id in live:
            rows.append([f"{t:.6f}", "Cancel", order_id, "", "", "", ""])
            t += 1e-6
        mid += rng.choice((-1, 0, 0, 1))
        live = []
        for side, price in (("B", mid - 2), ("A", mid + 2)):
            rows.append([f"{t:.6f}", "Insert", next_id, side, rng.randint(10, 40), price, "G"])
            live.append(next_id)
            next_id += 1
            t += 1e-6
        if second % 2:
            side = rng.choice("BA")
            rows.append([f"{second + 0.5:.6f}", "Insert", next_id, side, rng.randint(1, 8), mid + 5 if side == "B" else mid - 5, "F"])
            next_id += 1
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time", "Operation", "OrderId", "Side", "Volume", "Price", "Lifespan"])
        writer.writerows(rows)
    return path


def test_grid_end_to_end(tmp_path, capsys):
    data = write_backtest(tmp_path / "day.csv")
    out = tmp_path / "qgrid.csv"
    args = [str(BOT), str(data), *BASE, "--grid", "PARAMS.ASSET.make_edge=1,2", "--grid", "PARAMS.ASSET.make_size=5,10",
            "--jobs", "1", "--holdout", "0.5", "--out", str(out)]
    assert qgrid.main(args) == 0
    printed = capsys.readouterr().out
    assert "base" in printed and "best by pnl" in printed and "best by holdout" in printed
    with out.open() as f:
        rows = list(csv.DictReader(f))
    assert [row["cell"] for row in rows] == ["baseline"] + ["grid"] * 4
    assert all(row["error"] == "" for row in rows), rows
    for row in rows:  # the time split adds up, the per-file column is the total with one file
        assert float(row["in_pnl"]) + float(row["out_pnl"]) == pytest.approx(float(row["pnl"]))
        assert float(row[f"pnl:{data.name}"]) == pytest.approx(float(row["pnl"]))
    assert any(int(row["fills"]) > 0 for row in rows)


def test_split_and_drawdown():
    curve = [(0, 0.0), (1_000_000, 10.0), (2_000_000, 4.0), (3_000_000, 7.0), (4_000_000, 12.0)]
    assert qgrid.split_at(curve, 0.25) == (7.0, 5.0)  # the cut at 3 s
    assert qgrid.split_at(curve, 0.0) == (12.0, 0.0)
    assert qgrid.split_at(curve, 0.5) == (4.0, 8.0)
    assert qgrid.max_drawdown([pnl for _, pnl in curve]) == 6.0
    runs = [qgrid.Run(curve=curve), qgrid.Run(curve=[(0, 0.0), (1, -20.0)])]
    assert qgrid.chained(runs)[-1] == -8.0
    assert qgrid.max_drawdown(qgrid.chained(runs)) == 20.0


def test_overrides_reach_the_bot():
    base = dict([parse_override('PARAMS.ASSET={"fair": "mid"}'), parse_override("PARAMS.ASSET.make_edge=3")])
    module = BotFile(BOT, {}, base).load()
    assert module.PARAMS == {"ASSET": {"fair": "mid", "make_edge": 3}}
    assert module.params_for("ASSET")["make_edge"] == 3
    assert qgrid.strategy_class(module).__name__ == "ArenaBot"
    assert BotFile(BOT, {}).load().PARAMS == {}  # a fresh module each load: no override leaks
    with pytest.raises(OverrideError):  # the asset's entry must exist (or be --set whole) before its keys
        BotFile(BOT, {}, dict([parse_override("PARAMS.ASSET.make_edge=3")])).load()


def test_neighbourhood_and_axis_ends():
    axes = [qgrid.Axis("PARAMS.ASSET.make_edge", [0, 1, 2])]
    grid = [qgrid.Cell((i,), (v,), [qgrid.Run(pnl=p)]) for i, (v, p) in enumerate(zip([0, 1, 2], [1.0, 2.0, 6.0]))]
    cells = {c.index: c for c in grid}
    assert qgrid.neighborhood_mean(cells, (1,), (3,)) == 3.0
    assert qgrid.neighborhood_mean(cells, (2,), (3,)) == 4.0
    assert "highest value" in qgrid.axis_ends(axes, grid, "pnl")[0]
