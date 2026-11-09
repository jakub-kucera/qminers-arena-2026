"""Fill censoring, causal history, event attribution and time-split rates."""

import copy

import numpy as np
import pytest

from experiments.generator.gen_ladders import collect
from experiments.generator.gen_ladder_mechanics import DIMENSIONS, book_features, cancellation_models, fill_times, risk_cells
from test_gen_ladders import tape


def test_recognition_delays_entry_and_full_fills_censor_exposure(tmp_path):
    path = tape(tmp_path)
    data = collect(path)
    cache = tmp_path / "fills.npz"
    filled = fill_times(path, data, cache)
    assert filled[4] == 100_000
    assert np.array_equal(filled, fill_times(path, data, cache))
    exposure, events, summary = risk_cells(data, filled)
    assert exposure.sum() == pytest.approx(.038 + .058 + .086)
    assert events.sum() == 2
    assert summary["cancel_events"] == 2 and summary["filled_censors"] == 1
    changed = {**data, "sha256": np.array("different")}
    with pytest.raises(ValueError, match="fill cache source"):
        fill_times(path, changed, cache)


def test_cancellation_cannot_cause_its_own_distance_predictor():
    data = {k: np.array(v) for k, v in {
        "time_us": [10_000, 12_000, 14_000], "side": [0, 0, 0], "price": [98, 97, 96],
        "own": [100, 100, 100], "qty": [30, 30, 30], "cancel_us": [50_000, 50_000, 50_000],
        "cancel_remaining": [30, 30, 30], "touch_us": [1, 50_000], "bid": [100, 110],
        "ask": [111, 111]}.items()}
    data["end_us"] = np.array(50_001)
    exposure, events, _ = risk_cells(data, np.full(3, -1))
    assert events[:, :, :, 3].sum() == 3  # all in 2-4 bucket before cancel
    assert events[:, :, :, 7].sum() == 0  # the cancel's book update is not a trigger
    assert exposure[:, :, :, 7].sum() == 0


def test_book_history_is_strictly_prior():
    data = {"touch_us": np.array([1, 100, 200, 300]), "bid": np.array([100, 101, 102, 103]),
            "ask": np.array([101, 102, 103, 104])}
    original = book_features(data, np.array([200]))
    changed = copy.deepcopy(data)
    changed["bid"][2:] += 1000
    changed["ask"][2:] += 1000
    assert np.array_equal(original, book_features(changed, np.array([200])))
    assert not np.array_equal(original, book_features(changed, np.array([201])))


def test_holdout_events_cannot_change_fitted_hazards():
    exposure = np.ones((2, *DIMENSIONS))
    events = np.ones_like(exposure)
    a = cancellation_models(exposure, events, 60_000_000)
    events[1] *= 10
    b = cancellation_models(exposure, events, 60_000_000)
    for name in a["models"]:
        assert a["models"][name]["rate_per_s"] == b["models"][name]["rate_per_s"]
    assert a["test_cancels"] * 10 == b["test_cancels"]


def test_cancel_at_fold_boundary_belongs_to_the_new_fold():
    data = {k: np.array(v) for k, v in {
        "time_us": [59_990_000, 59_992_000, 59_994_000], "side": [0, 0, 0], "price": [98, 97, 96],
        "own": [100, 100, 100], "qty": [30, 30, 30], "cancel_us": [60_000_000] * 3,
        "cancel_remaining": [30, 30, 30], "touch_us": [1], "bid": [100], "ask": [101]}.items()}
    data["end_us"] = np.array(60_000_001)
    exposure, events, _ = risk_cells(data, np.full(3, -1))
    assert exposure[0].sum() > 0 and exposure[1].sum() == 0
    assert events[0].sum() == 0 and events[1].sum() == 3


def test_empty_cancellation_folds_report_insufficient_data():
    exposure = np.zeros((2, *DIMENSIONS))
    assert "insufficient" in cancellation_models(exposure, exposure, 60_000_000)["status"]
