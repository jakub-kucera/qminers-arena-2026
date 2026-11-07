"""Checks a bot file before submission.

    uv run python -m arena.validate python/bots/template.py 1
    uv run python -m arena.validate python/bots/template.py 1 --allow numpy --time-limit-ms 900
    uv run python -m arena.validate python/bots/template.py 1 --max-size 100KB   # the dashboard's "up to 100 kB"

File checks, as the portal's upload form makes them: a .py name, not empty, and with --max-size
no bigger than the cap (over it, arena.compact writes a copy without comments or docstrings).

Static checks: the file parses and defines the competition's entry point, imports only the
standard library (plus --allow and the modules the competition provides), and doesn't use
environment variables, files, processes or the network, which the submission environment
probably won't have.

Replay checks on the given days: no exceptions, well-formed orders, no orders cancelled for
breaching a position limit, no tick slower than --time-limit-ms, and with --max-state a WARN if the
largest traderData is longer than the exchange keeps. The first day is then
replayed again: once to check the results repeat exactly, twice in other Python processes with
other hash seeds (PYTHONHASHSEED), which catches a bot that iterates a set of strings, so that the
organisers' rerun wouldn't reproduce it, once reloading the bot every tick, which shows whether it
relies on state the real engine might not keep between calls, once with STRICT off, as
submitted, to check that no exception escapes its own error handling, and once with its orders a
step late (--late, while the run's own delay is 0): rules that don't say when orders arrive may mean
a step later (the 2026-10-30 rehearsal's did), and a bot that doesn't count what it sent and can't
see listed yet re-posts it into the exchange's caps and its own limits. Refusals or breaches there
FAIL; set the bot's DELAY (the template's ADAPTER), or pass --late 0 where the rules say orders
arrive at once.

A bot that games the exchange or other teams rather than trading well (spoofing, moving the mark,
an exchange bug) declares it with a module-level GRAY_AREA = "<what it does>": it may be built and
backtested, but validate FAILs it with that reason in capitals, so it can't be uploaded by
accident. Only --allow-gray-area, after an organiser has said it is allowed, turns that into a WARN.

Exits with 1 if any check fails.
"""

from __future__ import annotations

import argparse
from collections import Counter
import ast
import re
import gc
import hashlib
import inspect
import os
import statistics
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, replace
from pathlib import Path

from arena import report
from arena.botfile import OverrideError
from arena.cli import Setup, add_common_arguments, setup
from arena.engine import run_day

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"

RISKY_MODULES = {"subprocess", "socket", "urllib", "http", "requests"}
HASH_SEEDS = ("1", "2")  # PYTHONHASHSEED of the two other processes the first day is replayed in
UNITS = {"": 1, "b": 1, "k": 1024, "kb": 1024, "kib": 1024, "m": 1024**2, "mb": 1024**2, "mib": 1024**2}  # the portal's are binary
DECIMAL = {"k": 1000, "kb": 1000, "m": 1000**2, "mb": 1000**2}  # but rules may write kB for 1,000 bytes


@dataclass(frozen=True)
class Check:
    status: str
    message: str


def max_size(text: str) -> int:
    """--max-size as bytes: a number of bytes, or the dashboard's figure with its unit ("100 kB", "1.5MB").
    The dashboard shows the cap in binary units to one decimal, but a rules document may mean 1,000
    bytes by kB, so a figure with a unit is taken as the least it could be: rounded from 0.05 below,
    in decimal units unless it says KiB or MiB. 100 kB is 99,950 bytes (the 2026-10-26 dry run)."""
    number = text.strip().rstrip("bBiI").rstrip()
    unit = text.strip()[len(number):].strip().lower()
    number, letter = (number[:-1], number[-1].lower()) if number[-1:].isalpha() else (number, "")
    key = letter + unit
    if key not in UNITS:
        raise argparse.ArgumentTypeError(f"not a size: {text!r} (e.g. 102400, 100KB or 1.5MB)")
    try:
        value = float(number)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a size: {text!r} (e.g. 102400, 100KB or 1.5MB)") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"--max-size must be positive, not {text!r}")
    if UNITS[key] == 1:
        return int(value)
    return int((value - 0.05) * min(UNITS[key], DECIMAL.get(key, UNITS[key])))


