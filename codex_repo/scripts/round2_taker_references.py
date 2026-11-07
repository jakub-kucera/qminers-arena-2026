"""Reproduce the supplied cross-session taker public results in our native engine."""
from pathlib import Path
from scripts.benchmark import digest
from scripts.round2_taker_audit import batch
from scripts.round2_workbench import load_manifest


def main():
    m=load_manifest(Path('logs/round2'));candidates=[]
    for name in ('r2_T2_take_only_safe','r2_M2_flow_trend','r2_RA_flow_window','r2_M4_flow_window'):
        p=Path('strategies/round2_imported')/(name+'.py')
        candidates.append(dict(name=name,file=str(p),source_sha256=digest(p),risk='strict100'))
    batch(candidates,m['data'],'logs/round2/taker_references',
        (m['development_cutoff_us'],m['validation_cutoff_us']),workers=3,
        scope='Reproduction of imported sources on reused public data. Reported server results are recorded separately; no new server query.')


if __name__=='__main__':main()
