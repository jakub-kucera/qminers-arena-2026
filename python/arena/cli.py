"""Command-line options shared by arena.backtest, arena.validate, arena.grid, arena.compare and arena.stress."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from types import ModuleType

from arena.botfile import parse_override
from arena.engine import DayResult, EngineConfig, Mark, QueueModel, TradeMatching, run_market
from arena.formats import FORMATS
from arena.model import Cancel, Day


@dataclass
class Setup:
    format: ModuleType
    days: list[Day]
    config: EngineConfig
    overrides: dict[str, object]
    rivals: list[Path] = field(default_factory=list)  # bots trading in the same market (--vs)
    requote: bool = False  # the rivals cancel all their resting orders every tick (--requote)
    engine: str = "python"  # --engine: "rust" runs the backtests on rust/ (python/arena/rust.py)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("bot", type=Path, help="bot file")
    parser.add_argument("days", nargs="+", help="days to replay: ROUND for all its days, or ROUND-DAY (e.g. 1, 1-0, 1--1)")
    parser.add_argument("--format", default="prosperity", choices=sorted(FORMATS), help="competition format (default: prosperity)")
    parser.add_argument("--data", default="p3", help="data folder, or p2 / p3 / p4 for the Prosperity data in references/ (default: p3)")
    parser.add_argument(
        "--match-trades",
        type=TradeMatching,
        choices=list(TradeMatching),
        default=None,
        help="which market trades leftover orders can fill against: at the order's price or worse (all), "
        "strictly worse (worse), or none (default: the format's ENGINE, else all)",
    )
    parser.add_argument(
        "--resting",
        action="store_true",
        help="unfilled orders rest on the book until filled or cancelled, with a queue model "
        "(default: they're cancelled at the end of each tick, as in Prosperity; always on for a format whose orders rest)",
    )
    parser.add_argument(
        "--queue",
        type=QueueModel,
        choices=list(QueueModel),
        default=None,
        help="with --resting, where other orders' cancellations at your price fall: always behind you (back), "
        "split by your place in the queue (prob, see --queue-power), or everyone re-posts behind you every tick "
        "(front) (default: the format's ENGINE, else back)",
    )
    parser.add_argument(
        "--queue-power",
        type=float,
        default=None,
        help="--queue prob: a cancellation lands ahead of you with probability x**N, x your share of the queue "
        "ahead; 1 is uniform, a large N tends to back (default: 1)",
    )
    parser.add_argument(
        "--fill-ratio",
        type=float,
        default=None,
        help="share of book and market-trade volume available to you; below 1 approximates other teams "
        "competing for the same fills (default: 1)",
    )
    parser.add_argument("--print-share", type=float, default=None, metavar="SHARE",
                        help="each market trade offers your orders only this share of its volume, rounded down, the same every "
                        "time (an exchange whose prints also fill orders its book doesn't show; default: the format's ENGINE, else 1)")
    parser.add_argument("--seed", type=int, default=0, help="seed for --fill-ratio draws (default: 0)")
    parser.add_argument(
        "--mark",
        type=Mark,
        choices=list(Mark),
        default=None,
        help="the price positions are valued at each tick: the data's mid (mid), the best bid for a long position and "
        "the best ask for a short one (touch), or the last market trade (last) (default: the format's ENGINE, else mid)",
    )
    parser.add_argument(
        "--limit-penalty",
        type=float,
        default=None,
        metavar="RATE",
        help="no order is rejected for a position limit: each lot beyond it costs RATE every tick instead, in the data's price units "
        "(default: Prosperity's rule, every order for a product rejected if they could breach)",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=None,
        metavar="TICKS",
        help="orders reach the exchange this many ticks after the bot decides, meeting that tick's book and trades, as on an "
        "exchange that applies them a step late (default: 0, Prosperity's)",
    )
    parser.add_argument("--fee", type=float, default=None, metavar="PER_LOT",
                        help="charge every fill this much a lot, in the data's price units (default: the format's ENGINE, else 0, Prosperity's)")
    parser.add_argument("--fee-bps", type=float, default=None, metavar="BPS",
                        help="charge every fill this many basis points of its value (default: the format's ENGINE, else 0)")
    parser.add_argument("--deplete", action="store_true", default=None,
                        help="volume we take from the recorded book stays gone from later snapshots while its level shows more (a replay that keeps what we consume)")
    parser.add_argument("--max-orders", type=int, metavar="N",
                        help="new orders a bot may send a tick: the rest are dropped and logged as an error (an exchange's rate limit)")
    parser.add_argument("--max-actions", type=int, metavar="N",
                        help="orders and cancels a bot may send a tick: the rest are dropped and logged as an error")
    parser.add_argument("--max-resting", type=int, metavar="N",
                        help="orders a product may have working at once (kept ones first, then new ones that would rest): new ones beyond are dropped, an error")
    parser.add_argument("--maker-fee", type=float, metavar="PER_LOT",
                        help="a passive fill's fee a lot instead of --fee, in the data's price units; negative is a rebate")
    parser.add_argument("--maker-fee-bps", type=float, metavar="BPS",
                        help="a passive fill's basis points instead of --fee-bps; negative is a rebate")
    parser.add_argument("--order-fee", type=float, metavar="PER_ORDER",
                        help="charge every new order the exchange accepts this much, filled or not, in the data's price units "
                        "(default: the format's ENGINE, else 0)")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="override a bot global, e.g. --set PARAMS.KELP.make_edge=2 (repeatable)",
    )


def add_rival_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vs",
        dest="rivals",
        type=Path,
        action="append",
        default=[],
        metavar="BOT",
        help="another bot trading in the same market: it competes for the same fills and can trade with yours. "
        "Repeatable; give a file twice for two copies. --set only applies to your bot.",
    )
    parser.add_argument(
        "--requote",
        action="store_true",
        help="the rivals cancel all their resting orders before every tick, as bots written for orders that live one "
        "tick (Prosperity's) expect; use it with --resting",
    )


def add_engine_argument(parser: argparse.ArgumentParser, help: str | None = None) -> None:
    """--engine, and --allow-stale for a Rust twin checked against older Python code (python/arena/rust.py `prepare`)."""
    parser.add_argument("--engine", choices=["python", "rust"], default="python",
                        help=help or "run the backtests on our engine, or on its Rust port (rust/: needs cargo, and bots with a Rust twin, "
                        "rust/twins.json), with the same results: a backtest about 130 times faster on one core, a whole grid 40-80 times (default: python)")
    parser.add_argument("--allow-stale", action="store_true",
                        help="with --engine rust, run even if a twin's Python code changed since its Rust port was checked: Rust then "
                        "runs the old code (default: refuse)")


# The engine flags a format's ENGINE can set; a flag left out keeps the format's value (format_config).
CONFIG_FLAGS = ("trade_matching", "queue", "queue_power", "fill_ratio", "seed", "mark", "limit_penalty", "delay", "fee", "fee_bps",
                "maker_fee", "maker_fee_bps", "order_fee", "print_share", "deplete", "max_orders", "max_actions", "max_resting")
_ENUMS = {"trade_matching": TradeMatching, "queue": QueueModel, "mark": Mark}


def credits_per_unit(format_name: str, days) -> float:
    """What one engine price unit is worth in the portal's credits a lot: the data's unit (Day.info's, where
    every product has the same, an error if they differ; 1 if none says) times the format's CREDITS, the credits a lot one unit of its quoted
    prices is worth (a contract multiplier: the 2026-10-30 rehearsal's points were worth 2; 1 if it sets none)."""
    units = {(info or {}).get("unit") for day in days for info in day.info.values()} - {None}
    if len(units) > 1:  # one CREDITS can't convert them all (the audit's round 8, R18j)
        raise ValueError(f"the products carry different price units ({', '.join(map(str, sorted(units)))}): give every product "
                         "the same unit in the loader (ON_THE_DAY.md, \"The format swap, step by step\", step 1)")
    return (units.pop() if units else 1.0) * getattr(FORMATS[format_name], "CREDITS", 1.0)


def format_config(format_name: str, **changes) -> EngineConfig:
    """The engine settings a format's rules fix (its RESTING and ENGINE), with `changes` on top: what every tool
    starts from, so a backtest of their data runs under their rules without a flag for each. Prosperity's: the
    EngineConfig defaults."""
    fmt = FORMATS[format_name]
    engine = dict(getattr(fmt, "ENGINE", {}))
    known = {f.name for f in fields(EngineConfig)}
    unknown = sorted(set(engine) - known)
    if unknown:
        raise ValueError(f"{format_name}.ENGINE names no engine setting: {', '.join(unknown)} (EngineConfig's fields: {', '.join(sorted(known))})")
    base = {name: _ENUMS[name](value) if name in _ENUMS else value for name, value in engine.items()}
    base.setdefault("resting", bool(getattr(fmt, "RESTING", False)))  # a format whose orders rest runs that way
    return replace(EngineConfig(**base), **changes)


# What the experiments vary as their modes; every other field of a format's ENGINE is the rules' (under_rules).
VARIED = ("trade_matching", "resting", "delay")


def under_rules(config: EngineConfig, format_name: str) -> EngineConfig:
    """An experiment's config under the format's rules: each field the format's ENGINE sets, other than the
    matching, resting and delay the experiments vary as their modes, replaces the config's where the config
    leaves it at EngineConfig's default. So `experiments.day.premise` on their data pays their fees and is
    marked as their rules say, while its own modes stay its own (Prosperity's ENGINE is empty: no change)."""
    engine, default = getattr(FORMATS[format_name], "ENGINE", {}), EngineConfig()
    rules = format_config(format_name)
    changes = {name: getattr(rules, name) for name in engine if name not in VARIED and getattr(config, name) == getattr(default, name)}
    return replace(config, **changes)


def describe(config: EngineConfig) -> str:
    """The fields a config sets away from EngineConfig's defaults, for a table's header ("Prosperity's" if none)."""
    value = lambda v: v.value if hasattr(v, "value") else v
    changed = [f"{f.name} {value(getattr(config, f.name))}" for f in fields(EngineConfig) if getattr(config, f.name) != getattr(EngineConfig(), f.name)]
    return ", ".join(changed) or "Prosperity's"

def setup(args: argparse.Namespace) -> Setup:
    fmt = FORMATS[args.format]
    days = fmt.load_days(fmt.resolve_data_dir(args.data), args.days)
    flags = {name: getattr(args, "match_trades" if name == "trade_matching" else name) for name in CONFIG_FLAGS}
    config = format_config(args.format, **{name: value for name, value in flags.items() if value is not None})
    if args.resting:
        config = replace(config, resting=True)
    if config.delay < 0:
        raise ValueError("--delay needs 0 or more ticks")
    for name in ("max_orders", "max_actions", "max_resting"):
        if getattr(config, name) is not None and getattr(config, name) < 0:
            raise ValueError(f"--{name.replace('_', '-')} needs 0 or more")
    if not 0 < config.print_share <= 1:
        raise ValueError("--print-share needs a share above 0 and at most 1")
    if config.fee < 0 or config.fee_bps < 0 or config.order_fee < 0:
        raise ValueError("--fee, --fee-bps and --order-fee need 0 or more (a maker's rebate is a negative --maker-fee or --maker-fee-bps)")
    overrides = dict(parse_override(text) for text in args.overrides)
    return Setup(fmt, days, config, overrides, getattr(args, "rivals", []), getattr(args, "requote", False), getattr(args, "engine", "python"))


def participant_names(bot: Path, rivals: list) -> list[str]:
    """File stems, numbered from the second copy on: template, template#2, other. A rival is a path or
    an arena.scenario.Rival (a file with overrides)."""
    seen: Counter[str] = Counter()
    names = []
    for path in [bot, *(getattr(r, "path", r) for r in rivals)]:
        seen[path.stem] += 1
        names.append(path.stem if seen[path.stem] == 1 else f"{path.stem}#{seen[path.stem]}")
    return names


def participants(bot: Path, overrides: dict[str, object], rivals: list[Path], requote: bool = False) -> list[tuple[str, Path, dict, bool]]:
    """(name, file, overrides, requote) for the bot and its rivals, as python/arena/rust.py takes them."""
    names = participant_names(bot, rivals)
    return [(names[0], bot, overrides, False)] + [(name, path, {}, requote) for name, path in zip(names[1:], rivals)]


def backtest_days(data: str, specs: list[str], engine: str = "python", format_name: str = "prosperity") -> list:
    """The days the specs select, for backtests through `backtest` only: Python Days, or with engine
    "rust" and Prosperity data, references to their CSVs that Rust reads itself (nothing loaded here).
    A day in another format is loaded here, and Rust gets it exported once per process."""
    fmt = FORMATS[format_name]
    if engine == "rust" and format_name == "prosperity":
        from arena import rust

        return rust.prosperity_days(data, specs)
    return fmt.load_days(fmt.resolve_data_dir(data), specs)


def backtest(day: Day, bots: list[tuple[str, Path, dict, bool]], config: EngineConfig, engine: str = "python", strict: bool = False,
             fields: tuple[str, ...] | None = None, format_name: str = "prosperity", rules: bool = True) -> list[DayResult]:
    """The (name, bot file, overrides, requote) participants in one market on one day, in the format
    (Prosperity's by default), on either engine, under the format's rules (under_rules): each one's DayResult. With engine "rust" the day may
    be a day file (arena.rust.sim_day_file), `fields` limits what is read back, and `strict` is moot
    (a Rust twin can't raise from a bug)."""
    config = under_rules(config, format_name) if rules else config  # rules=False: the config exactly (experiments.day.calibrate)
    if engine == "rust":
        from arena import rust

        return rust.backtest(day, bots, config, fields)
    fmt = FORMATS[format_name]
    loaded = [(name, fmt.load_bot(path, overrides, strict)) for name, path, overrides, _ in bots]
    return run_market(day, [(name, Requote(bot) if requote else bot) for (name, bot), (*_, requote) in zip(loaded, bots)], config)


# ---------------------------------------------------------------------------- the day's data, for the experiments

TEMPLATE = Path("python/bots/template.py")
TEMPLATES = {"prosperity": TEMPLATE, "drill": Path("python/bots/drill/template.py"),
             "qminers": Path("python/bots/qminers/template.py")}  # the default --bot per format


def add_dataset_arguments(parser: argparse.ArgumentParser, products: bool = True, bot: bool = True) -> None:
    """--data, --days, --format, --bot and --products: one dataset in place of an experiment's
    built-in Prosperity ones, so it runs on the day's download (dataset_from reads them). Without
    --data the experiment runs as it always has, so the results it gave stay reproducible."""
    group = parser.add_argument_group("the day's data", "one dataset in place of the experiment's built-in Prosperity ones, "
                                      "e.g. --data data/arena --days 1 2 --format qminers --bot python/bots/qminers/template.py")
    group.add_argument("--data", help="a data folder, or p2 / p3 / p4")
    group.add_argument("--days", nargs="+", help="day specs as arena.backtest takes them (required with --data), e.g. 1 2, or all for drill sessions")
    group.add_argument("--format", default="prosperity", choices=sorted(FORMATS), help="the data's format (default: prosperity)")
    if bot:
        group.add_argument("--bot", type=Path, help="the template file to run, written for that format (default: "
                           + ", ".join(f"{path} for {name}" for name, path in TEMPLATES.items()) + ")")
    if products:
        group.add_argument("--products", help="comma-separated products to study (default: every product in the data"
                           + (" that the bot's PARAMS lists)" if bot else ")"))


@dataclass(frozen=True)
class Dataset:
    """The dataset add_dataset_arguments names: where it is, which days, its format, the bot and the products."""

    name: str  # as the experiment's tables show it
    data: str
    days: tuple[str, ...]
    format: str = "prosperity"
    bot: str = str(TEMPLATE)
    products: tuple[str, ...] = ()


def dataset_from(args: argparse.Namespace) -> Dataset | None:
    """The dataset the arguments name, or None when there is no --data (the experiment's own). A
    ValueError for options that need --data, or --data without --days."""
    bot = getattr(args, "bot", None)
    if args.data is None:
        if args.format != "prosperity" or bot is not None or args.days or getattr(args, "products", None):
            raise ValueError("--days, --format, --bot and --products choose the day's data: give --data too")
        return None
    if not args.days:
        raise ValueError("--data needs --days, e.g. --days 1 2 (Prosperity rounds) or --days all (drill sessions)")
    fmt = FORMATS[args.format]
    bot = str(bot or TEMPLATES.get(args.format, TEMPLATE))
    if getattr(args, "products", None):
        products = tuple(p.strip() for p in args.products.split(",") if p.strip())
    else:
        days = fmt.load_days(fmt.resolve_data_dir(args.data), list(args.days))
        products = sorted({p for day in days for p in day.products})
        if hasattr(args, "bot"):
            listed = bot_params(bot, args.format)
            products = [p for p in products if p in listed]
        products = tuple(products)
    return Dataset(f"{Path(args.data).name or args.data} {' '.join(args.days)}", args.data, tuple(args.days), args.format, bot, products)


def bot_module(path: str | Path, format_name: str):
    """The bot file loaded as a module under its format (with that format's provided modules)."""
    FORMATS[format_name].load_bot(Path(path), {}, strict=False)
    return sys.modules[f"arena_bot_{Path(path).stem}"]  # BotFile.load registers the module under this name


def bot_params(path: str | Path, format_name: str) -> dict:
    """The bot file's PARAMS, as it loads under its format ({} if it has none)."""
    params = getattr(bot_module(path, format_name), "PARAMS", None)
    return params if isinstance(params, dict) else {}


def run_with_rivals(
    fmt,
    day: Day,
    bot: Path,
    overrides: dict[str, object],
    rivals: list,
    config: EngineConfig,
    strict: bool = True,
    requote: bool = False,
) -> list[DayResult]:
    """Runs the bot, plus any rivals in the same market (paths, or arena.scenario.Rivals with their
    overrides). The bot's result comes first."""
    others = [fmt.load_bot(getattr(rival, "path", rival), getattr(rival, "overrides", {}), strict) for rival in rivals]
    if requote:
        others = [Requote(other) for other in others]
    bots = [fmt.load_bot(bot, overrides, strict), *others]
    return run_market(day, list(zip(participant_names(bot, rivals), bots)), config)


class Requote:
    """Cancels all of a bot's resting orders before each tick, and hides them from it.

    Bots written for orders that live one tick (Prosperity's) never cancel: under --resting their
    orders pile up until the limit check rejects everything. Wrapped, each tick's orders replace
    the last tick's, which is how they were meant to run, though they keep their queue place only
    for that tick.
    """

    def __init__(self, bot):
        self.bot = bot

    def step(self, tick, positions, own_fills, market_trades, open_orders):
        actions = self.bot.step(tick, positions, own_fills, market_trades, [])
        return [Cancel(order.id) for order in open_orders] + [a for a in actions if not isinstance(a, Cancel)]
