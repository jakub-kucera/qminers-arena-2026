"""Small combination study without refitting choices to full results."""
from pathlib import Path
from scripts.round2_t2_structural import build as structural,SOURCE
from scripts.round2_ra_composite import main
from scripts.benchmark import digest


def build():
    original=structural()
    cases={name:original[name].replace('    QUOTE_SIZE = 1','    QUOTE_SIZE = 0',1)
           for name in ('flow_bias0.2','flow_bias0.3','ridge3x')}
    cases['flow02_ridge3x']=cases['flow_bias0.2'].replace(
        'ridge = max(10.0, 0.001 * self._mass)','ridge = max(30.0, 0.003 * self._mass)',1)
    return cases


if __name__=='__main__':
    main(Path('logs/round2_t2_noquote_combo'),build(),
         'Four fixed combinations: no passive plus flow0.2/0.3, ridge3x, or flow0.2+ridge3x. Reference294098 first80=223851,later30-80=185349. No additive-gain assumption; same native fees and latency.',
         goal=dict(reference_audit='logs/round2_t2_liquidity_supplied/full_audit.json',reference_source_sha256=digest(SOURCE),increment=50000))
