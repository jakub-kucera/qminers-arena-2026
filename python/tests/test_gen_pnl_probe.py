"""Full-log accounting distinguishes liquidation marks and fills from mid returns."""

import json

import numpy as np
import pytest

from experiments.day.gen_pnl_probe import balances, curve_proxy, liquidation, probe


def test_liquidation_sweeps_market_depth_and_marks_residual_at_last_price():
    book = [{99: 20, 98: 30}, {101: 10, 103: 40}]
    assert liquidation(book, 100, 90) == 99 * 20 + 98 * 80
    assert liquidation(book, -100, 90) == -(101 * 10 + 103 * 90)
    assert liquidation([{}, {}], 100, 90) == 9000
    assert liquidation(book, 0, 90) == 0


def test_accounting_probe_refuses_to_infer_mid_from_fills_and_depth(tmp_path):
    (tmp_path / "metadata.json").write_text(json.dumps({"data_file": "fixture.csv", "position_limit": 100}))
    (tmp_path / "result.json").write_text(json.dumps({"pnl": -200, "mark_price": 99}))
    (tmp_path / "events.csv").write_text("timestamp_us,source,operation,order_id,side,price,quantity\n"
                                         "0,market,add,1,B,99,20\n")
    (tmp_path / "book_deltas.csv").write_text("timestamp_us,side,price,owner,qty_diff\n"
        "0,B,99,market,20\n0,B,98,market,100\n0,A,101,market,200\n"
        "500000,A,101,market,-100\n1250000,B,99,market,100\n1500000,B,99,market,-50\n")
    (tmp_path / "trades.csv").write_text(
        "timestamp_us,price,taker_side,quantity,taker_order_id,maker_order_id,taker_owner,maker_owner\n"
        "500000,101,B,100,10,3,user,market\n1500000,99,A,50,11,1,user,market\n")
    (tmp_path / "pnl.csv").write_text("elapsed_s,pnl\n0,0\n1,-280\n2,-200\n2.1,-200\n")
    r = probe(tmp_path)
    assert r["accounting_max_error"] == 0
    assert r["end_mid"] == 100
    assert r["result_mark_price"] == 99
    # Mid stayed fixed, but the 100-lot position's marked PnL moved by 80.
    assert r["oracle_signed_inventory"]["rmse"] == pytest.approx(.8)
    assert r["pnl_only_proxy"]["complete_1s_intervals"] == 2
    (tmp_path / "pnl.csv").write_text("elapsed_s,pnl\n0,0\n1,-279\n2,-200\n2.1,-200\n")
    with pytest.raises(ValueError, match="accounting mismatch"):
        probe(tmp_path)


def test_inventory_boundary_and_breach_integral(tmp_path):
    path = tmp_path / "trades.csv"
    path.write_text("timestamp_us,price,taker_side,quantity,taker_order_id,maker_order_id,taker_owner,maker_owner\n"
                    "500000,100,B,150,1,2,user,market\n1500000,101,A,100,3,4,user,market\n")
    r = balances(path, np.array([0, 500000, 1000000, 1500000, 2000000]), 100, 10_000)
    assert r["inventory"].tolist() == [0, 0, 150, 150, 50]
    assert r["penalty"].tolist() == [0, 0, 5000, 10000, 10000]
    assert r["cash"][-1] == -4900


def test_curve_proxy_uses_only_complete_seconds_and_does_not_invent_prices(tmp_path):
    path = tmp_path / "pnl.csv"
    path.write_text("elapsed_s,pnl\n0,0\n1,100\n2,-100\n2.5,1000\n")
    r = curve_proxy(path)
    assert r["complete_1s_intervals"] == 2
    assert r["rms_dpnl_over_exposure"] == pytest.approx(np.sqrt(2.5))
    assert "mid" not in r
