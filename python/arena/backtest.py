"""Backtests a bot file on recorded data.

    uv run python -m arena.backtest python/bots/template.py 1              # every day of round 1
    uv run python -m arena.backtest python/bots/template.py 1-0 --data p2  # Prosperity 2 data
    uv run python -m arena.backtest python/bots/template.py 1 --set PARAMS.KELP.make_edge=2 --out results/
    uv run python -m arena.backtest python/bots/template.py 1 --vs python/bots/template.py   # against a copy of itself
    uv run python -m arena.backtest python/bots/template.py 1 --engine rust            # the same results, on rust/ (bots with a Rust twin)
    uv run python -m arena.backtest python/bots/template.py 1 --metrics                # also the figures the Arena's portal shows
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from arena import report, rust
from arena.botfile import OverrideError
from arena.cli import add_common_arguments, add_engine_argument, add_rival_argument, credits_per_unit, participant_names, participants, run_with_rivals, setup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.backtest", description="Backtest a bot file on recorded data.")
    add_common_arguments(parser)
    add_rival_argument(parser)
    add_engine_argument(parser)
    parser.add_argument("--out", type=Path, help="write <day>_timeline.csv, _fills.csv and _orders.csv to this folder")
    parser.add_argument("--print", action="store_true", help="show the bot's prints")
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="also print the figures the Arena's portal shows on a submission: fills, volume, end position, cash, "
        "mark-out price, limit penalty, PnL standard error, |position| quantiles",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="leave the bot's STRICT flag alone, so it handles its own exceptions as it would when submitted",
    )
    args = parser.parse_args(argv)

    try:
        s = setup(args)
        s.format.load_bot(args.bot, s.overrides, strict=True)  # fail fast on a bad path or --set
        for rival in s.rivals:
            s.format.load_bot(rival, {}, strict=True)
        if s.engine == "rust":
            rust.prepare(args.format, [args.bot, *s.rivals], args.allow_stale)
            ran = rust.run_days(s.days, participants(args.bot, s.overrides, s.rivals, s.requote), s.config, threads=len(s.days))
    except (ValueError, OSError, OverrideError, RuntimeError) as error:
        parser.error(str(error))

    config = replace(s.config, capture_output=not args.print)
    names = participant_names(args.bot, s.rivals)
    results, rival_results = [], []
    for k, day in enumerate(s.days):
        if s.engine == "rust":
            result, *rivals = ran[k]
        else:
            result, *rivals = run_with_rivals(s.format, day, args.bot, s.overrides, s.rivals, config, strict=not args.no_strict, requote=s.requote)
        results.append(result)
        rival_results.append(rivals)
        print(report.format_day(result, config.limit_penalty))
        print(report.format_path(result))
        if args.metrics:
            print(report.format_metrics(result, config.limit_penalty))
        if rivals:
            print(report.format_rivals(names[1:], rivals))
        print()
        if args.out:
            report.write_csvs(result, args.out)

    if args.metrics and len(results) > 1:
        print(report.format_metrics_total(results, config.limit_penalty))
        print()
    scale = credits_per_unit(args.format, s.days) if args.metrics else 1.0
    if scale != 1.0:  # the tables are in the engine's price units
        finals = [(report.total_pnl(result) or [0.0])[-1] for result in results]
        print(f"  in the portal's credits ({scale:g} a price unit: the data's unit x the format's CREDITS): "
              f"pnl sum {sum(finals) * scale:,.2f} · mean {sum(finals) * scale / len(finals):,.2f}; cash, mark and penalty scale alike\n")
    if len(results) > 1:
        print(report.format_overall(results))
        if s.rivals:
            totals = [sum((report.total_pnl(day[k]) or [0.0])[-1] for day in rival_results) for k in range(len(s.rivals))]
            print("  rivals: " + " · ".join(f"{name} {total:,.0f}" for name, total in zip(names[1:], totals)))
    if args.out:
        print(f"CSVs written to {args.out}/")
    return 1 if any(r.errors for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
