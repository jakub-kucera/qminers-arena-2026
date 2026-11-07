"""Combine the successful distribution heads with narrow-spread shock exits.

Both components were selected on reused public results. This is explicitly
an adaptive followup, not an independently predeclared confirmation.
"""
from pathlib import Path

from scripts.build_round2_candidates import describe
from scripts.round2_distribution_ensemble import blend
from scripts.round2_distribution_shock_exit import shock_exit
from scripts.round2_full_public_study import run_public_study


def main():
    rich=Path('strategies/round2_distribution_rich_167958.py').read_text()
    mixed=Path('strategies/round2_distribution_mixed_170252.py').read_text()
    cases={'distribution_mixed_shock2':shock_exit(mixed,2),
        'distribution_ensemble_shock2':shock_exit(blend(rich,mixed),2)}
    cases={n:describe(s,'Distribution head plus observed-shock inventory exit. First60% fitted; adaptive reused-public combination; native risk constants unchanged.')
        for n,s in cases.items()}
    run_public_study(cases,'logs/round2/distribution_research/combination_replays',workers=2)


if __name__=='__main__':main()
