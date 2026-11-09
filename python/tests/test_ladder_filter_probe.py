"""No future chain membership or future target may enter the causal forecast arms."""

import numpy as np
import pytest

from experiments.filter.ladder_filter_probe import CausalClock, DelayedFilters, targets, replay, ARMS


def test_clock_labels_current_order_only_and_rejects_nearby_or_wrong_side():
    detector = CausalClock()
    assert detector.observe(1000, 0, 2) is False  # first child cannot be known yet
    assert detector.observe(2999, 0, 3) is False
    assert detector.observe(3000, 1, 3) is False
    assert detector.observe(3000, 0, 3) is True
    assert detector.observe(5000, 0, 8) is False  # current is outside the band's rule
    assert detector.observe(7000, 0, 4) is False  # invalid predecessor was never stored
    assert len(detector.seen) <= 2


def test_prefix_clock_decisions_never_change_when_more_orders_arrive():
    def decisions(rows):
        detector = CausalClock()
        return [detector.observe(*row) for row in rows]
    rows = [(10_000, 0, 2), (12_000, 0, 3), (14_000, 0, 4)]
    assert decisions(rows[:2]) == decisions(rows)[:2] == [False, True]


def test_future_targets_use_exact_time_and_purge_split_overlap():
    stamps = np.array([0, 50, 100, 200, 250, 300, 350]) * 1000
    rows = np.column_stack([stamps, np.arange(len(stamps))])
    ix, y, train, test = targets(rows, 100_000, 250_000, warmup_us=0)
    assert ix.tolist() == [0, 2, 3, 4]
    assert train.tolist() == [True, True, False, False]
    assert test.tolist() == [False, False, False, True]
    assert y.tolist() == [2, 1, 2, 2]


def test_excluding_filter_observation_does_not_remove_it_from_book(tmp_path):
    path = tmp_path / "tiny.csv"
    path.write_text("Time,Operation,OrderId,Side,Volume,Price,Lifespan\n"
                    "0.000001,Insert,1,B,10,100,G\n"
                    "0.000002,Insert,2,A,10,101,G\n"
                    "0.010000,Insert,3,B,20,98,G\n"
                    "0.012000,Insert,4,B,20,97,G\n"
                    "0.020000,Cancel,1,,,,\n"
                    "0.060000,Cancel,3,,,,\n"
                    "0.110000,Cancel,4,,,,\n")
    rows, info = replay(path, {3, 4})
    # At50ms the omitted first ladder order is the best bid, so it did enter the book.
    assert rows[0, 1] == 99.5
    assert info["dropped_observations"]["clock_2ms"] == 1
    assert info["dropped_observations"]["oracle_chain"] == 2
    assert info["dropped_observations"]["clock_1ms"] == 0
    assert info["dropped_observations"]["delayed_clock_2ms"] == 2
    # Both baseline and placebo have exactly the same filter values.
    assert np.array_equal(rows[:, 4:6], rows[:, 4 + 2 * ARMS.index("clock_1ms"):6 + 2 * ARMS.index("clock_1ms")])
    other, _ = replay(path, set())
    assert np.array_equal(rows[:, :10], other[:, :10])  # oracle labels cannot affect causal arms


def test_clock_rejects_time_reversal():
    detector = CausalClock()
    detector.observe(1000, 0, 2)
    with pytest.raises(ValueError, match="decrease"):
        detector.observe(999, 0, 2)


def test_delayed_predecessor_is_not_processed_before_the_current_event():
    delayed = DelayedFilters()
    delayed.insert(10_000, 0, 98, 100, 101, False)
    delayed.flush(12_000, inclusive=False)  # a sample before the event at12ms
    assert delayed.recognized == 0 and delayed.filters[0].n_obs == 0
    delayed.insert(12_000, 0, 97, 100, 101, True)
    delayed.flush(12_000, inclusive=True)
    assert delayed.recognized == delayed.dropped == 1
    assert delayed.filters[0].n_obs == 1 and delayed.filters[1].n_obs == 0
    delayed.flush(14_001, inclusive=False)
    assert delayed.recognized == delayed.dropped == 2
    assert delayed.filters[0].n_obs == 2 and delayed.filters[1].n_obs == 0
