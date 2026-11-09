"""Causal flow diagnostics and trustworthy round-transfer comparisons."""
import numpy as np
import pytest

from experiments.generator.gen_round_fit import BOT_NAMES, STAT_KEYS, distance, family_scores, flow_stats, load_cases, summarize


def events():
    rows = []
    for i in range(40):
        t = (i + 1) * 200_000
        # Centre=102, above pre-F mid=100.5. Six strictly previous Gs.
        rows.extend((t - 50_000 + j, 0, j % 2, 101 + 2 * (j % 2)) for j in range(6))
        rows.append((t, 1, 0 if i % 4 else 1, 100))
        # Same-time and future prices must never enter this F's proxy.
        rows.extend((t, 0, j % 2, -1000) for j in range(6))
    a = np.array(sorted(rows), dtype=np.int64)
    return dict(time_us=a[:, 0], kind=a[:, 1], side=a[:, 2], price=a[:, 3],
                bid=np.full(len(a), 100), ask=np.full(len(a), 101), end_us=a[-1, 0])


def test_prior_g_alignment_excludes_simultaneous_and_future_orders():
    got = flow_stats(events())
    assert got['prior_G_alignment']['1.0'] == {'n': 40, 'follow_share': .75}
    assert sum(x['n_aligned'] for x in got['by_1000s']) == 40


def test_side_persistence_accounts_for_unconditional_buy_share():
    got = flow_stats(events())
    assert got['buy_share'] == .75
    assert got['iid_same_side'] == .625
    assert got['excess_same_side'] == pytest.approx(got['same_side'] - .625)


def test_report_maps_f3_to_generator_filter_bot(tmp_path):
    p = tmp_path / 'family.txt'
    names = ['F3' if n == 'B1F' else n for n in BOT_NAMES]
    p.write_text('bot pnl first last\n' + '\n'.join(f'{n} 1,000 750 250 extra' for n in names))
    assert family_scores(p)['B1F'] == dict(pnl=1000, first75=750, last25=250)
    p.write_text('F3 1000 750 250\n')
    with pytest.raises(ValueError, match='needs'):
        family_scores(p)


def test_case_archive_selects_exact_options_and_rejects_duplicates(tmp_path):
    p = tmp_path / 'cases.json'
    p.write_text('{"cases":{"base":{"informed":0},"flow":{"informed":0.25}}}')
    assert load_cases([], p, 'flow') == {'flow': {'informed': .25}}
    with pytest.raises(ValueError, match='duplicate'):
        load_cases(['flow={}'], p)
    with pytest.raises(ValueError, match='simple names'):
        load_cases(['../escape={}'])


def test_wrong_sign_impact_cannot_improve_distance_by_disappearing():
    f = flow_stats(events())
    ref = dict(stats={k: 1. for k in STAT_KEYS}, flow=f)
    obs = dict(stats=dict(ref['stats']), flow=f)
    assert distance(obs, ref)['stat_log_rmse'] == 0
    obs['stats']['imp<=60'] = -1.
    assert distance(obs, ref)['stat_log_rmse'] > 1
    del obs['stats']['sd1']
    with pytest.raises(ValueError, match='sd1'):
        distance(obs, ref)


def test_quote_contrasts_use_paired_seeds_and_reject_duplicates():
    ref = dict(stats={k: 1. for k in STAT_KEYS})
    rows = [dict(case='a', seed=i, measurement=ref, scores={k: 100. for k in BOT_NAMES}) for i in (1, 2, 3)]
    for row, gain in zip(rows, (1, 2, 3)):
        row['scores']['L8'] += gain
    contrast = summarize(rows, ref)['a']['contrasts']['L8-L3']
    assert contrast['per_seed'] == [1., 2., 3.]
    assert contrast['mean'] == 2.
    assert contrast['seed_se'] == pytest.approx(1 / np.sqrt(3))
    with pytest.raises(ValueError, match='duplicate'):
        summarize(rows + [rows[0]], ref)


def test_drift_gate_suppresses_calm_motion_and_permits_active_motion(tmp_path):
    from experiments.generator.tape_gen import generate
    from test_gen_inventory import params
    p = params()
    p['f_rate'] = 0.
    p['latent'].update(drift_sd=3., drift_tau=1., jx_rate_off=1e-12, jx_rate_on=1e-12)
    paths = []
    for gate in (False, True):
        p['latent']['drift_jx_only'] = gate
        tape, latent = tmp_path / f'{gate}.csv', tmp_path / f'{gate}_latent.csv'
        generate(p, 71, 10., tape, latent)
        paths.append(np.loadtxt(latent, delimiter=',', skiprows=1)[:, 1])
    assert np.ptp(paths[0]) > 1
    assert np.ptp(paths[1]) == 0
    p['latent'].update(jx_rate_on=2e-12, jx_dwell_off=1e-5, jx_dwell_on=100_000.)
    latent = tmp_path / 'active_latent.csv'
    generate(p, 71, 10., tmp_path / 'active.csv', latent)
    active = np.loadtxt(latent, delimiter=',', skiprows=1)
    assert np.mean(active[:, 2] == 1) > .99
    assert np.ptp(active[:, 1]) > 1


def test_score_rejects_binary_replaced_during_batch(tmp_path, monkeypatch):
    from experiments.generator import gen_round_fit as fit
    binary = tmp_path / 'simulator'
    binary.write_bytes(b'old executable')
    def changed(*args, **kwargs):
        binary.write_bytes(b'new executable')
        return [[{'pnl': 100.}]] * len(BOT_NAMES)
    monkeypatch.setattr(fit.qsim_rust, 'run_batch', changed)
    previous_binary = fit.qsim_rust.BINARY
    with pytest.raises(ValueError, match='changed during'):
        fit.score(tmp_path / 'tape.csv', binary)
    assert fit.qsim_rust.BINARY == previous_binary
