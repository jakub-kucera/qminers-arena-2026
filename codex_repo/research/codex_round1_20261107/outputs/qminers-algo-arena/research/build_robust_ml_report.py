"""Make the auditable robustness report from frozen, completed replay results."""
import html
import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ml_round1_common import file_hash, load_features
from robust_ml_common import DEST, PREVIOUS, ROOT, at, enrich, load_json
from run_study import dump

OUT=ROOT.parent
OLD=ROOT/'research/round1_results'
NAMES=dict(f4='F4 baseline',prior_cat='Previous CatBoost',elastic250='Elastic Net',
    diverse_composite='Diverse composite',ridge250='Ridge',huber250='Huber',
    forest250='ExtraTrees',window_ensemble='Window ensemble',guarded_ensemble='Disagreement guard',
    calibrated_logit='Calibrated logistic')


def result(directory,name):
    r=load_json(directory/f'{name}.json')
    return enrich(r,directory)


def table(headers,rows):
    def cell(v):
        return html.escape(str(v))
    return '<div class="table"><table><thead><tr>'+''.join(f'<th>{cell(h)}</th>' for h in headers)+\
        '</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{cell(v)}</td>' for v in row)+'</tr>' for row in rows)+\
        '</tbody></table></div>'


def link(path,label):
    target=Path(path).relative_to(OUT).as_posix()
    return f'<a href="{html.escape(target)}">{html.escape(label)}</a>'


def n(value):
    return f'{value:,.0f}'


