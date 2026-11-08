"""Exact clock links, cancellation censoring, and book-band exit attribution."""

import numpy as np
import pytest

from experiments.day.gen_ladders import chains, collect, exit_delays, links, load, measure


HEADER = "Time,Operation,OrderId,Side,Volume,Price,Lifespan\n"


def tape(tmp_path, mirror=False):
    rows = [
        ["0.000001", "Insert", "1", "B", "10", "100", "G"],
        ["0.000002", "Insert", "2", "A", "10", "110", "G"],
        ["0.010000", "Insert", "3", "B", "30", "98", "G"],
        ["0.012000", "Insert", "4", "B", "35", "97", "G"],
        ["0.014000", "Insert", "5", "B", "31", "96", "G"],
        ["0.020000", "Insert", "6", "B", "10", "106", "G"],
        ["0.050000", "Cancel", "3", "", "", "", ""],
        ["0.070000", "Cancel", "4", "", "", "", ""],
        ["0.100000", "Insert", "7", "A", "100", "90", "F"],
        ["0.200000", "Cancel", "5", "", "", "", ""],
    ]
    if mirror:
        for row in rows:
            if row[1] == "Insert":
                row[3] = "A" if row[3] == "B" else "B"
                row[5] = str(200 - int(row[5]))
    path = tmp_path / ("mirror.csv" if mirror else "tape.csv")
    path.write_text(HEADER + "".join(",".join(row) + "\n" for row in rows))
    return path


def test_exact_ladder_and_mirror_keep_joint_marks(tmp_path):
    a, b = collect(tape(tmp_path)), collect(tape(tmp_path, mirror=True))
    left, right = links(a, 2000)
    assert left.tolist() == [2, 3] and right.tolist() == [3, 4]
    assert [c.tolist() for c in chains(len(a["oid"]), left, right)] == [[2, 3, 4]]
    ra, rb = measure(a), measure(b)
    assert ra.pop("source_sha256") != rb.pop("source_sha256")
    assert ra == rb
    assert ra["candidate_orders"] == 3
    pop = ra["populations"]["all"]
    assert pop["still_resting_at_cancel_share"] == pytest.approx(2 / 3)
    assert pop["exit_check"]["resting_cancels"] == 2  # filled third order excluded
    assert pop["exit_check"]["delay_after_first_exit_s"]["p50"] == .04
    assert a["depth"][2] == 0 and a["cancel_remaining"][4] == 0


def test_cancel_touch_update_does_not_cause_its_own_exit():
    data = {k: np.array(v) for k, v in {
        "time_us": [10, 10], "cancel_us": [100, 100], "cancel_remaining": [5, 5],
        "touch_us": [10, 100], "bid": [100, 110], "ask": [105, 115],
        "side": [0, 1], "price": [98, 107]}.items()}
    r = exit_delays(data, np.array([0, 1]))
    assert r["resting_cancels"] == r["no_prior_exit"] == 2
    assert r["delay_after_first_exit_s"] == {}


def test_cache_rejects_changed_source_and_missing_cancel_is_censored(tmp_path):
    path, cache = tape(tmp_path), tmp_path / "cache.npz"
    original = load(path, cache)
    assert original["sha256"] == load(path, cache)["sha256"]
    path.write_text(path.read_text().replace("0.200000,Cancel,5,,,,\n", ""))
    with pytest.raises(ValueError, match="cache does not match"):
        load(path, cache)
    r = measure(collect(path))
    assert r["populations"]["all"]["right_censored"] == 1
    with pytest.raises(ValueError, match="positive"):
        links(original, 0)


def test_nearby_clock_is_not_a_ladder(tmp_path):
    path = tape(tmp_path)
    path.write_text(path.read_text().replace("0.012000", "0.012001"))
    r = measure(collect(path))
    assert r["candidate_chains"] == 0
    assert r["timing_controls"]["2000"]["band_pairs"] == 0