def file_checks(path: Path, size: int, limit: int | None) -> list[Check]:
    """What the portal's upload form checks before sending the file: its name, that it isn't empty, its size."""
    checks = []
    if not path.name.lower().endswith(".py"):
        checks.append(Check(FAIL, f"{path.name}: the portal takes only a .py file"))
    if size == 0:
        checks.append(Check(FAIL, "the file is empty"))
    if limit is None:
        checks.append(Check(INFO, f"file size {size:,} bytes; pass the dashboard's cap as --max-size to check it"))
    elif size > limit:
        checks.append(Check(FAIL, f"file size {size:,} bytes, over the cap of {limit:,}: upload a compact copy "
                                  f"(uv run python -m arena.compact {path} <copy>.py) and validate that"))
    else:
        checks.append(Check(PASS, f"file size {size:,} bytes, within the cap of {limit:,}"))
    return checks


def gray_area(tree: ast.Module) -> str | None:
    """The bot's module-level GRAY_AREA string, if it sets one."""
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == "GRAY_AREA" for t in targets):
            value = node.value.value if isinstance(node.value, ast.Constant) else None
            return str(value) if value else "(no reason given)"
    return None


def gray_area_check(tree: ast.Module, allowed: bool) -> list[Check]:
    reason = gray_area(tree)
    if reason is None:
        return []
    if allowed:
        return [Check(WARN, f"GRAY AREA, ALLOWED BY --allow-gray-area: {reason}. Upload only if an organiser said yes, in writing in ON_THE_DAY.md")]
    return [Check(FAIL, f"GRAY AREA: {reason}. THIS BOT GAMES THE EXCHANGE OR OTHER TEAMS: DON'T UPLOAD IT. Only with an organiser's "
                        "yes, written in ON_THE_DAY.md, validate it with --allow-gray-area")]


def static_checks(source: str, fmt, allow: set[str]) -> tuple[list[Check], bool]:
    """Returns the checks, and whether the file is sound enough to replay."""
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [Check(FAIL, f"syntax error: {error}")], False

    checks = []
    problems = fmt.check_source(tree)
    if problems:
        checks.append(Check(FAIL, "entry point: " + "; ".join(problems)))
    else:
        checks.append(Check(PASS, "parses and defines the entry point"))

    imported = _imported_modules(tree)
    outside = sorted(
        m for m in imported if m not in sys.stdlib_module_names and m not in fmt.PROVIDED_MODULES and m not in allow
    )
    if outside:
        checks.append(
            Check(FAIL, f"imports outside the standard library: {', '.join(outside)} (--allow them if the competition does)")
        )
    else:
        checks.append(Check(PASS, f"imports: {', '.join(sorted(imported)) or 'none'}"))

    risky = _risky_uses(tree, imported)
    if risky:
        checks.append(Check(WARN, f"uses {', '.join(risky)}: probably unavailable when submitted"))
    else:
        checks.append(Check(PASS, "no environment variables, files, processes or network"))

    return checks, not problems


CAPPED = re.compile(r"order cap: \d+ of (\d+) new orders")
ACTIONS_CAPPED = re.compile(r"action cap: \d+ of (\d+) actions")
RESTING_CAPPED = re.compile(r"resting cap: (\d+) new orders")
UNKNOWN_CANCEL = re.compile(r"cancel for order \d+, which isn't open")


def sent(result) -> tuple[Counter, Counter]:
    """What the bot sent per tick, before any cap dropped it: (new orders, actions: new orders and cancels). An
    exchange that caps actions counts cancels too (the 2026-10-28 rehearsal's rules), and result.orders also
    holds the orders kept from earlier ticks, so neither is its length."""
    orders = Counter(ts for ts, o in result.orders if o.timestamp == ts)  # placed this tick
    cancels = Counter(ts for ts, _ in result.cancels)
    whole: dict[int, int] = {}
    for ts, error in result.errors:
        if (match := RESTING_CAPPED.match(error)):
            orders[ts] += int(match.group(1))
        elif UNKNOWN_CANCEL.match(error):
            cancels[ts] += 1
    for ts, error in result.errors:  # a cap applied earlier saw more: the order cap all new orders, the action cap all of it
        if (match := CAPPED.match(error)):
            orders[ts] = int(match.group(1))
        elif (match := ACTIONS_CAPPED.match(error)):
            whole[ts] = int(match.group(1))
    actions = Counter({ts: orders[ts] + cancels[ts] for ts in set(orders) | set(cancels)})
    actions.update({ts: n - actions[ts] for ts, n in whole.items()})
    return orders, actions


