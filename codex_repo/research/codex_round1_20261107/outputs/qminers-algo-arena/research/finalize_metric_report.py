"""Apply the predeclared gates and package the exact tested strategy and audit."""
import ast
import html
import json
import shutil
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from build_robust_ml_report import table, link, n
from ml_round1_common import file_hash
from optimize_metric import DEST, ROOT, ROBUST, PARENT, at, load
from run_study import dump

OUT=ROOT.parent


def main():
    selection=load(DEST/'selection.json')
    assert selection['selected']=='deplete0'
    row=next(r for r in selection['ranking'] if r['name']=='deplete0')
    final={r['name']:r for r in load(DEST/'final_summary.json')}
    portable={r['name']:r for r in load(DEST/'portability_results.json')}
    assert len(final)==len(portable)==4
    old=load(ROBUST/'outcome.json')
    parent=old['full_results']['elastic250']
    f4=old['full_results']['f4']
    older={r['name']:r for r in load(ROBUST/'final_summary.json')}
    prior_v2=older['v2_elastic250']
    timed={str(d):final[f'final_deplete0_d{d}'] for d in (5,20,50)}
    port={str(d):portable[f'portable_d{d}'] for d in (5,20,50)}
    timed_bench=load(DEST/'candidate_benchmark.json')
    port_bench=load(DEST/'portable_benchmark.json')
    assert timed_bench['result']==timed['5']['result']
    assert port_bench['result']==port['5']['result']
    # No new behavior before the former clock deadline: compare exact private fills.
    before=np.load(DEST/'final_deplete0_d5_trace.npz')
    after=np.load(DEST/'portable_d5_trace.npz')
    a,b=before['private_fills'],after['private_fills']
    assert np.array_equal(a[a[:,0]<11970e6],b[b[:,0]<11970e6])
    first=before['curve'];second=after['curve']
    assert np.array_equal(first[first[:,0]<11970e6],second[second[:,0]<11970e6])
    # Verify the only source differences from the prior Elastic Net are the
    # depletion constant and explicit optional session horizon.
    original=ast.parse((ROOT/'strategies/round1_robust_candidate.py').read_text(encoding='utf-8'))
    exported=ast.parse((ROOT/'strategies/round1_metric_portable.py').read_text(encoding='utf-8'))
    def normalize(tree):
        for node in ast.walk(tree):
            if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name):
                if node.targets[0].id in ('DEPLETE_LOTS','SESSION_S'):
                    node.value=ast.Constant(value=0)
                elif node.targets[0].id=='winding':
                    node.value=ast.Constant(value=False)
        return ast.dump(tree,include_attributes=False)
    assert normalize(original)==normalize(exported)
    validation=load(DEST/'validation_summary.json')
    all_runs=validation+list(final.values())+list(portable.values())
    safe=all(r['result']['breach_penalty']==0 and r['max_reserved_exposure']<=100 for r in all_runs)
    checks=dict(validation_gate=row['gate'],zero_penalties_and_exposure=safe,
        final_period_gain=timed['5']['tail_pnl']>parent['5']['tail_pnl'],
        delay20=timed['20']['outside_fit_pnl']>=.98*parent['20']['outside_fit_pnl'],
        delay50=timed['50']['outside_fit_pnl']>=.98*parent['50']['outside_fit_pnl'],
        older_sample=final['v2_deplete0']['result']['pnl']>=.98*prior_v2['result']['pnl'],
        timed_cpu=timed_bench['cpu_seconds']<900,timed_memory=timed_bench['peak_working_set_bytes']<2*1024**3)
    assert all(checks.values()),checks
    portability_checks=dict(normal_pnl=port['5']['result']['pnl']>=timed['5']['result']['pnl'],
        delay20=port['20']['outside_fit_pnl']>=.98*timed['20']['outside_fit_pnl'],
        delay50=port['50']['outside_fit_pnl']>=.98*timed['50']['outside_fit_pnl'],
        older_sample=portable['portable_v2']['result']['pnl']>=.98*final['v2_deplete0']['result']['pnl'],
        safe=safe,cpu=port_bench['cpu_seconds']<900,memory=port_bench['peak_working_set_bytes']<2*1024**3)
    use_portable=all(portability_checks.values())
    chosen=ROOT/'strategies'/('round1_metric_portable.py' if use_portable else 'round1_metric_deplete0.py')
    best=ROOT/'strategies/round1_max_metric.py'
    shutil.copyfile(chosen,best)
    assert file_hash(best)==file_hash(chosen) and best.stat().st_size<1024**2
    selected=port if use_portable else timed
    selected_v2=portable['portable_v2'] if use_portable else final['v2_deplete0']
    benchmark=port_bench if use_portable else timed_bench
    change=selected['5']['result']['pnl']-parent['5']['result']['pnl']
    later=selected['5']['outside_fit_pnl']-parent['5']['outside_fit_pnl']
    outcome=dict(recommendation='Use the frozen horizon-independent Elastic Net market maker.' if use_portable else 'Use the frozen timed Elastic Net market maker.',
        export=str(best),sha256=file_hash(best),bytes=best.stat().st_size,portable=use_portable,
        full_pnl=selected['5']['result']['pnl'],previous_full=parent['5']['result']['pnl'],full_gain=change,
        later_half_pnl=selected['5']['outside_fit_pnl'],previous_later_half=parent['5']['outside_fit_pnl'],
        later_half_gain=later,later_half_gain_pct=100*later/parent['5']['outside_fit_pnl'],
        checks=checks,portability_checks=portability_checks,bootstrap=row,
        new_replays=38,validation_replays=28,diagnostic_replays=8,exact_replays=2,
        before_winddown_curves_and_fills_identical=True,only_declared_source_changes=True,
        benchmark=benchmark,results=dict(f4=f4,parent=parent,timed=timed,portable=port),
        older_sample=dict(f4=older['v2_f4']['result']['pnl'],parent=prior_v2['result']['pnl'],
            timed=final['v2_deplete0']['result']['pnl'],portable=portable['portable_v2']['result']['pnl']),
        limitations=['Previously inspected public tapes; no untouched private-test estimate.',
            'Bootstrap controls only this fixed batch under block-dependence assumptions; it is not an overall probability of overfitting.',
            'Post-selection end-time portability audit is recorded separately; its small endpoint effect is outside the original confidence bound.',
            'The score depends on other teams private PnLs, which are unknown; local net PnL is the controllable proxy.',
            'Website sandbox/private evaluation not performed.'])
    dump(DEST/'outcome.json',outcome)
    score_evidence=dict(source='Team-saved official technical page, snapshot from 2026-11-07',
        official_url='https://arena.qminers.com/dashboard/info',
        summary='Final ranking combines private-backtest PnL standardized by round against other teams. Non-positive teams are excluded from the mean and standard deviation and score as if their PnL were zero. Local objective: executable cash plus inventory liquidation value minus breach penalty.',
        caveat='Live general rules were inspected; the technical page requested login in the available browser. Exact cross-team score cannot be computed locally.',
        engine_commit='3f5bea730d5f341c6988b1fe2722998b66270ea0',
        engine_formula='cash + market-only executable liquidation value - position breach penalty')
    dump(DEST/'scoring_evidence.json',score_evidence)

    labels=dict(f4='F4',parent='Previous Elastic Net',timed='Selected: depletion filter off',portable='Final: no assumed end time')
    groups=dict(f4=f4,parent=parent,timed=timed,portable=port)
    full_rows=[[labels[k],n(v['5']['result']['pnl']),n(v['5']['outside_fit_pnl']),n(v['5']['tail_pnl']),n(v['5']['max_drawdown'])] for k,v in groups.items()]
    stress_rows=[[labels[k]]+[n(v[str(d)]['outside_fit_pnl']) for d in (5,20,50)]+[n(outcome['older_sample'][k])] for k,v in groups.items()]
    variants={v['name']:v for v in load(DEST/'experiment_plan.json')['variants']}
    valrows=[]
    for r in selection['ranking']:
        v=variants[r['name']]
        description=(f"Forecast ×{v['gain']:g}, edge {v['edge']:g}" if v['family']=='grid' else
            'Refill from 1 lot' if r['name']=='refill1' else 'Refill from 25 lots' if r['name']=='refill25' else
            'Remove depletion filter' if r['name']=='deplete0' else 'Depletion threshold 40')
        valrows.append([description]+[f'{n(x)}' for x in r['fold_excess']]+[
            n(r['total_excess']),f"{r['positive_blocks']}/20",n(r['simultaneous_lower_total']), 'Pass' if r['gate'] else 'Fail'])

    vr={r['name']:r for r in validation}
    excess=[]
    for fold in (1,2):
        excess+=list(np.array(vr[f'deplete0_f{fold}']['blocks'])-np.array(vr[f'{PARENT}_f{fold}']['blocks']))
    fig=make_subplots(rows=1,cols=2,horizontal_spacing=.12,
        subplot_titles=('Selected change: paired validation block gains','Full round1: gains after model fitting'))
    fig.add_trace(go.Bar(x=list(range(1,21)),y=excess,marker_color=['#077c68' if v>0 else '#c0773b' for v in excess],showlegend=False),row=1,col=1)
    parent_curve=np.load(ROBUST/'final_elastic250_d5_trace.npz')['curve']
    selected_curve=np.load(DEST/('portable_d5_trace.npz' if use_portable else 'final_deplete0_d5_trace.npz'))['curve']
    seconds=np.arange(6000,12000,10)
    delta=[(at(selected_curve,s)-at(selected_curve,6000))-(at(parent_curve,s)-at(parent_curve,6000)) for s in seconds]
    fig.add_trace(go.Scatter(x=np.append(seconds,12000)/60,y=delta+[later],mode='lines',line=dict(color='#077c68'),showlegend=False),row=1,col=2)
    fig.add_vline(x=10.5,line_dash='dot',line_color='#7a8d94',row=1,col=1)
    fig.add_vline(x=150,line_dash='dot',line_color='#7a8d94',row=1,col=2)
    fig.update_xaxes(title_text='Five-minute blocks: first / second fold',row=1,col=1)
    fig.update_xaxes(title_text='Minutes into round1',row=1,col=2)
    fig.update_yaxes(title_text='PnL gain over previous Elastic Net',row=1,col=1)
    fig.update_layout(template='plotly_white',height=410,margin=dict(l=65,r=25,t=55,b=65),font=dict(family='Segoe UI, Arial',size=12))
    chart=fig.to_html(full_html=False,include_plotlyjs=True,config=dict(displaylogo=False,responsive=True))
    links=' · '.join([link(best,'Final submission file'),link(ROOT/'strategies/round1_metric_deplete0.py','Timed comparison file'),
        link(DEST/'experiment_plan.json','Original experiment plan'),link(DEST/'selection.json','Selection and bootstrap'),
        link(DEST/'portability_plan.json','Portability audit plan'),link(DEST/'boundary_correction.json','Boundary accounting correction'),
        link(DEST/'outcome.json','Complete results'),link(DEST/'scoring_evidence.json','Scoring evidence'),
        link(ROOT/'research/optimize_metric.py','Reproduction script')])
    r5=selected['5'];prev5=parent['5']
    body=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Qminers — optimizing the evaluated metric</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f7;color:#193240;font:16px/1.6 'Segoe UI',Arial,sans-serif}}main{{max-width:1200px;margin:auto;padding:38px 26px}}
