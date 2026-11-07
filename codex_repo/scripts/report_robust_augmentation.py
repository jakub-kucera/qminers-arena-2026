"""Freeze the recommended export and report every bounded augmentation trial."""
import argparse
import ast
import html
import json
from pathlib import Path
import shutil
import time

from scripts.benchmark import digest
from scripts.check_submission import check


def read(root, name):
    return json.loads((root/(name+'.json')).read_text())


def assess(root):
    protocol, selection = read(root, 'protocol'), read(root, 'selection')
    name = selection['confirmation_candidate']
    base = read(root, 'full_baseline')['clean_554347']
    candidate = read(root, 'full_candidate')[name]
    official = read(root, 'baseline_official')
    assert base['result'] == official['result']
    assert base['curve_sha256'] == official['curve_sha256']
    sample_b = read(root, 'sample_baseline')['clean_554347']
    sample_c = read(root, 'sample_candidate')[name]
    periods = []
    before_b = before_c = 0
    for label, boundary in [('Screen, first 50 minutes', '3000000000'),
                            ('Screen, next 49m 50s', '5990000000'),
                            ('Confirmation, to 150 minutes', '9000000000'),
                            ('Confirmation, final 50 minutes', None)]:
        b = base['boundary_pnl'][boundary] if boundary else base['result']['pnl']
        c = candidate['boundary_pnl'][boundary] if boundary else candidate['result']['pnl']
        periods.append({'period': label, 'baseline': b-before_b,
                        'candidate': c-before_c, 'gain': c-before_c-b+before_b})
        before_b, before_c = b, c
    stress = []
    all_runs = [base, candidate, sample_b, sample_c]
    for delay in (20, 50):
        b = read(root, f'full_latency{delay}_baseline')['clean_554347']
        c = read(root, f'full_latency{delay}_candidate')[name]
        all_runs.extend([b, c])
        stress.append({'delay_ms': delay, 'baseline': b['result']['pnl'],
                       'candidate': c['result']['pnl'],
                       'baseline_drawdown': b['max_drawdown_1s'],
                       'candidate_drawdown': c['max_drawdown_1s']})
    gain = candidate['result']['pnl']-base['result']['pnl']
    checks = {
        'screen_passed': selection['selected'] == name,
        'later_period_1_gain': periods[2]['gain'] > 0,
        'later_period_2_gain': periods[3]['gain'] > 0,
        'full_gain_at_least_half_percent': gain >= .005*base['result']['pnl'],
        'transfer_loss_at_most_one_percent': sample_c['result']['pnl'] >= .99*sample_b['result']['pnl'],
        'latency20_loss_at_most_one_percent': stress[0]['candidate'] >= .99*stress[0]['baseline'],
        'latency50_loss_at_most_one_percent': stress[1]['candidate'] >= .99*stress[1]['baseline'],
        'normal_latency_drawdown_within_125_percent': candidate['max_drawdown_1s'] <= 1.25*base['max_drawdown_1s'],
        'all_risk_invariants': all(r['result']['breach_penalty'] == 0 and r['max_abs_inventory'] <= 100
                                   and r['max_potential_inventory'] <= 100 for r in all_runs),
    }
    promoted = all(checks.values())
    recommended = name if promoted else 'clean_554347'
    return {'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'promoted': promoted, 'candidate': name, 'recommended': recommended,
            'checks': checks, 'baseline_pnl': base['result']['pnl'],
            'candidate_pnl': candidate['result']['pnl'], 'gain': gain,
            'gain_percent': 100*gain/base['result']['pnl'], 'periods': periods,
            'baseline_drawdown': base['max_drawdown_1s'],
            'candidate_drawdown': candidate['max_drawdown_1s'],
            'sample_v2': {'baseline': sample_b['result']['pnl'], 'candidate': sample_c['result']['pnl']},
            'stress': stress, 'recommended_source': protocol['sources'][recommended],
            'limitation': 'Previously consumed public tapes; no independent holdout or new website score.'}