def most_working(result) -> int:
    """The most orders one product had working in a tick (--max-resting's count)."""
    return max(Counter((ts, o.product) for ts, o in result.orders).values(), default=0)


class _GcClock:
    """Seconds the collector has run, from gc.callbacks: what to take out of a bot's timed call."""

    def __init__(self):
        self.total, self._start = 0.0, None

    def __call__(self, phase: str, info: dict) -> None:
        if phase == "start":
            self._start = time.perf_counter()
        elif self._start is not None:
            self.total += time.perf_counter() - self._start
            self._start = None


class _Timed:
    """The bot, with the collector's seconds during each of its calls recorded beside the engine's timing."""

    def __init__(self, bot, clock: _GcClock):
        self.bot, self.clock, self.gc_seconds = bot, clock, []

    def step(self, *args):
        before = self.clock.total
        try:
            return self.bot.step(*args)
        finally:
            self.gc_seconds.append(self.clock.total - before)

    def __getattr__(self, name):  # begin_day and the rest, as the bot has them
        return getattr(self.bot, name)


def replay_checks(path: Path, s: Setup, time_limit_ms: float, argv: list[str] | None = None,
                  max_state: int | None = None, late: int | None = None) -> list[Check]:
    """argv, this run's arguments, lets the first day be replayed in other processes (hash_seed_check).
    late: the steps of the late replay (late_check); None for 1 while the run's delay is 0, 0 for none."""
    results, bots = [], []
    # The loaded days are long-lived: freeze them out of the collector, or its pauses land inside
    # the bot's timed calls (43-53 ms against the bot's own 0.3 ms in the 2026-10-26 dry run).
    # A collection can still start inside a call and walk the engine's own objects (70-91 ms once a session in the
    # 2026-10-28 rehearsal, under load; 2.5 ms with the collector off): time it apart (_GcClock) and leave it out.
    gc.collect()
    gc.freeze()
    clock, timed = _GcClock(), []
    gc.callbacks.append(clock)
    try:
        for day in s.days:
            bot = s.format.load_bot(path, s.overrides, strict=True)
            timed.append(_Timed(bot, clock))
            results.append(run_day(day, timed[-1], s.config))
            bots.append(bot)
    finally:
        gc.callbacks.remove(clock)

    checks = []
    ticks = sum(len(r.timestamps) for r in results)
    errors = [(r.day, timestamp, error) for r in results for timestamp, error in r.errors]
    if errors:
        day, timestamp, error = errors[0]
        checks.append(
            Check(FAIL, f"{len(errors)} errors in {ticks:,} ticks; first on {day} at {timestamp}:\n{_indent(error)}")
        )
    else:
        checks.append(Check(PASS, f"no errors in {ticks:,} ticks"))

    breaches = [(r.day, timestamp, product) for r in results for timestamp, product in r.limit_breaches]
    if breaches:
        day, timestamp, product = breaches[0]
        checks.append(
            Check(
                FAIL,
                (f"{len(breaches)} ticks over a position limit (--limit-penalty charges each); " if s.config.limit_penalty is not None
                 else f"{len(breaches)} times orders were cancelled for breaching a position limit; ")
                + f"first {product} on {day} at {timestamp}",
            )
        )
    else:
        checks.append(Check(PASS, "orders never breach a position limit"))

    step_ms = [(seconds - collected) * 1000 for r, t in zip(results, timed) for seconds, collected in zip(r.step_seconds, t.gc_seconds)]
    raw = max((seconds * 1000 for r in results for seconds in r.step_seconds), default=0.0)
    slowest = max(step_ms, default=0.0)
    p99 = statistics.quantiles(step_ms, n=100)[98] if len(step_ms) >= 100 else slowest
    pauses = f"; {raw:.1f} ms with the backtester's garbage collections, left out" if raw - slowest >= 1 else ""
    checks.append(
        Check(
            FAIL if slowest > time_limit_ms else PASS,
            f"slowest tick {slowest:.1f} ms (limit {time_limit_ms:g} ms), 99th percentile {p99:.2f} ms, mean {statistics.fmean(step_ms or [0]):.2f} ms{pauses}",
        )
    )
    if slowest <= time_limit_ms < raw:  # their clock may count the collections the bot's own allocations set off
        checks.append(Check(WARN, f"a tick took {raw:.1f} ms with garbage collections, over the {time_limit_ms:g} ms limit: "
                                  "their clock may count them; allocate less per tick"))

    first, baseline = s.days[0], results[0].fills
    repeat = run_day(first, s.format.load_bot(path, s.overrides, strict=True), s.config)
    if repeat.fills == baseline:
        checks.append(Check(PASS, f"same fills when {first.name} is replayed again"))
    else:
        checks.append(Check(WARN, "fills differ on a repeat run: the bot isn't deterministic (clock, randomness, set order?)"))
    if argv is not None:
        checks.append(hash_seed_check(argv, fills_digest(baseline), first.name))

    fresh = run_day(first, s.format.load_bot(path, s.overrides, strict=True, fresh_each_tick=True), s.config)
    if fresh.fills == baseline:
        checks.append(Check(PASS, "same fills when the bot is reloaded every tick"))
    else:
        checks.append(
            Check(
                WARN,
                "fills change when the bot is reloaded every tick: it keeps state in instance or module "
                "variables, which the real engine may not preserve between calls",
            )
        )

    # The replays above set STRICT, so a bot's own error handling never ran. Run it as submitted.
    lenient = run_day(first, s.format.load_bot(path, s.overrides, strict=False), s.config)
    escaped = [(t, e) for t, e in lenient.errors if e.startswith("Traceback")]  # not the engine's own (order cap, cancels), the first check's
    if escaped:
        timestamp, error = escaped[0]
        checks.append(
            Check(
                FAIL,
                f"{len(escaped)} exceptions escaped the bot with STRICT off (as submitted); first at {timestamp}:\n"
                f"{_indent(error)}",
            )
        )
    else:
        checks.append(Check(PASS, f"no exception escapes the bot with STRICT off on {first.name}"))

    late = (1 if s.config.delay == 0 else 0) if late is None else late
    if late:
        checks.append(late_check(path, s, late))

    pnl = " · ".join(f"{r.day} {(report.total_pnl(r) or [0])[-1]:,.0f}" for r in results)
    state = max((getattr(bot, "max_state_chars", 0) for bot in bots), default=0)
    output = max(r.max_output_chars for r in results)
    checks.append(Check(INFO, f"pnl: {pnl}"))
    busiest = max((max(sent(r)[0].values(), default=0) for r in results), default=0)
    actions = max((max(sent(r)[1].values(), default=0) for r in results), default=0)
    working = max((most_working(r) for r in results), default=0)
    checks.append(Check(INFO, f"largest state {state:,} chars, largest print per tick {output:,} chars, most orders in a tick {busiest:,} "
                              f"(--max-orders N), most actions in a tick {actions:,} (orders and cancels, --max-actions N), "
                              f"most orders working a product {working:,} (--max-resting N): what the bot sent, before any cap"))
    if max_state is not None and state > max_state:  # Prosperity cut traderData at 50,000 and the bot read it back broken
        checks.append(Check(WARN, f"largest state {state:,} chars is over --max-state {max_state:,}: the exchange may cut it"))
    return checks


