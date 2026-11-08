"""Estimate clamped G placement laws from nearby F-price latent intervals.

An ordinary F priced at latent +/-1 reveals latent in [price-sign-.5,
price-sign+.5). G orders immediately BEFORE the next F avoid that F's impact.
The placement likelihood integrates the two possible integer reference bids,
includes the observed clamp, and fits a proper mixture with a clamped discrete
Laplace contamination law. This is offline identification, not an online feature.

FIRST run with --latent on synthetic tapes. A G's exact latent can be read from
the following 10-ms sample only when no later insert precedes that sample (and
no unlogged standalone jump process exists). It is not interpolation across a
jump. The same estimator then runs without truth. F offset1 and uniform latent
phase remain assumptions requiring validation; gap sensitivity is reported.

    uv run python -m experiments.day.filter_placement TAPE --cache EVENTS.npz \
        --latent LATENT.csv --out REPORT.json
"""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from experiments.day.gen_inventory import integer_us
from experiments.day.tape_book import Book


def read_events(path, cache=None):
    path = Path(path)
    stat = path.stat()
    identity = json.dumps([1, str(path.resolve()), stat.st_size, stat.st_mtime_ns])
    if cache and cache.exists():
        with np.load(cache, allow_pickle=False) as saved:
            if str(saved['identity']) != identity:
                raise ValueError('placement cache source/version differs; choose a fresh path')
            return {k: saved[k] for k in saved.files if k != 'identity'}
    names = ('time_us', 'kind', 'side', 'qty', 'price', 'bid', 'ask', 'filled')
    columns = {name: array('q') for name in names}
    book, digest = Book(), hashlib.sha256()
    end = 0
    with path.open('rb') as fh:
        header = next(fh)
        digest.update(header)
        if header.strip() != b'Time,Operation,OrderId,Side,Volume,Price,Lifespan':
            raise ValueError('unexpected header')
        for row in fh:
            digest.update(row)
            ts, op, oid, side, qty, price, life = row.decode().strip().split(',')
            now, oid = integer_us(ts), int(oid)
            if now < end:
                raise ValueError('decreasing timestamps')
            end = now
            if op == 'Cancel':
                book.cancel(oid)
                continue
            sd, q, p, f = int(side == 'A'), int(qty), int(price), int(life == 'F')
            bid, ask = book.best
            filled = book.insert(oid, sd, p, q, bool(f))
            for name, value in zip(names, (now, f, sd, q, p, bid or 0, ask or 0, filled)):
                columns[name].append(value)
    data = {k: np.asarray(v) for k, v in columns.items()}
    data.update(end_us=np.array(end), sha256=np.array(digest.hexdigest()))
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, identity=np.array(identity), **data)
    return data


def ordinary_f(data):
    t = data['time_us']
    return (data['kind'] == 1) & np.r_[t[:-1] != t[1:], True]


def anchor_pairs(data, max_gap_us=2000, stop_us=None):
    t = data['time_us']
    f = np.flatnonzero(data['kind'] == 1)
    g = np.flatnonzero(data['kind'] == 0)
    j = np.searchsorted(t[f], t[g], side='right')
    good = j < len(f)
    g, j = g[good], f[j[good]]
    good = ((t[j] - t[g]) <= max_gap_us) & ordinary_f(data)[j]
    good &= (data['bid'][g] > 0) & (data['ask'][g] > data['bid'][g])
    if stop_us is not None:
        good &= t[j] < stop_us  # the anchor itself must be inside the training prefix
    return g[good], j[good]


