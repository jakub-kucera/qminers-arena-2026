"""Process identification alignment and likelihood invariants."""
import math
import json

import numpy as np

from experiments.filter.filter_process_probe import (anchor_truth, at_grid,
                                                 clipped_jump_fit, fit_linear,
                                                 impulses, read_events, transient)
from experiments.filter.filter_process_probe import observable_fit
from experiments.filter.filter_process_probe import noise_diagnostics, prefix_events
from experiments.filter.filter_process_probe import cluster_ci
from experiments.filter.filter_process_probe import compare_impact_laws, fitted_prediction, size_basis


def events(t=(.1, .1, .4), ordinary=(False, True, True)):
    return dict(t=np.asarray(t), sign=np.asarray([1., -1., 1.]),
                qty=np.asarray([4., 9., 16.]), filled=np.asarray([1., 1., 1.]),
                ordinary=np.asarray(ordinary), insert_t=np.asarray([.1, .1, .3, .4, .8]),
                price=np.asarray([101., 99., 101.]), duration=np.asarray(1.))


def test_transient_respects_equal_time_order_and_excludes_injection():
    e = events()
    x, xi = impulses(e)
    assert x.tolist() == [0., -3., 4.]
    assert xi.tolist() == [2., 0., 0.]
    pre, post = transient(e['t'], x, 2.)
    assert pre[0] == pre[1] == 0
    assert post[1] == -3
    assert math.isclose(pre[2], -3 * math.exp(-.3 / 2))


def test_grid_decay_stops_at_last_base_insert_not_grid():
    e = events()
    stock, last = at_grid(e, np.asarray([0., .2, .35, .5, .9]), 2.)
    assert last.tolist() == [0., .1, .3, .4, .8]
    assert stock[0].tolist() == [0., 0., 0.]
    assert stock[1].tolist() == [-3., -3., 2.]
    assert math.isclose(stock[2, 1], -3 * math.exp(-.2 / 2))


def test_parser_book_fills_and_same_timestamp_classification(tmp_path):
    p = tmp_path / 'tape.csv'
    p.write_text('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n'
                 '0.01,Insert,1,A,5,101,G\n'
                 '0.10,Insert,2,B,3,101,F\n'
                 '0.10,Insert,3,B,4,101,F\n'
                 '0.20,Insert,4,B,5,101,F\n')
    e = read_events(p)
    assert e['ordinary'].tolist() == [False, True, True]
    assert e['filled'].tolist() == [3., 2., 0.]


def test_calm_anchor_reconstructs_preimpact_not_postimpact():
    e = events(t=(.011, .021, .031), ordinary=(True, True, True))
    e['insert_t'] = np.asarray([.011, .021, .031])
    cfg = dict(impact_sqrt=.1, impact_delay=-.2, impact_tau=2.)
    grid = np.arange(0, .051, .01)
    stock, _ = at_grid(e, grid, 2.)
    coefficients = np.asarray([.1, .02, .1])
    latent = np.column_stack((grid, 100.2 + stock @ coefficients, np.zeros(len(grid)), np.zeros(len(grid))))
    x, xi = impulses(e)
    pre, _ = transient(e['t'], x, 2.)
    exact = 100.2 + np.column_stack((np.cumsum(x) - x, pre, np.cumsum(xi) - xi)) @ coefficients
    e['price'] = np.floor(exact + .5) + e['sign']
    result = anchor_truth(e, latent, cfg)
    assert result['ordinary']['n'] == 3
    assert result['ordinary']['interval_coverage'] == 1.
    assert result['ordinary']['abs_error_quantiles'][-1] <= .5


def test_clipped_lognormal_recovers_law_with_lower_atom():
    rng = np.random.default_rng(471)
    v = np.clip(rng.lognormal(math.log(3), .85, 30000), 2, 100)
    result = clipped_jump_fit(v)
    assert abs(result['median'] - 3) < .06
    assert abs(result['logsd'] - .85) < .025
    assert result['lower_atom'] > 8000


def test_robust_linear_does_not_follow_one_large_outlier():
    x = np.arange(1., 100.)[:, None]
    y = .04 * x[:, 0]
    y[-1] += 1000
    beta, _ = fit_linear(x, y, robust=True)
    assert abs(beta[0] - .04) < .001