def export(root):
    decision_path = root/'decision.json'
    destination = Path('strategies/round1_robust_candidate.py')
    if decision_path.exists() or destination.exists():
        raise FileExistsError('Refusing to overwrite a frozen recommendation')
    decision = assess(root)
    source = Path(decision['recommended_source']['source'])
    assert digest(source) == decision['recommended_source']['sha256']
    text = source.read_text()
    parsed = ast.parse(text)
    cls = next(n for n in parsed.body if isinstance(n, ast.ClassDef))
    constants = {n.targets[0].id: n.value.value for n in cls.body
                 if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                 and isinstance(n.value, ast.Constant)}
    header = f'''"""Causal online market maker retained by a bounded robustness experiment.

{constants['FEATURE_COUNT']} features; {constants['HORIZON_US']/1000:g} ms matured midpoint labels sampled every
20 ms; exponentially weighted ridge regression refit once per second.
Model memory e-folding time: {constants['MODEL_MEMORY_US']/1000000:g} seconds. No pre-fitted weights.

The latest upstream execution is preserved: selective one-tick inside quotes,
fresh cached replenishment after cancel confirmations, and independent per-side
reservations including pending sends/cancels. Actual/potential limit: +/-100.
No files, future rows, absolute-price features, or session-end assumptions.

The inherited +/-1.1 normalized-flow thresholds are inactive by construction;
inventory bounds remain active. Public-tape checks cannot certify new-data PnL.
"""'''
    text = header+text[text.index('"""', 3)+3:]
    assert ast.dump(ast.Module(body=ast.parse(text).body[1:], type_ignores=[])) == ast.dump(
        ast.Module(body=parsed.body[1:], type_ignores=[]))
    if decision['promoted']:
        destination.write_text(text, encoding='utf-8', newline='\n')
    else:
        # With no promotion, preserve the exact cleaned baseline bytes so a
        # concurrently running official replay verifies the eventual export.
        shutil.copyfile(source, destination)
    assert not check(destination)
    decision['export_file'] = str(destination)
    decision['export_sha256'] = digest(destination)
    candidate_source = root/'sources'/(decision['candidate']+'.py')
    candidate_text = candidate_source.read_text()
    experimental = Path('strategies/round1_spread_pressure_experimental.py')
    if experimental.exists():
        raise FileExistsError(experimental)
    experimental_header = '''"""Experimental 17-feature augmentation of the 554347 online market maker.

Adds spread-scaled capped-volume and order-count imbalance, using min(4,spread).
All execution rules and baseline model parameters remain unchanged.
This experiment failed the predeclared simultaneous screening bound and is
retained for research, not promoted as the recommended submission. Both public
tapes were previously consumed; consult the full robustness report.
"""'''
    experimental_text = experimental_header+candidate_text[candidate_text.index('"""', 3)+3:]
    assert ast.dump(ast.Module(body=ast.parse(experimental_text).body[1:], type_ignores=[])) == ast.dump(
        ast.Module(body=ast.parse(candidate_text).body[1:], type_ignores=[]))
    experimental.write_text(experimental_text, encoding='utf-8', newline='\n')
    assert not check(experimental)
    decision['experimental_export_file'] = str(experimental)
    decision['experimental_export_sha256'] = digest(experimental)
    decision['experimental_frozen_source_sha256'] = digest(candidate_source)
    decision_path.write_text(json.dumps(decision, indent=2)+'\n')
    print(json.dumps(decision, indent=2))


