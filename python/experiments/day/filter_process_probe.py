"""Truth-first impact, transient drift and F-price anchor audit.

    uv run python -m experiments.day.filter_process_probe TAPE --latent LATENT \
        --params PARAMS --out REPORT.json --cache EVENTS.npz

Without --latent/--params this runs only the observable F-anchor estimator.
The observable estimator never reads latent states or jumps. Fit first 75% of
time, then freeze coefficients for last-25% anchor-increment prediction. The
truth audit separately uses known calm states and logged jumps; its successful
recovery does NOT establish identification from public data.

Ordinary F has requested-size permanent impact c*x plus overshoot b*x decaying
with tau, where x=sign*sqrt(q), b=-c*impact_delay. Earlier F inserts at the same
timestamp as another insert are classified as injected; tape_gen's inject()
bypasses the transient. Timestamp rounding can merge unrelated events, and an
unemitted base F can leave an injection last: residuals audit this approximation.
Latent rows reflect the last base event, not a continuously propagated process.
Jump rows aggregate all jumps in 10 ms, so jump-law/rate estimates are approximate.
--minutes restricts every observation and fit to that elapsed-time prefix.
Observable noise diagnostics use causal previous-F anchors at regular grids;
their tail rates are NOT identified jump intensities, and their variance mixes
diffusion, jumps, impact misspecification and anchor error. A 1/6 tick-squared
rounding correction is explicitly heuristic. With truth, compare these measured
quantities to the corresponding exogenous logged path before interpreting them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import log_ndtr
from scipy.stats import chi2

from experiments.day.gen_inventory import integer_us
from experiments.day.tape_book import Book


def read_events(path, cache=None):
    """Replay every event; F residual volume never rests. Cache is source bound."""
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if cache and Path(cache).exists():
        with np.load(cache) as z:
            if str(z['sha256']) == digest and int(z['version']) == 1:
                return {k: z[k] for k in z.files}
    book = Book()
    insert_us, rows, f_insert_indices = [], [], []
    last = -1
    with path.open() as fh:
        next(fh)
        for line in fh:
            a = line.rstrip('\n').split(',')
            t = integer_us(a[0])
            if t < last:
                raise ValueError('decreasing timestamps')
            last = t
            if a[1] == 'Cancel':
                book.cancel(int(a[2]))
                continue
            side, q, p = (0 if a[3] == 'B' else 1), int(a[4]), int(a[5])
            is_f = a[6] == 'F'
            traded = book.insert(int(a[2]), side, p, q, is_f)
            insert_us.append(t)
            if is_f:
                f_insert_indices.append(len(insert_us) - 1)
                rows.append((t / 1e6, 1 if side == 0 else -1, q, p, traded))
    ins = np.asarray(insert_us, dtype=np.int64)
    fi = np.asarray(f_insert_indices, dtype=np.int64)
    later = np.minimum(fi + 1, len(ins) - 1)
    ordinary = (fi == len(ins) - 1) | (ins[fi] != ins[later])
    a = np.asarray(rows, dtype=float)
    out = dict(t=a[:, 0], sign=a[:, 1], qty=a[:, 2], price=a[:, 3], filled=a[:, 4],
               ordinary=ordinary, insert_t=ins / 1e6, duration=np.asarray(last / 1e6),
               sha256=np.asarray(digest), version=np.asarray(1))
    if cache:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, **out)
    return out


def impulses(events, filled=False):
    x = events['sign'] * np.sqrt(events['filled' if filled else 'qty'])
    return x * events['ordinary'], x * ~events['ordinary']


def prefix_events(events, minutes=None):
    """Return only events known by the elapsed-time cutoff, retaining no suffix."""
    if minutes is None:
        return events
    if not math.isfinite(minutes) or minutes <= 0:
        raise ValueError('minutes must be finite and positive')
    end = min(float(events['duration']), minutes * 60.)
    f_keep, insert_keep = events['t'] <= end, events['insert_t'] <= end
    out = dict(events)
    for name in ('t', 'sign', 'qty', 'price', 'filled', 'ordinary'):
        out[name] = events[name][f_keep].copy()
    out['insert_t'] = events['insert_t'][insert_keep].copy()
    out['source_duration'] = events.get('source_duration', events['duration'])
    out['duration'] = np.asarray(end)
    if len(out['t']) < 20:
        raise ValueError('prefix needs at least20 F observations')
    return out


def transient(t, x, tau):
    """State immediately before and after each F, preserving equal-time order."""
    before, after = np.zeros(len(t)), np.zeros(len(t))
    previous, state = 0., 0.
    for i, (now, impulse) in enumerate(zip(t, x)):
        state *= math.exp(-(now - previous) / tau)
        before[i] = state
        state += impulse
        after[i] = state
        previous = now
    return before, after


def at_grid(events, grid, tau, filled=False):
    """Permanent, overshoot and injected stocks at last base tick <= each grid."""
    x, xi = impulses(events, filled)
    _, after = transient(events['t'], x, tau)
    j = np.searchsorted(events['t'], grid, side='right') - 1
    k = np.searchsorted(events['insert_t'], grid, side='right') - 1
    last_tick = np.where(k >= 0, events['insert_t'][np.maximum(k, 0)], 0.)
    idx = np.maximum(j, 0)
    valid = j >= 0
    permanent = np.where(valid, np.cumsum(x)[idx], 0.)
    injected = np.where(valid, np.cumsum(xi)[idx], 0.)
    decaying = np.where(valid, after[idx] * np.exp(-(last_tick - events['t'][idx]) / tau), 0.)
    return np.column_stack((permanent, decaying, injected)), last_tick


def fit_linear(X, y, robust=False):
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    if robust:
        for _ in range(30):
            r = y - X @ beta
            w = np.minimum(1., 1. / np.maximum(np.abs(r), 1e-12))
            new = np.linalg.lstsq(X * np.sqrt(w[:, None]), y * np.sqrt(w), rcond=None)[0]
            if np.max(np.abs(new - beta)) < 1e-8:
                beta = new
                break
            beta = new
    r = y - X @ beta
    loss = np.mean(np.where(np.abs(r) <= 1., .5 * r * r, np.abs(r) - .5)) if robust else np.mean(r * r)
    return beta, float(loss)


def cluster_ci(X, y, beta, t, robust=False):
    """300-s score-sandwich CI conditional on selected tau/model (not tau CI)."""
    block = (t // 300).astype(int)
    if len(np.unique(block)) < 6:
        return [None] * X.shape[1]
    r = y - X @ beta
    psi = np.clip(r, -1., 1.) if robust else r
    bread = np.linalg.pinv(X.T @ (X * ((np.abs(r) < 1.) if robust else np.ones(len(r)))[:, None]))
    scores = np.asarray([np.sum(X[block == b] * psi[block == b, None], axis=0) for b in np.unique(block)])
    n = len(scores)
    cov = bread @ (scores.T @ scores) @ bread * n / max(n - 1, 1)
    se = np.sqrt(np.maximum(0., np.diag(cov)))
    return np.column_stack((beta - 1.96 * se, beta + 1.96 * se)).tolist()


def metrics(y, prediction):
    if not len(y):
        return dict(n=0, status='no observations in this segment')
    r = y - prediction
    return dict(n=len(y), mse=float(np.mean(r * r)), mae=float(np.mean(np.abs(r))),
                bias=float(np.mean(r)), zero_forecast_mse=float(np.mean(y * y)))


def profile_fit(design, y, train, robust=False):
    profile = []
    def score(logtau):
        tau = math.exp(logtau)
        X = design(tau)
        beta, loss = fit_linear(X[train], y[train], robust)
        return loss
    grid = np.geomspace(.1, 100., 19)
    values = [score(math.log(v)) for v in grid]
    best = int(np.argmin(values))
    lo, hi = grid[max(0, best - 1)], grid[min(len(grid) - 1, best + 1)]
    opt = minimize_scalar(score, bounds=(math.log(lo), math.log(hi)), method='bounded', options={'xatol': .001})
    tau = math.exp(opt.x)
    X = design(tau)
    beta, loss = fit_linear(X[train], y[train], robust)
    for v, loss_v in zip(grid, values):
        coef_v, _ = fit_linear(design(v)[train], y[train], robust)
        profile.append(dict(tau_s=float(v), train_loss=float(loss_v), coefficients=coef_v.tolist()))
    profile.append(dict(tau_s=tau, train_loss=loss, coefficients=beta.tolist()))
    return tau, X, beta, loss, profile


def observable_fit(events, filled=False):
    """No truth labels, latent values, configured parameters, or future fitting."""
    t = events['t']
    anchor = events['price'] - events['sign']
    y = np.diff(anchor)
    x, xi = impulses(events, filled)
    dt = np.diff(t)
    split = .75 * float(events['duration'])
    train, test = t[1:] < split, t[:-1] >= split
    def design(tau):
        pre, _ = transient(t, x, tau)
        return np.column_stack((x[:-1], np.diff(pre), xi[:-1], dt))
    tau, X, beta, loss, profile = profile_fit(design, y, train, robust=True)
    active = np.any(X[train] != 0., axis=0)
    condition = float(np.linalg.cond(X[train][:, active]))
    intervals = cluster_ci(X[train], y[train], beta, t[:-1][train], True)
    # Descriptive profile sensitivity, deliberately not a calibrated interval.
    near = [z for z in profile if z['train_loss'] <= loss * 1.001]
    c_near = [z['coefficients'][0] for z in near]
    return dict(method='observable Huber F-anchor increment fit; delta=1 tick; conditional 300s cluster CIs',
                size='filled' if filled else 'requested', split_s=split, coefficients=beta.tolist(),
                coefficient_names=['permanent_c', 'transient_b', 'injected_c', 'drift_ticks_per_s'],
                active_parameters=active.tolist(),
                conditional_ci95=[ci if enabled else None for ci, enabled in zip(intervals, active)],
                conditional_ci_blocks_300s=int(len(np.unique(t[:-1][train] // 300))),
                conditional_ci_qualification='Conditions on selected tau; suppressed below6 training blocks. Synthetic202/203 permanent-c intervals miss truth; not calibrated joint uncertainty. Inactive columns are unidentified.',
                immediate_c=float(beta[0] + beta[1]), delay=float(-beta[1] / beta[0]) if beta[0] else None,
                tau_s=tau, tau_search_boundary=bool(tau < .11 or tau > 90), train_huber_loss=loss,
                train=metrics(y[train], X[train] @ beta), holdout=metrics(y[test], X[test] @ beta),
                tau_profile=profile, condition_number=condition if math.isfinite(condition) else None,
                design_rank=int(np.linalg.matrix_rank(X[train])),
                profile_sensitivity=dict(relative_loss_tolerance=.001, permanent_c_range=[min(c_near), max(c_near)],
                                         tau_range_s=[min(z['tau_s'] for z in near), max(z['tau_s'] for z in near)],
                                         qualification='Descriptive grid profile within0.1% of minimum Huber loss; NOT a confidence interval.'),
                limitations=['F limit offset assumed 1; not established for real tapes.',
                             'Tau and permanent/transient split can be weakly identified; CIs condition on chosen tau.',
                             'Injected classification uses complete same-time group and generator structure.',
                             'Increment endpoint is next F anchor, not future mid or trading PnL.'])


def moment_summary(t, increments, changed, horizon, bootstrap=True):
    """Descriptive moments with300-s blocks; no Gaussian or jump decomposition."""
    if len(increments) < 2:
        return dict(n=len(increments), status='too few increments')
    duration = len(increments) * horizon
    drift = float(increments.sum() / duration)
    variance = float(np.sum((increments - drift * horizon) ** 2) / duration)
    corrected = variance - float(np.count_nonzero(changed)) / (6 * duration)
    out = dict(n=len(increments), exposure_s=duration, drift_ticks_per_s=drift,
               total_variance_per_s=variance, rounding_corrected_variance_per_s=corrected,
               tail3_per_s=float(np.count_nonzero(np.abs(increments) >= 3) / duration),
               tail5_per_s=float(np.count_nonzero(np.abs(increments) >= 5) / duration),
               abs_increment_quantiles=np.quantile(np.abs(increments), [.5, .9, .99, .999]).tolist())
    block = (t // 300).astype(int)
    ids = np.unique(block)
    out['blocks_300s'] = len(ids)
    if bootstrap and len(ids) >= 6:
        rows = []
        for b in ids:
            use = block == b
            r = increments[use]
            rows.append([r.sum(), np.sum(r * r), len(r) * horizon, np.count_nonzero(changed[use]),
                         np.count_nonzero(np.abs(r) >= 3), np.count_nonzero(np.abs(r) >= 5)])
        rows = np.asarray(rows)
        rng = np.random.default_rng(871)
        sums = rows[rng.integers(0, len(rows), size=(1000, len(rows)))].sum(axis=1)
        d = sums[:, 0] / sums[:, 2]
        v = sums[:, 1] / sums[:, 2] - d * d * horizon
        cols = (d, v, v - sums[:, 3] / (6 * sums[:, 2]), sums[:, 4] / sums[:, 2], sums[:, 5] / sums[:, 2])
        names = ('drift_ticks_per_s', 'total_variance_per_s', 'rounding_corrected_variance_per_s', 'tail3_per_s', 'tail5_per_s')
        out['block_ci95'] = {name: np.quantile(col, [.025, .975]).tolist() for name, col in zip(names, cols)}
    else:
        out['block_ci95'] = None
    return out


def noise_diagnostics(events, fit):
    """Observable exogenous-proxy path; coefficients already frozen at75% time."""
    x, xi = impulses(events)
    pre, _ = transient(events['t'], x, fit['tau_s'])
    stocks = np.column_stack((np.cumsum(x) - x, pre, np.cumsum(xi) - xi))
    anchor = events['price'] - events['sign']
    adjusted = anchor - stocks @ np.asarray(fit['coefficients'][:3])
    result = dict(horizons={}, qualifications=[
        'Previous-F anchor is causal and may be stale; no future anchor interpolation.',
        'Effective variance includes diffusion, jumps, anchor error and impact-model misspecification.',
        '1/6 rounding variance per changed anchor pair assumes independent uniform errors; heuristic only.',
        'Tail exceedances are observable rates, NOT jump intensities or inferred regime labels.',
        '300s block bootstrap is descriptive; fewer than6 blocks gives no interval.'])
    duration, split = float(events['duration']), fit['split_s']
    for h in (.1, .5, 1., 5.):
        grid = np.arange(0., duration + 1e-9, h)
        index = np.searchsorted(events['t'], grid, side='right') - 1
        good = index >= 0
        grid, index = grid[good], index[good]
        value = adjusted[index]
        increments, changed = np.diff(value), np.diff(index) != 0
        masks = dict(prefix=np.ones(len(increments), bool), train=grid[1:] < split, holdout=grid[:-1] >= split)
        result['horizons'][str(h)] = {
            name: moment_summary(grid[:-1][use], increments[use], changed[use], h)
            for name, use in masks.items()}
        result['horizons'][str(h)]['anchor_age_quantiles_s'] = np.quantile(grid - events['t'][index], [.5, .9, .99]).tolist()
    return result


def validate_noise(events, latent, cfg, diagnostics):
    """Compare anchor moments to logged exogenous process, not configured means."""
    grid, level, state, jumps = latent.T
    c, tau = cfg['impact_sqrt'], cfg.get('impact_tau', 5.)
    stock, _ = at_grid(events, grid, tau)
    exogenous = level - stock @ np.asarray([c, -c * cfg.get('impact_delay', 0), c])
    without_jumps = exogenous - np.cumsum(jumps)
    result = dict(horizons={}, logged_nonzero_jump_intervals=int(np.count_nonzero(jumps)),
                  logged_jump_interval_rate=float(np.count_nonzero(jumps) / (grid[-1] - grid[0])),
                  logged_on_state_share=float(np.mean(state)),
                  qualifications=['Truth sampled at regular grids; anchor uses last F before each grid, so endpoints differ.',
                                  'Logged jumps aggregate10ms intervals; realized diffusion variance includes alignment residual.'])
    for key in diagnostics['horizons']:
        h = float(key)
        selected = np.arange(0, len(grid), max(1, round(h / .01)))
        ts = grid[selected]
        total = moment_summary(ts[:-1], np.diff(exogenous[selected]), np.zeros(len(ts) - 1, bool), h, False)
        diffusion = moment_summary(ts[:-1], np.diff(without_jumps[selected]), np.zeros(len(ts) - 1, bool), h, False)
        observed = diagnostics['horizons'][key]['prefix']
        true_v = total.get('total_variance_per_s', 0.)
        ratio = observed.get('rounding_corrected_variance_per_s', 0.) / true_v if true_v > 0 else None
        result['horizons'][key] = dict(truth_total=total, truth_without_logged_jumps=diffusion,
                                      observed_corrected_variance_ratio=ratio,
                                      observed_drift_error=observed.get('drift_ticks_per_s', 0.) - total.get('drift_ticks_per_s', 0.))
    return result


def poisson_ci(n, exposure):
    return [float(chi2.ppf(.025, 2 * n) / (2 * exposure)) if n else 0.,
            float(chi2.ppf(.975, 2 * (n + 1)) / (2 * exposure))] if exposure else [None, None]


def clipped_jump_fit(values, lower=2., upper=100.):
    """Fit atoms at clipping limits, rather than treating them as density points."""
    v = np.abs(np.asarray(values))
    v = v[v > 0]
    invalid = (v < lower - .0001) | (v > upper + .0001)
    use = v[~invalid]
    low, high = use <= lower + .0001, use >= upper - .0001
    interior = np.log(use[~(low | high)])
    def nll(theta):
        mu, logsigma = theta
        sigma = math.exp(logsigma)
        z = (interior - mu) / sigma
        return float(np.sum(logsigma + interior + .5 * z * z + .5 * math.log(2 * math.pi))
                     - low.sum() * log_ndtr((math.log(lower) - mu) / sigma)
                     - high.sum() * log_ndtr((mu - math.log(upper)) / sigma))
    if len(use) < 10:
        return dict(n=len(use), status='too few jumps')
    opt = minimize(nll, [math.log(3), math.log(.85)], method='BFGS')
    mu, logsigma = opt.x
    h = 1e-4
    eye = np.eye(2) * h
    H = np.empty((2, 2))
    for i in range(2):
        for j in range(2):
            H[i, j] = (nll(opt.x + eye[i] + eye[j]) - nll(opt.x + eye[i] - eye[j])
                       - nll(opt.x - eye[i] + eye[j]) + nll(opt.x - eye[i] - eye[j])) / (4 * h * h)
    se = np.sqrt(np.maximum(0., np.diag(np.linalg.pinv(H))))
    return dict(n=len(use), excluded_aggregate_outside_support=int(invalid.sum()), lower_atom=int(low.sum()),
                median=math.exp(mu), logsd=math.exp(logsigma),
                median_ci95=np.exp(mu + np.asarray([-1.96, 1.96]) * se[0]).tolist(),
                logsd_ci95=np.exp(logsigma + np.asarray([-1.96, 1.96]) * se[1]).tolist(),
                qualification='Conditional iid intervals; multiple jumps in one logged interval may merge/cancel.')


def truth_audit(events, latent_path, params, diagnostics=None):
    a = np.loadtxt(latent_path, delimiter=',', skiprows=1)
    a = a[a[:, 0] <= float(events['duration'])]
    grid, level, state, jump = a.T
    split = .75 * float(events['duration'])
    cfg = params['latent']
    y = np.diff(level) - jump[1:]
    stable = state[1:] == state[:-1]
    # A CSV event rounded exactly onto a grid boundary has unknown sub-us order.
    boundary = np.isin(np.rint(grid * 1e6).astype(np.int64),
                       np.rint(events['insert_t'] * 1e6).astype(np.int64))
    clean = stable & ~boundary[1:] & ~boundary[:-1]
    calm = clean & (state[1:] == 0)
    train, test = calm & (grid[1:] < split), calm & (grid[:-1] >= split)
    def design(tau):
        stock, last_tick = at_grid(events, grid, tau)
        return np.column_stack((np.diff(stock, axis=0), np.diff(last_tick)))
    tau, X, beta, loss, profile = profile_fit(design, y, train)
    resid = y - X @ beta
    stock, last_tick = at_grid(events, grid, tau)
    dt = np.diff(last_tick)
    states = {}
    for s in (0, 1):
        use = clean & (state[1:] == s) & (dt > 0)
        n, exposure = int(use.sum()), float(dt[use].sum())
        if not n or not exposure:
            states[str(s)] = dict(n=n, exposure_s=exposure, status='state absent from prefix')
            continue
        variance_rate = float(np.sum(resid[use] ** 2) / exposure)
        effective_df = exposure ** 2 / float(np.sum(dt[use] ** 2))
        states[str(s)] = dict(n=n, exposure_s=exposure, residual_drift=float(resid[use].sum() / exposure),
                             diffusion_sd=math.sqrt(variance_rate), nearest_neighbor_filter_rate=variance_rate / 2,
                             effective_df=effective_df,
                             diffusion_sd_ci95=[math.sqrt(effective_df * variance_rate / chi2.ppf(.975, effective_df)),
                                                math.sqrt(effective_df * variance_rate / chi2.ppf(.025, effective_df))],
                             qualification='Moment-matched Gaussian conditional CI accounts for unequal dt; state boundary bins removed.')
    jumps = {}
    for s in (0, 1):
        use = stable & (state[1:] == s)
        exposure = float(np.diff(grid)[use].sum())
        n = int(np.count_nonzero(jump[1:][use]))
        transitions = int(np.count_nonzero((state[:-1] == s) & (state[1:] != s)))
        state_exposure = float(np.diff(grid)[state[:-1] == s].sum())
        if not state_exposure:
            jumps[str(s)] = dict(jump_intervals=0, exposure_s=0., status='state absent from prefix')
            continue
        rate_ci = poisson_ci(transitions, state_exposure)
        jumps[str(s)] = dict(jump_intervals=n, exposure_s=exposure, rate=n / exposure if exposure else None,
                            rate_ci95=poisson_ci(n, exposure), exits=transitions,
                            dwell_mean_s=state_exposure / transitions if transitions else None,
                            dwell_ci95_s=[1 / rate_ci[1], 1 / rate_ci[0] if rate_ci[0] else None],
                            state_exposure_s=state_exposure)
    anchors = anchor_truth(events, a, cfg)
    result = dict(method='ORACLE state-labelled latent differences minus logged jumps; calm first75 fit',
                expected=dict(c=cfg['impact_sqrt'], b=-cfg['impact_sqrt'] * cfg.get('impact_delay', 0),
                              delay=cfg.get('impact_delay', 0), tau_s=cfg.get('impact_tau', 5),
                              injected_c=cfg['impact_sqrt'], diffusion_sd_on=cfg.get('jx_diff_sd', 0)),
                coefficients=beta.tolist(), conditional_ci95=cluster_ci(X[train], y[train], beta, grid[1:][train]),
                tau_s=tau, delay=float(-beta[1] / beta[0]), train_mse=loss,
                holdout=metrics(y[test], X[test] @ beta), tau_profile=profile,
                diffusion=states, regimes=jumps, jump_law=clipped_jump_fit(jump), anchors=anchors,
                dropped_boundary_intervals=int(np.count_nonzero(boundary[1:] | boundary[:-1])),
                qualifications=['10ms logger reflects last base tick; decay stops at that tick.',
                                'Diffusion/jump/dwell estimates use all truth within the selected prefix for audit, not a public estimator.',
                                'Missing un-emitted base events and rounded timestamp ties can affect alignment.'])
    if diagnostics is not None:
        result['observable_noise_validation'] = validate_noise(events, a, cfg, diagnostics)
    return result


def anchor_truth(events, latent, cfg):
    """Exact calm pre-F reconstruction; on-state requires unlogged sub-grid noise."""
    grid, level, state, jump = latent.T
    c, tau = cfg['impact_sqrt'], cfg.get('impact_tau', 5)
    b = -c * cfg.get('impact_delay', 0)
    x, xi = impulses(events)
    pre, _ = transient(events['t'], x, tau)
    before = np.column_stack((np.cumsum(x) - x, pre, np.cumsum(xi) - xi)) @ np.asarray([c, b, c])
    stock, _ = at_grid(events, grid, tau)
    dgrid = stock @ np.asarray([c, b, c])
    left = np.searchsorted(grid, events['t'], side='left') - 1
    good = (left >= 0) & (left + 1 < len(grid))
    li = np.clip(left, 0, len(grid) - 2)
    good &= (state[li] == 0) & (state[li + 1] == 0) & (jump[li + 1] == 0)
    # If either grid endpoint has an insert exactly there, rounded time is ambiguous.
    ambiguous = np.isin(np.rint(grid * 1e6).astype(np.int64), np.rint(events['insert_t'] * 1e6).astype(np.int64))
    good &= ~ambiguous[li] & ~ambiguous[li + 1]
    true_pre = level[li] + before - dgrid[li]
    proxy = events['price'] - events['sign']
    out = {}
    for label, selected in [('ordinary', events['ordinary']), ('injected', ~events['ordinary'])]:
        use = good & selected
        error = proxy[use] - true_pre[use]
        out[label] = dict(n=int(use.sum()), rmse=float(np.sqrt(np.mean(error ** 2))) if len(error) else None,
                          bias=float(np.mean(error)) if len(error) else None,
                          interval_coverage=float(np.mean(np.abs(error) <= .5002)) if len(error) else None,
                          abs_error_quantiles=np.quantile(np.abs(error), [.5, .95, .99, 1.]).tolist() if len(error) else [],
                          previous_grid_age_s=np.quantile(events['t'][use] - grid[li[use]], [.5, .99]).tolist() if len(error) else [])
    out['qualification'] = 'Uses configured impact for calm/no-jump pre-event reconstruction only; no exact on-state pre-F truth is logged.'
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tape', type=Path)
    p.add_argument('--latent', type=Path)
    p.add_argument('--params', type=Path)
    p.add_argument('--cache', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--filled-control', action='store_true')
    p.add_argument('--minutes', type=float, help='fit only observations through this elapsed-time prefix')
    args = p.parse_args(argv)
    if bool(args.latent) != bool(args.params):
        p.error('--latent and --params must be used together')
    started = time.monotonic()
    e = prefix_events(read_events(args.tape, args.cache), args.minutes)
    result = dict(source=str(args.tape), sha256=str(e['sha256']), duration_s=float(e['duration']),
                  f_count=len(e['t']), inferred_injected=int((~e['ordinary']).sum()),
                  observable=observable_fit(e))
    result['minutes_requested'] = args.minutes
    result['observable_noise'] = noise_diagnostics(e, result['observable'])
    if args.filled_control:
        result['observable_filled_control'] = observable_fit(e, filled=True)
    if args.latent:
        result['truth_audit'] = truth_audit(e, args.latent, json.loads(args.params.read_text()), result['observable_noise'])
    result['elapsed_s'] = time.monotonic() - started
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps(dict(out=str(args.out), elapsed_s=result['elapsed_s'],
                          observable_c=result['observable']['coefficients'][0],
                          observable_tau=result['observable']['tau_s'])))


if __name__ == '__main__':
    main()
