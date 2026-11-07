"""Freeze a small development-chosen set before the next public20% replay.

Reuses exact audited development outcomes by source and data fingerprint;
selection then replays continuously through the 80% boundary using the normal
workbench. This consumes the middle public20% for selection, never private data.
"""
import json
from pathlib import Path

from scripts.benchmark import digest
from scripts.round2_workbench import prepare,write_json,load_manifest,select


CHOICES=(
    ('absolute_variance_followups','absolute_variance_tau3_risk200'),
    ('absolute_volatility','absolute_vol_tau10_risk200_power2'),
    ('absolute_vol_followups','absolute_vol_tau3_risk100'),
    ('queue_combinations','queue25target_jump'),
    ('queue_pause500','queue50_pause500'),
)
OUTPUT=Path('logs/round2_selection_v1')


def main():
    intake=load_manifest(Path('logs/round2'))
    results={};sources=[];origin={}
    for folder,name in CHOICES:
        report_path=Path('logs/round2')/folder/'results.json'
        study=json.loads(report_path.read_text())
        assert study['native']==intake['native']
        assert study['data_sha256']==intake['development_sha256']
        r=study['results'][name]
        assert digest(r['source'])==r['source_sha256']
        sources.append(Path(r['source']));results[name]=r
        origin[name]=str(report_path)
    flat=next(c for c in intake['candidates'] if c['name']=='round2_flat')
    sources.append(Path(flat['file']))
    results['round2_flat']=json.loads(Path('logs/round2/development.json').read_text())['results']['round2_flat']
    origin['round2_flat']='logs/round2/development.json'
    if not (OUTPUT/'manifest.json').exists():
        manifest=prepare(intake['data'],OUTPUT,sources)
        assert manifest['development_sha256']==intake['development_sha256']
        assert manifest['validation_prefix_sha256']==intake['validation_prefix_sha256']
        reused={}
        for c in manifest['candidates']:
            r=dict(results[c['name']])
            assert c['source_sha256']==r['source_sha256']
            assert r['data_sha256']==manifest['development_sha256']
            r['development_window_pnl']=r['boundary_pnl'][str(manifest['development_cutoff_us'])]
            r['development_cache_reused_from']=origin[c['name']]
            reused[c['name']]=r
        write_json(OUTPUT/'development.json',dict(data_sha256=manifest['development_sha256'],results=reused))
        write_json(OUTPUT/'shortlist_before_selection.json',dict(
            choices=[c['name'] for c in manifest['candidates']],
            source_hashes={c['name']:c['source_sha256'] for c in manifest['candidates']},
            reasoning='Three inverse-volatility/variance leaders, a signal-target alternative, a fixed-cap maker and flat control. Chosen only on first60% development.',
            public_next20_previously_replayed=False,
            public_last20_previously_replayed=False))
    manifest=load_manifest(OUTPUT)
    selected=select(manifest,OUTPUT,workers=3)
    print(json.dumps(selected,indent=2),flush=True)


if __name__=='__main__':main()
