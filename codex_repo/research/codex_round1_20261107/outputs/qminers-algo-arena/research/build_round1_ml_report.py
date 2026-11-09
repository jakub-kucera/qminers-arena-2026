"""Explain the learned-model experiment without presenting training gains as test gains."""
import html
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

from ml_round1_common import DEST, ROOT, file_hash

OUT = ROOT.parent
NAMES = {'ridge9_1s':'Ridge, 9 features, 1 s', 'ridge24_1s':'Ridge, 24 features, 1 s',
         'cat9_1s':'CatBoost, 9 features, 1 s', 'cat24_1s':'CatBoost, history features, 1 s',
         'cat24_025s':'CatBoost, history features, 250 ms', 'mlp24_1s':'Neural network, history features, 1 s',
         'cat_fill25':'CatBoost, fill-conditioned markout'}


def read(name):
    return json.loads((DEST / name).read_text(encoding='utf-8'))


def signed(number):
    return f'{number:+,.0f}'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{html.escape(str(x))}</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def main():
    selection, outcome, fitting = read('selection.json'), read('outcome.json'), read('fit_results.json')
    results, stress, benchmark = read('validation_summary.json'), read('stress_summary.json'), read('candidate_benchmark.json')
    interpretation = read('interpretation.json')
    ml = read('final_ml.json')
    f4 = json.loads((ROOT / 'research/round1_results/team_F4.json').read_text())
    prior_stress = json.loads((ROOT / 'research/round1_results/stress_summary.json').read_text())
    by_name = {r['name']:r for r in results + stress + prior_stress}
    reference = by_name['f4_reference']['policy_validation_pnl']
    assert len(results) == 18 and len(stress) == 2
    assert benchmark['result'] == ml['result']
    assert all(r['result']['breach_penalty']==0 and r['max_reserved_exposure']<=100 for r in results+stress+[ml])
    source = Path(selection['export'])
    assert file_hash(source) == selection['sha256'] == benchmark['sha256']
    training_f4, training_ml = sum(f4['quarter_pnl'][:2]), sum(ml['quarter_pnl'][:2])
    later_f4, later_ml = sum(f4['quarter_pnl'][2:]), sum(ml['quarter_pnl'][2:])
    full_gain = ml['result']['pnl'] - f4['result']['pnl']
    later_gain, later_pct = later_ml-later_f4, 100*(later_ml/later_f4-1)
    training_share = 100*(training_ml-training_f4)/full_gain
    rows = []
    for key, label in NAMES.items():
        a, b = by_name[f'{key}_t0'], by_name[f'{key}_t40']
        best = max(a['policy_validation_pnl'], b['policy_validation_pnl'])
        rows.append([label, signed(a['policy_validation_pnl']), signed(b['policy_validation_pnl']), signed(best-reference)])
    rows.sort(key=lambda row:float(row[-1].replace(',','')), reverse=True)
    ranking = table(['Learned model', 'Quote filter only', 'Filter + inventory target', 'Best versus F4'], rows)
    stage_rows = [
        ['First 100 min: used for model fitting', signed(training_f4), signed(training_ml), signed(training_ml-training_f4)],
        ['Next 50 min: policy validation', signed(f4['quarter_pnl'][2]), signed(ml['quarter_pnl'][2]), signed(ml['quarter_pnl'][2]-f4['quarter_pnl'][2])],
        ['Last 50 min: reused diagnostic tail', signed(f4['quarter_pnl'][3]), signed(ml['quarter_pnl'][3]), signed(ml['quarter_pnl'][3]-f4['quarter_pnl'][3])],
        ['Periods excluded from fitting, combined', signed(later_f4), signed(later_ml), signed(later_gain)],
        ['Entire tape, includes training', signed(f4['result']['pnl']), signed(ml['result']['pnl']), signed(full_gain)],
    ]
    stages = table(['Period', 'F4', 'Selected ML', 'Difference'], stage_rows)
    latency_rows=[]
    for delay, base, candidate in [(5,f4,ml),(20,by_name['team_F4_delay20'],by_name['ml_delay20']),
                                   (50,by_name['team_F4_delay50'],by_name['ml_delay50'])]:
        latency_rows.append([f'{delay} ms',signed(base['result']['pnl']),signed(candidate['result']['pnl']),
            signed(sum(candidate['quarter_pnl'][2:])-sum(base['quarter_pnl'][2:]))])
    latency = table(['Order delay', 'F4 full tape', 'ML full tape', 'ML advantage in periods excluded from fitting'],latency_rows)

    original_curve = np.load(ROOT/'research/round1_results/team_F4_trace.npz')['curve']
    candidate_curve = np.load(DEST/'final_ml_trace.npz')['curve']
    assert np.array_equal(original_curve[:,0],candidate_curve[:,0])
    curve = go.Figure(go.Scatter(x=(candidate_curve[:,0]/60e6).tolist(),
        y=(candidate_curve[:,1]-original_curve[:,1]).tolist(),name='ML minus F4',line=dict(color='#3568a8',width=2)))
    curve.add_vrect(x0=0,x1=100,fillcolor='#bfc7ce',opacity=.3,line_width=0,
                   annotation_text='Used for fitting',annotation_position='top left')
    curve.add_vrect(x0=100,x1=150,fillcolor='#c6e4e4',opacity=.3,line_width=0,
                   annotation_text='Policy validation',annotation_position='bottom left')
    curve.add_vrect(x0=150,x1=200,fillcolor='#ffe5ae',opacity=.35,line_width=0,
                   annotation_text='Reused diagnostic tail',annotation_position='bottom right')
    curve.update_layout(template='plotly_white',height=390,margin=dict(l=70,r=20,t=30,b=50),
                        xaxis_title='Round time (minutes)',yaxis_title='Cumulative ML PnL advantage',font=dict(family='Segoe UI, sans-serif'))
    chart = pio.to_html(curve,full_html=False,include_plotlyjs=True,div_id='ml-advantage',config=dict(displaylogo=False,responsive=True))
    importance = interpretation['selected_model_feature_importance'][:5]
    importance_table = table(['Feature', 'Training importance'],[[label,f'{value:.1f}%'] for label,value in importance])
    old = interpretation['old_forecasts_on_same_validation']
    prediction_rows = [['Earlier sample-trained Ridge, 1 s',f'{old["old_ridge"]["correlation"]:.3f}'],
        ['Earlier sample-trained ensemble, 1 s',f'{old["old_ensemble"]["correlation"]:.3f}']]
    for name in ['ridge9_1s','ridge24_1s','cat9_1s','cat24_1s','mlp24_1s']:
        prediction_rows.append([NAMES[name],f'{fitting[name]["policy_validation_forecast"]["correlation"]:.3f}'])
    prediction_table = table(['One-second forecast on the same validation period', 'Correlation'],prediction_rows)

    conclusion = (f'Machine learning is worth investigating, but this experiment does not establish a strong '
        f'advantage over F4. The selected 250 ms CatBoost policy earned +403,073 versus +399,096 over the '
        f'whole tape. However, {training_share:.1f}% of the 3,977-point gain came from the period used for '
        f'fitting. In the periods excluded from fitting, it earned +209,513 versus +209,052: a gain of '
        f'461 points ({later_pct:.2f}%). The neural-network configuration did not beat F4 in policy validation.')
    recommendation = ('Keep the frozen ML file as an experimental challenger alongside F4. Its positive '
        'validation and diagnostic-tail margins satisfy the predeclared numerical gate, but the margins '
        'are too small and the evaluation too reused to establish a reliable winning advantage. Evaluate '
        'both once on genuinely new round data before preferring ML for generalization. No policy was '
        'retuned after the final-quarter result.')
    model_description = ('The selected model is CatBoost with 192 symmetric trees of depth four. It learns '
        'a roughly 250 ms future mid-price change from 24 causal features: nine current book/flow '
        'measurements plus changes over 250 ms, one second, and five seconds. Predicted moves shift a '
        'bounded inventory target and suppress quotes whose predicted edge is below 0.15 ticks. F4-style '
        'queue preservation, replenishment, depletion checks and per-side exposure reservation remain '
        'deterministic. Training used the NVIDIA RTX 3070 Ti; the exported strategy runs on the CPU.')
    fitting_description = ('Seven models were fitted: two Ridge regressions, four GPU CatBoost models '
        '(including a fill-conditioned model), and one 32/16-unit ReLU neural network with 1,345 learned '
        'parameters. The neural network was trained on CPU. Initial fitting used seconds 0–4,800; '
        'seconds 4,800–6,000 selected tree count or neural training duration. Models were then refitted '
        'on seconds 0–6,000 with those settings. Targets crossing boundaries were excluded. Two '
        'predeclared quoting policies per model were evaluated on seconds 6,000–9,000, alongside two '
        'raw-microprice policies and two equivalent F4 controls. The F4 implementation and the ML '
        'execution framework reproduced exactly with the learned signals disabled.')
    evaluation_description = ('The best ML validation policy was frozen before its full-tape replay. '
        'The final 3,000 seconds were excluded from new fitting and policy tuning, but had already '
        'been viewed in earlier round-one analyses. They are a reused diagnostic tail, not an untouched '
        'test set. The validation selection replay ends at 9,000 seconds and uses terminal liquidation; '
        'the continuous full run uses its sampled PnL at the boundary. Consequently selection scores '
        'are 106,950 versus 106,807, while the continuous-run validation interval is 106,896 versus '
        '106,753. The relative ML advantage is 143 in both calculations.')
    prediction_note = ('Retraining substantially improved one-second predictive correlation compared '
        'with the old sample-trained models, but higher correlation did not reliably increase profit. '
        'The selected shorter-horizon model has correlation 0.476 against its own 250 ms target; this '
        'is not directly comparable with the one-second values below. The neural network was tested '
        'only at a one-second horizon, so the experiment does not prove trees are universally superior '
        'to neural networks. Targets use the last sampled mid at or before the requested horizon.')
    fill_note = ('The fill-conditioned model used 21,154 first-half F4 fill observations, with features '
        'available at least 5 ms before each fill and weights capped at 100 lots. Its target was a '
        'one-second signed mid markout from the earlier decision touch. It performed poorly as a quote '
        'filter. Training conditional on one policy’s fills does not by itself estimate the value of '
        'all the counterfactual fills under a changed policy.')
    runtime = (f'The exact 93,771-byte ML export reproduced +403,073 using the official loader and '
        f'engine in {benchmark["wall_seconds"]:.1f} seconds wall time and '
        f'{benchmark["cpu_seconds"]:.1f} seconds CPU, with '
        f'{benchmark["peak_working_set_bytes"]/1024**2:.1f} MiB peak working set on Windows. '
        'Other final checks ran concurrently; remote sandbox runtime is unmeasured. The export imports '
        'only math, struct and the public simulator API, with no training-library, network or file '
        'dependency. The local source validator passed it.')
    verification = ('Eighteen prefix replays, one full-tape diagnostic replay, one exact-file benchmark '
        'and two latency checks were completed. All research replays had zero penalties and maximum '
        'reserved exposure at most 100. The final ML run reached inventory 100, had median absolute '
        'inventory 98, and finished flat. Its one-second sampled maximum drawdown was 956 versus '
        '1,045 for F4. Faster excursions are not captured by this drawdown. Streaming and batch history '
        'features matched exactly on 87,414 observations. Exports matched native model predictions '
        'to less than 1e-8 on 2,500 checked rows per model. GPU fitting is not bitwise deterministic; '
        'the actual fitted models, literal exports and hashes are retained.')
    latency_note = ('The frozen ML candidate stayed ahead of F4 in the additional 20 ms and 50 ms '
        'checks, without penalties. Full-tape stress scores still include training data; the last '
        'column isolates the later periods excluded from model fitting. These are sensitivity '
        'checks on the same tape, not new independent evaluations.')
    next_steps = ('The next useful comparison is the same short horizon across Ridge, trees and the '
        'neural network on genuinely new chronological data. Use ML to estimate quote value or '
        'adjust inventory, retain deterministic risk limits, and judge it by executable PnL with '
        'fill and latency effects. A larger network or reinforcement-learning agent is not justified '
        'by this small gain; more diverse market episodes and a reliable evaluation matter more.')
    command = '.venv/Scripts/exchange-simulator.exe --strategy strategies/round1_ml_candidate.py --backtest data/round1.csv --log-dir logs/round1-ml --no-logs'
    paragraphs = [
        'QMINERS ROUND-ONE MACHINE-LEARNING EXPERIMENT — 7 NOVEMBER 2026', conclusion, recommendation,
        'MODEL\n'+model_description, 'CHRONOLOGICAL FITTING\n'+fitting_description,
        'VALIDATION PNL\nModel | Quote filter only | Filter + inventory target | Best minus F4\n'+'\n'.join(' | '.join(r) for r in rows),
        'FULL REPLAY DECOMPOSITION\nPeriod | F4 | ML | Difference\n'+'\n'.join(' | '.join(r) for r in stage_rows),
        evaluation_description, prediction_note, fill_note, runtime, verification,
        'LATENCY\nDelay | F4 full | ML full | Later-period ML advantage\n'+'\n'.join(' | '.join(r) for r in latency_rows),
        latency_note, 'NEXT EXPERIMENT\n'+next_steps,
        'REPRODUCE\n'+command,
        'EXPORT SHA256\n'+selection['sha256'],
        'PRIMARY DOCUMENTATION\nhttps://catboost.ai/docs/en/features/training-on-gpu\nhttps://catboost.ai/docs/en/features/export-model-to-python',
    ]
    txt = OUT/'Qminers-round1-ML-results.txt'
    txt.write_text('\n\n'.join(paragraphs)+'\n',encoding='utf-8')
    page = OUT/'Qminers-round1-ML-results.html'
    parts=[
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qminers — learned-model experiment</title>',
        '<style>body{margin:0;background:#f3f5f7;color:#23364b;font:16px/1.6 "Segoe UI",sans-serif}main{max-width:1100px;margin:auto;padding:38px 24px 65px}h1{font-size:35px;line-height:1.2}h2{font-size:23px;margin-top:32px}small,.note{color:#5c6f81}.callout{border-left:4px solid #c4963e;background:#fff4dd;padding:16px 20px;margin:22px 0}a{color:#275f9c}.button{display:inline-block;border-radius:5px;padding:10px 16px;background:#3568a8;color:white;text-decoration:none}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;background:white;font-size:14px}th,td{padding:10px 12px;border-bottom:1px solid #e0e6ec;text-align:right;white-space:nowrap}th{background:#e9eef4}th:first-child,td:first-child{text-align:left}pre{background:#e5ebf0;padding:15px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}footer{font-size:13px;color:#5c6f81;margin-top:30px}code{overflow-wrap:anywhere}details{margin-top:24px}summary{cursor:pointer;font-weight:600}@media(max-width:650px){main{padding:24px 12px}h1{font-size:28px}}</style></head><body><main>',
        '<small>LOCAL EXPERIMENT · 7 NOVEMBER 2026</small><h1>ML is competitive; the measured advantage is small</h1>',
        '<p>'+html.escape(conclusion)+'</p>',
        '<div class="callout"><strong>Keep training gains separate.</strong> The ML advantage is <strong>0.22%</strong> across the periods excluded from fitting. The final quarter was previously inspected. This is an experimental challenger, with no demonstrated advantage on unseen competition data.</div>',
        '<a class="button" href="qminers-algo-arena/strategies/round1_ml_candidate.py" download>Download the frozen ML candidate</a> &nbsp; <a href="qminers-algo-arena/strategies/round1_best.py" download>F4 baseline</a> &nbsp; <a href="Qminers-round1-ML-results.txt">Plain-text report</a>',
        '<h2>Where the gain came from</h2>'+stages+chart+'<p>'+html.escape(evaluation_description)+'</p>',
        '<h2>What the model learns</h2><p>'+html.escape(model_description)+'</p>'+importance_table,
        '<p class="note">Training importance describes the fitted model; it is not causal attribution.</p>',
        '<h2>All learned-model policy comparisons</h2><p>F4 validation reference: <strong>+106,807</strong>. All models retain the same execution and risk controls. The two policy settings were fixed before backtesting.</p>'+ranking,
        '<h2>Prediction quality and trading profit</h2><p>'+html.escape(prediction_note)+'</p>'+prediction_table+'<p>'+html.escape(fill_note)+'</p>',
        '<h2>Latency checks</h2>'+latency+'<p>'+html.escape(latency_note)+'</p>',
        '<h2>Training and verification</h2><p>'+html.escape(fitting_description)+'</p><p>'+html.escape(verification)+'</p><p>'+html.escape(runtime)+'</p>',
        '<p>CatBoost documents <a href="https://catboost.ai/docs/en/features/training-on-gpu">GPU training and its nondeterminism</a> and <a href="https://catboost.ai/docs/en/features/export-model-to-python">standalone Python export</a>. The compact numeric-tree evaluator here was independently checked against the fitted library models.</p>',
        '<h2>Practical recommendation</h2><p>'+html.escape(recommendation)+'</p><p>'+html.escape(next_steps)+'</p><pre>'+html.escape(command)+'</pre>',
        '<details><summary>Experiment records</summary><p><a href="qminers-algo-arena/research/ml_round1_results/experiment_plan.json">Predeclared plan</a> · <a href="qminers-algo-arena/research/ml_round1_results/fit_results.json">Training and prediction results</a> · <a href="qminers-algo-arena/research/ml_round1_results/validation_summary.json">All policy runs</a> · <a href="qminers-algo-arena/research/ml_round1_results/selection.json">Frozen selection</a> · <a href="qminers-algo-arena/research/ml_round1_results/outcome.json">Outcome</a> · <a href="qminers-algo-arena/research/ml_round1_results/candidate_benchmark.json">Exact-file benchmark</a></p></details>',
        '<footer><p>Export SHA256: <code>'+selection['sha256']+'</code></p><p>The F4 baseline and original simulator remain unchanged. No website upload, repository push or sharing change was performed.</p></footer></main></body></html>',
    ]
    page.write_text(''.join(parts),encoding='utf-8')
    manifest=dict(models=7,prefix_replays=18,full_diagnostic_replays=1,exact_export_replays=1,
        latency_replays=2,later_period_gain=later_gain,later_period_gain_percent=later_pct,
        full_gain=full_gain,training_share_of_gain_percent=training_share,
        files={str(p.relative_to(OUT)):file_hash(p) for p in [source,txt,page,DEST/'outcome.json']})
    (DEST/'report_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(dict(report=str(page),later_gain=later_gain,later_gain_percent=later_pct,training_share=training_share)))


if __name__=='__main__':
    main()
