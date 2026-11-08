"""Causal flow diagnostics and trustworthy round-transfer comparisons."""
import numpy as np
import pytest

from experiments.day.gen_round_fit import BOT_NAMES, STAT_KEYS, distance, family_scores, flow_stats


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
