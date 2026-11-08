"""Clamped probability normalization and interval-anchor identification."""

import numpy as np
import pytest

from experiments.day.filter_placement import anchor_pairs, exact_truth, fit_mixture, fit_phase, likelihood_matrix, measure


@pytest.mark.parametrize('side,state', [(0, 105), (1, 95)])
def test_price_components_remain_normalized_after_clamping(side, state):
    prices = np.arange(-100, 104) if side == 0 else np.arange(101, 300)
    data = {'side': np.full(len(prices), side), 'price': prices,
            'bid': np.full(len(prices), 100), 'ask': np.full(len(prices), 104)}
    matrix = likelihood_matrix(data, np.arange(len(prices)), np.full(len(prices), state), max_k=2)
    assert np.allclose(matrix.sum(axis=0), 1)


def test_crossing_prices_have_zero_probability():
    data = {'side': np.array([0, 1]), 'price': np.array([101, 100]),
            'bid': np.full(2, 100), 'ask': np.full(2, 101)}
    assert not likelihood_matrix(data, np.arange(2), np.array([105, 95])).any()


def test_em_recovers_known_law_from_quantized_anchors():
    rng = np.random.default_rng(31)
    n = 80_000
    states = 100 - rng.integers(2, size=n)
    side = rng.integers(2, size=n)
    k = rng.choice(3, size=n, p=[.55, .39, .06])
    prices = np.where(side == 0, np.minimum(states - k, 100), np.maximum(states + 1 + k, 101))
    data = {'side': side, 'price': prices, 'bid': np.full(n, 100), 'ask': np.full(n, 101)}
    m = likelihood_matrix(data, np.arange(n), np.column_stack((np.full(n, 99), np.full(n, 100))), max_k=2)
    patterns, counts = np.unique(m, axis=0, return_counts=True)
    theta = fit_mixture(patterns, counts)
    assert np.allclose(theta[:3], [.55, .39, .06], atol=.01)
    assert theta[-1] < .01


def test_anchor_itself_cannot_cross_training_prefix():
    data = {'time_us': np.array([100, 200, 200, 300]), 'kind': np.array([0, 1, 0, 1]),
            'bid': np.full(4, 100), 'ask': np.full(4, 101)}
    g, f = anchor_pairs(data, 200, 250)
    assert len(g) == 0  # F200 is an injection, and ordinary F300 is beyond prefix
    g, f = anchor_pairs(data, 200, 400)
    assert g.tolist() == [2] and f.tolist() == [3]


def test_phase_em_recovers_nonuniform_book_conditioned_phase():
    rng = np.random.default_rng(32)
    n = 40_000
    upper = rng.random(n) < .9
    states = 99 + upper
    side = rng.integers(2, size=n)
    k = rng.choice(3, size=n, p=[.55, .39, .06])
    price = np.where(side == 0, np.minimum(states - k, 100), np.maximum(states + 1 + k, 101))
    data = {'side': side, 'price': price, 'bid': np.full(n, 100), 'ask': np.full(n, 101)}
    matrix = np.stack([likelihood_matrix(data, np.arange(n), np.full(n, lb), max_k=2) for lb in (99, 100)], axis=1)
    theta, phase = fit_phase(matrix, np.zeros(n, int))
    assert np.allclose(theta[:3], [.55, .39, .06], atol=.015)
    assert abs(phase[0] - .9) < .015


def test_truth_only_when_no_intervening_insert(tmp_path):
    path = tmp_path / 'latent.csv'
    path.write_text('time,latent,state,jump\n0.00,100.2,0,0\n0.01,101.2,0,0\n0.02,102.2,0,0\n0.03,103.2,0,0\n')
    data = {'time_us': np.array([5_000, 15_000, 19_000, 25_000]), 'kind': np.array([0, 0, 1, 0]),
            'bid': np.full(4, 100), 'ask': np.full(4, 101)}
    safe, lb, _ = exact_truth(data, path)
    assert safe.tolist() == [True, False, False, True]
    assert lb[safe].tolist() == [101, 103]


def test_prefix_report_cannot_use_changed_future_prices():
    n = 900
    t = np.repeat(np.arange(n) * 100_000, 2) + np.tile([0, 100], n)
    kind = np.tile([0, 1], n)
    side = np.repeat(np.arange(n) % 2, 2)
    prices = np.where(side == 0, 100 + kind * 2, 101 - kind * 2)
    data = dict(time_us=t, kind=kind, side=side, price=prices, qty=np.ones(len(t), int),
                bid=np.full(len(t), 100), ask=np.full(len(t), 101), filled=np.zeros(len(t), int),
                end_us=np.array(90_000_000), sha256=np.array('fixture'))
    before = measure(data, minutes=80 / 60, max_k=2, bootstrap=0)
    data['price'][t >= 80_000_000] = 1000  # invalid future G prices must also be ignored
    assert measure(data, minutes=80 / 60, max_k=2, bootstrap=0) == before
    assert 'uncertainty_status' in before['gaps']['2000']['F_anchor_learned_phase']