def likelihood_matrix(data, indices, reference, max_k=12, rho=.5):
    """Rows are normalized price probabilities per component, including clamp."""
    i = np.asarray(indices)
    side, price, bid, ask = (data[k][i] for k in ('side', 'price', 'bid', 'ask'))
    clamped = np.where(side == 0, price == ask - 1, price == bid + 1)
    reference = np.asarray(reference)
    if reference.ndim == 1:
        reference = reference[:, None]
    k = np.arange(max_k + 1)
    matrix = np.zeros((len(i), max_k + 2))
    for state in reference.T:
        distance = np.where(side == 0, state - price, price - 1 - state)
        matrix[:, :-1] += np.where(clamped[:, None], k <= distance[:, None], k == distance[:, None]) / reference.shape[1]
    own = np.where(side == 0, bid, ask)
    offset = np.where(side == 0, own - price, price - own)
    # D has a two-sided geometric law around the visible own touch. Clamping
    # accumulates its lower tail at D=1-spread, rather than dropping that mass.
    matrix[:, -1] = np.where(clamped, rho ** (ask - bid - 1) / (1 + rho),
                            (1 - rho) / (1 + rho) * rho ** np.abs(offset.astype(float)))
    matrix[:, -1] = np.maximum(matrix[:, -1], 1e-300)
    matrix[np.where(side == 0, price >= ask, price <= bid)] = 0
    return matrix


def fit_mixture(matrix, counts=None, iterations=250):
    if not len(matrix):
        raise ValueError('no placement observations')
    weights = np.ones(len(matrix)) if counts is None else np.asarray(counts, dtype=float)
    theta = np.ones(matrix.shape[1]) / matrix.shape[1]
    for _ in range(iterations):
        denom = np.maximum(matrix @ theta, 1e-300)
        mass = theta * (matrix.T @ (weights / denom))
        new = (mass + .1) / (weights.sum() + .1 * len(theta))
        if np.max(np.abs(new - theta)) < 1e-9:
            theta = new
            break
        theta = new
    return theta


def fit_report(matrix, times, split_us, bootstrap=40):
    train, test = times < split_us, times >= split_us
    if train.sum() < 100 or test.sum() < 100:
        return {'status': 'insufficient observations in both folds', 'train_n': int(train.sum()), 'test_n': int(test.sum())}
    patterns, labels = np.unique(matrix[train], axis=0, return_inverse=True)
    theta = fit_mixture(patterns, np.bincount(labels, minlength=len(patterns)))
    out = {'train_n': int(train.sum()), 'test_n': int(test.sum()), 'component_weights': theta.tolist(),
           'pi_conditional_core': (theta[:-1] / theta[:-1].sum()).tolist(), 'noise_weight': float(theta[-1]),
           'train_loglik': float(np.log(matrix[train] @ theta).mean()),
           'test_loglik': float(np.log(matrix[test] @ theta).mean())}
    # Keep row patterns, resample 300-s training blocks. Conditional on anchor
    # and reference assumptions; not uncertainty in the hidden process itself.
    block = times[train] // 300_000_000
    unique = np.unique(block)
    if len(unique) < 6:
        out['uncertainty_status'] = 'fewer than six 300s training blocks; block interval suppressed'
        bootstrap = 0
    counts = np.array([np.bincount(labels[block == b], minlength=len(patterns)) for b in unique])
    rng, draws = np.random.default_rng(71), []
    for _ in range(bootstrap):
        c = counts[rng.integers(len(counts), size=len(counts))].sum(axis=0)
        fitted = fit_mixture(patterns, c, iterations=150)
        draws.append(np.r_[fitted[:-1] / fitted[:-1].sum(), fitted[-1]])
    if draws:
        out['conditional_block_ci95_pi_and_noise'] = np.quantile(draws, [.025, .975], axis=0).T.tolist()
    return out


def phase_cells(data, g, anchors):
    """Book-conditioned phase prior; never condition on the G price or side."""
    return np.column_stack((np.clip(anchors - data['bid'][g], -10, 10),
                            np.clip(data['ask'][g] - data['bid'][g], 1, 10)))