def plot_results(root, output, candidate, selection):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    base = np.asarray(json.loads((root/'full_baseline/clean_554347/pnl.json').read_text()))
    new = np.asarray(json.loads((root/'full_candidate'/candidate/'pnl.json').read_text()))
    # Official samples are anchored identically; terminal drain times can differ.
    times, ib, ic = np.intersect1d(base[:-1, 0], new[:-1, 0], return_indices=True)
    delta = new[ic, 1]-base[ib, 1]
    scores = selection['scores']
    names = sorted(scores, key=lambda n: scores[n]['gain'])
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), gridspec_kw={'width_ratios': [1.1, 1]})
    axes[0].plot(times/60000000, delta, color='#087e8b', lw=1.5)
    axes[0].axhline(0, color='#78838f', lw=.8)
    axes[0].axvspan(0, 5990/60, color='#c2d2e8', alpha=.4)
    axes[0].axvline(5990/60, color='#50647a', ls='--', lw=.8)
    axes[0].axvline(150, color='#50647a', ls=':', lw=.8)
    axes[0].set(title='Frozen candidate minus 554,347 baseline', xlabel='Elapsed minutes', ylabel='Cumulative PnL difference')
    axes[0].text(.02, .97, 'Shaded: screening window\nAll periods use previously consumed data',
                 va='top', transform=axes[0].transAxes, fontsize=9)
    y = np.arange(len(names))
    gains = np.array([scores[n]['gain'] for n in names])
    lower = np.array([scores[n]['simultaneous_lower_bound'] for n in names])
    axes[1].barh(y, gains, color=['#087e8b' if scores[n]['eligible'] else '#a9b3bd' for n in names])
    axes[1].hlines(y, lower, gains, color='#263746', lw=1.5)
    axes[1].scatter(lower, y, marker='|', color='#263746', s=70)
    axes[1].axvline(0, color='#78838f', lw=.8)
    axes[1].set(yticks=y, yticklabels=names, xlabel='PnL gain through 5,990 seconds',
                title='All 11 trials and simultaneous lower bounds')
    for axis in axes:
        axis.spines[['top', 'right']].set_visible(False)
        axis.grid(axis='x', alpha=.15)
    fig.suptitle('Bounded augmentation of the latest repository model', fontsize=15, weight='bold')
    fig.text(.5, .01, 'Bounds: 20,000 paired circular-block bootstrap draws; conditional selection diagnostic, not proof of generalization.',
             ha='center', fontsize=8)
    fig.tight_layout(rect=[0, .035, 1, .94])
    fig.savefig(output/'Qminers-robust-augmentation.png', dpi=160)
    plt.close(fig)


