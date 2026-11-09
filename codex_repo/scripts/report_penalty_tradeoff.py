"""Summarize explicit penalty economics and preserve unsuccessful probes."""
import argparse
import html
import json
from pathlib import Path
import shutil

from scripts.benchmark import digest
from scripts.probe_penalty_tradeoff import load_protocol


def read(root,name):
    return json.loads((root/(name+'.json')).read_text())


def verify_reference(root):
    references=read(root,'baseline_references')
    for ref in references.values():
        path=Path(ref['path'].replace('\\','/'))
        if not path.exists():
            path=Path('research/robust_augmentation_20261107')/path.name
        assert digest(path)==ref['sha256']
    return {name:ref['record'] for name,ref in references.items()}


def make_plot(root,output,candidate,baseline,name):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    times=[0];gross=[0];net=[0]
    for stamp,mark in candidate['marks'].items():
        times.append(int(stamp)/60000000)
        gross.append(mark['net']+mark['penalty']-baseline['boundary_pnl'][stamp])
        net.append(mark['net']-baseline['boundary_pnl'][stamp])
    times.append(200);gross.append(candidate['gross_pnl']-baseline['result']['pnl'])
    net.append(candidate['result']['pnl']-baseline['result']['pnl'])
    episodes=json.loads((root/'full_candidate'/name/'episodes.json').read_text())
    durations=np.sort([e['duration_us']/1000 for e in episodes])
    fig,axes=plt.subplots(1,2,figsize=(12.5,4.8))
    axes[0].plot(times,gross,label='Gross trading PnL change',color='#167f88',lw=2)
    axes[0].plot(times,net,label='Net change after penalty',color='#b55335',lw=2)
    axes[0].axhline(0,color='#6f7f8e',lw=.8)
    axes[0].axvspan(0,5990/60,color='#ccd7e5',alpha=.35)
    axes[0].set(title='Least damaging active probe vs baseline',xlabel='Elapsed minutes',ylabel='PnL difference')
    axes[0].legend(fontsize=9)
    if len(durations):
        axes[1].step(durations,np.arange(1,len(durations)+1)/len(durations),where='post',color='#167f88',lw=2)
        axes[1].scatter(durations,np.arange(1,len(durations)+1)/len(durations),s=20,color='#167f88')
    axes[1].axvline(100,color='#b55335',ls='--',lw=1,label='100 ms recovery trigger')
    axes[1].set(title=f'Actual breach durations ({len(durations)} episodes)',xlabel='Milliseconds above |inventory| = 100',ylabel='Cumulative fraction',ylim=(0,1.05))
    axes[1].legend(fontsize=9)
    for axis in axes:
        axis.spines[['top','right']].set_visible(False)
        axis.grid(alpha=.15)
    fig.suptitle('Does additional trading pay for the inventory penalty?',fontsize=15,weight='bold')
    fig.text(.5,.015,'Shaded period: screening. All data was previously consumed. Fee = 10,000 × seconds above the soft limit.',ha='center',fontsize=8)
    fig.tight_layout(rect=[0,.045,1,.94])
    fig.savefig(output/'Qminers-penalty-tradeoff.png',dpi=160)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('logs/penalty_tradeoff'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--archive',type=Path,default=Path('research/penalty_tradeoff_20261107'))
    a=p.parse_args();root=a.root
    protocol=load_protocol(root);selection=read(root,'selection')
    screens=read(root,'screen');screens.update(read(root,'activation_screen'))
    references=verify_reference(root)
    name=selection['confirmation_candidate']
    candidate=read(root,'full_candidate')[name]
    baseline=references['full_baseline']
    official=read(root,'export_benchmark');export=read(root,'export_manifest')
    assert official['source_sha256']==export['sha256']==digest(export['file'])
    assert official['result']==candidate['result'], 'Official and audited results differ'
    assert official['curve_sha256']==candidate['curve_sha256'], 'PnL curves differ'
    periods=[];pb=pc=0
    for label,boundary in [('First 50 minutes','3000000000'),('Next 49m 50s','5990000000'),
                           ('Later period to 150m','9000000000'),('Final 50 minutes',None)]:
        b=baseline['boundary_pnl'][boundary] if boundary else baseline['result']['pnl']
        c=candidate['boundary_pnl'][boundary] if boundary else candidate['result']['pnl']
        periods.append({'period':label,'baseline':b-pb,'candidate':c-pc,'gain':c-pc-b+pb})
        pb,pc=b,c
    comparisons=[]
    for label,stage,base_stage in [('round1_5ms','full_candidate','full_baseline'),
                                  ('sample_v2','sample_candidate','sample_baseline'),
                                  ('round1_20ms','full_latency20_candidate','full_latency20_baseline'),
                                  ('round1_50ms','full_latency50_candidate','full_latency50_baseline')]:
        c=read(root,stage)[name];b=references[base_stage]
        comparisons.append({'case':label,'baseline_net':b['result']['pnl'],
                            'candidate_gross':c['gross_pnl'],'penalty':c['result']['breach_penalty'],
                            'candidate_net':c['result']['pnl'],'net_gain':c['result']['pnl']-b['result']['pnl'],
                            'breach_seconds':c['breach_seconds'],'episodes':c['breach_episodes'],
                            'duration_ms_p50_p95_max':c['duration_ms_p50_p95_max'],
                            'max_inventory':c['max_abs_inventory'],'max_potential':c['max_potential_inventory'],
                            'new_order_rejections':c['new_order_rejections'],
                            'drawdown_1s':c['max_drawdown_1s']})
    checks={'screen_passed':selection['selected'] is not None,
            'first_later_gain':periods[2]['gain']>0,'second_later_gain':periods[3]['gain']>0,
            'full_gain_at_least_one_percent':comparisons[0]['net_gain']>=.01*comparisons[0]['baseline_net'],
            'transfer_and_latency_within_one_percent':all(c['candidate_net']>=.99*c['baseline_net'] for c in comparisons[1:]),
            'hard_limits_and_acceptance':all(c['max_inventory']<=1000 and c['max_potential']<=1000 and c['new_order_rejections']==0 for c in comparisons)}
    promoted=all(checks.values())
    screen_rows=[]
    base=screens['baseline']['result']['pnl']
    for n,r in screens.items():
        spec=protocol['sources'][n]
        gross_gain=r['gross_pnl']-base
        screen_rows.append({'name':n,'kind':spec['kind'],'cap':spec['cap'],
                            'gross':r['gross_pnl'],'penalty':r['result']['breach_penalty'],
                            'net':r['result']['pnl'],'net_gain':r['result']['pnl']-base,
                            'gross_gain':gross_gain,'breach_seconds':r['breach_seconds'],
                            'episodes':r['breach_episodes'],'max_inventory':r['max_abs_inventory'],
                            'max_potential':r['max_potential_inventory'],
                            'duration_ms_p50_p95_max':r['duration_ms_p50_p95_max'],
                            'break_even_fee_per_second':gross_gain/r['breach_seconds'] if r['breach_seconds']>0 and gross_gain>0 else None})
    result={'promoted':promoted,'recommended':'baseline' if not promoted else name,
            'diagnostic_candidate':name,'checks':checks,'screen':screen_rows,'comparisons':comparisons,
            'periods':periods,'selection':selection,'export':export,'official_export':official,
            'official_result_exact_parity':True,'official_curve_exact_parity':True,
            'data_sha256':protocol['data_sha256'],'engine_sha256':protocol['engine_sha256'],
            'tests_passed':69,'new_replays':21,
            'limitations':['Previously consumed public tapes; no new independent holdout.',
                           'Five activation probes were added after initial gated variants produced no breaches; this adaptive extension is disclosed and all fourteen trials are included in selection.',
                           'Only the specified admission, cap and recovery policies were tested; this is not a proof that every penalty-paying strategy is unprofitable.',
                           'No website submission or private-round result is claimed.',
                           'Configured hold duration is a recovery trigger, not a guarantee of exit time.']}
    a.output.mkdir(parents=True,exist_ok=True);a.archive.mkdir(parents=True,exist_ok=True)
    (a.archive/'sources').mkdir(exist_ok=True)
    for file in (root/'sources').glob('*.py'):shutil.copyfile(file,a.archive/'sources'/file.name)
    for file in root.glob('*.json'):shutil.copyfile(file,a.archive/file.name)
    (a.archive/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    (a.output/'Qminers-penalty-tradeoff.json').write_text(json.dumps(result,indent=2)+'\n')
    shutil.copyfile(export['file'],a.output/'round1_penalty_experimental.py')
    (a.archive/'.gitattributes').write_text('* -text whitespace=cr-at-eol\n*.json linguist-generated=true\n*.png binary\n')
    make_plot(root,a.output,candidate,baseline,name)
    shutil.copyfile(a.output/'Qminers-penalty-tradeoff.png',a.archive/'Qminers-penalty-tradeoff.png')
    row=lambda values:'<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in values)+'</tr>'
    money=lambda x:f'{x:,.2f}'
    screen_table=''.join(row((r['name'],r['cap'],money(r['gross']),money(r['penalty']),money(r['net']),
                              f"{r['breach_seconds']:.4f}",r['max_inventory'])) for r in screen_rows)
    comparison_table=''.join(row((r['case'],money(r['baseline_net']),money(r['candidate_gross']),money(r['penalty']),
                                  money(r['candidate_net']),f"{r['net_gain']:+,.2f}")) for r in comparisons)
    period_table=''.join(row((r['period'],money(r['baseline']),money(r['candidate']),f"{r['gain']:+,.2f}")) for r in periods)
    cap101=next(r for r in screen_rows if r['name']=='continuous_101')
    cap250=next(r for r in screen_rows if r['name']=='continuous_250')
    best=comparisons[0]
    conclusion=('The tested penalty policy passed the frozen gates.' if promoted else
                'Keep the 100-lot, penalty-free model. No tested policy earned a reliable net improvement from paying the fee.')
    body=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Qminers: inventory penalty economics</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;background:#f4f6f9;color:#213249;margin:0}}main{{max-width:1200px;padding:34px 24px;margin:auto}}h1{{font-size:38px;line-height:1.15}}h2{{margin-top:34px}}.eyebrow{{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#60718b}}.cards{{display:flex;gap:14px;flex-wrap:wrap}}.card{{background:white;padding:18px;border:1px solid #dae2eb;border-radius:10px;flex:1;min-width:190px}}.big{{font-size:30px;font-weight:750;color:#087f89}}table{{border-collapse:collapse;width:100%;background:white;font-size:13px}}td,th{{padding:11px;text-align:left;border-bottom:1px solid #e0e6ed;vertical-align:top}}th{{background:#e7edf4}}.scroll{{overflow-x:auto}}.note{{background:#fff5e3;border-left:4px solid #b78431;padding:15px 18px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#e7edf4;padding:16px;font-size:13px}}img{{width:100%;background:white}}a{{color:#006f94}}small{{color:#61738a}}</style></head><body><main>
<div class="eyebrow">Qminers Arena · explicit penalty tradeoff · 7 November 2026</div>
<h1>Extra capacity is cheap only if the inventory breach is extremely brief.</h1><p>{conclusion}</p>
<div class="cards"><div class="card"><small>Penalty-free full-round baseline</small><div class="big">{baseline['result']['pnl']:,.0f}</div><div>100-lot cap</div></div><div class="card"><small>Least damaging active probe</small><div class="big">{best['candidate_net']:,.2f}</div><div>{best['net_gain']:+,.2f} after fees</div></div><div class="card"><small>Official fee while breached</small><div class="big">10,000 / s</div><div>Same at 101 or 1,000 lots</div></div></div>
<h2>What the simulator actually charges</h2><pre>penalty = 10,000 × total seconds with |actual inventory| > 100
net score = cash + executable liquidation value − penalty
hard potential-position limit = 1,000</pre>
<p>The threshold is strict: exactly ±100 has no fee. Pending order capacity by itself does not incur this fee. Breach size does not change the rate: 101 and 1,000 both cost 50 over 5 ms, 200 over 20 ms, or 1,000 over 100 ms. Natural offsetting fills can end a breach sooner than an actively submitted exit order. No simulator limit, fee, matching rule or scoring logic was changed.</p>
<p>The rule is unfavorable to small overshoots. For a five-millisecond episode, the extra one lot at a 101 cap would need 50 ticks of incremental profit just to cover the fee. An extra 400 lots would need 0.125 ticks per extra lot, but achieving those fills and exiting them still carries execution cost. The hard limit does not guarantee that the available capacity can actually be filled or unwound profitably.</p>
<h2>Experiments and actual recovery</h2><p>The first frozen cohort included continuous caps of 101, 250 and 1,000, plus six signal-gated burst policies and two controls. Initial gates required aligned inventory of at least 80 and a forecast edge of 0.5 or 1.0 ticks. They posted a few larger orders but never realized a breach. Five separately preregistered activation probes therefore lowered the admission threshold, allowed aligned inventory from zero, and included a 100 ms hold matching the forecast horizon. All fourteen candidates were included in the final selection check; the adaptive extension is preserved in the history.</p>
<p>On breach, guarded policies cancel risk-increasing orders. At the hold trigger they cancel normal quotes and submit IOC reductions toward the soft limit, allowing two ticks through the last visible market touch. All pending sends, cancellation requests, opposite quotes and partial IOC residuals remain reserved. A one-second cooldown follows recovery. Callback gaps, 5 ms order latency and insufficient liquidity can prolong a breach. The independent audit tracks exact charged time and every outstanding reservation, including orders currently being activated.</p>
<p>A synthetic integration test created a 300-lot position, recovered to 100 in 5 ms, and verified the real 50-unit fee. Separate tests establish the exact soft boundary, amount-independent charge, unchanged hard limit, partial-exit handling and cancellation reservations. All 69 repository tests pass.</p>
<h2>First 100-minute replay: gross profit versus fee</h2><div class="scroll"><table><tr><th>Policy</th><th>Cap</th><th>Gross PnL</th><th>Penalty</th><th>Net PnL</th><th>Seconds over 100</th><th>Actual peak</th></tr>{screen_table}</table></div>
<p>The 101 cap earned only {money(cap101['gross_gain'])} extra gross PnL but paid {money(cap101['penalty'])} in penalties. The 250 cap added {money(cap250['gross_gain'])} gross, versus {money(cap250['penalty'])} of fees. Its break-even fee rate would have been about {cap250['break_even_fee_per_second']:.2f} per second, compared with the actual 10,000. The 1,000 cap also lost gross trading profit before fees.</p>
<p>The initial guarded policies' unchanged scores are controls with no realized breach, not evidence that paying the penalty works. The activation probes made actual fee-paying trades and all lost net PnL in screening. Screening used exact five-minute boundary marks through 5,990 seconds, avoiding artificial prefix-end order draining. Promotion required a 1% gain, gains in both halves, 12/20 positive blocks and a positive joint-bootstrap lower bound across all fourteen trials; none qualified.</p>
<h2>Frozen diagnostic on the full tape and stress cases</h2><p>The least damaging active candidate was <code>{name}</code>. It was frozen for further diagnostic replay and cannot be promoted after failing the screen. The penalty-free controls were reused only after checking source/data/engine hashes and exact prefix-result/curve parity.</p>
<div class="scroll"><table><tr><th>Case</th><th>Baseline net</th><th>Candidate gross</th><th>Penalty</th><th>Candidate net</th><th>Net difference</th></tr>{comparison_table}</table></div>
<p>Full-round active exposure: {best['breach_seconds']:.6f} seconds across {best['episodes']} episodes; actual peak {best['max_inventory']} lots. Median / 95th percentile / longest episode: {best['duration_ms_p50_p95_max'][0]:.3f} / {best['duration_ms_p50_p95_max'][1]:.3f} / {best['duration_ms_p50_p95_max'][2]:.3f} ms. No hard-limit order rejection occurred.</p>
<table><tr><th>Period</th><th>Baseline net</th><th>Candidate net</th><th>Difference</th></tr>{period_table}</table>
<img src="Qminers-penalty-tradeoff.png" alt="Incremental gross and net profit of the frozen penalty probe, and observed breach duration distribution">
<h2>Artifacts and verification</h2><p><a href="round1_robust_candidate.py">Recommended penalty-free submission</a> · <a href="round1_penalty_experimental.py">Unpromoted penalty experiment</a> · <a href="Qminers-penalty-tradeoff.json">Complete machine-readable evidence</a>.</p>
<p>The exact experimental export was also replayed through the unmodified engine. Every result field and the complete PnL curve matched the audited replay exactly. Exact export CPU time: {official['cpu_seconds']:.1f} seconds; peak working set {official['peak_working_set_bytes']/2**20:.1f} MiB. Sixteen screening replays, four confirmation replays and one official export replay were completed.</p>
<pre>Experimental source SHA-256: {export['sha256']}
Engine SHA-256: {protocol['engine_sha256']}</pre>
<div class="note"><b>Scope:</b> this study tests specified higher-cap and guarded-recovery policies; it does not prove every conceivable penalty-paying strategy is unprofitable. Both public tapes were previously consumed, and the activation extension was adaptive. No fresh holdout, website submission or private leaderboard result is claimed. The current evidence supports retaining the 100-lot strategy.</div>
</main></body></html>'''
    (a.output/'Qminers-penalty-tradeoff.html').write_text(body,encoding='utf-8')
    archive_body=body.replace('href="round1_robust_candidate.py"','href="../../strategies/round1_robust_candidate.py"').replace(
        'href="round1_penalty_experimental.py"','href="../../strategies/round1_penalty_experimental.py"').replace(
        'href="Qminers-penalty-tradeoff.json"','href="summary.json"')
    (a.archive/'report.html').write_text(archive_body,encoding='utf-8')
    (a.archive/'README.txt').write_text('''Inventory penalty tradeoff, 7 November 2026

The exchange configuration remains max_position=100, max_potential_position=1000,
and penalty=10000 per second above the soft limit. Strategy caps do not alter
those settings. Net PnL always includes the actual engine penalty.

protocol.json freezes the first nine candidates plus two controls. The initial
guarded candidates produced no realized breaches, so activation_protocol.json
preregisters five additional activation probes. It records that deviation and
expands the joint selection family to fourteen. No candidate passed screening.
selection.json freezes one active diagnostic; it cannot be promoted afterwards.
baseline_references.json records reused source/data/engine-verified controls.
All public data has been consumed before; no new holdout or website score exists.

Frozen source bytes are in sources/. Original working paths under logs/ are
retained in metadata. Raw tapes and large per-event traces are excluded.

From repository root:
python -m unittest discover -s tests -v
python -m scripts.probe_penalty_tradeoff --prepare --root logs/penalty_replay --source strategies/round1_robust_candidate.py --data data/round1.csv --prefix PATH_TO_6000_SECOND_PREFIX --transfer data/sample_v2.csv
python -m scripts.probe_penalty_tradeoff --root logs/penalty_replay --data PATH_TO_6000_SECOND_PREFIX --stage screen --workers 8
python -m scripts.probe_penalty_tradeoff --root logs/penalty_replay --prepare-activation
Run activation_screen with the five active_* names from activation_protocol.json,
then --select. Full_* stages use round1 boundaries; sample_* use sample_v2.
--delay 20 and --delay 50 supply latency stress. Use a complete prefix from tape
start, never an empty-book restart in the middle of a tape.

python -m scripts.benchmark_depth_submission --strategy strategies/round1_penalty_experimental.py --data data/round1.csv --output logs/penalty_export.json
''')
    print(json.dumps({'promoted':promoted,'candidate':name,'checks':checks,'comparisons':comparisons},indent=2))


if __name__=='__main__':main()