def fit_phase(matrix, cell, counts=None, iterations=300):
    """EM for common placement weights and P(lb=A | A, pre-G book).

    Half probability on each floor is biased: the book informs phase. The
    nuisance prior is shared by both sides, with a Beta(2,2) regularizer.
    """
    weights = np.ones(len(matrix)) if counts is None else np.asarray(counts, float)
    theta = np.ones(matrix.shape[2]) / matrix.shape[2]
    phase = np.full(int(cell.max()) + 1, .5)
    totals = np.bincount(cell, weights=weights, minlength=len(phase))
    for _ in range(iterations):
        prior = np.column_stack((1 - phase[cell], phase[cell]))
        z = matrix * theta[None, None, :] * prior[:, :, None]
        z *= (weights / np.maximum(z.sum((1, 2)), 1e-300))[:, None, None]
        new_theta = (z.sum((0, 1)) + .1) / (weights.sum() + .1 * len(theta))
        new_phase = (np.bincount(cell, weights=z[:, 1, :].sum(1), minlength=len(phase)) + 1) / (totals + 2)
        change = max(np.max(np.abs(theta - new_theta)), np.max(np.abs(phase - new_phase)))
        theta, phase = new_theta, new_phase
        if change < 1e-8:
            break
    return theta, phase


def phase_report(data, g, anchors, times, split_us, max_k=12, bootstrap=40, book_reference=False, phase_prior=None):
    train, test = times < split_us, times >= split_us
    if train.sum() < 100 or test.sum() < 100:
        return {'status': 'insufficient observations', 'train_n': int(train.sum()), 'test_n': int(test.sum())}
    matrix = np.stack([likelihood_matrix(data, g, anchors - 1, max_k),
                       likelihood_matrix(data, g, anchors, max_k)], axis=1)
    if book_reference:
        own = np.where(data['side'][g] == 0, data['bid'][g], data['ask'][g] - 1)
        book_matrix = likelihood_matrix(data, g, own, max_k)
        matrix = np.concatenate((matrix[:, :, :-1], np.repeat(book_matrix[:, None, :], 2, axis=1)), axis=2)
    keys = phase_cells(data, g, anchors)
    cells, cell = np.unique(keys, axis=0, return_inverse=True)
    if phase_prior is not None:
        # Side-only fits cannot identify phase and placement separately; use
        # the joint two-sided training prior, frozen before evaluating either.
        phase = np.array([phase_prior.get(tuple(k), .5) for k in cells])
        averaged = (matrix * np.column_stack((1 - phase[cell], phase[cell]))[:, :, None]).sum(1)
        result = fit_report(averaged, times, split_us, bootstrap)
        result['phase_source'] = 'frozen joint-side training fit'
        return result
    packed = np.column_stack((cell[train], matrix[train].reshape(train.sum(), -1)))
    patterns, labels = np.unique(packed, axis=0, return_inverse=True)
    cm = patterns[:, 1:].reshape(-1, 2, matrix.shape[2])
    ci = patterns[:, 0].astype(int)
    counts = np.bincount(labels, minlength=len(patterns))
    iterations = 1000 if book_reference else 300
    theta, fitted_phase = fit_phase(cm, ci, counts, iterations=iterations)
    phase = np.full(len(cells), .5)
    phase[:len(fitted_phase)] = fitted_phase
    prob = (matrix @ theta * np.column_stack((1 - phase[cell], phase[cell]))).sum(1)
    out = {'train_n': int(train.sum()), 'test_n': int(test.sum()), 'component_weights': theta.tolist(),
           'pi_conditional_core': (theta[:-1] / theta[:-1].sum()).tolist(), 'noise_weight': float(theta[-1]),
           'train_loglik': float(np.log(prob[train]).mean()), 'test_loglik': float(np.log(prob[test]).mean()),
           'phase_cells': [{'anchor_minus_bid': int(k[0]), 'spread': int(k[1]), 'p_upper': float(p)}
                           for k, p in zip(cells, phase)]}
    if book_reference:
        n = max_k + 1
        out.update(latent_weight=float(theta[:n].sum()), book_weight=float(theta[n:-1].sum()),
                   pi_conditional_core=(theta[:n] / theta[:n].sum()).tolist(),
                   book_pi=(theta[n:-1] / theta[n:-1].sum()).tolist())
    block = times[train] // 300_000_000
    bc = np.array([np.bincount(labels[block == b], minlength=len(patterns)) for b in np.unique(block)])
    if len(bc) < 6:
        out['uncertainty_status'] = 'fewer than six 300s training blocks; block interval suppressed'
        bootstrap = 0
    rng, draws = np.random.default_rng(72), []
    for _ in range(bootstrap):
        th, _ = fit_phase(cm, ci, bc[rng.integers(len(bc), size=len(bc))].sum(0), iterations=iterations if book_reference else 300)
        draws.append(np.r_[th[:max_k + 1] / th[:max_k + 1].sum(), th[-1], th[max_k + 1:-1].sum()] if book_reference
                     else np.r_[th[:-1] / th[:-1].sum(), th[-1]])
    if draws:
        out['conditional_block_ci95_pi_and_noise'] = np.quantile(draws, [.025, .975], axis=0).T.tolist()
        if book_reference:
            out['conditional_ci_columns'] = 'latent pi0..K, noise_weight, book_weight; conditional on model'
    return out


