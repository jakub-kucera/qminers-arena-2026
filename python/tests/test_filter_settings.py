"""Forecast gate, online mixture normalization and prefix boundaries."""
import math

import numpy as np
import pytest

from experiments.filter.filter_placement import likelihood_matrix
from experiments.filter.filter_settings import BASELINE, _selection, correlations, run
from experiments.filter.latent_filter import DEFAULTS, LatentFilter, ReferenceFilter, replay, settings_params


@pytest.mark.parametrize('side,state', [(0, 105), (1, 95)])
def test_online_reference_likelihood_matches_identification(side, state):
    model = dict(latent_pi=[.6, .3, .1], book_pi=[.5, .4, .1], book_weight=.4, noise_weight=.05)
    prices = np.arange(50, 104) if side == 0 else np.arange(101, 155)
    data = dict(side=np.full(len(prices), side), bid=np.full(len(prices), 100), ask=np.full(len(prices), 104), price=prices)
    latent = likelihood_matrix(data, np.arange(len(prices)), np.full(len(prices), state), max_k=2)
    own = likelihood_matrix(data, np.arange(len(prices)), np.full(len(prices), 100 if side == 0 else 103), max_k=2)
    expected = .55 * (latent[:, :3] @ model['latent_pi']) + .4 * (own[:, :3] @ model['book_pi']) + .05 * latent[:, -1]
    actual = []
    for price in prices:
        f = ReferenceFilter(model)
        f.reset(100)
        f.p = [float(f.base + i == state) for i in range(f.n)]
        f.insert(side, int(price), 100, 104)
        actual.append(math.exp(f.loglik))
    assert np.allclose(actual, expected)
    assert sum(actual) == pytest.approx(1)


def scores(train, test):
    return {'correlations': {fold: {h + '_purged': value for h in ('0.4s', '1s')}
                             for fold, value in [('first75', train), ('last25', test)]}}


def test_candidate_selection_never_uses_holdout_to_pick_winner():
    base = settings_params(BASELINE)
    models = {'baseline': base, 'a': {**base, 'rate': 3}, 'b': {**base, 'rate': 4},
              'reference': {**base, 'reference': {}}}
    results = {'baseline': scores(.3, .3), 'a': scores(.35, .29), 'b': scores(.34, .5), 'reference': scores(.9, .9)}
    settings, report = _selection(results, models, .005)
    assert report['selected_on_training'] == 'a'
    assert report['selected'] == 'baseline'
    assert settings == BASELINE


def test_exported_keys_are_accepted_and_unknown_keys_rejected():
    assert settings_params(BASELINE)['impact_scale'] == 3
    with pytest.raises(ValueError, match='unsupported'):
        settings_params({'FILTER_UNIMPLEMENTED': 1})


def test_linear_impact_structural_hypothesis_uses_lots():
    filt = LatentFilter(linear_c=.003, sqrt_c=.1)
    filt.reset(100)
    filt.trade(1, 400)
    assert filt.moments()[0] == pytest.approx(101.2)


def test_prefix_and_extra_filter_parity(tmp_path):
    tape = tmp_path / 'tape.csv'
    text = 'Time,Operation,OrderId,Side,Volume,Price,Lifespan\n0,Insert,1,B,20,100,G\n0.01,Insert,2,A,20,101,G\n0.02,Insert,3,B,20,100,G\n0.2,Insert,4,A,20,102,G\n'
    tape.write_text(text + '0.5,Insert,5,B,50,110,F\n')
    params = {**DEFAULTS, 'impact_scale': 3, 'depth': 6}
    first = replay(tape, params, extra=({},), until_s=.3)[0]
    assert np.array_equal(first[:, 2], first[:, 7])
    tape.write_text(text + '0.5,Insert,5,A,500,50,F\n')
    second = replay(tape, params, extra=({},), until_s=.3)[0]
    assert np.array_equal(first, second)


def test_sparse_tape_writes_baseline_with_reason(tmp_path):
    tape = tmp_path / 'sparse.csv'
    tape.write_text('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n0,Insert,1,B,1,100,G\n600,Cancel,1,,,,\n')
    report = run(tape, tmp_path / 'settings.json')
    assert report['settings'] == BASELINE
    assert 'fewer than100' in report['settings_status']


def test_wall_time_holdout_does_not_move_when_initial_samples_missing():
    t = np.arange(2., 20., .05)
    rows = np.zeros((len(t), 3))
    rows[:, 0] = t
    rows[:, 1] = t ** 2
    rows[:, 2] = np.where(t < 15, t, -t)
    result = correlations(rows, 2, split_s=15.)
    assert result['last25']['0.4s_purged'] == pytest.approx(-1)
    assert result['first75']['0.4s_purged'] == pytest.approx(1)