def report(root, output, archive):
    decision = read(root, 'decision')
    protocol, selection, screen = read(root, 'protocol'), read(root, 'selection'), read(root, 'screen')
    benchmark = read(root, 'export_benchmark')
    expected = (read(root, 'full_candidate')[decision['candidate']] if decision['promoted']
                else read(root, 'full_baseline')['clean_554347'])
    assert benchmark['result'] == expected['result']
    assert benchmark['curve_sha256'] == expected['curve_sha256']
    assert benchmark['source_sha256'] == decision['export_sha256']
    decision['export_benchmark'] = benchmark
    decision['selection'] = selection
    output.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    (archive/'sources').mkdir(exist_ok=True)
    for path in (root/'sources').glob('*.py'):
        shutil.copyfile(path, archive/'sources'/path.name)
    for path in root.glob('*.json'):
        shutil.copyfile(path, archive/path.name)
    shutil.copyfile(decision['export_file'], output/'round1_robust_candidate.py')
    shutil.copyfile(decision['experimental_export_file'], output/'round1_spread_pressure_experimental.py')
    (output/'Qminers-robust-augmentation.json').write_text(json.dumps(decision, indent=2)+'\n')
    (archive/'summary.json').write_text(json.dumps(decision, indent=2)+'\n')
    (archive/'.gitattributes').write_text('* -text whitespace=cr-at-eol\n*.json linguist-generated=true\n*.png binary\n')
    plot_results(root, output, decision['candidate'], selection)
    shutil.copyfile(output/'Qminers-robust-augmentation.png', archive/'Qminers-robust-augmentation.png')
    num = lambda value: f'{value:,.0f}'
    row = lambda cells: '<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in cells)+'</tr>'
    rows = []
    for name, score in sorted(selection['scores'].items(), key=lambda kv: -kv[1]['simultaneous_lower_bound']):
        rows.append((name, f"{score['gain']:+,.0f}",
                     f"{score['half_gains'][0]:+,.0f} / {score['half_gains'][1]:+,.0f}",
                     str(score['positive_blocks'])+'/20', f"{score['simultaneous_lower_bound']:+,.0f}",
                     'Pass' if score['eligible'] else 'Fail'))
    verdict = ('Promote the augmented model' if decision['promoted'] else 'Retain the verified 554,347 model')
    explanation = ('The frozen candidate passed all screening and confirmation gates.' if decision['promoted'] else
                   'The augmentation did not pass every predeclared gate. The recommended file preserves the verified baseline with runtime-only cleanup.')
    table = [('Round1, 5 ms', decision['baseline_pnl'], decision['candidate_pnl']),
             ('Older sample_v2', decision['sample_v2']['baseline'], decision['sample_v2']['candidate'])]
    table += [(f"Round1, {s['delay_ms']} ms", s['baseline'], s['candidate']) for s in decision['stress']]
    feature_rows = [(name, item[1], '; '.join(item[0])) for name, item in protocol['features'].items()]
    checks = ''.join(row((name, 'PASS' if good else 'FAIL')) for name, good in decision['checks'].items())
    body = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qminers: robust augmentation</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;color:#203044;background:#f4f6f9;margin:0}}main{{max-width:1150px;margin:auto;padding:34px 24px}}h1{{font-size:38px;line-height:1.15}}h2{{margin-top:34px}}.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.13em;color:#607087}}.cards{{display:flex;gap:14px;flex-wrap:wrap}}.card{{flex:1;background:white;padding:18px;border:1px solid #d8e0e8;border-radius:10px;min-width:180px}}.big{{font-size:31px;font-weight:bold;color:#087e8b}}table{{border-collapse:collapse;width:100%;font-size:14px;background:white}}th,td{{padding:11px;border-bottom:1px solid #e0e5eb;text-align:left;vertical-align:top}}th{{background:#e6edf4}}.scroll{{overflow-x:auto}}.note{{background:#fff4df;border-left:4px solid #ba8a32;padding:15px 19px}}img{{width:100%;background:white}}code,pre{{font:13px/1.5 ui-monospace,monospace}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#e6edf4;padding:15px}}a{{color:#006e94}}small{{color:#5f7082}}</style></head><body><main>
