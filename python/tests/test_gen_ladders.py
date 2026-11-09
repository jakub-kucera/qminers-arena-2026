"""Exact clock links, cancellation censoring, and book-band exit attribution."""

import numpy as np
import pytest

from experiments.generator.gen_ladders import chains, collect, exit_delays, links, load, measure
from experiments.generator.gen_ladders import fit_population
from experiments.generator.tape_gen import LadderStream, generate
from test_gen_inventory import params


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


def test_population_fit_preserves_total_rate_and_excludes_joint_marks():
    data = {k: np.array(v) for k, v in {
        "time_us": [1, 2, 10_000, 12_000, 14_000, 50_000],
        "side": [0, 1, 0, 0, 0, 0], "qty": [10, 10, 30, 35, 31, 10],
        "price": [100, 101, 98, 97, 96, 100], "own": [100, 101, 100, 100, 100, 100],
        "opposite": [101, 100, 101, 101, 101, 101],
        "cancel_us": [100_001, 100_002, 50_000, 80_000, 90_000, 150_000]}.items()}
    data.update(end_us=np.array(200_000), sha256=np.array("fixture"))
    original = params()
    result = fit_population(data, original)
    spec = result["g_ladders"]
    assert spec["batches"] == [[[2, 30, 40_000], [3, 35, 68_000], [4, 31, 76_000]]]
    assert result["g_rate"] + spec["rate"] * 3 == pytest.approx(6 / .199999)
    assert result["sizes"]["deeper"] == [[10, 3]]  # no labelled ladder sizes leaked back
    assert "g_ladders" not in original
    assert spec["fit"]["batch_g_orders"] == 3


def test_batch_clock_interleaves_overlapping_starts_and_preserves_marks():
    spec = {"rate": 1000, "bid_share": 1., "gap_us": 2000,
            "batches": [[[2, 777, 200_000], [3, 778, 300_000]]]}
    stream = LadderStream(spec, np.random.default_rng(17))
    rows = [stream.pop() for _ in range(1000)]
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)
    starts = {r[0] for r in rows if r[3] == 777}
    for t, side, offset, q, life in rows:
        assert side == 0
        if q == 778:
            assert t - 2000 in starts and offset == 3 and life == 300_000
    with pytest.raises(ValueError, match="rate"):
        LadderStream({**spec, "rate": float("nan")}, np.random.default_rng(1))


def test_generated_ladders_keep_exact_clocks_and_lifetimes(tmp_path):
    p = params()
    p["g_ladders"] = {"rate": 2., "bid_share": .5, "gap_us": 2000,
                      "batches": [[[2, 777, 200_000], [3, 778, 300_000]]]}
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    generate(p, 13, 40, a)
    generate(p, 13, 40, b, tmp_path / "latent.csv")
    assert a.read_bytes() == b.read_bytes()
    data = collect(a)
    marked = (data["qty"] == 777) | (data["qty"] == 778)
    ended = marked & (data["cancel_us"] >= 0)
    expected = np.where(data["qty"][ended] == 777, 200_000, 300_000)
    assert ended.sum() > 50
    assert np.array_equal(data["cancel_us"][ended] - data["time_us"][ended], expected)
    left, right = links(data, 2000)
    assert sum((data["qty"][left] == 777) & (data["qty"][right] == 778)) > 40
    insert_ids = [int(row.split(",")[2]) for row in a.read_text().splitlines()[1:] if ",Insert," in row]
    assert np.all(np.diff(insert_ids) == 1)