def ladder_labels(data):
    """Descriptive full-chain labels, including the parent; never online inputs."""
    labels = np.zeros(len(data['kind']), bool)
    own_offset = np.where(data['side'] == 0, data['bid'] - data['price'], data['price'] - data['ask'])
    for side in (0, 1):
        ix = np.flatnonzero((data['kind'] == 0) & (data['side'] == side))
        t = data['time_us'][ix]
        parent = np.searchsorted(t, t - 2000, side='right') - 1
        valid = parent >= 0
        ii, pp = ix[valid], ix[parent[valid]]
        good = (data['time_us'][ii] - data['time_us'][pp] == 2000)
        good &= (own_offset[ii] >= 2) & (own_offset[ii] <= 7) & (own_offset[pp] >= 2) & (own_offset[pp] <= 7)
        labels[ii[good]] = True
        labels[pp[good]] = True
    return labels


def exact_truth(data, latent_path):
    latent = np.loadtxt(latent_path, delimiter=',', skiprows=1)
    grid = np.rint(latent[:, 0] * 1e6).astype(np.int64)
    t = data['time_us']
    j = np.searchsorted(grid, t, side='right')
    next_t = np.r_[t[1:], np.iinfo(np.int64).max]
    safe = j < len(grid)
    bounded = np.minimum(j, len(grid) - 1)
    safe &= (data['kind'] == 0) & (grid[bounded] < next_t)
    if 'end_us' in data:
        safe &= grid[bounded] < int(data['end_us'])
    safe &= (data['bid'] > 0) & (data['ask'] > data['bid'])
    # Latent logger rounds to four decimals; do not floor near an integer.
    level = latent[bounded, 1]
    safe &= np.abs(level - np.rint(level)) > .00011
    return safe, np.floor(level).astype(np.int64), latent[bounded, 2].astype(int)


