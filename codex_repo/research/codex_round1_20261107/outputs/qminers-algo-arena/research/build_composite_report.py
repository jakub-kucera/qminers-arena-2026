"""Build the composite experiment report from recorded, frozen replay results."""
import csv
import hashlib
import html
import importlib.metadata
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent
RESULTS = ROOT / 'research/composite_results'
OLD = ROOT / 'research/results'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def money(value):
    return f'{value:+,.0f}'


def table(headers, rows):
    head = ''.join(f'<th>{html.escape(str(x))}</th>' for x in headers)
    body = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in row) + '</tr>' for row in rows)
    return f'<div class="table-scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def main():
    phases = ['screen', 'refine', 'room', 'confirm', 'final', 'stress', 'max_pnl_stress']
    all_runs = []
    for phase in phases:
        for result in read(RESULTS / f'{phase}_summary.json'):
            all_runs.append(dict(result, phase=phase))
    assert len(all_runs) == 47
    by_name = {r['name']: r for r in all_runs}
    final = read(RESULTS / 'final_summary.json')
    f4, ensemble, best = [by_name[k] for k in ('final_F4', 'final_selected', 'final_alternative')]
    f2 = read(OLD / 'team_F2.json')
    benchmark = read(OLD / 'benchmark_composite_max_pnl_v2.json')
    selection = read(RESULTS / 'selection.json')
    fit = read(RESULTS / 'model_fit.json')
    split = read(RESULTS / 'split_plan.json')
    candidate = ROOT / 'strategies/composite_max_pnl_v2.py'
    assert digest(candidate) == selection['alternative']['sha256'] == best['source_sha256']
    assert benchmark['result'] == best['result']
    assert all(r['result']['breach_penalty'] == 0 and r['max_reserved_exposure'] <= 100 for r in all_runs)
    assert best['result']['pnl'] == 272088
    assert len([r for r in all_runs if r['phase'] in phases[:4]]) == 37

    fields = ['phase', 'case', 'dataset', 'delay_ms', 'pnl', 'validation_pnl', 'tail_pnl',
              'penalty', 'max_abs_inventory', 'max_reserved_exposure', 'sampled_drawdown',
              'traded_volume', 'fills', 'cpu_seconds', 'source_sha256']
    flat = []
    for r in all_runs:
        flat.append(dict(phase=r['phase'], case=r['name'], dataset=r['data'], delay_ms=r['delay_ms'],
            pnl=r['result']['pnl'], validation_pnl=r.get('validation_pnl', ''),
            tail_pnl=r.get('tail_pnl', ''), penalty=r['result']['breach_penalty'],
            max_abs_inventory=r['max_abs_inventory'], max_reserved_exposure=r['max_reserved_exposure'],
            sampled_drawdown=r['max_drawdown'], traded_volume=r['result']['traded_volume'],
            fills=r['result']['fills'], cpu_seconds=r['cpu_seconds'], source_sha256=r['source_sha256']))
    with (RESULTS / 'all_composite_runs.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(flat)

    uplift_f2 = 100 * (best['result']['pnl'] / f2['result']['pnl'] - 1)
    uplift_f4 = 100 * (best['result']['pnl'] / f4['result']['pnl'] - 1)
    memory = benchmark['peak_working_set_bytes'] / (1024 ** 2)
    full_rows = [
        ('Earlier F2 reference', f2['result']['pnl'], f2['third_quarter_pnl'], f2['last_quarter_pnl']),
        ('Latest team F4', f4['result']['pnl'], f4['validation_pnl'], f4['tail_pnl']),
        ('Composite + model ensemble', ensemble['result']['pnl'], ensemble['validation_pnl'], ensemble['tail_pnl']),
        ('Composite + linear forecast', best['result']['pnl'], best['validation_pnl'], best['tail_pnl']),
    ]
    score_table = table(['Strategy', 'Full public tape', 'Validation 50–75%', 'Reused tail 75–100%'],
                        [[label, money(full), money(valid), money(tail)] for label, full, valid, tail in full_rows])
    latency_rows = []
    for label, normal, slow20, slow50 in [
        ('Composite + linear', best, by_name['max_pnl_20ms'], by_name['max_pnl_50ms']),
        ('Composite + ensemble', ensemble, by_name['stress_20ms'], by_name['stress_50ms']),
    ]:
        latency_rows.append([label] + [money(r['result']['pnl']) for r in (normal, slow20, slow50)])
    latency_table = table(['Policy', 'Official 5 ms', 'Stress: 20 ms', 'Stress: 50 ms'], latency_rows)
    trial_rows = sorted((r for r in all_runs if r['phase'] in phases[:4]), key=lambda r: r['validation_pnl'], reverse=True)
    trial_table = table(['Case', 'Stage', 'Validation PnL', 'Max reserved', 'Penalty'],
                        [[r['name'], r['phase'], money(r['validation_pnl']), r['max_reserved_exposure'],
                          r['result']['breach_penalty']] for r in trial_rows])

    fig = go.Figure()
    for label, path, color in [
        ('Earlier F2', OLD / 'team_F2_trace.npz', '#83909e'),
        ('Latest F4', RESULTS / 'final_F4_trace.npz', '#e7a33e'),
        ('Composite + ensemble', RESULTS / 'final_selected_trace.npz', '#7b70df'),
        ('Composite + linear', RESULTS / 'final_alternative_trace.npz', '#0c9a83'),
    ]:
        curve = np.load(path)['curve']
        fig.add_trace(go.Scatter(x=(curve[:, 0] / 1e6).tolist(), y=curve[:, 1].tolist(),
            name=label, line=dict(color=color, width=2), hovertemplate='%{x:.1f} s · %{y:,.0f}<extra>%{fullData.name}</extra>'))
    fig.add_vrect(x0=split['training_end_s'], x1=split['validation_end_s'],
                 fillcolor='#d9eef6', opacity=.5, line_width=0, layer='below', annotation_text='Policy validation', annotation_position='top left')
    fig.add_vrect(x0=split['validation_end_s'], x1=5749.896405,
                 fillcolor='#f7e4c1', opacity=.5, line_width=0, layer='below', annotation_text='Reused diagnostic tail', annotation_position='bottom right')
    fig.update_layout(template='plotly_white', height=450, margin=dict(l=65, r=25, t=35, b=70),
        legend=dict(orientation='h', y=-.2), xaxis_title='Recorded session time (seconds)', yaxis_title='Simulator PnL',
        font=dict(family='Segoe UI, sans-serif', color='#173047'), hovermode='x unified')
    chart = pio.to_html(fig, full_html=False, include_plotlyjs=True,
                        config=dict(displaylogo=False, responsive=True), div_id='pnl-chart')

    components = [
        'Queue preservation and replenishment: retain live same-price quotes and refill available capacity behind them, instead of losing priority through repeated replacements.',
        'Depletion protection: pull a side when external volume at its best price falls below 20 lots; step the inventory-increasing quote one tick back when inventory error reaches 95 lots.',
        'Causal forecasting: a regularized linear model combines spread, touch/depth imbalance, signed flow, short price trends, displayed depth, flow volume, and microprice displacement. Features update every 100 ms; flow updates on each event.',
        'Forecast-driven inventory: target inventory is 40 times the predicted one-second price change, clipped to ±50 lots. Suppress a quote when its forecast edge is below 0.15 ticks.',
        'Strict reservation: position plus all pending buys stays at or below 100, and position minus all pending sells stays at or above −100. Cancelling orders retain their reservation until acknowledged; buys and sells are never netted against each other.',
        'Session control: stop adding to an existing position in the last 30 seconds of the configured 5,750-second session. This is passive wind-down, not guaranteed flattening; the final position was −36 and the official score includes its liquidation value.',
    ]
    methodology = (
        'Models were first fitted on 0–40% of the tape; nonnegative blend weights were calibrated on 40–50%; '
        'the base models were then refitted on the first 50%. Labels crossing split boundaries were purged. '
        'Thirty-seven policy trials used the 50–75% segment for selection, with every replay starting at the '
        'beginning to preserve the order book and FIFO queues. The ensemble policy won that validation '
        'comparison and was frozen before the full runs. Its matched linear-only alternative was frozen at '
        'the same time. The linear version subsequently earned the highest full-tape PnL. Calling it the '
        'highest observed public-data candidate therefore uses the full results for selection. The last '
        'quarter had already been inspected in earlier work and team research; it is a reused diagnostic '
        'segment, not an untouched holdout. Full PnL also includes the model training interval.'
    )
    model_detail = (
        f'The tested ensemble combined {100 * fit["weights"][0]:.1f}% one-second Ridge forecast and '
        f'{100 * fit["weights"][2]:.1f}% shallow gradient-boosted trees. Five-second Ridge, raw microprice, '
        'and the zero forecast received effectively zero blend weight. The blend slightly improved '
        'validation forecast correlation (0.4055 versus 0.4035 for Ridge), and policy validation PnL '
        '(69,257 versus 69,053), but its full PnL was 4,243 lower. The delivered maximum-PnL file uses '
        'the linear forecast only within the composite execution policy. Unused ensemble constants are '
        'retained to preserve the exact tested export. Increasing complexity did not win this comparison.'
    )
    stress_detail = (
        'Both composites remained profitable at hypothetical 20 ms and 50 ms order delays, with zero '
        'penalties and maximum reserved exposure of 100 in each run. The linear version scored '
        '−5,965 on the older original sample, versus −7,649 for the ensemble and −8,704 for F4; these '
        'cross-tape checks changed only the session length to match that tape. The prior study found '
        'that M2 did well on the old tape and very poorly on v2. This is strong evidence of regime '
        'dependence, not a reason to switch policies after seeing their future returns.'
    )
    risk_detail = (
        f'The best file traded {best["result"]["traded_volume"]:,} lots in {best["result"]["fills"]:,} '
        f'engine-counted fills, with zero penalties and peak absolute inventory/reserved exposure of 100. '
        'Its time-weighted median absolute inventory was also 100: it uses the full allowed inventory '
        'budget and leaves no soft-limit headroom. The 203-point maximum drawdown is sampled from the '
        'one-second PnL curve and can miss faster excursions. Forty cancel rejections were late-cancel '
        'races against orders no longer resting, not inventory-limit rejections. The official simulator '
        f'charges no fees; an extra hypothetical uniform cost of '
        f'{best["result"]["pnl"] / best["result"]["traded_volume"]:.3f} ticks per traded lot would consume '
        'the entire measured profit, before any additional fill changes.'
    )
    verification = (
        'The new study contains 37 prefix policy trials, 3 full-tape confirmation comparisons, and 7 '
        'stress/cross-tape checks, plus a separate replay of the exact delivered file. All 47 research '
        'runs had zero penalties and reserved exposure at most 100. Twelve strategy risk tests and '
        'five deterministic engine probes passed earlier in this study, covering pending/cancelling '
        'reservations, late fills, side-specific exposure, rejected modifications, delayed acceptance, '
        'FIFO, depletion protection, inventory skew, and the soft/hard limits. Controls reproduced F2 '
        'and F4 exactly. Exported tree predictions matched the training library to 1.11e−16 on 1,500 '
        'checked rows. The team source validator passed the delivered file; the official loader and '
        'engine replayed it successfully. These local checks do not replace the website sandbox check.'
    )
    deployment = (
        f'The exact 20,304-byte file ran locally in {benchmark["wall_seconds"]:.1f} seconds wall time '
        f'({benchmark["cpu_seconds"]:.1f} seconds CPU), with {memory:.1f} MiB peak Windows working set, '
        'including Python and harness imports. It imports only math and the simulator API, has one '
        'BaseStrategy subclass, and performs no file/network/process access. This fits the published '
        '1 MiB source, 1 CPU, 2 GB RAM, and 15-minute limits in the local measurements; the remote Linux '
        'runtime has not been measured. Upload only composite_max_pnl_v2.py to the matching public-v2 '
        'website test. A successful upload may become the selected final submission. No website upload, '
        'Git push, sharing change, or organizer message was made in this work.'
    )
    next_round = (
        'For a new round, first inspect the new tape’s spread, queue depth, flow, session duration, and '
        'fill-conditioned markouts. Freeze a small comparison of F4, the linear composite, the ensemble '
        'composite, and an appropriate directional baseline. Fit/calibrate on chronological development '
        'data, then evaluate once on genuinely unseen data. Check a range of inventory targets and '
        'depletion thresholds for a broad plateau, rather than chasing one best point. Test a causal '
        'regime gate only with development data; the simple regime guard in this study did not improve '
        'the v2 validation result. Add larger sequence models only if they improve executable PnL and '
        'meet the complete-run budget. The present 2.8% gain over F4 is not established as statistically '
        'robust or as an advantage on private competition data.'
    )

    command = '.venv/Scripts/exchange-simulator.exe --strategy strategies/composite_max_pnl_v2.py --backtest data/sample_v2.csv --log-dir logs/composite-max --no-logs'
    source_links = (
        '<a href="https://github.com/QminersOrg/qminers-algo-arena/tree/3f5bea730d5f341c6988b1fe2722998b66270ea0">Official engine revision</a> · '
        '<a href="https://github.com/jakub-kucera/qminers-arena-hachathon/tree/5003a3553c32335e6c0d2acde9b9dce8deb92ea4">Team F4 revision (requires access)</a> · '
        '<a href="qminers-algo-arena/research/composite_results/all_composite_runs.csv">All 47 runs (CSV)</a> · '
        '<a href="qminers-algo-arena/research/composite_results/selection.json">Frozen selection</a> · '
        '<a href="qminers-algo-arena/research/composite_results/composite_manifest.json">Reproducibility manifest</a>'
    )
    texts = [
        'QMINERS COMPOSITE RESULTS — 7 NOVEMBER 2026',
        f'Highest observed public-v2 result: +272,088. This is {uplift_f2:.1f}% above the earlier F2 reference and {uplift_f4:.1f}% above the latest team F4.',
        'Upload candidate: qminers-algo-arena/strategies/composite_max_pnl_v2.py\nThis is a local public-data result, not a website score or proof of a private-round win.',
        'COMPARISON\nStrategy | Full tape | Validation 50–75% | Reused final quarter\n' + '\n'.join(' | '.join([label, money(a), money(b), money(c)]) for label, a, b, c in full_rows),
        'HOW THE APPROACHES ARE COMBINED\n' + '\n'.join(f'{i + 1}. {s}' for i, s in enumerate(components)),
        'MODEL COMPARISON\n' + model_detail,
        'SELECTION AND EVIDENCE LIMITS\n' + methodology,
        'LATENCY\nPolicy | 5 ms | 20 ms | 50 ms\n' + '\n'.join(' | '.join(r) for r in latency_rows),
        stress_detail, risk_detail, verification, deployment,
        'NEXT ROUND\n' + next_round,
        'REPRODUCE FROM THE LOCAL OFFICIAL CHECKOUT\n' + command,
        'PROVENANCE\nOfficial engine: 3f5bea730d5f341c6988b1fe2722998b66270ea0\nTeam F4: 5003a3553c32335e6c0d2acde9b9dce8deb92ea4\nDataset: sample_v2.csv, 2,000,000 rows, 5,749.869 s\nDataset SHA256: ' + digest(ROOT / 'data/sample_v2.csv') + '\nUpload SHA256: ' + digest(candidate),
        'ALL POLICY TRIALS (validation-ranked)\n' + '\n'.join(f'{r["name"]}: {money(r["validation_pnl"])}' for r in trial_rows),
    ]
    txt_path = OUT / 'Qminers-composite-results.txt'
    txt_path.write_text('\n\n'.join(texts) + '\n', encoding='utf-8')

    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qminers — composite results</title>',
        '<style>body{margin:0;background:#f3f6f8;color:#173047;font:16px/1.6 "Segoe UI",sans-serif}main{max-width:1100px;margin:auto;padding:42px 24px 70px}h1{font-size:38px;line-height:1.15;margin:10px 0 20px}h2{font-size:24px;margin-top:36px}p,li{max-width:1000px}a{color:#007d71}header small{letter-spacing:.1em;color:#597084}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:24px 0}.card{padding:20px;background:white;border-radius:10px;border:1px solid #dce4eb}.card strong{display:block;font-size:30px}.callout{padding:16px 20px;border-left:4px solid #dfab44;background:#fff6e5}.table-scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}th,td{padding:11px 15px;border-bottom:1px solid #e0e7ed;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{background:#e9eff4}tbody tr:last-child{font-weight:600}code,pre{font-size:13px;background:#e7edf2;padding:4px 6px;white-space:pre-wrap;overflow-wrap:anywhere}details{margin-top:24px}summary{cursor:pointer;font-weight:600}footer{margin-top:32px;font-size:13px;color:#50677a}.button{display:inline-block;background:#087f70;color:white;padding:10px 16px;border-radius:6px;text-decoration:none}.muted{color:#5e7182;font-size:14px}@media(max-width:650px){.cards{grid-template-columns:1fr}h1{font-size:30px}main{padding:24px 15px}}</style></head><body><main>',
        '<header><small>LOCAL EXPERIMENTS · 7 NOVEMBER 2026</small><h1>Composite execution improves the public-v2 score</h1>',
        '<p>The best observed candidate combines queue-aware market making, depletion protection, a learned linear forecast, and inventory control.</p>',
        '<a class="button" href="qminers-algo-arena/strategies/composite_max_pnl_v2.py" download>Download the tested Python file</a> &nbsp; <a href="Qminers-composite-results.txt">Plain-text report</a></header>',
        f'<div class="cards"><div class="card">Full public-v2 PnL<strong>+272,088</strong></div><div class="card">Versus latest F4<strong>+{uplift_f4:.1f}%</strong></div><div class="card">Exact-file local runtime<strong>{benchmark["wall_seconds"]:.1f} seconds</strong></div></div>',
        '<div class="callout"><strong>Public-data selection, not a private-round result.</strong> The linear composite wins the full-sample comparison; the tree ensemble was the original validation winner. The final quarter was already inspected in previous work. The linear composite loses 5,965 on the older sample.</div>',
        '<h2>Measured comparison</h2>' + score_table + chart,
        '<p class="muted">Official simulator score, including final executable inventory valuation and penalties. Curves are sampled once per second. Full results include training data.</p>',
        '<h2>What is combined</h2><ol>' + ''.join(f'<li>{html.escape(s)}</li>' for s in components) + '</ol>',
        '<h2>What the model ensemble taught us</h2><p>' + html.escape(model_detail) + '</p>',
        '<h2>How selection was controlled</h2><p>' + html.escape(methodology) + '</p>',
        '<h2>Stress checks and risk</h2>' + latency_table + '<p>' + html.escape(stress_detail) + '</p><p>' + html.escape(risk_detail) + '</p>',
        '<h2>Validation and deployment</h2><p>' + html.escape(verification) + '</p><p>' + html.escape(deployment) + '</p>',
        '<p>From the official local checkout:</p><pre>' + html.escape(command) + '</pre>',
        '<p>The separately frozen validation winner is <a href="qminers-algo-arena/strategies/composite_best_v2.py" download>composite_best_v2.py</a> (+267,845). The name reflects validation selection; use <strong>composite_max_pnl_v2.py</strong> for the highest observed full-public-data result.</p>',
        '<h2>Next-round strategy</h2><p>' + html.escape(next_round) + '</p>',
        '<details><summary>All 37 policy trials, including failed improvements</summary>' + trial_table + '</details>',
        '<footer><p>' + source_links + '</p><p>Dataset SHA256: <code>' + digest(ROOT / 'data/sample_v2.csv') + '</code><br>Delivered file SHA256: <code>' + digest(candidate) + '</code></p><p>Original simulator sources are unchanged. All comparisons were run locally; no website score is claimed.</p></footer></main></body></html>',
    ]
    html_path = OUT / 'Qminers-composite-results.html'
    html_path.write_text(''.join(parts), encoding='utf-8')
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        python_version=sys.version,
        research_dependencies={name: importlib.metadata.version(name)
            for name in ['numpy', 'scipy', 'scikit-learn', 'pandas', 'plotly']},
        official_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        team_commit='5003a3553c32335e6c0d2acde9b9dce8deb92ea4',
        data_sha256=digest(ROOT / 'data/sample_v2.csv'),
        candidate_sha256=digest(candidate), candidate=str(candidate),
        selection_type='Highest observed public full-tape PnL; original validation selection remains the ensemble.',
        new_research_runs=len(all_runs), policy_trials=len(trial_rows), exact_file_benchmark=benchmark,
        limitations=['Previously inspected public tail; full tape used to select maximum-PnL alternative.',
                     'No private data or website result. Negative PnL on the older original sample.',
                     'Inventory often at the 100-lot boundary. Runtime measured on Windows locally.'],
        files={str(p.relative_to(OUT)): digest(p) for p in [candidate, txt_path, html_path,
            RESULTS / 'all_composite_runs.csv', RESULTS / 'selection.json', RESULTS / 'model_fit.json']})
    (RESULTS / 'composite_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(dict(html=str(html_path), text=str(txt_path), runs=len(all_runs),
                         uplift_f2=uplift_f2, uplift_f4=uplift_f4, candidate_sha256=digest(candidate))))


if __name__ == '__main__':
    main()
