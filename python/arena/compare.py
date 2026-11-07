"""Compares several bots, or variants of them, against one baseline, in parallel.

    uv run python -m arena.compare python/bots/template.py 1 --bot python/bots/zoo/claude/*.py --modes all,worse
    uv run python -m arena.compare python/bots/template.py 1 --bot python/bots/mine.py "python/bots/template.py@PARAMS.KELP.make_edge=1"
    uv run python -m arena.compare python/bots/template.py 1 2 --data p4 --resting --bot python/bots/a.py python/bots/b.py --vs python/bots/rivals/sniper.py
    uv run python -m arena.compare python/bots/template.py 1 --bot python/bots/zoo/*/*.py --engine rust     # the same, on rust/ (bots with a Rust twin)

The first bot is the baseline, the bot as is (`--set` applies to it alone). Each `--bot` is a
file, or a variant of one: FILE@PATH=VALUE@PATH=VALUE sets globals as `--set` does, and a leading
NAME: names it in the tables (a value longer than MAX_VALUE_CHARS is cut in the label, and the
summary lists such bots' settings in full). Every bot runs
on every day under each `--modes` entry and `--scenario` (arena.scenario: a fill model with its own
rivals), one backtest per worker task, against the same `--vs` rivals unless a scenario names its
own. The summary ranks the bots by PnL, worst day, the other modes and, with a scenario, the worst
case over them all; it scores each day held
out, and then judges the choice as arena.grid judges a grid's (references/wiki/concepts/
validation-and-overfitting.md): PBO, the DSR, Hansen's SPA and Romano and Wolf's StepM against the
baseline, and a pick: StepM's best bot that beats the baseline under every mode, else the
baseline. A bot that fails to load, raises or breaches a limit is reported and left out of the
picks. `--out` writes one row per bot.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path

from arena import grid, report, rust
from arena.botfile import OverrideError, parse_override
from arena.cli import Setup, add_common_arguments, add_engine_argument, add_rival_argument, participant_names, run_with_rivals, setup
from arena.engine import TradeMatching
from arena.formats import FORMATS
from arena.scenario import add_scenario_argument, config_for, every_rival, rivals_for, scenarios_from

MAX_PRODUCT_COLUMNS = 10
MAX_VALUE_CHARS = 16  # a longer setting is cut in the label; --out and the legend keep it whole


@dataclass(frozen=True)
class Candidate:
    path: Path
    overrides: dict
    label: str
    named: bool = False  # the label was given as NAME:FILE...


def _value(value) -> str:
    """A setting's value for a label, cut to MAX_VALUE_CHARS (a whole dict would make the table unreadable)."""
    text = str(value).replace(" ", "")
    return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS - 1] + "…"


def default_label(path: Path, overrides: dict) -> str:
    return path.stem + "".join(f" {k.removeprefix('PARAMS.')}={_value(v)}" for k, v in overrides.items())


def parse_candidate(text: str) -> Candidate:
    """[NAME:]FILE or [NAME:]FILE@PATH=VALUE@...; the label is NAME, else the file's stem plus its settings."""
    name, sep, rest = text.partition(":")
    if not sep or any(c in name for c in "/@="):
        name, rest = "", text
    path, *settings = rest.split("@")
    overrides = dict(parse_override(s) for s in settings)
    if not Path(path).is_file():
        raise ValueError(f"no bot file {path!r}")
    return Candidate(Path(path), overrides, name or default_label(Path(path), overrides), bool(name))


def labelled(candidates: list[Candidate]) -> list[Candidate]:
    """Makes labels unique: two files with one stem get their parent folder, then a number."""
    stems = [c.label for c in candidates]
    out = []
    for c in candidates:
        label = c.label if stems.count(c.label) == 1 else f"{c.path.parent.name}/{c.label}"
        out.append(replace(c, label=label))
    seen: dict[str, int] = {}
    for k, c in enumerate(out):
        seen[c.label] = seen.get(c.label, 0) + 1
        if seen[c.label] > 1:
            out[k] = replace(c, label=f"{c.label}#{seen[c.label]}")
    return out


# ---------------------------------------------------------------------------- running

_WORKER: dict = {}


def _init_worker(format_name, data_arg, day_specs, rivals, config, requote, days=None):
    fmt = FORMATS[format_name]
    days = days if days is not None else fmt.load_days(fmt.resolve_data_dir(data_arg), day_specs)
    _WORKER.update(fmt=fmt, days=days, rivals=rivals, config=config, requote=requote)