def measure(data, latent_path=None, max_k=12, minutes=None, bootstrap=40):
    limit = min(int(data['end_us']), round(minutes * 60e6)) if minutes else int(data['end_us'])
    duration = int(data['end_us']) / 1e6
    prefix = data['time_us'] < limit
    data = {k: v[prefix] if np.asarray(v).ndim == 1 and len(v) == len(prefix) else v for k, v in data.items()}
    data['end_us'] = np.array(limit)
    valid = (data['kind'] == 0) & (data['bid'] > 0) & (data['ask'] > data['bid'])
    crossing = valid & np.where(data['side'] == 0, data['price'] >= data['ask'], data['price'] <= data['bid'])
    if crossing.any():
        raise ValueError(f'{crossing.sum()} G orders cross the pre-insert book; clamp model unsupported')
    split = round(limit * .75)
    out = {'source_sha256': str(data['sha256']), 'duration_s': duration,
           'prefix_s': limit / 1e6, 'split_s': split / 1e6, 'k_support': list(range(max_k + 1)),
           'assumptions': ['Ordinary F limit at latent plus/minus1 tick.', 'Learned phase conditions on anchor location relative to the pre-G book; uniform phase is a diagnostic.',
                           'Near-F sampling may select a different regime mix; check gap and truth sensitivity.',
                           'Proper normalized likelihood; existing filter eps+pi scores are not comparable when optimizing eps.'],
           'g_clamp_share': float(np.mean(np.where(data['side'][data['kind'] == 0] == 0,
                                    data['price'][data['kind'] == 0] == data['ask'][data['kind'] == 0] - 1,
                                    data['price'][data['kind'] == 0] == data['bid'][data['kind'] == 0] + 1))),
           'gaps': {}}
    truth = exact_truth(data, latent_path) if latent_path else None
    for gap in (500, 1000, 2000, 5000):
        g, f = anchor_pairs(data, gap, limit)
        anchors = data['price'][f] - np.where(data['side'][f] == 0, 1, -1)
        states = np.column_stack((anchors - 1, anchors))
        references = {'F_anchor_interval': states,
                      'visible_own_touch': np.where(data['side'][g] == 0, data['bid'][g], data['ask'][g] - 1),
                      'visible_mid_floor': (data['bid'][g] + data['ask'][g]) // 2}
        result = {}
        for name, reference in references.items():
            matrix = likelihood_matrix(data, g, reference, max_k)
            result[name] = fit_report(matrix, data['time_us'][f], split, bootstrap if gap == 2000 else 0)
        result['F_anchor_learned_phase'] = phase_report(data, g, anchors, data['time_us'][f], split, max_k,
                                                       bootstrap if gap == 2000 else 0)
        if gap == 2000:
            result['F_anchor_book_mixture'] = phase_report(data, g, anchors, data['time_us'][f], split,
                                                          max_k, bootstrap, book_reference=True)
            phase_prior = {(x['anchor_minus_bid'], x['spread']): x['p_upper']
                           for x in result['F_anchor_learned_phase'].get('phase_cells', [])}
            ladder = ladder_labels(data)
            mid = (data['bid'] + data['ask']) / 2
            past = np.maximum(0, np.searchsorted(data['time_us'], data['time_us'] - 5_000_000) - 1)
            moves = np.r_[0, np.cumsum(np.abs(np.diff(mid)))]
            activity = moves - moves[past]
            threshold = float(np.median(activity[g[data['time_us'][f] < split]]))
            out['activity_proxy_threshold_5s_total_mid_move'] = threshold
            masks = {'bid': data['side'][g] == 0, 'ask': data['side'][g] == 1,
                     'ladder': ladder[g], 'non_ladder': ~ladder[g],
                     'calm_proxy': activity[g] <= threshold, 'active_proxy': activity[g] > threshold}
            result['strata'] = {label: phase_report(data, g[mask], anchors[mask], data['time_us'][f[mask]], split, max_k, 0,
                                                   phase_prior=phase_prior if label in ('bid', 'ask') else None)
                                for label, mask in masks.items()}
        if truth:
            safe, lb, regime = truth
            ix = g[safe[g]]
            result['exact_truth_same_subset'] = fit_report(likelihood_matrix(data, ix, lb[ix], max_k),
                                                         data['time_us'][ix], split, bootstrap if gap == 2000 else 0)
            result['truth_subset_n'] = len(ix)
        out['gaps'][str(gap)] = result
    if truth:
        safe, lb, regime = truth
        for label, select in [('all', safe), ('calm', safe & (regime == 0)), ('volatile', safe & (regime == 1))]:
            ix = np.flatnonzero(select & (data['time_us'] < limit))
            out[f'exact_truth_{label}'] = fit_report(likelihood_matrix(data, ix, lb[ix], max_k), data['time_us'][ix], split, 0)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('tape', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--latent', type=Path)
    parser.add_argument('--minutes', type=float)
    parser.add_argument('--max-k', type=int, default=12)
    parser.add_argument('--bootstrap', type=int, default=40)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.max_k < 2 or args.max_k > 100 or args.bootstrap < 0 or (args.minutes is not None and args.minutes <= 0):
        parser.error('max-k must be2-100, bootstrap nonnegative, and minutes positive')
    start = time.monotonic()
    report = measure(read_events(args.tape, args.cache), args.latent, args.max_k, args.minutes, args.bootstrap)
    report['elapsed_s'] = time.monotonic() - start
    report['source'] = str(args.tape)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    for gap, result in report['gaps'].items():
        for reference, r in result.items():
            if isinstance(r, dict):
                print(gap, reference, r.get('train_n'), r.get('test_n'), r.get('test_loglik'), r.get('pi_conditional_core', [])[:4], r.get('noise_weight'))
    print('seconds', report['elapsed_s'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