def main():
    selection=load_json(DEST/'selection.json')
    final=load_json(DEST/'final_summary.json')
    assert len(final)==10
    benchmark=load_json(DEST/'candidate_benchmark.json')
    verify=load_json(DEST/'verification.json')
    fit=load_json(DEST/'fit_results.json')
    candidates=selection['candidates']
    validation=load_json(DEST/'validation_summary.json')+load_json(DEST/'reused_controls.json')
    byname={r['name']:r for r in validation}
    byfinal={r['name']:r for r in final}
    runs={}
    for delay in (5,20,50):
        runs[('f4',delay)]=result(OLD,'team_F4'+('' if delay==5 else f'_delay{delay}'))
        runs[('prior_cat',delay)]=result(PREVIOUS,'final_ml' if delay==5 else f'ml_delay{delay}')
        for c in candidates:
            runs[(c['name'],delay)]=byfinal[f"final_{c['name']}_d{delay}"]
    names=['f4','prior_cat']+[c['name'] for c in candidates]
    primary=candidates[0]['name']
    winner=runs[(primary,5)]
    baseline=runs[('f4',5)]
    assert winner['result']==benchmark['result']
    assert benchmark['cpu_seconds']<900 and benchmark['peak_working_set_bytes']<2*1024**3
    assert file_hash(ROOT/'strategies/round1_best.py')=='4667d01bfd43e92e75369576ddf777fbfb62ea5923d320ae06849c5059564b04'
    assert file_hash(ROOT/'strategies/round1_ml_candidate.py')=='afcd83d1a5e77cfbdb7db8d6953cd33b51686b3639c0149dee1be58cddbafc35'
    assert all(r['result']['breach_penalty']==0 and r['max_reserved_exposure']<=100 for r in final+validation)
    full_gain=winner['result']['pnl']-baseline['result']['pnl']
    later_gain=winner['outside_fit_pnl']-baseline['outside_fit_pnl']
    tail_gain=winner['tail_pnl']-baseline['tail_pnl']
    v2delta=byfinal[f'v2_{primary}']['result']['pnl']-byfinal['v2_f4']['result']['pnl']

    # Paired five-minute blocks are descriptive diagnostics, not independent trials.
    curves={name:np.load((OLD if name=='f4' else PREVIOUS if name=='prior_cat' else DEST)/
        (('team_F4' if name=='f4' else 'final_ml' if name=='prior_cat' else f'final_{name}_d5')+'_trace.npz'))['curve']
        for name in names}
    block_records={}
    for name in names[1:]:
        differences=[]
        for left in range(9000,12000,300):
            right=left+300
            end=runs[(name,5)]['result']['pnl'] if right==12000 else at(curves[name],right)
            base_end=baseline['result']['pnl'] if right==12000 else at(curves['f4'],right)
            differences.append((end-at(curves[name],left))-(base_end-at(curves['f4'],left)))
        block_records[name]=dict(excess_by_5min_block=differences,positive=sum(v>0 for v in differences),total=10)

    validation_rows=[]
    for row in selection['ranking']:
        name=row['name']
        validation_rows.append([NAMES[name],n(byname[name+'_d5']['validation_pnl']),
            f"{row['excess'][0]:+,.0f}",n(byname[name+'_d20']['validation_pnl']),
            f"{row['excess'][1]:+,.0f}",f"{row['positive_blocks']}/6",
            'Pass' if row['passes_validation_gate'] else 'Fail'])
    full_rows=[]
    for name in names:
        r=runs[(name,5)]
        full_rows.append([NAMES[name],n(r['result']['pnl']),n(r['training_pnl']),
            n(r['validation_pnl']),n(r['tail_pnl']),n(r['outside_fit_pnl']),n(r['max_drawdown'])])
    latency_rows=[]
    for name in names:
        vals=[runs[(name,d)]['outside_fit_pnl'] for d in (5,20,50)]
        latency_rows.append([NAMES[name]]+[n(v) for v in vals]+[
            f"{vals[i]-runs[('f4',d)]['outside_fit_pnl']:+,.0f}" for i,d in enumerate((5,20,50))])
    v2_rows=[]
    for name in names:
        r=byfinal[f'v2_{name}']
        v2_rows.append([NAMES[name],n(r['result']['pnl']),
            f"{r['result']['pnl']-byfinal['v2_f4']['result']['pnl']:+,.0f}",n(r['max_drawdown'])])

    fig=make_subplots(rows=2,cols=1,vertical_spacing=.18,
        subplot_titles=('Cumulative profit difference versus F4, reset after fitting',
                        'Final 50 minutes: profit difference in five-minute blocks'))
    colors={'elastic250':'#078b75','diverse_composite':'#7060bc','prior_cat':'#bc7a21'}
    for name in names[1:]:
        grid=np.arange(6000,12000,10)
        delta=np.array([at(curves[name],s)-at(curves['f4'],s) for s in grid])
        delta-=at(curves[name],6000)-at(curves['f4'],6000)
        grid=np.append(grid,12000)
        delta=np.append(delta,runs[(name,5)]['outside_fit_pnl']-baseline['outside_fit_pnl'])
        fig.add_trace(go.Scatter(x=grid/60,y=delta,name=NAMES[name],line=dict(color=colors[name],width=2.3)),row=1,col=1)
        fig.add_trace(go.Bar(x=[f'{s/60:.0f}–{(s+300)/60:.0f}' for s in range(9000,12000,300)],
            y=block_records[name]['excess_by_5min_block'],name=NAMES[name],showlegend=False,
            marker_color=colors[name]),row=2,col=1)
    fig.add_vline(x=150,line_dash='dot',line_color='#82939a',row=1,col=1)
    fig.add_hline(y=0,line_color='#82939a',row=1,col=1)
    fig.add_hline(y=0,line_color='#82939a',row=2,col=1)
    fig.update_layout(height=700,template='plotly_white',font=dict(family='Segoe UI, Arial',size=13),
        margin=dict(l=55,r=25,t=65,b=55),legend=dict(orientation='h',y=1.08),barmode='group',
        paper_bgcolor='white',plot_bgcolor='white')
    fig.update_xaxes(title_text='Minutes into round1 (100–150 selected on; 150–200 diagnostic)',row=1,col=1)
    fig.update_xaxes(title_text='Minutes into round1',row=2,col=1)
    fig.update_yaxes(title_text='PnL difference',row=1,col=1)
    fig.update_yaxes(title_text='PnL difference',row=2,col=1)
    chart=fig.to_html(full_html=False,include_plotlyjs=True,config=dict(displaylogo=False,responsive=True))

    # Standardized linear coefficients are descriptive, not causal importance.
    f,_,x=load_features()
    train=f[:,0]+250000<6000e6
    params=load_json(DEST/'all_parameters.json')
    base_names=['Spread','Touch imbalance','Five-tick depth imbalance','Signed flow / volume (1s)',
        'Mid minus 1s EMA','Mid minus 5s EMA','Log touch volume','Log flow volume','Microprice minus mid']
    feature_names=base_names[:]
    for lag in ('250ms','1s','5s'):
        feature_names += [base_names[i]+' change '+lag for i in (1,2,3,8)]+['Mid change '+lag]
    coefficient=np.array(params['elastic250'][0]['coef'])
    scale=x[train].std(axis=0)
    importance=sorted(zip(feature_names,coefficient,coefficient*scale),key=lambda z:abs(z[2]),reverse=True)
    coefficient_rows=[[name,f'{raw:+.5f}',f'{standard:+.5f}'] for name,raw,standard in importance[:10]]

    recommendation=(f'Elastic Net is the preferred round1 challenger: {n(winner["result"]["pnl"])} total PnL, '
        f'{later_gain:+,.0f} ({later_gain/baseline["outside_fit_pnl"]:.2%}) over F4 in the later half excluded from fitting. '
        f'Its older-sample result is {v2delta:+,.0f} versus F4, so it is not a universal replacement. '
        'Keep F4 as the reference and use the composite as a frozen alternative.')
    outcome=dict(recommendation=recommendation,primary=primary,full_gain=full_gain,
        outside_fit_gain=later_gain,outside_fit_relative_gain=later_gain/baseline['outside_fit_pnl'],
        tail_gain=tail_gain,v2_gain=v2delta,training_gain=winner['training_pnl']-baseline['training_pnl'],
        full_results={name:{str(d):runs[(name,d)] for d in (5,20,50)} for name in names},
        tail_blocks=block_records,replays_new=29,validation_replays=18,final_replays=10,exact_export_replays=1,
        training_seconds=fit['seconds'],benchmark=benchmark,
        limitations=['Repeatedly inspected tapes; no untouched test set or selection-adjusted significance claim.',
            'Labels use the last sampled mid at/before 250ms; median realized horizon 204.8ms.',
            'Risk controls verified locally; dashboard/server evaluation not performed.',
            'PnL includes executable terminal liquidation; prefix and continuous boundary values differ.',
            'The official simulator has no fees; real-market queue position, impact and fees are not validated.'])
    dump(DEST/'outcome.json',outcome)

    artifacts=' · '.join([link(candidates[0]['export'],'Elastic Net submission file'),
        link(candidates[1]['export'],'Composite submission file'),link(ROOT/'strategies/round1_best.py','F4 baseline'),
        link(DEST/'experiment_plan.json','Frozen experiment plan'),link(DEST/'selection.json','Selection record'),
        link(DEST/'outcome.json','All results JSON'),link(ROOT/'research/fit_robust_ml.py','Training script'),
        link(ROOT/'research/run_robust_ml.py','Replay script'),link(DEST/'verification.json','Verification')])
    body=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qminers — robust ML comparison</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f2f5f7;color:#172c38;font:16px/1.6 'Segoe UI',Arial,sans-serif}}