def _run(k: int, candidate: Candidate, day_index: int, mode: TradeMatching) -> tuple:
    """One bot on one day under one mode (or scenario)."""
    w = _WORKER
    day = w["days"][day_index]
    config = config_for(w["config"], mode)
    try:
        result = run_with_rivals(w["fmt"], day, candidate.path, candidate.overrides, rivals_for(w["rivals"], mode), config, requote=w["requote"])[0]
    except Exception:  # a bot that doesn't load (syntax error, missing class): every day fails
        return k, day_index, mode, None, report.last_line(traceback.format_exc())
    series = report.total_pnl(result) or [0.0] * len(day.ticks)
    stats = {s.product: s.pnl for s in report.product_stats(result)}
    summary = {
        "pnl": series[-1],
        "coarse": grid.block_pnl(series, grid.blocks_per_day(len(w["days"]))),
        "fine": grid.block_pnl(series, len(series) // grid.FINE_TICKS),
        "products": stats,
        "fills": len(result.fills),
        "errors": len(result.errors),
        "breaches": len(result.limit_breaches),
        "first_error": report.last_line(result.errors[0][1]) if result.errors else "",
    }
    return k, day_index, mode, summary, ""


def _run_rust(s: Setup, candidates: list[Candidate], tasks: list[tuple], jobs: int) -> dict:
    """The tasks as one `arena-rs batch` on `jobs` threads, each summary as _run returns it."""
    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        paths = [rust.write_day(day, scratch / f"day{d}") for d, day in enumerate(s.days)]
        specs = [rust.bot_spec(c.path, c.overrides) for c in candidates]
        rival_specs: dict[str, int] = {}  # each distinct rival's spec, once
        batch = []
        for k, c, d, m in tasks:
            rivals = rivals_for(s.rivals, m)
            names = participant_names(c.path, rivals)
            bots = [[names[0], k]]
            for name, r in zip(names[1:], rivals):
                if str(r) not in rival_specs:
                    rival_specs[str(r)] = len(specs)
                    specs.append(rust.bot_spec(getattr(r, "path", r), getattr(r, "overrides", {}), s.requote))
                bots.append([name, rival_specs[str(r)]])
            batch.append({"day": d, "config": rust.config_json(config_for(s.config, m)), "bots": bots,
                          "blocks": grid.blocks_per_day(len(s.days)), "fine": len(s.days[d].ticks) // grid.FINE_TICKS})
        results = rust.run_batch(paths, specs, batch, jobs, scratch)
    keys = ("pnl", "fine", "products", "fills", "errors", "breaches", "first_error")
    return {(k, d, m): ({"coarse": r["blocks"]} | {key: r[key] for key in keys}, "") for (k, _, d, m), r in zip(tasks, results)}


def run_compare(s: Setup, candidates: list[Candidate], modes: list[TradeMatching], jobs: int, format_name: str, data_arg: str,
                day_specs: list[str]) -> dict[int, grid.Outcome]:
    """Every candidate on every day under every mode; outcome k is candidates[k] (0 is the baseline)."""
    tasks = [(k, c, d, m) for k, c in enumerate(candidates) for m in modes for d in range(len(s.days))]
    init_args = (format_name, data_arg, day_specs, s.rivals, s.config, s.requote)
    found = {}
    progress = grid._Progress(len(tasks))
    if s.engine == "rust":
        found = _run_rust(s, candidates, tasks, jobs)
    elif jobs <= 1:
        _init_worker(*init_args, days=s.days)
        for task in tasks:
            k, d, m, summary, error = _run(*task)
            found[(k, d, m)] = (summary, error)
            progress.step()
    else:
        with ProcessPoolExecutor(jobs, initializer=_init_worker, initargs=init_args) as pool:
            for future in as_completed([pool.submit(_run, *task) for task in tasks]):
                k, d, m, summary, error = future.result()
                found[(k, d, m)] = (summary, error)
                progress.step()
    progress.done()

    outcomes = {}
    for k, c in enumerate(candidates):
        o = grid.Outcome((k,), (c.label,))
        for number, mode in enumerate(modes):
            days, products = o.day_pnl.setdefault(mode, {}), o.product_pnl.setdefault(mode, {})
            coarse, fine = o.block_pnl.setdefault(mode, []), o.fine_pnl.setdefault(mode, [])
            for d, day in enumerate(s.days):
                summary, error = found[(k, d, mode)]
                if summary is None:
                    days[day.name] = 0.0
                    o.errors += 1
                    o.first_error = o.first_error or error
                    continue
                days[day.name] = summary["pnl"]
                coarse += summary["coarse"]
                fine += summary["fine"]
                for p, v in summary["products"].items():
                    products[p] = products.get(p, 0.0) + v
                if number == 0:
                    o.fills += summary["fills"]
                o.errors += summary["errors"]
                o.limit_breaches += summary["breaches"]
                o.first_error = o.first_error or summary["first_error"]
        outcomes[k] = o
    return outcomes


# ---------------------------------------------------------------------------- results


def format_legend(candidates: list[Candidate]) -> str:
    """The full settings of each bot whose label doesn't show them: named, or with a value cut."""
    hidden = [c for c in candidates if c.overrides and (c.named or any(_value(v) != str(v).replace(" ", "") for v in c.overrides.values()))]
    lines = [f"  {c.label}: {c.path} " + " ".join(f"{k}={v!r}" for k, v in c.overrides.items()) for c in hidden]
    return "\n".join(["settings in full:", *lines]) if lines else ""


def format_table(candidates: list[Candidate], modes: list[TradeMatching], outcomes: dict[int, grid.Outcome], top: int) -> str:
    primary, base, worst = modes[0], outcomes[0], grid.scored_worst(modes)
    header = ["rank", "bot", f"pnl({primary})", "vs base", "min day", *(f"pnl({m})" for m in modes[1:]), *(["worst"] if worst else []), "fills", ""]
    ranked = sorted(outcomes.items(), key=lambda item: (item[1].failed, -item[1].pnl(primary)))
    rows = []
    for rank, (k, o) in enumerate(ranked[:top], 1):
        flag = f"! {o.errors} errors, {o.limit_breaches} breaches" if o.failed else ("(base)" if k == 0 else "")
        rows.append([str(rank), candidates[k].label, grid._num(o.pnl(primary)), f"{o.pnl(primary) - base.pnl(primary):+,.0f}",
                     grid._num(o.min_day(primary)), *(grid._num(o.pnl(m)) for m in modes[1:]),
                     *([grid._num(grid.worst_case(o, modes))] if worst else []), f"{o.fills:,}", flag])
    widths = [max(len(cell) for cell in column) for column in zip(header, *rows)]
    lines = ["  ".join((cell.ljust(w) if i == 1 else cell.rjust(w)) for i, (cell, w) in enumerate(zip(cells, widths))).rstrip()
             for cells in [header, *rows]]
    if len(ranked) > top:
        lines.append(f"  ... {len(ranked) - top} more (--top, or --out for all)")
    for k, o in sorted(outcomes.items()):
        if o.first_error:
            lines.append(f"! {candidates[k].label}: {o.first_error}")
    usable = [(k, o) for k, o in outcomes.items() if not o.failed]
    if usable:
        lines.append("")
        named = {"pnl": lambda o: o.pnl(primary), "min-day": lambda o: o.min_day(primary)} | {m.value: (lambda o, m=m: o.pnl(m)) for m in modes[1:]}
        named |= {"worst": lambda o: grid.worst_case(o, modes)} if worst else {}
        width = max(len(name) for name in named)
        picks = set()
        for name, key in named.items():
            k, o = max(usable, key=lambda item: key(item[1]))
            picks.add(k)
            lines.append(f"best by {name:<{width}}  {candidates[k].label}  ({grid._num(key(o))})")
        lines.append("all measures agree" if len(picks) == 1 else "measures disagree: prefer a bot near the top on every measure")
    return "\n".join(lines)


def format_products(candidates: list[Candidate], mode: TradeMatching, outcomes: dict[int, grid.Outcome], top: int) -> str:
    """PnL per product under the first mode, the products with the most PnL at stake first."""
    totals: dict[str, float] = {}
    for o in outcomes.values():
        for p, v in o.product_pnl[mode].items():
            totals[p] = max(totals.get(p, 0.0), abs(v))
    products = [p for p in sorted(totals, key=lambda p: -totals[p]) if totals[p]][:MAX_PRODUCT_COLUMNS]
    if not products:
        return ""
    ranked = sorted(outcomes.items(), key=lambda item: -item[1].pnl(mode))[:top]
    header = ["bot", *products]
    rows = [[candidates[k].label, *(grid._num(o.product_pnl[mode].get(p, 0.0)) for p in products)] for k, o in ranked]
    widths = [max(len(cell) for cell in column) for column in zip(header, *rows)]
    lines = [f"pnl({mode}) per product" + (f" ({len(totals) - len(products)} more products in --out)" if len(totals) > len(products) else "")]
    lines += ["  ".join((cell.ljust(w) if i == 0 else cell.rjust(w)) for i, (cell, w) in enumerate(zip(cells, widths))).rstrip()
              for cells in [header, *rows]]
    return "\n".join(lines)


def write_csv(path: Path, candidates: list[Candidate], modes: list[TradeMatching], outcomes: dict[int, grid.Outcome]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    days = {m: list(outcomes[0].day_pnl[m]) for m in modes}
    products = {m: sorted({p for o in outcomes.values() for p in o.product_pnl[m]}) for m in modes}
    header = ["bot", "file", "overrides"]
    for m in modes:
        header += [f"pnl_{m}", f"min_day_{m}", *(f"pnl_{m}_{d}" for d in days[m]), *(f"pnl_{m}_{p}" for p in products[m])]
    worst = grid.scored_worst(modes)
    header += (["worst"] if worst else []) + ["fills", "errors", "limit_breaches"]
    with path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        for k, o in sorted(outcomes.items()):
            c = candidates[k]
            row = [c.label, str(c.path), " ".join(f"{a}={b}" for a, b in c.overrides.items())]
            for m in modes:
                row += [o.pnl(m), o.min_day(m), *(o.day_pnl[m][d] for d in days[m]), *(o.product_pnl[m].get(p, 0.0) for p in products[m])]
            row += ([grid.worst_case(o, modes)] if worst else []) + [o.fills, o.errors, o.limit_breaches]
            writer.writerow(row)


# ---------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.compare", description="Compare bots against a baseline, with robustness checks.")
    add_common_arguments(parser)
    add_rival_argument(parser)
    add_engine_argument(parser)
    parser.add_argument("--bot", dest="bots", action="extend", nargs="+", required=True, metavar="[NAME:]FILE[@PATH=VALUE...]",
                        help="a bot to compare with the baseline, or a variant FILE@PATH=VALUE@..., optionally named NAME:...; repeatable, and takes several")
    parser.add_argument("--modes", help="comma-separated trade-matching modes, e.g. all,worse; the first is the main one (default: --match-trades)")
    add_scenario_argument(parser)
    parser.add_argument("--top", type=int, default=20, help="rows to show (default: 20)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="worker processes (default: CPU count)")
    parser.add_argument("--out", type=Path, help="write one row per bot to this CSV")
    args = parser.parse_args(argv)

    try:
        s = setup(args)
        modes = scenarios_from(args.modes, args.scenarios, s.config.trade_matching)
        base = Candidate(args.bot, s.overrides, default_label(args.bot, s.overrides))
        candidates = labelled([base, *(parse_candidate(text) for text in args.bots)])
        if s.engine == "rust":
            rust.prepare(args.format, [*{c.path for c in candidates}, *every_rival(s.rivals, modes)], args.allow_stale)
            for c in [*candidates, *(r for m in modes for r in rivals_for([], m))]:
                rust.bot_spec(c.path, c.overrides)  # --set or @ settings on a zoo twin: refused
    except (ValueError, OSError, OverrideError, RuntimeError) as error:
        parser.error(str(error))

    runs = len(candidates) * len(s.days) * len(modes)
    jobs = max(1, min(args.jobs, runs))
    print(f"{len(candidates) - 1} bots and the baseline × {len(s.days)} days × {len(modes)} modes ({runs} backtests) on {jobs} workers")
    if s.rivals:
        print(f"each against {', '.join(str(r) for r in s.rivals)} in the same market")
    described = grid.format_scenarios(modes, s)
    if described:
        print(described)
    start = time.perf_counter()
    outcomes = run_compare(s, candidates, modes, jobs, args.format, args.data, args.days)
    print(f"done in {time.perf_counter() - start:.1f} s\n")
    print(f"baseline: {candidates[0].label}\n")
    legend = format_legend(candidates)
    if legend:
        print(legend + "\n")
    print(format_table(candidates, modes, outcomes, args.top))
    same = [candidates[k].label for k, o in outcomes.items() if k and candidates[k].overrides and not o.failed and not outcomes[0].failed
            and candidates[k].path == candidates[0].path and grid._fingerprint(o, modes) == grid._fingerprint(outcomes[0], modes)]
    for label in same:
        print(f"! {label} makes exactly the baseline's PnL: its settings may have no effect (a typo'd key, or a setting another one overrides)")
    products = format_products(candidates, modes[0], outcomes, args.top)
    if products:
        print("\n" + products)

    axes = [grid.Axis("bot", [c.label for c in candidates])]
    others = {key: o for key, o in outcomes.items() if key != 0}
    keyed = {(k,): o for k, o in others.items()}
    held_out = grid.format_held_out(axes, modes, {(k,): o for k, o in outcomes.items()}, grid.repeated_days(s.days))
    if held_out:
        print("\n" + held_out)
    print("\n" + grid.format_overfitting(outcomes[0], keyed, modes, len(s.days), axes, rust.stats_engine(s.engine)))
    if args.out:
        write_csv(args.out, candidates, modes, outcomes)
        print(f"\nall bots written to {args.out}")
    return 1 if all(o.failed for o in others.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
