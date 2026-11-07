"""Build a self-contained interactive report and compact machine-readable comparison."""
import csv
import html
import json
from pathlib import Path
import numpy as np
import plotly.graph_objects as go
from run_study import ROOT, OUT, dump

LABELS={
 'record':'No trading', 'official_trend':'Official trend (original)', 'fixed_trend':'Official trend (cancel fix)',
 'team_F2':'Team F2, cap 100', 'team_F2_cap80':'Team F2, cap 80', 'team_M2':'Team M2 momentum',
 'protected_maker':'Protected maker, 6-second pause', 'microprice_maker':'Microprice maker, size 20',
 'mean_reversion':'EMA mean-reversion IOC', 'ridge_ioc':'Ridge IOC, conservative threshold',
 'ridge_maker':'Ridge maker, size 20', 'ridge_maker_size80':'Ridge maker, size 80',
 'microprice_maker_size80':'Microprice maker, size 80','ridge_ioc_edge0':'Ridge IOC, zero extra buffer',
 'F2_cap50':'Team F2, cap 50','F2_delay20ms':'F2 at 20 ms delay','F2_delay50ms':'F2 at 50 ms delay',
 'F2_original_sample':'F2 on original sample','M2_original_sample':'M2 on original sample',
 'microprice_original_sample':'Microprice maker on original sample',
 'ridge_maker_original_sample':'Ridge maker on original sample'}


def fill_diagnostics(row):
    a=np.load(OUT/(row['name']+'_trace.npz'))
    tr, market=a['trades'],a['market']
    if not len(tr):
        return {}
    mid=(market[:,1]+market[:,2])/2
    result={}
    for maker,word in [(1,'maker'),(0,'taker')]:
        rows=tr[tr[:,4]==maker]
        if not len(rows):
            continue
        stats={'lots':int(rows[:,3].sum()),'matches':len(rows),'markouts':{}}
        for seconds in (1,5,30):
            good=(rows[:,0]>=market[0,0])&(rows[:,0]+seconds*1e6<=market[-1,0])
            rr=rows[good]
            if not len(rr):
                continue
            i=np.searchsorted(market[:,0],rr[:,0]+seconds*1e6,side='right')-1
            values=rr[:,2]*(mid[i]-rr[:,1])
            stats['markouts'][str(seconds)]=dict(eligible_lots=int(rr[:,3].sum()),
               mean_signed_future_mid_minus_fill=float(np.average(values,weights=rr[:,3])))
        result[word]=stats
    result['caveat']='Future mid is the latest 100-ms sample at or before the horizon; terminal pending fills may be absent from public trade callbacks. Descriptive markout, not a second PnL measure.'
    return result


def table(rows):
    heads=['Approach','Full PnL','First half','Third quarter','Last quarter','Max |position|','Drawdown¹','Lots','CPU sec']
    body=[]
    for r in rows:
        vals=[LABELS[r['name']],f"{r['result']['pnl']:+,.0f}",f"{r['first_half_pnl']:+,.0f}",
          f"{r['third_quarter_pnl']:+,.0f}",f"{r['last_quarter_pnl']:+,.0f}",
          str(r['max_abs_inventory']),f"{r['max_drawdown']:,.0f}",f"{r['result']['traded_volume']:,}",f"{r['cpu_seconds']:.1f}"]
        body.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in heads)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'


def chart(cases,byname,title):
    fig=go.Figure()
    for name in cases:
        a=np.load(OUT/(name+'_trace.npz'))['curve']
        fig.add_trace(go.Scatter(x=(a[:,0]-a[0,0])/60e6,y=a[:,1],mode='lines',name=LABELS[name]))
    fig.update_layout(title=title,template='plotly_white',height=430,
        margin=dict(l=60,r=30,t=60,b=40),xaxis_title='Elapsed minutes',yaxis_title='Official PnL',
        legend=dict(orientation='h',y=-.2),hovermode='x unified')
    return fig


