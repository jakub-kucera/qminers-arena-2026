"""Publish diagnostics from the frozen round-one comparisons and stress checks."""
import hashlib
import html
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

from round1_study import ROOT, DEST

OUT = ROOT.parent
LABELS = {
    'team_F4': 'F4, round-one clock',
    'pasted_passive': 'Pasted passive strategy',
    'composite_ensemble': 'Composite + ensemble',
    'composite_linear': 'Composite + linear forecast',
    'pasted_flow06': 'Pasted strategy, flow guard 0.6',
    'team_F2': 'F2, 100-lot limit',
    'team_F2_cap80': 'F2, 80-lot configuration',
    'microprice_maker': 'Small microprice maker',
    'ridge_maker': 'Small Ridge maker',
    'fixed_trend': 'Corrected trend example',
    'mean_reversion': 'Mean reversion',
    'team_M2': 'M2 directional runner',
}


def read(name):
    return json.loads((DEST / name).read_text(encoding='utf-8'))


def signed(value):
    return f'{value:+,.0f}'


def table(headers, rows):
    heading = ''.join(f'<th>{html.escape(str(x))}</th>' for x in headers)
    content = ''.join('<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in row) + '</tr>' for row in rows)
    return f'<div class="scroll"><table><thead><tr>{heading}</tr></thead><tbody>{content}</tbody></table></div>'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    plan, data = read('comparison_plan.json'), read('dataset.json')
    runs, stress = read('comparison_summary.json'), read('stress_summary.json')
    benchmark, selected, diagnostics = read('winner_benchmark.json'), read('selection.json'), read('market_diagnostics.json')
    assert len(runs) == 16 and len(stress) == 4
    entries = {e['name']: e for e in plan['entries']}
    ranked = sorted((r for r in runs if entries[r['name']]['role'] == 'primary'), key=lambda r: r['result']['pnl'], reverse=True)
    by_name = {r['name']: r for r in runs + stress}
    best, second = ranked[:2]
    assert best['name'] == selected['selected_case'] == 'team_F4'
    assert benchmark['result'] == best['result']
    assert all(r['result']['breach_penalty'] == 0 and r['max_reserved_exposure'] <= 100 for r in runs + stress)
    source = Path(selected['export'])
    assert digest(source) == selected['sha256'] == benchmark['source_sha256']
    gap = best['result']['pnl'] - second['result']['pnl']
    pct_gap = 100 * gap / second['result']['pnl']
    pair = np.array(best['twelve_segment_pnl']) - np.array(second['twelve_segment_pnl'])
    wins = int(np.sum(pair > 0))
    memory = benchmark['peak_working_set_bytes'] / 1024 ** 2

    rows = [[LABELS[r['name']], signed(r['result']['pnl']), f'{r["max_drawdown"]:,.0f}',
             r['max_abs_inventory'], f'{r["positive_segments"]}/12',
             f'{r["result"]["traded_volume"]:,}', f'{r["pnl_per_traded_lot"]:.3f}'] for r in ranked]
    ranking_table = table(['Strategy', 'PnL', 'Drawdown¹', 'Peak inventory', 'Profitable segments', 'Lots', 'PnL / lot'], rows)
    quarter_table = table(['Strategy', '0–50 min', '50–100 min', '100–150 min', '150–200 min'],
        [[LABELS[r['name']]] + [signed(v) for v in r['quarter_pnl']] for r in ranked[:6]])
    clock_rows = []
    for old, new in [('old_clock_F4', 'team_F4'), ('old_clock_composite', 'composite_linear'), ('old_clock_F2', 'team_F2')]:
        a, b = by_name[old], by_name[new]
        clock_rows.append([LABELS[new], signed(a['result']['pnl']), signed(b['result']['pnl']),
                           signed(b['result']['pnl'] - a['result']['pnl'])])
    clock_table = table(['Strategy', 'Old sample clock', '12,000-second clock', 'Difference'], clock_rows)
    latency_rows = [[LABELS[name]] + [signed(by_name[key]['result']['pnl']) for key in (name, f'{name}_delay20', f'{name}_delay50')]
                    for name in ('team_F4', 'pasted_passive')]
    latency_table = table(['Strategy', 'Official 5 ms', 'Stress 20 ms', 'Stress 50 ms'], latency_rows)
    market_new, market_old = diagnostics['round1_market'], diagnostics['sample_v2_market']
    market_table = table(['Sampled market property', 'Earlier sample v2', 'Round one'], [
        ['One-tick spread', f'{100 * market_old["spread_one_fraction"]:.1f}%', f'{100 * market_new["spread_one_fraction"]:.1f}%'],
        ['Median bid / ask depth', f'{market_old["median_bid_depth"]:.0f} / {market_old["median_ask_depth"]:.0f}', f'{market_new["median_bid_depth"]:.0f} / {market_new["median_ask_depth"]:.0f}'],
        ['Mean absolute one-second mid move', f'{market_old["one_second_absolute_mid_move_mean"]:.3f} ticks', f'{market_new["one_second_absolute_mid_move_mean"]:.3f} ticks'],
        ['Mid-price range', f'{market_old["min_mid"]:,.1f}–{market_old["max_mid"]:,.1f}', f'{market_new["min_mid"]:,.1f}–{market_new["max_mid"]:,.1f}'],
    ])
    metrics = diagnostics['frozen_forecast_metrics']
    model_table = table(['Frozen forecast', 'Round-one correlation', 'Mean squared error'],
        [[label, f'{metrics[name]["correlation"]:.3f}', f'{metrics[name]["mse"]:.3f}']
         for name, label in [('ridge_1s', 'One-second Ridge'), ('ensemble', 'Calibrated ensemble'),
                             ('boosted_1s', 'Boosted trees alone'), ('raw_microprice', 'Raw microprice')]])

    colors = ['#1467a3', '#d1872b', '#8c59aa', '#389988', '#8b6b53', '#7c8794']
    fig = go.Figure()
    for i, r in enumerate(ranked):
        curve = np.load(DEST / f'{r["name"]}_trace.npz')['curve']
        fig.add_trace(go.Scatter(x=(curve[:, 0] / 60e6).tolist(), y=curve[:, 1].tolist(),
            name=LABELS[r['name']], visible=True if i < 5 else 'legendonly',
            line=dict(width=2, color=colors[i % len(colors)]),
            hovertemplate='%{x:.1f} min · %{y:,.0f}<extra>%{fullData.name}</extra>'))
    fig.update_layout(template='plotly_white', height=510, margin=dict(l=70, r=25, t=20, b=150),
        xaxis_title='Round time (minutes)', yaxis_title='Simulator PnL',
        legend=dict(orientation='h', y=-.2), font=dict(family='Segoe UI, sans-serif'), hovermode='x unified')
    plot = pio.to_html(fig, full_html=False, include_plotlyjs=True, div_id='round1-pnl',
                       config=dict(displaylogo=False, responsive=True))
    blocks = go.Figure()
    blocks.add_trace(go.Bar(x=list(range(1, 13)), y=pair.tolist(),
        marker_color=['#1467a3' if v >= 0 else '#d1872b' for v in pair],
        hovertemplate='Segment %{x}: F4 minus pasted %{y:+,.0f}<extra></extra>'))
    blocks.update_layout(template='plotly_white', height=270, margin=dict(l=70, r=20, t=15, b=55),
        xaxis=dict(title='Equal time segment (16 min 40 s each)', dtick=1), yaxis_title='F4 PnL advantage',
        font=dict(family='Segoe UI, sans-serif'))
    block_plot = pio.to_html(blocks, full_html=False, include_plotlyjs=False, div_id='round1-blocks', config=dict(displaylogo=False, responsive=True))

    conclusion = (f'F4 with the round-one session clock achieved +399,096, ahead of the pasted passive strategy by '
                  f'{gap:,.0f} ({pct_gap:.2f}%). Both were profitable in all 12 time segments. F4 won {wins} of '
                  'the 12 paired segments. The pasted strategy led over the first half of the round; F4 earned '
                  'its overall advantage in the second half. This is an observed result on the supplied tape, '
                  'not proof that a 2.26% advantage persists on another round.')
    clock_note = ('This tape lasts 12,000 seconds (200 minutes), compared with about 5,750 seconds in sample v2. '
                  'Several earlier files would start winding down halfway through the new round. Primary '
                  'comparisons change only SESSION_S to 12000.0 where that setting exists. The pasted strategy, '
                  'its previously tested 0.6 flow-guard variant, and the corrected trend example are unchanged. '
                  'Model coefficients, forecast weights, inventory caps and all other policy parameters remain '
                  'frozen. Separate unchanged-clock controls show the effect directly; their last two quarters '
                  'contribute zero PnL.')
    regime_note = ('Round one has tighter spreads and faster short-horizon price movements than the earlier '
                   'sample. The v2-trained linear and ensemble composites underperformed F4 here. On sampled '
                   'round-one data, raw microprice had higher correlation with the next one-second mid move '
                   'than either frozen composite forecast. Boosted trees alone had the lowest prediction MSE '
                   'among the displayed forecasts, but this is not a tested standalone trading policy. '
                   'Forecast accuracy and executable trading profit are separate measures; no model was '
                   'retrained on round one.')
    risk_note = ('All 20 research runs had zero inventory penalties and reserved exposure at most 100. '
                 'F4 reached 100 lots and had time-weighted median absolute inventory of 99. Its sampled '
                 'maximum drawdown was 1,045, versus 1,003 for the pasted strategy. F4 traded 2,387,642 lots '
                 'versus 1,639,822 for the pasted strategy. The latter earned more per traded lot (0.238 '
                 'versus 0.167), but F4 earned more in total under the official zero-fee rules. '
                 'The 80-lot F2 configuration earned +247,424 with peak inventory 80 and sampled drawdown '
                 '604; its quote size and skew also differ, so this is not a pure cap-only comparison.')
    stress_note = ('At the official 5 ms delay, F4 leads. It also leads at hypothetical 20 ms, while the pasted '
                   'strategy leads by 4,557 at 50 ms. Both remain profitable in all four quarters in these '
                   'stress replays, without penalties. Higher latency materially reduces both scores, so '
                   'the small normal-delay lead should not be treated as universal. The 0.6 flow guard '
                   'also reduced normal-delay round-one PnL, from +390,288 to +353,035.')
    verification = (f'The exported file reproduced +399,096 in {benchmark["wall_seconds"]:.1f} seconds wall '
                    f'time and {benchmark["cpu_seconds"]:.1f} seconds CPU, using {memory:.1f} MiB peak Windows '
                    'working set. This benchmark used the official loader/engine without research callback '
                    'instrumentation; other stress jobs ran concurrently. The 13,499-byte export passed '
                    'the local team source validator. It has one strategy class and imports only __future__ '
                    'and simulator modules. The original simulator files were unchanged. Remote Linux '
                    'sandbox execution and a website score have not been measured.')
    method = ('Twelve predeclared trading candidates, one no-trade control, and three old-clock controls '
              'were replayed on all 4,411,336 events. Each run started at the beginning with an intact order '
              'book; no shuffling or reset within time segments. The top two then received four higher-delay '
              'checks, followed by verification of the exact export (21 total replays including that '
              'benchmark). Official settings: depth 20 ticks, 5 ms acceptance delay, soft inventory limit '
              '100, hard potential-exposure limit 1,000, and penalty 10,000 per second beyond the soft '
              'limit. Ranking uses final official PnL after penalties and executable terminal inventory '
              'valuation. Segment results are diagnostics on this same round, not separate independent '
              'holdouts. The winner finished flat.')
    hardware = ('Comparison phase: 16 independent worker processes on an Intel i7-12700H with 20 logical '
                'processors; observed aggregate CPU utilization reached 100%. An RTX 3070 Ti Laptop GPU '
                'with 8 GB was detected. The event-driven Python engine and frozen policies have no GPU '
                'execution path, so no GPU acceleration or additional model training was used.')
    footnote = ('¹ Drawdown is calculated from the official one-second PnL curve and can miss faster '
                'excursions. Market statistics are sampled no faster than every 100 ms and are sample-weighted.')
    command = '.venv/Scripts/exchange-simulator.exe --strategy strategies/round1_best.py --backtest data/round1.csv --log-dir logs/round1-best --no-logs'

    text_parts = [
        'QMINERS ROUND-ONE DIAGNOSTICS — 7 NOVEMBER 2026', conclusion,
        'TESTED EXPORT\nqminers-algo-arena/strategies/round1_best.py\nOnly F4 SESSION_S changes to 12000.0.',
        'RANKING\nStrategy | PnL | Drawdown (1s) | Peak inventory | Positive segments | Lots | PnL / lot\n' + '\n'.join(' | '.join(map(str, row)) for row in rows),
        'CLOCK DIAGNOSTICS\n' + clock_note + '\n' + '\n'.join(' | '.join(row) for row in clock_rows),
        'LATENCY\nStrategy | 5 ms | 20 ms | 50 ms\n' + '\n'.join(' | '.join(row) for row in latency_rows),
        stress_note, 'MARKET AND MODEL DIAGNOSTICS\n' + regime_note,
        f'One-tick spread share: {100*market_old["spread_one_fraction"]:.1f}% -> {100*market_new["spread_one_fraction"]:.1f}%. Mean absolute one-second mid move: {market_old["one_second_absolute_mid_move_mean"]:.3f} -> {market_new["one_second_absolute_mid_move_mean"]:.3f} ticks.',
        'RISK\n' + risk_note, 'VERIFICATION\n' + verification, 'METHOD\n' + method, hardware, footnote,
        'REPRODUCE\n' + command,
        'DATA SHA256\n' + data['sha256'], 'EXPORT SHA256\n' + selected['sha256'],
    ]
    text_path = OUT / 'Qminers-round1-diagnostics.txt'
    text_path.write_text('\n\n'.join(text_parts) + '\n', encoding='utf-8')
    blocks_html = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qminers round-one diagnostics</title>',
        '<style>body{margin:0;background:#f3f5f8;color:#192f43;font:16px/1.6 "Segoe UI",sans-serif}main{max-width:1160px;margin:auto;padding:38px 24px 64px}h1{font-size:36px;line-height:1.2;margin:12px 0 20px}h2{font-size:23px;margin-top:32px}small,.note{color:#536b80}.banner{background:#fff5df;border-left:4px solid #c9902d;padding:15px 20px;margin:22px 0}.button{display:inline-block;background:#1467a3;color:white;text-decoration:none;border-radius:5px;padding:10px 17px}a{color:#145d95}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}th,td{padding:11px 12px;white-space:nowrap;text-align:right;border-bottom:1px solid #dee5ec}th{background:#e6edf4}th:first-child,td:first-child{text-align:left}pre{background:#e5ebf1;padding:15px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}footer{font-size:13px;color:#536b80;margin-top:30px}code{overflow-wrap:anywhere}details{margin-top:25px}summary{font-weight:600;cursor:pointer}@media(max-width:700px){main{padding:24px 12px}h1{font-size:29px}}</style></head><body><main>',
        '<small>LOCAL SIMULATOR RESULTS · 7 NOVEMBER 2026</small><h1>F4 leads on round one: +399,096</h1>',
        '<p>' + html.escape(conclusion) + '</p>',
        '<a class="button" href="qminers-algo-arena/strategies/round1_best.py" download>Download the exact tested strategy</a> &nbsp; <a href="Qminers-round1-diagnostics.txt">Plain-text report</a>',
        '<div class="banner"><strong>Use the round-one session clock.</strong> The export sets <code>SESSION_S = 12000.0</code>. An unchanged sample-v2 F4 file stops around halfway through this round and scores only +180,241.</div>',
        '<h2>All twelve trading candidates</h2>' + ranking_table,
        '<p class="note">All candidates had zero penalties. A no-trade control scored zero. Parameters were frozen except the explicitly disclosed session duration.</p>' + plot,
        '<h2>Stability across the round</h2>' + quarter_table + block_plot,
        '<h2>Session-clock effect</h2><p>' + html.escape(clock_note) + '</p>' + clock_table,
        '<h2>Latency sensitivity</h2>' + latency_table + '<p>' + html.escape(stress_note) + '</p>',
        '<h2>Why the earlier ranking changed</h2>' + market_table + '<p>' + html.escape(regime_note) + '</p>' + model_table,
        '<p class="note">Forecast diagnostics use the unchanged v2 model coefficients and a one-second mid-price target interpolated on the no-trade sampled tape. No model selection or retraining was performed on these forecast metrics.</p>',
        '<h2>Inventory and execution</h2><p>' + html.escape(risk_note) + '</p>',
        '<h2>Verified export</h2><p>' + html.escape(verification) + '</p><pre>' + html.escape(command) + '</pre>',
        '<details><summary>Method, hardware and evidence</summary><p>' + html.escape(method) + '</p><p>' + html.escape(hardware) + '</p>',
        '<p><a href="qminers-algo-arena/research/round1_results/comparison_plan.json">Frozen comparison plan</a> · <a href="qminers-algo-arena/research/round1_results/comparison_summary.json">All comparison results</a> · <a href="qminers-algo-arena/research/round1_results/stress_summary.json">Latency checks</a> · <a href="qminers-algo-arena/research/round1_results/winner_benchmark.json">Exact-file benchmark</a> · <a href="qminers-algo-arena/research/round1_results/market_diagnostics.json">Market and model diagnostics</a></p></details>',
        '<footer><p>' + html.escape(footnote) + '</p><p>Source: <a href="qminers-algo-arena/data/round1.csv">round1.csv</a>, 161,219,988 bytes, 4,411,336 rows, no backward timestamps. The provided download is preserved.</p>',
        '<p>Dataset SHA256: <code>' + data['sha256'] + '</code><br>Export SHA256: <code>' + selected['sha256'] + '</code></p>',
        '<p>No website upload, Git push, sharing change, or organizer message was performed.</p></footer></main></body></html>',
    ]
    page = OUT / 'Qminers-round1-diagnostics.html'
    page.write_text(''.join(blocks_html), encoding='utf-8')
    manifest = dict(dataset=data, winner=selected, trading_candidates=len(ranked),
        initial_comparisons=len(runs), latency_checks=len(stress), exact_export_replays=1,
        top_pair_gap=gap, top_pair_gap_percent=pct_gap, top_pair_segment_wins=wins,
        files={str(p.relative_to(OUT)): digest(p) for p in (source, text_path, page,
            DEST / 'comparison_summary.json', DEST / 'stress_summary.json', DEST / 'winner_benchmark.json')})
    (DEST / 'report_manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(dict(report=str(page), winner=best['name'], pnl=best['result']['pnl'],
                         gap=gap, gap_percent=pct_gap, positive_segments=best['positive_segments'])))


if __name__ == '__main__':
    main()