<div class="eyebrow">Qminers Arena · bounded feature and parameter experiment · 7 November 2026</div>
<h1>{verdict}</h1><p>{explanation}</p>
<div class="cards"><div class="card"><small>Latest upstream baseline</small><div class="big">{num(decision['baseline_pnl'])}</div><div>Official engine reproduced</div></div><div class="card"><small>Frozen experiment: {html.escape(decision['candidate'])}</small><div class="big">{num(decision['candidate_pnl'])}</div><div>{decision['gain']:+,.0f} PnL · {decision['gain_percent']:+.2f}%</div></div><div class="card"><small>Recommended submission</small><div class="big">{num(benchmark['result']['pnl'])}</div><div>{html.escape(decision['recommended'])}</div></div></div>
<h2>What changed upstream</h2><p>The latest main commit inspected at the start was <code>{protocol['upstream_main'][:7]}</code>. It froze <code>strategies/round1_submission.py</code> at 554,347. Intermediate commits preserved 538,075 and 544,764 queue policies, 550,873 selective inside quotes, and 554,318 cancellation-triggered replenishment. The previous independent Codex extension scored 534,941.</p>
<p>The latest architecture uses fifteen causal features and 100 ms matured labels sampled every 20 ms. It fits an exponentially weighted ridge model once per second, with 300-second memory. It caps individual order quantities at 20 for depth signals, uses inventory skew 0.025, quotes one tick inside a spread of at least two ticks when predicted edge exceeds 0.30, and replenishes after cancellation confirmations from quotes cached for at most 5 ms. Pending exposure remains reserved. Execution methods were held fixed throughout this experiment.</p>
<h2>Cheap features with structural constraints</h2><p>Every added feature uses aggregates already calculated by the baseline. None needs an extra order-book scan, an absolute price/time index, or an offline-fitted transformation. The new terms are bounded, unchanged by translating all prices, and change sign when bid and ask sides are mirrored. Tests verify those properties. These choices reduce avoidable fitting freedom but cannot guarantee generalization.</p>
<div class="scroll"><table><tr><th>Feature family</th><th>Purpose</th><th>Expression</th></tr>{''.join(row(r) for r in feature_rows)}</table></div>
<p>Here <code>br/ar</code> are capped touch volumes, <code>bd_r/ad_r</code> capped two-tick depth volumes, <code>bn/an</code> touch order counts, and <code>bd_n/ad_n</code> depth counts. The six parameter probes changed one setting at a time: memory 240/360 seconds, ridge coefficient 0.00075/0.0015 (floor 10 retained), or horizon 80/120 ms. There was no broad grid, automatic stacking, or retuning after confirmation.</p>
<h2>Selection fixed before replay</h2><p>Eleven candidate definitions were frozen alongside original and cleaned controls. Selection used twenty paired five-minute PnL blocks through exactly 5,990 seconds, excluding artificial prefix-end order draining. Gates required positive gains in both chronological halves, at least 0.5% total gain, at least 12/20 positive blocks, and a positive one-sided 95% simultaneous lower bound across all eleven trials. The bound used 20,000 circular paired-block bootstrap draws, ten-minute blocks resampled within each half. The largest passing lower bound determined the single frozen finalist.</p>
<div class="scroll"><table><tr><th>Variant</th><th>Screen gain</th><th>Half gains</th><th>Positive blocks</th><th>Simultaneous lower bound</th><th>Screen</th></tr>{''.join(row(r) for r in rows)}</table></div>
<p>These bootstrap bounds describe conditional uncertainty within the reused tape and fixed trial set. They do not account for all earlier searches across the repository, establish a fresh test set, or supply a calibrated probability of winning on another round.</p>
<img src="Qminers-robust-augmentation.png" alt="Cumulative candidate PnL gain and all screening gains with simultaneous lower bounds">
<h2>Frozen confirmation</h2><table><tr><th>Replay</th><th>Baseline</th><th>Candidate</th><th>Gain</th></tr>{''.join(row((label,num(b),num(c),f'{c-b:+,.0f}')) for label,b,c in table)}</table>
<p>Normal-latency one-second sampled drawdown: {num(decision['baseline_drawdown'])} baseline versus {num(decision['candidate_drawdown'])} candidate. Every run checks zero position penalties and maximum actual/submitted potential exposure of 100. Later data is reused diagnostic evidence; coefficients continue learning only from matured past outcomes.</p>
<table><tr><th>Period</th><th>Baseline</th><th>Candidate</th><th>Gain</th></tr>{''.join(row((r['period'],num(r['baseline']),num(r['candidate']),f"{r['gain']:+,.0f}")) for r in decision['periods'])}</table>
<details><summary>All promotion gates</summary><table>{checks}</table></details>
<h2>Ready-to-test file and reproducibility</h2><p><a href="round1_robust_candidate.py">Download the recommended standalone file</a>. Its executable AST matches the frozen recommended source; only its documentation changed. A separate replay of that exact export through the unmodified engine matched every official result field and the full PnL-curve hash.</p>
<p><a href="round1_spread_pressure_experimental.py">Download the unpromoted spread-pressure experiment</a> for separate research. Its executable AST matches the frozen diagnostic source; the header explicitly records its failed screening gate.</p>
<p>Exact-export local runtime: {benchmark['cpu_seconds']:.1f} CPU seconds, {benchmark['peak_working_set_bytes']/2**20:.1f} MiB peak working set; {benchmark['source_bytes']:,} source bytes. Local timing is not a server-runtime guarantee. Sixty tests passed, covering causal label timing, nonlinear-feature invariance, bootstrap properties, cached quote validity and asynchronous reservation accounting. Source, tape and engine hashes accompany all outcomes.</p>
<pre>Recommended source SHA-256: {decision['export_sha256']}</pre>
<div class="note"><b>What remains unproven:</b> no fresh competition tape was available and no new website submission was made. All round1/sample_v2 data has been examined before. Passing consistency, transfer and latency gates reduces reasons to distrust an incremental change; it cannot prove absence of overfitting. Keep the upstream model as a fallback and judge future performance on genuinely new data.</div>
<p><small><a href="Qminers-robust-augmentation.json">Machine-readable decision and results</a>. The repository archive retains the frozen protocol, all thirteen source files, all rejected trials and every confirmation run. Raw market data is excluded.</small></p></main></body></html>'''
    (output/'Qminers-robust-augmentation.html').write_text(body, encoding='utf-8')
    archive_body = body.replace('href="round1_robust_candidate.py"', 'href="../../strategies/round1_robust_candidate.py"').replace(
        'href="Qminers-robust-augmentation.json"', 'href="summary.json"')
    archive_body = archive_body.replace('href="round1_spread_pressure_experimental.py"',
                                        'href="../../strategies/round1_spread_pressure_experimental.py"')
    (archive/'report.html').write_text(archive_body, encoding='utf-8')
    (archive/'README.txt').write_text('''Bounded augmentation of upstream 554347 model, 7 November 2026