def main():
    rows=[]
    for phase in ('base','models','stress','followup'):
        rows.extend(json.loads((OUT/(phase+'_summary.json')).read_text()))
    byname={r['name']:r for r in rows}
    profile=json.loads((OUT/'dataset_profile.json').read_text())
    signal=json.loads((OUT/'signal_analysis.json').read_text())
    benchmarks=[json.loads(p.read_text()) for p in sorted(OUT.glob('benchmark_*.json'))]
    exports=json.loads((OUT/'exports.json').read_text())
    assert len(byname)==21
    assert all(r['result']['breach_penalty']==0 for r in rows)
    assert all(r['max_reserved_exposure']<=100 for r in rows)
    assert len(json.loads((OUT/'engine_probes.json').read_text()))==5
    diagnostics={n:fill_diagnostics(byname[n]) for n in ('team_F2','team_F2_cap80','ridge_maker','team_M2')}
    dump(OUT/'fill_diagnostics.json',diagnostics)
    cols=['name','dataset','delay_ms','pnl','first_half','third_quarter','last_quarter','max_inventory','max_reserved',
          'drawdown_1s','lots','penalty','cpu_seconds','pnl_per_traded_lot']
    flat=[]
    for r in rows:
        res=r['result']
        flat.append(dict(zip(cols,[r['name'],r['data'],r['delay_ms'],res['pnl'],r['first_half_pnl'],r['third_quarter_pnl'],
            r['last_quarter_pnl'],r['max_abs_inventory'],r['max_reserved_exposure'],r['max_drawdown'],res['traded_volume'],
            res['breach_penalty'],r['cpu_seconds'],res['pnl']/res['traded_volume'] if res['traded_volume'] else None])))
    with (OUT/'comparison.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,cols);w.writeheader();w.writerows(flat)
    dump(OUT/'study_manifest.json',dict(date='2026-11-07',official_commit='3f5bea730d5f341c6988b1fe2722998b66270ea0',
         team_commit='6ca459e966bb1f9e767258ef5ae0ef0bce979c3f',dataset=profile,
         experiments=21,engine_probes=5,exports=exports,benchmarks=benchmarks,
         scope='Local research only; no portal submissions, repository pushes or sharing changes.',
         validation='Exploratory comparison on known public tapes. Ridge fits first half only; chronological quarter metrics are not a fresh independent holdout.'))
    primary_names=['team_F2','team_F2_cap80','ridge_maker','ridge_maker_size80','microprice_maker','microprice_maker_size80',
        'fixed_trend','official_trend','mean_reversion','team_M2','protected_maker','ridge_ioc','ridge_ioc_edge0','record']
    primary=[byname[n] for n in primary_names]
    winner=chart(['team_F2','team_F2_cap80','ridge_maker','microprice_maker'],byname,'Profitable candidates on sample v2')
    regimes=go.Figure()
    regimes.add_trace(go.Bar(name='Original sample',x=['F2 maker','M2 momentum'],y=[-28429,305374]))
    regimes.add_trace(go.Bar(name='Sample v2',x=['F2 maker','M2 momentum'],y=[212831,-870942]))
    regimes.update_layout(title='The preferred strategy reverses between tapes',template='plotly_white',barmode='group',height=380,yaxis_title='Full-tape PnL')
    costs=go.Figure()
    for n in ['team_F2','team_F2_cap80','ridge_maker']:
        r=byname[n]['result'];x=np.linspace(0,1,51)
        costs.add_trace(go.Scatter(x=x,y=r['pnl']-x*r['traded_volume'],name=LABELS[n],mode='lines'))
    costs.update_layout(title='Hypothetical extra cost per traded lot (official simulator charges none)',template='plotly_white',height=380,xaxis_title='Extra cost per traded lot',yaxis_title='PnL after hypothetical cost')
    benchtext='; '.join(f"{b['file']}: {b['wall_seconds']:.1f} s wall, {b['cpu_seconds']:.1f} s CPU, {b['peak_working_set_bytes']/2**20:.1f} MiB peak working set" for b in benchmarks)
    introduction="""Use the simple F2 market maker as the current sample-v2 reference. The 100-lot version earns the most among tested candidates (+212,831); the 80-lot version retains 88.1% of that PnL (+187,588) and leaves 20 lots below the penalty boundary. The 80-lot variant changes quote size and skew as well as the cap, so this is a configuration comparison, not a pure cap ablation. Neither is established as the winner on private round data. The small learned maker is a useful challenger: +73,797, observed peak inventory 53, and a smaller sampled drawdown."""
    explanation="""The downloaded file contains 2,000,000 ordered events, 1,067,532 inserts and 932,468 cancels over 5,749.869 seconds (95.83 minutes). It is not the original 53,758-event sample. Sampled spreads are usually 1–2 ticks and median displayed volume at the best price is about 768–769 lots per side. Replay starts at the beginning and preserves every cancellation and order queue; no shuffled or truncated-book backtests were used."""
    validation="""These are exploratory public-data results. F2 had already been tuned on this tape in the team repository. Its last quarter is a stability diagnostic, not an untouched holdout. Ridge coefficients and normalizers use only the first half, with crossing labels purged; the next quarter is validation. Subsequent comparisons reuse the same tape, and the final quarter is reported as a diagnostic tail. Learned candidates' full PnL includes their training period. Drawdown¹ comes from the engine's one-second PnL curve and may miss intrasecond excursions. All 21 research runs had zero penalties; that does not guarantee performance or safety on another tape."""
    regression="""The nine-feature Ridge model predicts the next one-second mid change with correlation 0.404 on validation and 0.396 on the diagnostic tail. However, the validation 95th percentile of absolute predictions is only 0.367 ticks. At the conservative IOC threshold it places no orders; removing the extra buffer produces -307. Using the signal to position passive quotes earns +73,797 versus +61,615 for the microprice maker at the same 20-lot size. At 80-lot size, learned and microprice makers earn +98,774 and +90,649, still below F2's 80-lot configuration (+187,588). Prediction quality alone is not enough to justify crossing the spread."""
    pitfalls="""The original trend example makes its last fill around second 206.61 and then stops after an unfilled IOC: its cancellation branch does not clear the in-flight flag. Fixing that lifecycle bug changes PnL from -531 to -14,125 because trading continues. The protected maker's default six-second pause produces no trades on this tape. These are implementation and configuration findings, not evidence that all momentum or protection methods fail."""
    stress="""F2 stays profitable when the simulated delay is increased from the official 5 ms to hypothetical 20 ms (+205,307) and 50 ms (+193,173). Reducing quote size/cap/skew to 50/50/30 yields +144,264. F2 loses -28,429 on the original sample, while M2 wins +305,374 there and loses -870,942 on v2. Market regime matters more than adding model complexity. These cross-tape results used the session length appropriate to each tape. F2's v2 break-even hypothetical extra cost is about 0.547 ticks per traded lot; the official simulator has no fees."""
    probes="""Five deterministic engine probes passed: order acceptance occurs after 5 ms; an order can fill while its cancellation is pending; older same-price orders fill first at the maker's price; a rejected quantity increase leaves the original order live; and 101 lots held above the soft limit for one second costs 10,000, whereas a 1,001-lot order is rejected by the potential-exposure limit. The first probe combines delayed acceptance, partial fills, and a cancellation race. Strategy risk accounting reserves pending and cancelling orders separately on each side. Late-cancel rejections in full runs are recorded as such, not mistaken for limit breaches."""
    research="""For the next round, start with the new tape's spread, queue depth, signed-flow markouts and executable PnL. Compare a small, frozen set of maker and taker candidates on chronological development segments, then inspect one untouched test segment once. Fit time-based features and export coefficients as literals. A tiny event-history model is a reasonable later challenger only if it improves fill-conditioned PnL and fits the complete-run budget. Keep model fitting outside strategy callbacks."""
    more=[
      ['Queue-aware selective making','Next experiment','Estimate fill probability and future value conditional on a fill; preserve queue priority, suppress only the threatened side. Compare with plain F2 at matched inventory limits.'],
      ['Regime-aware maker/taker selection','Next experiment','Choose from measured public-tape behavior per round. An online switch needs causal thresholds, hysteresis and validation on multiple independent tapes. Avoid choosing from future PnL.'],
      ['Small event-history linear/MLP/TCN model','Research option','Use recent adds, cancels, trades and depth at several time scales; train offline and benchmark exported inference. Start with the current Ridge baseline.'],
      ['Robust inventory control','Next experiment','Compare continuous inventory skew, a smaller cap, and quote-size adaptation. Score executable PnL, cancellation exposure, and drawdown together.'],
      ['Pure IOC momentum / mean reversion','Tested, unsuitable here at these settings','Keep as regime probes. Their current v2 executions lose money; M2 works on the original sample.'],
      ['Large transformer / online reinforcement learning','Defer','No demonstrated benefit here; limited independent data and the one-CPU submission budget make validation and execution the current bottlenecks.'],
    ]
    moretable='<div class="scroll"><table><tr><th>Approach</th><th>Status</th><th>Concrete next step</th></tr>'+''.join('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in a)+'</tr>' for a in more)+'</table></div>'
    commands=r"""# From this qminers-algo-arena directory (PowerShell):
.venv/Scripts/exchange-simulator.exe --strategy strategies/team_f2_cap80_v2.py --backtest data/sample_v2.csv --log-dir logs/v2-cap80 --no-logs
.venv/Scripts/exchange-simulator.exe --strategy strategies/ridge_maker_v2.py --backtest data/sample_v2.csv --log-dir logs/v2-ridge --no-logs
.venv/Scripts/python.exe research/test_engine_probes.py
# Rebuild the full research comparison:
.venv/Scripts/python.exe research/run_study.py --phase base --jobs 2
.venv/Scripts/python.exe research/analyze_features.py
.venv/Scripts/python.exe research/run_study.py --phase models --jobs 2
.venv/Scripts/python.exe research/prepare_stress.py
.venv/Scripts/python.exe research/run_study.py --phase stress --jobs 2
.venv/Scripts/python.exe research/prepare_followup.py
.venv/Scripts/python.exe research/run_study.py --phase followup --jobs 2
.venv/Scripts/python.exe research/export_candidates.py
.venv/Scripts/python.exe research/build_report.py"""
    ruletext="""The signed-in website was inspected on 7 November: one Python file at most 1 MiB, one CPU, 2 GB RAM, no network, and 15 minutes; ten submissions per competition round (Playground showed 100). Public submissions only check sandbox execution; private data determines ranking. Keep a private team research repository, preserve experiments including failures, commit at least every 30 minutes, and share Read access with the named organizer. AI assistants and public research are allowed. No uploads, pushes, sharing changes, or organizer messages were made by this task. Local static checks are not a substitute for the server's checker."""
    sourcehtml='''The implementation reference is the <a href="https://github.com/QminersOrg/qminers-algo-arena">official public starter</a> at 3f5bea7 and the authorized <a href="https://github.com/jakub-kucera/qminers-arena-hachathon/tree/6ca459e966bb1f9e767258ef5ae0ef0bce979c3f">team repository</a> at 6ca459e. Rules: <a href="https://arena.qminers.com/dashboard/info">technical info</a> and <a href="https://arena.qminers.com/rules">official rules</a>.'''
    papers='''Public research supports testing event history and fill quality rather than assuming a larger predictor earns more: <a href="https://arxiv.org/html/2610.02917v1">Event History Over Scale (October 2026)</a>, <a href="https://arxiv.org/abs/2502.18625">The Market Maker’s Dilemma (2025)</a>, <a href="https://arxiv.org/abs/2502.15757">TLOB (2025)</a>, and <a href="https://onlinelibrary.wiley.com/doi/10.1111/mafi.12413">Deep Order Flow Imbalance (2023)</a>. These motivate the proposed tests; their published results do not establish performance in this Arena simulator.'''
    style='''body{font:16px/1.55 system-ui,sans-serif;background:#f5f7fb;color:#182a40;margin:0}main{max-width:1180px;margin:40px auto;padding:30px;background:white;border-radius:16px}h1{font-size:32px;line-height:1.2}p{max-width:1080px}a{color:#0758a8}.note{background:#eaf3fb;border-left:4px solid #2575bc;padding:18px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px;margin:20px 0}th,td{padding:10px 12px;border-bottom:1px solid #dce4ee;text-align:right;white-space:nowrap}th{background:#edf2f8}th:first-child,td:first-child{text-align:left}td:last-child{white-space:normal}pre{padding:20px;background:#0c2238;color:#eaf1fa;overflow:auto;font-size:13px}details{margin:24px 0}small{color:#516477}.links a{display:inline-block;margin:4px 20px 4px 0}'''
    article='<p class="note">'+introduction+'</p><p>'+explanation+'</p>'+winner.to_html(full_html=False,include_plotlyjs=True)
    article+=table(primary)+'<p>'+validation+'</p><p>'+regression+'</p><p>'+pitfalls+'</p>'+regimes.to_html(full_html=False,include_plotlyjs=False)
    article+='<p>'+stress+'</p>'+costs.to_html(full_html=False,include_plotlyjs=False)+'<p>'+probes+'</p>'
    article+='<p><b>Standalone export verification:</b> '+html.escape(benchtext)+'. Exported files are 5–7 KB and pass local AST/import checks against the documented restrictions. The resource figures are measured locally on Windows, not in the remote sandbox.</p>'
    article+='<p>'+research+'</p>'+moretable+'<p>'+papers+'</p><p>'+ruletext+'</p><p>'+sourcehtml+'</p>'
    article+='<p class="links"><a href="qminers-algo-arena/strategies/team_f2_cap80_v2.py">F2 cap-80 file</a><a href="qminers-algo-arena/strategies/team_f2_v2.py">F2 cap-100 file</a><a href="qminers-algo-arena/strategies/ridge_maker_v2.py">Learned maker file</a><a href="qminers-algo-arena/research/results/comparison.csv">All 21 results</a><a href="Qminers-local-testing.txt">Plain-text analysis</a></p>'
    article+='<details><summary>Replay commands and data provenance</summary><pre>'+html.escape(commands)+'</pre><p>SHA256: '+profile['sha256']+'</p><p>Source: data/sample_v2.csv (user-provided original), copied unchanged into data/sample_v2.csv. Team snapshots are retained under research/reference_strategies.</p></details>'
    page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Qminers local testing</title><style>'+style+'</style><main><h1>Qminers local testing</h1><p><small>7 November 2026 · 21 replay experiments · 5 engine probes · Playground sample v2</small></p>'+article+'</main></html>'
    (ROOT.parent/'Qminers-local-testing.html').write_text(page,encoding='utf-8')
    text='QMINERS LOCAL TESTING — 7 NOVEMBER 2026\n\n'+'\n\n'.join([introduction,explanation,validation,regression,pitfalls,stress,probes,research,ruletext])
    text+='\n\nMEASURED LOCAL RUNTIME\n'+benchtext+'\n\nALL REPLAY RESULTS\n'
    text+='Case | Data | PnL | Last quarter | Max inventory | Drawdown (1s) | Lots\n'
    for r in rows:
        text+=f"{r['name']} | {r['data']} | {r['result']['pnl']:+,.0f} | {r['last_quarter_pnl']:+,.0f} | {r['max_abs_inventory']} | {r['max_drawdown']:,.0f} | {r['result']['traded_volume']:,}\n"
    text+='\nADDITIONAL APPROACHES\n'+'\n'.join(' | '.join(r) for r in more)
    text+='\n\nREPRODUCE\n'+commands+'\n\nPROVENANCE\nOfficial commit 3f5bea730d5f341c6988b1fe2722998b66270ea0\nTeam commit 6ca459e966bb1f9e767258ef5ae0ef0bce979c3f\nData SHA256 '+profile['sha256']+'\n'
    text+='\nSources: https://arena.qminers.com/dashboard/info ; https://arena.qminers.com/rules ; https://github.com/QminersOrg/qminers-algo-arena ; https://github.com/jakub-kucera/qminers-arena-hachathon\nResearch: https://arxiv.org/html/2610.02917v1 ; https://arxiv.org/abs/2502.18625 ; https://arxiv.org/abs/2502.15757 ; https://onlinelibrary.wiley.com/doi/10.1111/mafi.12413\n'
    (ROOT.parent/'Qminers-local-testing.txt').write_text(text,encoding='utf-8')
    print('Wrote report, comparison, fill diagnostics, and manifest.')


if __name__=='__main__':
    main()