def late_check(path: Path, s: Setup, steps: int) -> Check:
    """The first day replayed with every order `steps` steps later than the run's: FAIL on any error (a cap's
    refusal, an exception) or breach, as a bot that re-posts what it can't see listed yet gets them."""
    config = replace(s.config, delay=s.config.delay + steps)
    result = run_day(s.days[0], s.format.load_bot(path, s.overrides, strict=True), config)
    where = f"{s.days[0].name} with orders {steps} step{'s' if steps > 1 else ''} late (--delay {config.delay})"
    races = f"; {len(result.races):,} race ticks (a fill since the bot decided), not counted" if result.races else ""
    problems = []
    if result.errors:
        timestamp, error = result.errors[0]
        problems.append(f"{len(result.errors):,} errors, first at {timestamp}: {error.splitlines()[-1] if error.startswith('Traceback') else error}")
    if result.limit_breaches:
        timestamp, product = result.limit_breaches[0]
        problems.append(f"{len(result.limit_breaches):,} breach ticks, first {product} at {timestamp}")
    if problems:
        return Check(FAIL, f"{where}: {'; '.join(problems)}{races}. If their rules don't say orders arrive at once, set the bot's "
                           f"DELAY (and ORDERS_REST) so it counts what it sent and can't see yet; if they do, --late 0")
    return Check(PASS, f"{where}: no errors or breaches{races}")


