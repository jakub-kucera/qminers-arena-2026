"""Discrete-law identification, censoring, and the v2 generator's seed contract."""

from collections import Counter
import copy
import hashlib

import numpy as np
import pytest

from experiments.day.gen_calibrate import PRESETS, parse_opts
from experiments.day.gen_inventory import fit_sizes, integer_us, inventory, lognormal_mass
from experiments.day.tape_gen import SizeLawSampler, generate


def params():
    return {"g_rate": 40., "f_rate": 5., "g_bid_share": .5,
            "sizes": {c: [[1, 1], [10, 3], [100, 1]] for c in ("inside", "touch", "behind1", "deeper")},
            "f_sizes": [[10, 2], [100, 2], [500, 1]], "f_offsets": [[0, 1], [1, 1]],
            "lifetime_quantiles": [.05, .3, 1., 2.],
            "latent": {"continuous": True, "stale_s": .2, "jump_rate": 0., "jump_size": .5, "informed": 0.,
                       "k_pmf": [[0, 6], [1, 3], [2, 1]], "impact": [[100, .2], [100000, .5]], "start_bid": 9999}}


def test_preset_overlay_preserves_named_baseline():
    original = copy.deepcopy(PRESETS["r3_public_after"])
    opts = parse_opts('r3_public_after:{"impact_traded":true,"impact_sqrt":0.05}')
    assert opts["impact_traded"] is True and opts["impact_sqrt"] == .05
    assert opts["jx_after_extra"] == original["jx_after_extra"]
    assert PRESETS["r3_public_after"] == original
    assert parse_opts('{"impact_traded":true}') == {"impact_traded": True}
    with pytest.raises(ValueError, match="JSON object"):
        parse_opts("r3_public_after:[]")


@pytest.mark.parametrize("preset,digest", [
    (None, "e95a44d5c473a0d99f13b31adf7ed56c844b4a80353ee3264bc03002bbb23cc7"),
    ("r3_public_after", "a6a6e9d8627439c4ff38ccbab57be600c5dcec87481ea335769d3d55c4b50135"),
])
def test_existing_draws_remain_byte_identical(tmp_path, preset, digest):
    p = params()
    if preset:
        p["latent"].update(PRESETS[preset])
    target = tmp_path / "tape.csv"
    generate(p, 71, 40, target)
    # Recorded from the unmodified generator at 659515d, numpy 2.5.4.
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest


def test_discrete_fit_recovers_rounding_and_censored_lower_tail():
    rng = np.random.default_rng(17)
    q = np.maximum(1, np.rint(rng.lognormal(2.65, 1.8, 150_000))).astype(int)
    best, second, *_ = fit_sizes(Counter(map(int, q)))
    assert (best["law"], best["rounding"]) == ("lognormal", "round")
    assert abs(best["mu"] - 2.65) < .025
    assert abs(best["sigma"] - 1.8) < .025
    assert best["cdf_distance"] < .005
    assert second["aic"] - best["aic"] > 100
    assert best["iid_ci95"]["mu"][0] < best["mu"] < best["iid_ci95"]["mu"][1]


def test_log_mass_contains_all_values_that_round_to_one():
    # E[log X] = 0, sigma=1: P(round(X) <= 1) = P(X < 1.5),
    # including X < .5, which would be lost by a naive rounding likelihood.
    from statistics import NormalDist
    actual = lognormal_mass(np.array([1, 2]), 0., 1., "round")
    assert actual[0] == pytest.approx(NormalDist().cdf(np.log(1.5)))
    assert actual.sum() == pytest.approx(NormalDist().cdf(np.log(2.5)))