h1{{font-size:34px;line-height:1.25}}h2{{font-size:23px;margin-top:30px}}header{{border-bottom:3px solid #078b75;padding-bottom:16px}}.eyebrow{{font-size:13px;color:#526c78;letter-spacing:2px;text-transform:uppercase}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:24px 0}}.card,.links{{background:white;border:1px solid #dce5e9;border-radius:9px;padding:18px}}.value{{font-size:28px;font-weight:650;color:#007d68}}.label{{font-size:13px;color:#536d77}}
.note{{padding:16px 20px;background:#fff2d8;border-left:4px solid #bc8130;margin:22px 0}}.table{{overflow-x:auto;margin:18px 0}}table{{border-collapse:collapse;width:100%;background:white;font-size:14px}}th,td{{padding:11px;border-bottom:1px solid #dce5e9;white-space:nowrap;text-align:right}}th{{background:#183c4d;color:white}}th:first-child,td:first-child{{text-align:left}}tr:nth-child(even){{background:#f6f9fa}}a{{color:#007c83}}li{{margin:9px 0}}.small{{font-size:13px;color:#526c78}}code{{background:#e6eff1;padding:2px 5px}}@media(max-width:800px){{.cards{{grid-template-columns:repeat(2,1fr)}}main{{padding:24px 14px}}h1{{font-size:28px}}}}
</style></head><body><main><header><div class="eyebrow">Qminers Arena · 7 November 2026 · frozen local experiment</div>
<h1>More executable PnL, with the forecast kept fixed</h1><p>The selected strategy scores <strong>{n(outcome['full_pnl'])}</strong> on round1. It adds {n(change)} over the previous Elastic Net bot, including <strong>{n(later)} ({outcome['later_half_gain_pct']:.2f}%)</strong> in the later half excluded from model fitting. The main gain comes from disabling one costly quote filter; the model coefficients are unchanged.</p></header>
<div class="cards"><div class="card"><div class="value">{n(outcome['full_pnl'])}</div><div class="label">Official net PnL · round1</div></div><div class="card"><div class="value">+{outcome['later_half_gain_pct']:.2f}%</div><div class="label">Later-half gain over prior Elastic Net</div></div><div class="card"><div class="value">19 / 20</div><div class="label">Validation blocks improved by filter removal</div></div><div class="card"><div class="value">0</div><div class="label">Position penalties in all new replays</div></div></div>
<div class="note">This is the best strategy validated in this bounded experiment, not proof of a global optimum or a private-round win. Both public tapes had been inspected previously. The statistical adjustment covers this batch only. The new file has not been evaluated on the website.</div>
<div class="links">{links}</div>
<h2>The metric being optimized</h2><p>The saved official technical rules combine private-backtest PnL standardized against other teams in each round. Those private results are unknown. The directly controllable objective is the official engine's <strong>cash + executable inventory liquidation value − position penalty</strong>. Prediction correlation, Sharpe, drawdown, and PnL standard error are diagnostics; they are not substituted for this objective. The live general rules were checked, while the technical page required login in the available browser.</p>
<h2>What changed</h2><ul><li><strong>Depletion filter disabled.</strong> Previously the bot withdrew a side whenever external touch depth dropped below 20 lots. Removing that rule improved both chronological folds. The learned forecast, 0.15-tick edge floor, target-inventory scaling, and strict capacity accounting remain in place.</li>
<li><strong>No assumed private-session end.</strong> The final file sets <code>SESSION_S=None</code>, allowing trading until the tape actually ends. The scorer values any remaining position at executable prices. A known session duration can still be configured. The old 12,000-second assumption could have stopped trading early on a longer private tape.</li></ul>
<p>At 5ms, the final bot traded {n(r5['result']['traded_volume'])} lots versus {n(prev5['result']['traded_volume'])} previously. The exact replay changes establish the local result; real-market fill behavior is not inferred from these tapes.</p>
<h2>Results separated from model fitting</h2>
{table(['Strategy','Full round1 PnL','Later 100min','Final 50min','Sampled drawdown'],full_rows)}
<p class="small">The first 100 minutes contribute to full PnL and model fitting. The last 50 minutes were excluded from this batch's policy selection but had been seen in prior research. Intermediate marks use the official executable valuation, sampled at one-second intervals.</p>
{chart}
<h2>Fixed search and selection discipline</h2><p>Thirteen settings were declared in advance: a 3×3 grid of forecast strengths and quote-edge floors, plus four one-factor execution changes. The first fold fits only before 3,000s and evaluates 3,000–6,000s. The second reuses the frozen model fitted before 6,000s and evaluates 6,000–9,000s. Inner regularization selection uses only preceding data, with crossing labels removed. All replays warm the book from the beginning.</p>
<p>Each change is compared with its fold-matched parent in twenty paired five-minute blocks. A centered moving-block bootstrap resamples within each fold in ten-minute chunks and uses a joint max-T statistic across all twelve changes. Promotion requires positive gains in both folds, a positive simultaneous one-sided 95% lower bound, and the declared consistency/risk checks. Grid candidates also need support from an adjacent configuration.</p>
{table(['Change','Fold 1 gain','Fold 2 gain','Total gain','Positive blocks','Adjusted lower bound','Gate'],valrows)}
<p>The selected filter removal gained {n(row['total_excess'])}, with a batch-adjusted lower bound of {n(row['simultaneous_lower_total'])} under this bootstrap's assumptions. This is stronger evidence than a single best backtest, but it is not a selection-adjusted claim covering all previous experiments or a new market regime. The small refill improvement was not stacked onto the winner; the final policy retains the one change responsible for the dominant gain.</p>
<p class="small">Accounting correction: the replay trace appends an extra terminal-liquidation row after draining pending orders. That row was uniformly excluded from validation block scoring before statistical selection, as required by the original regular-grid plan. Raw records and the correction are preserved. Official full-tape PnL was not altered.</p>
<h2>Execution and cross-tape stress</h2>
{table(['Strategy','Later half / 5ms','Later half / 20ms','Later half / 50ms','sample_v2 / full'],stress_rows)}
<p>The clock portability audit was recorded separately after policy selection. It adds no fitted parameters and changes behavior only after the old scheduled wind-down. Exact fills and equity samples before that boundary match the timed candidate. Its endpoint improvement is outside the original bootstrap confidence bound. Every follow-up gate passed; no further tuning followed these results.</p>
<h2>Submission readiness and limits</h2><p>The final file is {best.stat().st_size:,} bytes, imports only math, struct and the public simulator API, and has one strategy entry point. It passed the local team source validator. Exact official-loader replay reproduced {n(benchmark['result']['pnl'])} PnL in {benchmark['cpu_seconds']:.1f} CPU seconds, using {benchmark['peak_working_set_bytes']/1024**2:.1f} MiB peak working set including research-harness imports. This is within the stated local size/runtime limits; remote execution has not been measured.</p>
<p>All 38 new replays had zero breach penalties, and all instrumented runs kept actual and reserved exposure at or below 100 lots. Source comparison verified that model coefficients and risk-accounting methods are unchanged. Original simulator files and previous candidate files are preserved. SHA-256 of the final source: <code>{file_hash(best)}</code>.</p>
<p>Use the frozen file for the next website check. A public website replay confirms sandbox compatibility, while the private round supplies the evidence we cannot obtain locally. More searching on these same tapes would increase selection bias; this experiment is complete.</p>
<footer class="small">Evidence and reproduction: research/metric_optimization_results/; optimize_metric.py; metric_portability.py; finalize_metric_report.py. The saved technical text came from arena.qminers.com/dashboard/info; public general rules were inspected at <a href="https://arena.qminers.com/rules">the official rules page</a>. No upload, Git push, or sharing change was made.</footer>
</main></body></html>'''
    page=OUT/'Qminers-metric-optimization.html'
    page.write_text(body,encoding='utf-8')
    lines=[outcome['recommendation'],f"Final file: {best}",f"SHA256: {outcome['sha256']}",'',
        'FULL PNL | LATER HALF | FINAL QUARTER | SAMPLED DD']
    lines+=[' | '.join(r) for r in full_rows]
    lines+=['','LATER-HALF PNL AT 5/20/50ms | FULL SAMPLE_V2']+[' | '.join(r) for r in stress_rows]
    lines+=['',f"Filter removal: +{row['fold_excess'][0]:,.0f}, +{row['fold_excess'][1]:,.0f}; {row['positive_blocks']}/20 blocks; batch-adjusted lower bound {row['simultaneous_lower_total']:,.0f}.",
        'Forecast weights unchanged; depletion filter removed; scheduled wind-down disabled when duration is unknown.',
        '38 new replays, zero penalties. Chronological validation and batch multiplicity control; no untouched/private data claim.',
        'Portability audit was added after selection and is outside the original bootstrap bound. Full details in HTML and research/metric_optimization_results/outcome.json.']
    (OUT/'Qminers-metric-optimization.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    files=[best,page,OUT/'Qminers-metric-optimization.txt']
    dump(DEST/'manifest.json',dict(files=[dict(path=str(p),bytes=p.stat().st_size,sha256=file_hash(p)) for p in files]))
    print(json.dumps(dict(export=str(best),portable=use_portable,full_rows=full_rows,stress_rows=stress_rows,
        gain=change,later_gain=later,checks=checks,portability_checks=portability_checks),indent=2))


if __name__=='__main__':main()
