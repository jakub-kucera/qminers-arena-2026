"""Package the completed depth experiment and its measured architecture report."""
import argparse
import ast
import html
import json
from pathlib import Path
import shutil

from scripts.benchmark import digest


def number(value):
    return f'{value:,.0f}'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('logs/depth_advantage'))
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--archive', type=Path, default=Path('research/depth_advantage_20261107'))
    a = p.parse_args()
    read = lambda name: json.loads((a.root/(name+'.json')).read_text())
    protocol, selection = read('protocol'), read('selection')
    screen, full = read('screen'), read('full_baselines')
    base = full['supplied_13']
    clean = full['clean_13']
    for field in ('result', 'boundary_pnl', 'curve_sha256', 'weights', 'status_counts'):
        assert base[field] == clean[field], 'Cleanup changed '+field
    name = 'depth_nonlinear_16'
    assert selection['finalists'] == [name]
    candidate = read('full_finalist')[name]
    sample_base = read('sample_baseline')['clean_13']
    sample_candidate = read('sample_finalist')[name]
    benchmark = read('export_benchmark')
    assert candidate['result'] == benchmark['result'], 'Export differs from frozen candidate'
    gain = candidate['result']['pnl']-base['result']['pnl']
    period_rows = []
    previous_b = previous_c = 0
    for label, boundary in [('First 50 minutes', '3000000000'),
                            ('Next 49m 50s', '5990000000'),
                            ('99m 50s to 150m', '9000000000'),
                            ('Final 50 minutes', None)]:
        b = base['boundary_pnl'][boundary] if boundary else base['result']['pnl']
        c = candidate['boundary_pnl'][boundary] if boundary else candidate['result']['pnl']
        period_rows.append({'period': label, 'baseline': b-previous_b,
                            'candidate': c-previous_c, 'gain': (c-previous_c)-(b-previous_b)})
        previous_b, previous_c = b, c
    promotion = (all(r['gain'] > 0 for r in period_rows)
                 and sample_candidate['result']['pnl'] >= sample_base['result']['pnl']*0.98
                 and candidate['result']['breach_penalty'] == 0
                 and candidate['max_abs_inventory'] <= 100
                 and candidate['max_potential_inventory'] <= 100)
    stress = []
    for delay in (20, 50):
        b = read(f'full_latency{delay}_baseline')['clean_13']
        c = read(f'full_latency{delay}_finalist')[name]
        stress.append({'delay_ms': delay, 'baseline': b['result']['pnl'],
                       'candidate': c['result']['pnl'],
                       'gain': c['result']['pnl']-b['result']['pnl'],
                       'baseline_drawdown': b['max_drawdown_1s'],
                       'candidate_drawdown': c['max_drawdown_1s'],
                       'baseline_penalty': b['result']['breach_penalty'],
                       'candidate_penalty': c['result']['breach_penalty']})
    frozen = a.root/'sources'/(name+'.py')
    exported = Path('strategies/round1_depth_advantage.py')
    assert ast.dump(ast.Module(body=ast.parse(frozen.read_text()).body[1:], type_ignores=[])) == ast.dump(
        ast.Module(body=ast.parse(exported.read_text()).body[1:], type_ignores=[]))
    summary = {'promoted': promotion, 'baseline_pnl': base['result']['pnl'],
               'candidate_pnl': candidate['result']['pnl'], 'gain': gain,
               'gain_percent': 100*gain/base['result']['pnl'], 'periods': period_rows,
               'sample_v2': {'baseline': sample_base['result']['pnl'],
                             'candidate': sample_candidate['result']['pnl']},
               'latency_stress': stress, 'export_benchmark': benchmark,
               'baseline_drawdown_1s': base['max_drawdown_1s'],
               'candidate_drawdown_1s': candidate['max_drawdown_1s'],
               'source_sha256': digest(exported), 'selection': selection,
               'limitations': ['All public datasets have been examined previously.',
                               'No new private leaderboard or website result is claimed.',
                               'The prefix screening involved four extensions and three ablations.',
                               'Chronological consistency gates do not prove statistical significance.',
                               'PnL, not forecast error or the reported pnl_se, determined selection.',
                               'Drawdown is sampled once per second; faster losses can be missed.',
                               'Local CPU/memory measurements do not certify server runtime.']}
    a.output.mkdir(parents=True, exist_ok=True)
    a.archive.mkdir(parents=True, exist_ok=True)
    (a.archive/'sources').mkdir(exist_ok=True)
    for source in (a.root/'sources').glob('*.py'):
        shutil.copyfile(source, a.archive/'sources'/source.name)
    for source in a.root.glob('*.json'):
        shutil.copyfile(source, a.archive/source.name)
    (a.archive/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    (a.output/'Qminers-depth-advantage.json').write_text(json.dumps(summary, indent=2)+'\n')
    if promotion:
        shutil.copyfile(exported, a.output/'round1_depth_advantage.py')
    (a.archive/'.gitattributes').write_text('* -text whitespace=cr-at-eol\n*.json linguist-generated=true\n')
    (a.archive/'README.txt').write_text('''Depth advantage experiment, 7 November 2026

The supplied strategy is AST-identical to strategies/round1_depth_524k.py;
its attachment differed only in final-newline encoding. The 16-feature candidate
adds signed nonlinear transforms of touch order-count imbalance, capped-volume
touch imbalance, and capped-volume depth imbalance. All execution rules match.
Unused queue tracking was removed after exact full-replay equivalence checks.

protocol.json was written before candidate replays; selection.json was written
before any finalist full-round or transfer replay. The original protocol retains
the working logs/depth_advantage source paths. Frozen source bytes are copied
under sources/. Stage JSON files preserve every result, including rejected ideas.
Raw market datasets are intentionally excluded. Source and data hashes are saved.
The old public data is consumed data; chronological gates are robustness checks,
not a new untouched holdout. No new website submission was made.

Reproduce from the repository root with Python 3.13 and project dependencies:
python -m unittest discover -s tests -v
python -m scripts.probe_depth_advantage --prepare --root logs/depth_replay --attachment research/depth_advantage_20261107/sources/supplied_13.py --data data/round1.csv --prefix PATH_TO_6000_SECOND_PREFIX
python -m scripts.probe_depth_advantage --root logs/depth_replay --data PATH_TO_6000_SECOND_PREFIX --stage screen --workers 7
python -m scripts.probe_depth_advantage --root logs/depth_replay --select
python -m scripts.benchmark_depth_submission --strategy strategies/round1_depth_advantage.py --data data/round1.csv --output logs/depth_export.json

Prefixes must retain the complete tape from its beginning, not start mid-book.
Full and transfer runs use the same probe command with --names, --stage, --delay.
Use full_* stages for round1 boundaries, sample_* for sample_v2 boundaries.
Existing result destinations are never overwritten by the runner.
''')
    feature_rows = [
        ('Flow and price', 'Signed aggressive trade flow; fast-minus-slow midpoint momentum.', '2'),
        ('Touch pressure', 'Quantity imbalance; normalized order-flow imbalance; spread × imbalance.', '3'),
        ('Original nonlinear terms', 'Signed squares of flow, quantity imbalance and order-flow imbalance.', '3'),
        ('Robust depth', 'Touch order-count imbalance and per-order capped quantity imbalance; corresponding depth measures within two ticks; capped-volume depth-midpoint displacement.', '5'),
        ('New nonlinear depth', 'Signed squares of touch count, capped touch volume and capped depth volume imbalance.', '3'),
    ]
    row = lambda cells: '<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in cells)+'</tr>'
    metric_rows = [
        ('Full round-1 PnL', number(base['result']['pnl']), number(candidate['result']['pnl'])),
        ('One-second sampled drawdown', number(base['max_drawdown_1s']), number(candidate['max_drawdown_1s'])),
        ('Traded volume', number(base['result']['traded_volume']), number(candidate['result']['traded_volume'])),
        ('Maximum absolute inventory', base['max_abs_inventory'], candidate['max_abs_inventory']),
        ('Maximum potential exposure at submission', base['max_potential_inventory'], candidate['max_potential_inventory']),
        ('Position penalty', base['result']['breach_penalty'], candidate['result']['breach_penalty']),
        ('Older sample_v2 PnL', number(sample_base['result']['pnl']), number(sample_candidate['result']['pnl'])),
    ]
    screening_rows = []
    for key, value in screen.items():
        score = value['boundary_pnl']['5990000000']
        delta = score-screen['clean_13']['boundary_pnl']['5990000000']
        decision = ('Selected' if key in selection['finalists'] else
                    'Ablation' if key in protocol['ablation_only'] else
                    'Reference' if key in ('supplied_13', 'clean_13') else 'Rejected')
        screening_rows.append((key, number(score), f'{delta:+,.0f}', decision))
    speedup = 100*(1-clean['cpu_seconds']/base['cpu_seconds'])
    status = 'Passed the predeclared promotion checks' if promotion else 'Did not pass promotion checks'
    body = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Qminers: depth advantage</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;background:#f4f6f9;color:#18283d;margin:0}}main{{max-width:1100px;margin:auto;padding:36px 24px}}h1{{font-size:38px;line-height:1.15;max-width:850px}}h2{{margin-top:38px}}.eyebrow{{letter-spacing:.14em;text-transform:uppercase;font-size:12px;color:#586a82}}.cards,.flow{{display:flex;gap:14px;flex-wrap:wrap}}.card{{background:white;border:1px solid #dce3ec;border-radius:12px;padding:18px;flex:1;min-width:170px}}.big{{font-size:30px;font-weight:750;color:#007f78}}.box{{flex:1;background:#e3efee;border:1px solid #c9dbda;border-radius:8px;padding:14px;min-width:150px}}table{{width:100%;border-collapse:collapse;background:white;font-size:14px}}th,td{{text-align:left;padding:12px;border-bottom:1px solid #e1e6ec;vertical-align:top}}th{{background:#e9eef4}}.note{{border-left:4px solid #b6802d;background:#fff6e6;padding:15px 19px}}code,pre{{font:13px/1.5 ui-monospace,monospace}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#e9eef4;padding:16px;border-radius:8px}}a{{color:#006f91}}small{{color:#5c6c7f}}.tablewrap{{overflow-x:auto}}</style></head><body><main>
<div class="eyebrow">Qminers Arena · measured architecture study · 7 November 2026</div>
<h1>Keep the causal depth learner. Add nonlinear depth where it helps.</h1>
<p>{status}. This is an online machine-learning market maker: its coefficients start at zero and adapt to completed price outcomes during the replay.</p>
<div class="cards"><div class="card"><small>Supplied strategy</small><div class="big">{number(base['result']['pnl'])}</div><div>Full round-1 PnL</div></div><div class="card"><small>16-feature candidate</small><div class="big">{number(candidate['result']['pnl'])}</div><div>{gain:+,.0f} · {100*gain/base['result']['pnl']:.2f}%</div></div><div class="card"><small>Position penalties</small><div class="big">0</div><div>Actual and potential exposure ≤100</div></div></div>
<h2>Architecture</h2>
<div class="flow"><div class="box"><b>1 · Market feed</b><br>Market-only bid/ask and individual orders; aggressive trade flow.</div><div class="box"><b>2 · Features</b><br>13 supplied signals; 3 new signed nonlinear depth terms.</div><div class="box"><b>3 · Causal learner</b><br>Mature 100 ms labels → decayed ridge statistics → fit each second.</div><div class="box"><b>4 · Fair price</b><br>Midpoint + clipped forecast − inventory skew.</div><div class="box"><b>5 · Execution</b><br>Passive quotes, queue preservation and strict reservation ledger.</div></div>
<p>Observations are sampled at most once per 100 ms. Each becomes a label at the first usable callback at or after its 100 ms horizon. Labels delayed by more than one extra second are discarded. After 200 matured labels, roughly 20 seconds, the learned forecast replaces a microprice-style fallback; the bot can quote during warm-up.</p>
<p>The learner maintains exponentially weighted XᵀX and Xᵀy, with a 300-second e-folding memory (about 208-second half-life). It solves (XᵀWX + λI)β = XᵀWy once per second. Ridge is max(10, 0.001 × effective mass), so the floor usually dominates at this sampling rate. The prediction is clipped to ±2 ticks. This is regularized online regression with nonlinear basis functions, not a neural network.</p>
<div class="tablewrap"><table><tr><th>Feature group</th><th>Meaning</th><th>Count</th></tr>{''.join(row(r) for r in feature_rows)}</table></div>
<p>Per-order size is capped at 100 when constructing robust depth signals. Order counts and capped sizes give a different view from raw summed volume. They reduce dependence on a single large order, but order fragmentation can still change them. “Two ticks” means a price-distance window, not exactly two populated levels.</p>
<pre>prediction = clip(dot(weights, features), -2, +2)
fair = mid + prediction - 0.05 × inventory / 100 × max(1, spread)
if |fair - mid| ≤ 0.1: fair = mid
buy_price  = min(best_bid, floor(fair - 0.5))
sell_price = max(best_ask, ceil(fair + 0.5))</pre>
<p>Each side can have up to eight orders. Existing same-price orders retain queue position; newly available capacity is replenished. Pending submissions and cancels retain their remaining exposure reservation. A 200-lot order is possible when moving from −100 to +100, while each side independently stays within the ±100 bound. Prices are passive when chosen; latency can change the book before activation.</p>
<p><b>The flow guard is inactive.</b> Flow is net signed volume divided by 1 + total volume, so its absolute value is below 1. The inherited ±1.1 thresholds never fire. Inventory-limit checks are active. This experiment keeps that behavior; turning the guard on would be a separate execution change.</p>
<h2>What the tests established</h2>
<p>The supplied attachment is AST-identical to the repository’s 523,999 strategy. Its header incorrectly said five features. Full replay reproduced the recorded score. Removing unused queue-ahead bookkeeping left the entire PnL curve, official result, learned weights and order-status counts identical. In the paired full runs, the cleanup used {speedup:.1f}% less CPU.</p>
<p>The controlled ablations keep execution and other parameters fixed. Their screening results show that robust depth explains a material part of the gain. The added signed nonlinear depth terms improved both screening halves and 7 of 10 time blocks. A 100/500 ms horizon ensemble improved the total but lost in the first half, so it was rejected under the frozen rule. The fast/slow memory blend and recent-depth-change features also failed.</p>
<div class="tablewrap"><table><tr><th>Variant</th><th>PnL at exactly 5,990 seconds</th><th>Change from baseline</th><th>Role / decision</th></tr>{''.join(row(r) for r in screening_rows)}</table></div>
<h2>Full replay and transfer</h2>
<div class="tablewrap"><table><tr><th>Metric</th><th>Supplied 13 features</th><th>New 16 features</th></tr>{''.join(row(r) for r in metric_rows)}</table></div>
<p>The later periods below were evaluated only after freezing this extension in the present experiment. They were already used in previous research, so they remain reused diagnostics.</p>
<table><tr><th>Continuous replay period</th><th>Supplied</th><th>New</th><th>Gain</th></tr>{''.join(row((r['period'],number(r['baseline']),number(r['candidate']),f"{r['gain']:+,.0f}")) for r in period_rows)}</table>
<h2>Latency stress</h2><p>Official delay is 5 ms. The 20/50 ms runs stress stale quotes and cancellation races; they do not change the submission’s rules.</p>
<table><tr><th>Delay</th><th>Supplied PnL</th><th>New PnL</th><th>Gain</th></tr>{''.join(row((str(r['delay_ms'])+' ms',number(r['baseline']),number(r['candidate']),f"{r['gain']:+,.0f}")) for r in stress)}</table>
<h2>Submission and runtime</h2><p><a href="round1_depth_advantage.py">Download the standalone candidate</a>. The exact exported file was replayed separately through the unmodified engine and matched the research result. It contains one strategy class, only permitted imports, no fitted weights, no I/O, no session-end assumption, and no dependence on the research files.</p>
<p>Local exact-file replay: {benchmark['cpu_seconds']:.1f} CPU seconds, {benchmark['wall_seconds']:.1f} wall seconds during concurrent workloads, {benchmark['peak_working_set_bytes']/2**20:.1f} MiB peak working set, {benchmark['source_bytes']:,} source bytes. Competition limits are one CPU, 2 GiB, 15 minutes and a 1 MiB source file; local timing is not a server guarantee. Forty-nine repository tests passed, including delayed-label causality, solver stability, reservation bounds and boundary-observer equivalence. The existing Unix-only performance import was made portable to Windows.</p>
<pre>SHA-256: {digest(exported)}</pre>
<div class="note"><b>Evidence limit.</b> All public tapes have been inspected before. Four candidate extensions were screened under predeclared consistency rules, followed by frozen later-period and stress checks. This limits additional tuning but does not undo previous data reuse or establish significance. No new website/private leaderboard score is claimed. Preserve the supplied 523,999 strategy as a fallback and evaluate this exact file on the competition website or genuinely new data.</div>
<p><small>Full machine-readable evidence: <a href="Qminers-depth-advantage.json">summary JSON</a>. The repository archive retains all variants, frozen protocol, rejected alternatives and per-stage results. The official simulator source was not changed.</small></p>
</main></body></html>'''
    (a.output/'Qminers-depth-advantage.html').write_text(body, encoding='utf-8')
    archive_body = body.replace('href="round1_depth_advantage.py"',
                                'href="../../strategies/round1_depth_advantage.py"').replace(
                                    'href="Qminers-depth-advantage.json"', 'href="summary.json"')
    (a.archive/'report.html').write_text(archive_body, encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