protocol.json was written before all candidate replays; selection.json froze
the one candidate before later-period, transfer and latency confirmation.
If screening fails, the diagnostic finalist cannot be promoted afterwards.
decision.json records every gate. summary.json adds exact-export verification.
All datasets are previously consumed. Results are robustness checks, not a new
holdout. No website/private leaderboard result is claimed.

Source paths in the protocol describe the original logs/robust_augmentation
working directory. Frozen source bytes are retained in sources/. The untouched
upstream strategy remains strategies/round1_submission.py. Reproduction:

python -m unittest discover -s tests -v
python -m scripts.probe_robust_augmentation --prepare --root logs/augmentation_replay --source strategies/round1_submission.py --data data/round1.csv --prefix PATH_TO_6000_SECOND_PREFIX --transfer data/sample_v2.csv
python -m scripts.probe_robust_augmentation --root logs/augmentation_replay --data PATH_TO_6000_SECOND_PREFIX --stage screen --workers 8
python -m scripts.probe_robust_augmentation --root logs/augmentation_replay --select

Use full_* stages for round1 and sample_* for sample_v2, --names for the frozen
controls/finalist and --delay 20 or 50 for stress. Every prefix must retain the
full event tape from its beginning; do not restart mid-book.
python -m scripts.benchmark_depth_submission --strategy strategies/round1_robust_candidate.py --data data/round1.csv --output logs/augmentation_export.json

Matching engine files are unchanged. New feature transforms are pure arithmetic
over existing depth aggregates; all execution/risk methods remain unchanged.
''')
    print(json.dumps({k: decision[k] for k in ('promoted', 'candidate', 'recommended', 'baseline_pnl', 'candidate_pnl', 'gain', 'gain_percent', 'checks')}, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('logs/robust_augmentation'))
    p.add_argument('--export', action='store_true')
    p.add_argument('--output', type=Path)
    p.add_argument('--archive', type=Path, default=Path('research/robust_augmentation_20261107'))
    a = p.parse_args()
    if a.export:
        export(a.root)
    else:
        report(a.root, a.output, a.archive)


if __name__ == '__main__':
    main()