def test_unique_timestamps_report_inactive_injection_and_finite_json():
    rng = np.random.default_rng(61)
    t = np.cumsum(rng.exponential(.1, 120))
    sign = rng.choice([-1., 1.], len(t))
    qty = rng.integers(1, 500, len(t))
    increments = .05 * sign * np.sqrt(qty)
    anchor = np.rint(100 + np.r_[0., np.cumsum(increments[:-1])])
    e = dict(t=t, sign=sign, qty=qty, price=anchor + sign, ordinary=np.ones(len(t), bool), duration=t[-1])
    result = observable_fit(e)
    assert not result['active_parameters'][2]
    assert result['conditional_ci95'][2] is None
    assert result['design_rank'] == 3
    json.dumps(result, allow_nan=False)


def test_prefix_removes_all_future_observations_and_duration():
    t = np.arange(1., 101.)
    e = dict(t=t, sign=np.ones(100), qty=np.ones(100), filled=np.ones(100),
             ordinary=np.ones(100, bool), price=np.arange(100.), insert_t=np.arange(.5, 101., .5),
             duration=np.asarray(100.))
    a = prefix_events(e, 1.)
    assert a['duration'] == 60.
    assert len(a['t']) == 60
    assert a['t'].max() == a['insert_t'].max() == 60.
    e['price'][60:] = 99999
    e['qty'][60:] = 99999
    e['duration'] = np.asarray(1000.)
    b = prefix_events(e, 1.)
    assert np.array_equal(a['price'], b['price'])
    assert np.array_equal(a['qty'], b['qty'])
    assert a['duration'] == b['duration']


def test_observable_variance_recovers_rounded_brownian_scale_without_jumps():
    rng = np.random.default_rng(817)
    t = np.arange(1, 30001) * .1
    level = np.cumsum(rng.normal(0, 2 * math.sqrt(.1), len(t)))
    e = dict(t=t, sign=np.ones(len(t)), qty=np.ones(len(t)), ordinary=np.ones(len(t), bool),
             price=np.rint(level) + 1, duration=t[-1])
    fit = dict(tau_s=1., coefficients=[0., 0., 0., 0.], split_s=.75 * t[-1])
    result = noise_diagnostics(e, fit)['horizons']['1.0']['prefix']
    assert abs(result['rounding_corrected_variance_per_s'] - 4.) < .3
    # Diffusion alone generates threshold exceedances: they cannot be jump rates.
    assert result['tail3_per_s'] > .1


def test_parameter_uncertainty_suppressed_with_fewer_than_six_blocks():
    x = np.column_stack((np.ones(100), np.arange(100.)))
    y = np.sin(np.arange(100.))
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    assert cluster_ci(x, y, beta, np.arange(100.)) == [None, None]
    assert cluster_ci(x, y, beta, np.linspace(0, 1499, 100)) == [None, None]
    assert all(interval is not None for interval in cluster_ci(x, y, beta, np.linspace(0, 1799, 100)))


def test_fixed_table_thresholds_and_zero_fills():
    actual = size_basis(np.asarray([0, 1, 10, 11, 1000, 1001, 10**10]), 'r1_table')
    assert np.allclose(actual, [0, .097, .097, .111, .704, .903, .903])


def test_noise_diagnostics_uses_selected_law_and_filled_quantity():
    rng = np.random.default_rng(18)
    t = np.arange(1, 1001) * .1
    sign = rng.choice([-1., 1.], len(t))
    filled = rng.integers(1, 30, len(t))
    x = sign * filled
    anchor = 100 + .05 * (np.cumsum(x) - x)
    e = dict(t=t, sign=sign, qty=filled + 100, filled=filled, ordinary=np.ones(len(t), bool),
             price=anchor + sign, duration=t[-1])
    fit = dict(tau_s=1., coefficients=[.05, 0., 0., 0.], split_s=75., size='filled', impact_law='linear')
    assert np.allclose(fitted_prediction(e, fit), np.diff(anchor))
    noise = noise_diagnostics(e, fit)
    assert noise['horizons']['1.0']['prefix']['total_variance_per_s'] < 1e-20


def test_form_comparison_selects_sqrt_for_known_sqrt_process():
    rng = np.random.default_rng(913)
    t = np.cumsum(rng.exponential(.1, 2500))
    sign = rng.choice([-1., 1.], len(t))
    qty = np.rint(np.exp(rng.uniform(0, math.log(10000), len(t))))
    x = sign * np.sqrt(qty)
    anchor = np.rint(1000 + .05 * (np.cumsum(x) - x))
    e = dict(t=t, sign=sign, qty=qty, price=anchor + sign, ordinary=np.ones(len(t), bool), duration=t[-1])
    fitted = observable_fit(e)
    report = compare_impact_laws(e, fitted)['sizes']['requested']
    assert report['selected_by_training_huber'] == 'sqrt'
    assert report['holdout_mse_winner'] == 'sqrt'
    assert report['paired_holdout_vs_sqrt']['linear_minus_sqrt']['ci95'] is None
