"""Estimate and forecast-check filter settings from a causal public-tape prefix.

    uv run python -m experiments.day.filter_settings TAPE --minutes 20 --out settings.json

Writes only existing Rust FILTER_* keys; latent_filter accepts the same file
with --settings. A sibling .report.json separates estimates, unsupported model
parameters, candidate forecasts and fallback reasons. A .reference.json is an
OFFLINE structural hypothesis, not an accepted Rust settings file.

Fit parameters on the first75% of the selected prefix. Select a compatible
candidate using first75% correlations, then require at least .005 absolute
correlation gain at BOTH .4/1s in BOTH folds. Otherwise retain F3's baseline.
This explicit operational screen is not a significance test or a PnL claim.
Reference-mixture and linear-impact arms are diagnostics and cannot silently alter Rust behavior.
--full reproduces the requested whole-tape B comparison. Single process/thread;
no future observations beyond --minutes contribute to fitted/exported values.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import numpy as np

from experiments.day import filter_placement as placement
from experiments.day import filter_process_probe as process
from experiments.day.latent_filter import DEFAULTS, SETTINGS_KEYS, replay

BASELINE = dict(FILTER_PI0=.55, FILTER_PI1=.39, FILTER_PI2=.06, FILTER_RATE=2.,
                FILTER_IMPACT=3., FILTER_SQRT_C=0., FILTER_DEPTH=6, FILTER_EPS=.01)


def process_events(data, limit):
    keep = (data['kind'] == 1) & (data['time_us'] < limit)
    return dict(t=data['time_us'][keep] / 1e6, sign=np.where(data['side'][keep] == 0, 1., -1.),
                qty=data['qty'][keep].astype(float), price=data['price'][keep].astype(float),
                filled=data['filled'][keep].astype(float), ordinary=placement.ordinary_f(data)[keep],
                insert_t=data['time_us'][data['time_us'] < limit] / 1e6,
                duration=np.array(limit / 1e6), sha256=data['sha256'])


def candidate_models(estimated, impact, noise, impact_laws=None):
    base = {SETTINGS_KEYS[k]: v for k, v in BASELINE.items()}
    pure = estimated['gaps']['2000']['F_anchor_learned_phase']
    mix = estimated['gaps']['2000']['F_anchor_book_mixture']
    pi = np.asarray(pure['pi_conditional_core'][:3])
    pi /= pi.sum()
    pset = {f'pi{k}': float(v) for k, v in enumerate(pi)}
    # These are explicit hypotheses, not claims that F-anchor assumptions or
    # a diffusion-only interpretation have been identified on this tape.
    c = max(0., min(.2, impact['immediate_c']))
    variance = noise['horizons']['1.0']['train']['rounding_corrected_variance_per_s']
    rate = max(0., min(30., variance / 2))
    reference = dict(latent_pi=mix['pi_conditional_core'], book_pi=mix['book_pi'],
                     book_weight=mix['book_weight'], noise_weight=mix['noise_weight'])
    models = dict(baseline=base, placement={**base, **pset},
                  impact={**base, 'sqrt_c': c, 'impact_scale': 0 if c == 0 else base['impact_scale']},
                  placement_impact={**base, **pset, 'sqrt_c': c, 'impact_scale': 0 if c == 0 else base['impact_scale']},
                  variance_as_diffusion={**base, 'rate': rate},
                  reference={**base, 'reference': reference},
                  reference_impact={**base, 'reference': reference, 'sqrt_c': c,
                                    'impact_scale': 0 if c == 0 else base['impact_scale']})
    if impact_laws:
        fits = impact_laws['sizes']['filled']['fits']
        models['fitted_table'] = {**base, 'impact_scale': max(0., fits['r1_table']['immediate_c'])}
        linear = max(0., fits['linear']['immediate_c'])
        models['linear_impact'] = {**base, 'linear_c': linear, 'sqrt_c': 0.,
                                   'impact_scale': 0 if linear == 0 else base['impact_scale']}
    return models, reference


def correlations(rows, column, split_s=None):
    n, cut = len(rows), int(len(rows) * .75)
    out = {}
    if split_s is not None:
        # Use the same wall-clock cutoff as parameter fitting. Missing book
        # samples must neither shorten the horizon nor move the holdout start.
        t = rows[:, 0]
        for name, first in [('first75', True), ('last25', False)]:
            out[name] = {}
            for h in (.4, 1.):
                j = np.searchsorted(t, t + h - 1e-7)
                good = j < n
                bounded = np.minimum(j, n - 1)
                good &= np.abs(t[bounded] - t - h) < 1e-6
                good &= (t < split_s) if first else (t >= split_s)
                for purged in (False, True):
                    use = good & ((t[bounded] < split_s) if first and purged else True)
                    ix = np.flatnonzero(use)
                    y, x = rows[j[ix], 1] - rows[ix, 1], rows[ix, column]
                    value = float(np.corrcoef(x, y)[0, 1]) if len(ix) > 2 and np.std(x) and np.std(y) else None
                    out[name][f'{h:g}s' + ('_purged' if purged else '')] = value
        return out
    for name, lo, hi in [('first75', 0, cut), ('last25', cut, n)]:
        out[name] = {}
        for h in (.4, 1.):
            lag = round(h / .05)
            # Match latent_filter.evaluate exactly, and also report purged
            # training labels whose endpoints remain strictly in that fold.
            for purged in (False, True):
                end = min(hi - lag if purged else hi, n - lag)
                ix = np.arange(lo, end)
                y, x = rows[ix + lag, 1] - rows[ix, 1], rows[ix, column]
                corr = float(np.corrcoef(x, y)[0, 1]) if len(ix) > 2 and np.std(x) and np.std(y) else None
                out[name][f'{h:g}s' + ('_purged' if purged else '')] = corr
    return out


def _selection(results, models, minimum_gain):
    baseline = results['baseline'].get('causal_correlations', results['baseline']['correlations'])
    compatible = [n for n, p in models.items() if n != 'baseline' and 'reference' not in p and 'linear_c' not in p]
    def gain(name, fold, h):
        candidate = results[name].get('causal_correlations', results[name]['correlations'])
        a, b = candidate[fold][h + '_purged'], baseline[fold][h + '_purged']
        return a - b if a is not None and b is not None else -1e9
    chosen = max(compatible, key=lambda n: min(gain(n, 'first75', h) for h in ('0.4s', '1s')))
    changes = {fold: {h: gain(chosen, fold, h) for h in ('0.4s', '1s')} for fold in ('first75', 'last25')}
    passed = min(v for a in changes.values() for v in a.values()) >= minimum_gain
    selected = chosen if passed else 'baseline'
    settings = {key: models[selected][value] for key, value in SETTINGS_KEYS.items() if key in BASELINE}
    return settings, dict(selected=selected, selected_on_training=chosen, gains=changes, passed=passed,
                          minimum_absolute_correlation_gain=minimum_gain,
                          qualification='Operational screen, not statistical significance or a bot-profit test; structural reference/linear arms are not exported.')


def forecast_diagnostics(rows, column, split_s):
    """Frozen gap-only regression; future-move strata are evaluation-only."""
    t, mid, signal = rows[:, 0], rows[:, 1], rows[:, column]
    out = {}
    for h in (.4, 1.):
        j = np.searchsorted(t, t + h - 1e-7)
        good = j < len(t)
        bounded = np.minimum(j, len(t) - 1)
        good &= np.abs(t[bounded] - t - h) < 1e-6
        train = good & (t[bounded] < split_s)
        test = good & (t >= split_s)
        y = mid[bounded] - mid
        x = np.column_stack((np.ones(len(t)), signal))
        if train.sum() < 20 or test.sum() < 20:
            continue
        beta = np.linalg.lstsq(x[train], y[train], rcond=None)[0]
        error = (y - x @ beta) ** 2
        energy = float(np.sum(y[test] ** 2))
        result = {'training_beta': beta.tolist(), 'qualification': 'Descriptive holdout strata; future moves never select settings.'}
        for name, large in [('under5ticks', False), ('at_least5ticks', True)]:
            use = test & ((np.abs(y) >= 5) == large)
            result[name] = dict(n=int(use.sum()), mse=float(np.mean(error[use])) if use.any() else None,
                                target_squared_move_share=float(np.sum(y[use] ** 2) / energy) if energy else None)
        out[f'{h:g}s'] = result
    return out


def run(tape, out, minutes=20., cache=None, bootstrap=20, rows_out=None):
    started = time.monotonic()
    data = placement.read_events(tape, cache)
    limit = min(int(data['end_us']), round(minutes * 60e6)) if minutes is not None else int(data['end_us'])
    report = dict(source=str(tape), source_sha256=str(data['sha256']), prefix_s=limit / 1e6,
                  baseline_settings=BASELINE, settings_status='pending', version=3)
    reason = 'fewer than five minutes' if limit < 300e6 else None
    g, f = placement.anchor_pairs(data, 2000, limit) if len(data['time_us']) else ([], [])
    if reason is None:
        anchor_train = np.sum(data['time_us'][f] < .75 * limit)
        f_times = data['time_us'][(data['kind'] == 1) & (data['time_us'] < limit)]
        if min(anchor_train, len(f) - anchor_train) < 100:
            reason = 'fewer than100 nearby G/F observations in either fold'
        elif np.sum(f_times < .75 * limit) < 20 or np.sum(f_times >= .75 * limit) < 10:
            reason = 'too few F observations in a process-fit fold'
    if reason:
        settings = dict(BASELINE)
        report.update(settings_status='baseline: ' + reason, settings=settings)
    else:
        estimates = placement.measure(data, minutes=limit / 60e6, bootstrap=bootstrap)
        events = process_events(data, limit)
        requested = process.observable_fit(events)
        filled = process.observable_fit(events, filled=True)
        impact_laws = process.compare_impact_laws(events, requested, filled)
        noise = process.noise_diagnostics(events, requested)
        models, reference = candidate_models(estimates, filled, noise, impact_laws)
        out.with_suffix('.reference.json').write_text(json.dumps(reference, indent=2) + '\n')
        report.update(placement=estimates, impact_requested=requested, impact_filled=filled, impact_laws=impact_laws, process_noise=noise,
                      candidate_params=models)
        # One replay/book, independent filters; no candidate uses future
        # F anchors as online observations. Only the frozen parameters use them.
        names = list(models)
        rows, _, _ = replay(tape, {**DEFAULTS, **models['baseline']},
                            extra=tuple(models[n] for n in names[1:]), until_s=limit / 1e6)
        likelihoods = [replay.last_loglik] + replay.last_extra_loglik
        results = {}
        if len(rows) < 40:
            settings = dict(BASELINE)
            report.update(settings_status='baseline: fewer than40 valid replay samples', settings=settings, samples=len(rows))
            return finish(report, settings, out, started)
        for i, name in enumerate(names):
            ll, count = likelihoods[i]
            results[name] = dict(correlations=correlations(rows, 2 if i == 0 else 6 + i),
                                 causal_correlations=correlations(rows, 2 if i == 0 else 6 + i, split_s=.75 * limit / 1e6),
                                 diagnostics=forecast_diagnostics(rows, 2 if i == 0 else 6 + i, .75 * limit / 1e6),
                                 insert_log_score=ll / max(1, count), observed_inserts=count,
                                 likelihood_kind='unconditioned normalized price likelihood on depth-selected observations' if 'reference' in models[name] else 'legacy eps+pi score; not normalized')
        settings, selection = _selection(results, models, .005)
        report.update(forecasts=results, selection=selection, settings=settings,
                      settings_status='forecast-screened compatible hypothesis' if selection['passed'] else 'baseline fallback: forecast gate failed',
                      samples=len(rows), unsupported=['Latent diffusion/jump decomposition and per-regime jump law',
                        'Permanent/transient impact split and decay tau', 'F-price anchor rule on real volatile tapes',
                        'Reference mixture needs main-session implementation before bot/Rust use'])
        if rows_out:
            rows_out.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(rows_out, rows=rows, names=np.array(names))
    return finish(report, settings, out, started)


def finish(report, settings, out, started):
    report['parameter_minutes'] = dict(placement='5-10min for a rough effective PMF; at least40min for six training blocks; hidden-regime coverage unproved',
        immediate_impact='5-20min recovered synthetic impact; real anchors are misspecified, so forecast gate required',
        rate='No minimum established for diffusion alone; effective variance changes strongly across5/10/20min',
        depth_eps='Retained F3 defaults; no claim of identification', permanent_impact_tau='Not identified even on the complete real tapes')
    report['elapsed_s'] = time.monotonic() - started
    report['under_5_minutes'] = report['elapsed_s'] < 300
    out.write_text(json.dumps(settings, indent=2, allow_nan=False) + '\n')
    out.with_suffix('.report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('tape', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--minutes', type=float, default=20.)
    ap.add_argument('--full', action='store_true', help='use entire tape for the first75/last25 B test')
    ap.add_argument('--cache', type=Path)
    ap.add_argument('--bootstrap', type=int, default=20)
    ap.add_argument('--rows-out', type=Path)
    args = ap.parse_args(argv)
    if not np.isfinite(args.minutes) or args.minutes <= 0 or args.bootstrap < 0:
        ap.error('minutes must be finite and positive; bootstrap nonnegative')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    r = run(args.tape, args.out, None if args.full else args.minutes, args.cache, args.bootstrap, args.rows_out)
    print(json.dumps({k: r[k] for k in ('prefix_s', 'settings_status', 'settings', 'elapsed_s', 'under_5_minutes')}, indent=2))
    for name, result in r.get('forecasts', {}).items():
        print(name, result['correlations'], 'insert_score', result['insert_log_score'], flush=True)


if __name__ == '__main__':
    main()