def test_conditioned_sizes_follow_the_tail_without_an_atom_at_minimum():
    sampler = SizeLawSampler({"law": "lognormal", "mu": 4.1, "sigma": 1.4},
                             np.random.default_rng(23), minimum=500)
    q = np.array([sampler.draw() for _ in range(20_000)])
    assert q.min() >= 500
    assert (q == 500).mean() < .01
    assert q.max() > 5000  # not limited by the old empirical table's support
    uniform = SizeLawSampler({"law": "uniform", "low": 20, "high": 40},
                             np.random.default_rng(7), minimum=35)
    assert set(uniform.draw() for _ in range(1000)) == set(range(35, 41))


def test_law_draws_are_reproducible_with_latent_logging(tmp_path):
    p = params()
    p["latent"].update(PRESETS["r3_public_after"])
    p["latent"]["f_size_law"] = {"law": "lognormal", "mu": 4.1, "sigma": 1.4}
    p["latent"]["g_size_law"] = {"law": "uniform", "low": 20, "high": 40}
    untouched = copy.deepcopy(p)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    generate(p, 8, 40, a)
    generate(p, 8, 40, b, tmp_path / "latent.csv")
    assert a.read_bytes() == b.read_bytes()
    assert p == untouched
    g = [int(line.split(",")[4]) for line in a.read_text().splitlines()[1:] if line.endswith(",G")]
    assert min(g) == 20 and max(g) == 40


@pytest.mark.parametrize("sqrt_c", [0., .05])
def test_unfilled_iocs_have_no_traded_impact(tmp_path, sqrt_c):
    p = params()
    p["f_offsets"] = [[-1000, 1]]  # Every IOC limit is behind the opposite touch.
    p["latent"].update(impact_sqrt=sqrt_c, impact_traded=True)
    target, latent = tmp_path / "tape.csv", tmp_path / "latent.csv"
    generate(p, 71, 40, target, latent)
    path = np.loadtxt(latent, delimiter=",", skiprows=1)
    assert np.all(path[:, 1] == 9999.5)
    assert ",F\n" in target.read_text()
    p["latent"]["impact_traded"] = False
    generate(p, 71, 40, target, latent)
    assert np.std(np.loadtxt(latent, delimiter=",", skiprows=1)[:, 1]) > 0


def test_raw_inventory_keeps_censoring_ids_and_microseconds(tmp_path):
    p = tmp_path / "tiny.csv"
    p.write_text("Time,Operation,OrderId,Side,Volume,Price,Lifespan\n"
                 "0.000001,Insert,1000001,B,2,9999,G\n"
                 "0.000002,Insert,1000002,A,2,10000,G\n"
                 "0.050001,Cancel,1000001,,,,\n"
                 "0.100000,Insert,1000004,B,5,10000,F\n"
                 "0.100001,Insert,1000005,A,7,9999,F\n"
                 "0.200002,Cancel,1000002,,,,\n"
                 "0.300001,Insert,1000006,B,2,9999,G\n")
    r = inventory(p, reconstructed=True)
    assert r["ids"]["insert_delta_counts"] == {1: 3, 2: 1}
    assert r["time"]["adjacent_gap_us_counts"][1] == 2
    assert r["cancels"]["matched"] == 2
    assert r["cancels"]["right_censored"] == 1
    assert r["cancels"]["observed_lifetime_s"]["min"] == .05
    assert r["cancels"]["age_hazard"][0]["exposure_s"] == pytest.approx(.1)
    assert r["reconstructed"] and "Imputed" in r["caution"]
    assert integer_us("12345.000001") == 12345000001
    with pytest.raises(ValueError, match="sub-microsecond"):
        integer_us("1.0000001")


@pytest.mark.parametrize("spec", [
    {"law": "lognormal", "mu": 0, "sigma": 0},
    {"law": "lognormal", "mu": float("nan"), "sigma": 1},
    {"law": "uniform", "low": 1.5, "high": 2},
    {"law": "uniform", "low": 3, "high": 2},
    {"law": "unknown"},
])
def test_invalid_laws_fail_early(spec):
    with pytest.raises(ValueError):
        SizeLawSampler(spec, np.random.default_rng(1))