def conflict_checks(path: Path, s: Setup) -> list[Check]:
    """A WARN for each setting the bot itself says can't matter, if it says (the template's
    param_conflicts(product): a second target mode, a target a mode replaces, a mode's own setting
    while the mode is off)."""
    s.format.load_bot(path, s.overrides, strict=True)
    module = sys.modules.get(f"arena_bot_{Path(path).stem}")  # BotFile.load registers the module under this name
    conflicts, params = getattr(module, "param_conflicts", None), getattr(module, "PARAMS", None)
    if not callable(conflicts) or not isinstance(params, dict):
        return []
    checks = limit_checks(module, s.days) + wall_checks(module, s.days)
    found = [f"{product}: {reason}" for product in params for reason in conflicts(product)]
    if not found:
        return checks + [Check(PASS, "no setting in PARAMS is overridden by another or left without its mode")]
    return checks + [Check(WARN, "settings that can't matter: " + "; ".join(found))]


WALL_FALLBACK = 0.2  # share of book sides without a level of wall_size above which sized_mid is mostly the plain mid


def wall_checks(module, days) -> list[Check]:
    """A WARN for each traded product on `fair: "sized_mid"` whose book sides lack a level of its
    wall_size more than WALL_FALLBACK of the time: there sized_mid falls back to the best level, the
    noisiest price (the second audit, A8). arena.diagnose's `wall` column is the size to set."""
    defaults, params = getattr(module, "DEFAULTS", None), getattr(module, "PARAMS", None)
    if not isinstance(defaults, dict) or not isinstance(params, dict) or "wall_size" not in defaults:
        return []
    found = []
    for product in sorted(params):
        p = {**defaults, **params[product]}
        if p.get("fair") != "sized_mid":
            continue
        sides = [levels for day in days for tick in day.ticks if (book := tick.books.get(product)) for levels in (book.bids, book.asks) if levels]
        if not sides:
            continue
        short = sum(1 for levels in sides if max(v for _, v in levels) < p["wall_size"]) / len(sides)
        if short > WALL_FALLBACK:
            largest = sorted(max(v for _, v in levels) for levels in sides)[len(sides) // 2]
            found.append(f"{product} on {short:.0%} of book sides (no level of {p['wall_size']}; the largest's median is {largest})")
    if not found:
        return []
    return [Check(WARN, "sized_mid falls back to the plain mid, so set wall_size near the market maker's size: " + "; ".join(found))]


def limit_checks(module, days) -> list[Check]:
    """A WARN for each traded product whose limit in the bot isn't the data's: a PARAMS entry
    without "limit" silently gets DEFAULTS'. Only for a bot whose params_for(product) takes the
    product alone; one that also takes the exchange's API (the drill template) reads the limit
    from it."""
    params_for = getattr(module, "params_for", None)
    if not callable(params_for) or len(inspect.signature(params_for).parameters) != 1:
        return []
    limits = {product: limit for day in days for product, limit in day.limits.items()}
    found, missing = [], []
    for product in sorted(set(getattr(module, "PARAMS", {})) & set(limits)):
        if "limit" not in module.PARAMS[product]:  # the template's params_for refuses it, so the product never trades
            missing.append(f"{product} (the data's {limits[product]})")
            continue
        ours = params_for(product)["limit"]
        if ours != limits[product]:
            found.append(f"{product} {ours}, the data's {limits[product]}")
    checks = [Check(FAIL, "no limit in PARAMS for " + "; ".join(missing))] if missing else []
    if found:
        checks.append(Check(WARN, "position limits differ from the data's: " + "; ".join(found)))
    return checks or [Check(PASS, "every traded product's limit is the data's")]


def fills_digest(fills) -> str:
    return hashlib.sha256(repr(fills).encode()).hexdigest()


def hash_seed_check(argv: list[str], digest: str, day: str) -> Check:
    """The first day's fills in two other Python processes, with other PYTHONHASHSEEDs, against
    this process's. A repeat in one process can't see a dependence on the hash seed: set and dict
    order of strings stay the same there, and change between processes."""
    found = []
    for seed in HASH_SEEDS:
        out = subprocess.run([sys.executable, "-m", "arena.validate", *argv, "--fills-digest"], capture_output=True, text=True,
                             env={**os.environ, "PYTHONHASHSEED": seed})
        if out.returncode != 0:
            last = (out.stderr.strip().splitlines() or ["no output"])[-1]
            return Check(WARN, f"couldn't replay {day} in another Python process: {last}")
        found.append(out.stdout.split()[-1])
    if all(other == digest for other in found):
        return Check(PASS, f"same fills when {day} is replayed in other Python processes (PYTHONHASHSEED {', '.join(HASH_SEEDS)})")
    return Check(WARN, "fills differ between Python processes with other hash seeds: the bot depends on the order of a set of "
                 "strings (or something built from one), so a rerun by the organisers may not reproduce its result")


def _imported_modules(tree: ast.Module) -> set[str]:
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def _risky_uses(tree: ast.Module, imported: set[str]) -> list[str]:
    found = {module for module in imported if module in RISKY_MODULES}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr in {"environ", "getenv"}
        ):
            found.add(f"os.{node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            found.add("open()")
    return sorted(found)


def _indent(text: str) -> str:
    return textwrap.indent(text.rstrip(), "        ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.validate", description="Check a bot file before submitting it.")
    add_common_arguments(parser)
    parser.add_argument("--allow", default="", help="comma-separated non-standard-library modules the competition allows")
    parser.add_argument("--time-limit-ms", type=float, default=900, help="slowest allowed tick (default: 900, Prosperity's limit)")
    parser.add_argument("--max-size", type=max_size, help="the dashboard's file-size cap: bytes, or as shown (100KB, 1.5MB)")
    parser.add_argument("--max-state", type=int, metavar="CHARS", help="the largest traderData the exchange keeps (Prosperity: 50000): WARN above it")
    parser.add_argument("--late", type=int, metavar="STEPS",
                        help="replay the first day with orders this many steps late too, FAIL on refusals or breaches "
                             "(default: 1 while the run's delay is 0; 0 for none, where the rules say orders arrive at once)")
    parser.add_argument("--allow-gray-area", action="store_true",
                        help="a GRAY_AREA bot WARNs instead of FAILing: only after an organiser has said it is allowed")
    parser.add_argument("--fills-digest", action="store_true", help=argparse.SUPPRESS)  # hash_seed_check's other processes
    argv = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(argv)
    if args.fills_digest:
        s = setup(args)
        print(fills_digest(run_day(s.days[0], s.format.load_bot(args.bot, s.overrides, strict=True), s.config).fills))
        return 0

    try:
        s = setup(args)
        source = args.bot.read_text(encoding="utf-8")
        size = args.bot.stat().st_size
    except (ValueError, OSError) as error:
        parser.error(str(error))

    allow = {module.strip() for module in args.allow.split(",") if module.strip()}
    print(f"Validating {args.bot} on {', '.join(day.name for day in s.days)} ({args.format} format)")
    checks = file_checks(args.bot, size, args.max_size)
    found, replayable = static_checks(source, s.format, allow)
    checks += found
    try:
        tree = ast.parse(source)
    except SyntaxError:  # static_checks has failed it already
        tree = None
    if tree is not None:
        checks += gray_area_check(tree, args.allow_gray_area)
    if replayable:
        try:
            checks += replay_checks(args.bot, s, args.time_limit_ms, argv, args.max_state, args.late)
            checks += conflict_checks(args.bot, s)
        except OverrideError as error:
            parser.error(str(error))
        except Exception as error:  # the bot failed while loading, before any tick ran
            checks.append(Check(FAIL, f"bot failed to load: {type(error).__name__}: {error}"))

    for check in checks:
        print(f"  {check.status}  {check.message}")
    failed = any(check.status == FAIL for check in checks)
    marked = gray_area(tree) if tree is not None else None
    if marked is not None:
        print(f"!!! GRAY AREA BOT: {marked} !!!")
    print("Result: FAILED" if failed else "Result: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