main{{max-width:1220px;margin:auto;padding:42px 28px}}header{{border-bottom:3px solid #078b75;padding-bottom:25px;margin-bottom:28px}}
h1{{font-size:35px;line-height:1.2;margin:8px 0 18px}}h2{{font-size:24px;margin:32px 0 12px}}h3{{font-size:19px;margin:24px 0 10px}}
p{{max-width:1080px}}.eyebrow{{text-transform:uppercase;font-size:13px;letter-spacing:2px;color:#52707c}}
.lead{{font-size:19px}}.note{{background:#fff2d8;border-left:4px solid #bd7d25;padding:16px 20px;margin:22px 0}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card{{background:white;border:1px solid #dce5e9;border-radius:10px;padding:18px}}
.value{{font-size:29px;font-weight:650;color:#067663}}.label{{font-size:13px;color:#526b77}}.table{{overflow-x:auto;margin:18px 0}}
table{{border-collapse:collapse;width:100%;background:white;font-size:14px}}th,td{{padding:12px;border-bottom:1px solid #dce5e9;text-align:right;white-space:nowrap}}
th{{background:#173b4b;color:white;font-weight:600}}th:first-child,td:first-child{{text-align:left}}tr:nth-child(even){{background:#f6f9fa}}
a{{color:#007b81;text-decoration:underline}}.artifacts{{background:white;padding:20px;border-radius:10px;line-height:2.2}}
.small{{font-size:13px;color:#536b76}}code{{background:#e5eef0;padding:2px 5px;border-radius:3px}}li{{margin:8px 0}}
@media(max-width:800px){{main{{padding:24px 16px}}.cards{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:29px}}}}
</style></head><body><main>
<header><div class="eyebrow">Qminers Arena · round1 · local research · 7 November 2026</div>
<h1>Robust ML helps — but the market regime still matters</h1><p class="lead">{html.escape(recommendation)}</p></header>
<div class="cards"><div class="card"><div class="value">{n(winner['result']['pnl'])}</div><div class="label">Elastic Net · full tape · 5ms</div></div>
<div class="card"><div class="value">{later_gain/baseline['outside_fit_pnl']:+.2%}</div><div class="label">Later-half improvement versus F4</div></div>
<div class="card"><div class="value">{candidates[0]['positive_blocks']}/6</div><div class="label">Validation blocks improved · two delays</div></div>
<div class="card"><div class="value">0</div><div class="label">Inventory penalties · all new runs</div></div></div>
<div class="note">Both tapes were already inspected during earlier research. The later half was excluded from model fitting, but it is not a new untouched test set. These improvements support a local challenger, not a proven winning strategy. The round1 export assumes a 12,000-second session.</div>
<div class="artifacts">{artifacts}</div>
<h2>What was tested</h2><p>Eight new candidates: Ridge, Elastic Net, Huber regression, 64 shallow randomized trees, a three-window CatBoost ensemble, its disagreement guard, an equal blend of Elastic Net / ExtraTrees / CatBoost, and temperature-calibrated multinomial logistic regression. CatBoost training used the RTX 3070 Ti. Up to 18 CPU replay workers ran concurrently. This phase completed 29 new replays, including an exact official-loader benchmark.</p>
<p>All forecasts use the same 24 causal features and the last sampled midpoint at or before 250ms ahead (median actual horizon {verify['label_horizon_ms_quantiles'][1]:.1f}ms). Execution stays fixed: forecast-driven target inventory, a 0.15-tick edge floor, 100-lot inventory reservation limits, and the same cancel/acknowledgement handling.</p>
<h2>Validation selected Elastic Net and the composite</h2><p>Fit and tuning use the first 100 minutes. Validation covers minutes 100–150, divided into three blocks, at 5ms and 20ms latency. A model must improve total profit at both delays and at least four of the six paired blocks. Ranking uses the smaller relative improvement across the two delays. The top two new models were frozen before the follow-up runs.</p>
{table(['Model','5ms PnL','Δ F4','20ms PnL','Δ F4','Blocks improved','Gate'],validation_rows)}
<p class="small">F4 validation totals: {n(byname['f4_d5']['validation_pnl'])} at 5ms and {n(byname['f4_d20']['validation_pnl'])} at 20ms. Prefix-end liquidation differs slightly from the continuous full-tape boundary; the full table below uses continuous runs. All values are simulator PnL units.</p>
<h2>Full round1 results, with fitting separated</h2>
{table(['Model','Full PnL','First 100min','Validation 50min','Final 50min','Later 100min','Sampled drawdown'],full_rows)}
<p>Elastic Net adds {later_gain:+,.0f} after fitting, including {tail_gain:+,.0f} in the final 50 minutes. It improves {block_records[primary]['positive']}/10 five-minute blocks in that final period. Blocks share one market session and are descriptive, not independent evidence of statistical significance. Drawdown is measured on one-second samples.</p>
{chart}
<h2>Latency stress: later-half PnL only</h2>
{table(['Model','5ms','20ms','50ms','Δ F4 5ms','Δ F4 20ms','Δ F4 50ms'],latency_rows)}
<p>These tests change order and cancellation delays together. The candidate parameters and execution rules remain frozen.</p>
<h2>Transfer to sample_v2 exposes a limitation</h2>
{table(['Model','Full PnL at 5ms','Δ F4','Sampled drawdown'],v2_rows)}
<p>No model was retrained on this stress tape. Only the session horizon changed to 5,750 seconds. Elastic Net trails F4 by {n(-v2delta)} here, while the composite is close to F4. The sample has a different spread and price-motion regime. This is evidence against claiming a universal winner; the transfer test alone does not identify the cause of the difference.</p>
<h2>What the models taught us</h2><ul>
<li><strong>Short-horizon regularized models were the strongest new candidates.</strong> Matched-horizon Ridge also improved validation. We cannot attribute all improvement to Elastic Net's extra regularization: horizon choice and how forecasts affect quotes matter.</li>
<li><strong>Forecast accuracy is not the trading objective.</strong> The window ensemble's validation correlation is about 0.475, versus 0.445 for Elastic Net; Elastic Net still wins the execution replay.</li>
<li><strong>Combining models helped stability across the two tapes, but did not maximize round1 profit.</strong> The blend uses fixed equal family weights, with no late-data weight fitting.</li>
<li><strong>Disagreement guarding helped only slightly.</strong> It reduces the forecast toward zero when tree models disagree. Its model spread is not a calibrated probability or confidence interval.</li>
<li><strong>Huber was a poor fit for this target.</strong> {verify['training_label_zero_fraction']:.1%} of training labels are zero. The fitted residual scale nearly collapsed, producing almost no predictive adjustment. This does not reject robust losses at other horizons or with other targets.</li>
<li><strong>Calibrating a directional classifier was insufficient.</strong> Its probability calibration improved slightly internally, but its ordinary-delay trading profit fell below F4.</li></ul>
<h2>How the Elastic Net strategy trades</h2><p>Every roughly 100ms, it builds current order-book / flow measurements plus changes over 250ms, 1s, and 5s. A learned linear forecast estimates the near-term midpoint move. The forecast sets target inventory to <code>clip(40 × forecast, −50, +50)</code> and suppresses a quote when estimated edge falls below 0.15 tick. F4-style queue and inventory handling then places, retains, or cancels orders. Pending cancellations continue to consume reserved capacity.</p>
<p>Elastic Net combines L1 and L2 penalties. Its strength was selected from three fixed choices using expanding chronological folds entirely before 6,000s, with labels crossing boundaries removed. The selected penalty is 0.0001 with L1 ratio 0.5; 23 of 24 coefficients remain nonzero. This is a modest regularizer, not an aggressive feature filter.</p>
{table(['Feature','Raw coefficient','Coefficient × training std'],coefficient_rows)}
<p class="small">Coefficients are associations in this fitted linear model. Correlated features make them unsuitable as causal importance estimates.</p>
<h2>Validation and execution constraints</h2><p>The preferred file is {candidates[0]['bytes']:,} bytes. The exact official-loader replay produced the same {n(benchmark['result']['pnl'])} PnL, used {benchmark['cpu_seconds']:.1f} CPU seconds and {benchmark['peak_working_set_bytes']/1024**2:.1f} MiB peak working set locally. The composite is {candidates[1]['bytes']:,} bytes. Both pass the team source validator and the 1MiB size check. The exports need only math, struct, and the public simulator API; sklearn and CatBoost are used offline only.</p>
<p>All eight exported predictors matched native calculations to within {max(r['export_max_error'] for r in fit['models']):.2g} on the checked validation examples. AST comparison confirmed all six feature/risk/order-handling methods were unchanged; disagreement fallback invariants passed. Original simulator files, F4, and the previous ML candidate are unchanged. The dashboard/server has not evaluated these new exports.</p>
<h2>Next experiment that would add evidence</h2><p>Run the frozen Elastic Net and composite against a genuinely new round or server test. If the session differs materially from round1, compare both against F4 before selecting one. With only these reused tapes, adding more model families or repeatedly tuning blend weights would mostly increase selection bias. A later research step could learn quote-fill probability and adverse selection jointly, but it needs faithful queue/fill labels and separate validation before changing this execution policy.</p>
<h2>Primary references</h2><p><a href="https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.ElasticNet.html">Elastic Net documentation</a> explains the combined penalties;
<a href="https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.ExtraTreesRegressor.html">ExtraTrees documentation</a> describes randomized-tree averaging;
<a href="https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html">time-series validation documentation</a> explains why training on future observations is inappropriate (this experiment uses time-based purged masks, not row-count TimeSeriesSplit);
<a href="https://catboost.ai/docs/en/references/uncertainty">CatBoost uncertainty documentation</a> motivates distinguishing disagreement from observation noise. The implemented guard is a simple independent-model heuristic, not CatBoost posterior sampling.</p>
<p><a href="https://www.nber.org/papers/w25398">Gu, Kelly and Xiu: Empirical Asset Pricing via Machine Learning</a> provides financial research context for regularization and nonlinear models. Its asset-pricing results are not evidence that these specific high-frequency competition strategies will win.</p>
<footer class="small">Reproduce from research/fit_robust_ml.py, run_robust_ml.py, finalize_robust_ml.py, verify_robust_ml.py and build_robust_ml_report.py. Finished experiments are protected against accidental overwrites. GPU retraining may produce different trees; the frozen source files and SHA-256 hashes identify the exact tested artifacts.</footer>
</main></body></html>'''
    page=OUT/'Qminers-robust-ML-results.html'
    page.write_text(body,encoding='utf-8')
    text_lines=[recommendation,'','FULL ROUND1 / 5ms','Model | Full PnL | Fitting half | Validation | Final quarter | Later half | Sampled DD']
    text_lines+=[' | '.join(row) for row in full_rows]
    text_lines+=['','LATER-HALF LATENCY STRESS','Model | 5ms | 20ms | 50ms | Excess vs F4 5ms | 20ms | 50ms']
    text_lines+=[' | '.join(row) for row in latency_rows]
    text_lines+=['','OLDER SAMPLE / NO RETRAINING','Model | Full PnL | Excess vs F4 | Sampled DD']
    text_lines+=[' | '.join(row) for row in v2_rows]
    text_lines+=['','EIGHT-MODEL VALIDATION','Model | 5ms | Excess F4 | 20ms | Excess F4 | Positive blocks | Gate']
    text_lines+=[' | '.join(row) for row in validation_rows]
    text_lines+=['',f"Exact export: CPU {benchmark['cpu_seconds']:.1f}s; memory {benchmark['peak_working_set_bytes']/1024**2:.1f}MiB; zero penalties.",
        '29 new replays; two GPU CatBoost fits; up to 18 CPU replay workers.',
        'Caveats: reused tapes, no independent winning guarantee, no server evaluation, round1 session horizon 12000s.',
        'See HTML and research/robust_ml_results/outcome.json for complete results, methodology and references.']
    (OUT/'Qminers-robust-ML-results.txt').write_text('\n'.join(text_lines)+'\n',encoding='utf-8')
    paths=[page,OUT/'Qminers-robust-ML-results.txt']+[Path(c['export']) for c in candidates]
    dump(DEST/'report_manifest.json',dict(files=[dict(path=str(p),bytes=p.stat().st_size,sha256=file_hash(p)) for p in paths]))
    print(json.dumps(dict(recommendation=recommendation,full=full_rows,latency=latency_rows,v2=v2_rows,
        tail_blocks=block_records,report=str(page)),indent=2))


if __name__=='__main__':
    main()
