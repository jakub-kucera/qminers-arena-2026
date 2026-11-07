"""Fill-model scenarios: the ways the real market might fill our orders, which arena.grid and
arena.compare score every cell or bot under.

    --scenario NAME:match=worse,resting,queue=front,power=2,fill=0.7,seed=1,mark=touch,penalty=5,delay=1,fee=0.5,bps=2,mbps=-1,vs=FILE@PATH=VALUE

Each item changes one engine setting from the run's own (`--match-trades`, `--resting`, `--queue`,
`--queue-power`, `--fill-ratio`, `--seed`, `--mark`, `--limit-penalty`, `--delay`, `--fee`, `--fee-bps`, and `mfee`, `mbps` for
`--maker-fee`, `--maker-fee-bps`, `deplete` for `--deplete` and `cap` for `--max-orders`); `resting=no` (and `deplete=no`)
turns it off. `vs=` (repeatable) gives
the scenario its own rivals in place of `--vs`, each a file or a variant FILE@PATH=VALUE@... as
arena.compare takes them; `vs=none` runs it with none. A value can't hold a comma. Without NAME the
scenario is named by its items. `--modes all,worse` are the plain scenarios, named by their mode,
so the tables print as they did; with any other scenario the summaries add the worst case over
them all (`worst`), the measure IDEAS.md's "Choosing a cell by its worst case over fill-model
scenarios" tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from arena.botfile import parse_override
from arena.engine import EngineConfig, Mark, QueueModel, TradeMatching


@dataclass(frozen=True)
class Rival:
    """A rival bot file, with `--set`-style overrides from FILE@PATH=VALUE@..."""

    path: Path
    overrides: dict = field(default_factory=dict, compare=False, hash=False)
    text: str = ""  # as given: what tells two rivals apart

    def __str__(self) -> str:
        return self.text or str(self.path)


def parse_rival(text: str) -> Rival:
    path, *settings = text.split("@")
    if not Path(path).is_file():
        raise ValueError(f"no rival bot file {path!r}")
    return Rival(Path(path), dict(parse_override(s) for s in settings), text)


@dataclass(frozen=True)
class Scenario:
    name: str
    trade_matching: TradeMatching | None = None
    resting: bool | None = None
    queue: QueueModel | None = None
    queue_power: float | None = None
    fill_ratio: float | None = None
    seed: int | None = None
    rivals: tuple[Rival, ...] | None = None  # None: the run's --vs
    mark: Mark | None = None
    limit_penalty: float | None = None
    delay: int | None = None  # ticks between decision and exchange
    fee: float | None = None  # per lot filled
    fee_bps: float | None = None  # basis points of a fill's value
    maker_fee: float | None = None  # a passive fill's, instead (negative: a rebate)
    maker_fee_bps: float | None = None
    deplete: bool | None = None  # what we take from the recorded book stays gone
    max_orders: int | None = None  # new orders a bot may send a tick
    max_actions: int | None = None  # orders and cancels a bot may send a tick
    max_resting: int | None = None  # orders a product may have working at once
    order_fee: float | None = None  # per new order accepted
    print_share: float | None = None  # the share of each market trade our orders may take

    def __str__(self) -> str:
        return self.name

    def __format__(self, spec: str) -> str:
        return format(self.name, spec)

    @property
    def value(self) -> str:  # as a TradeMatching's: the tables name a mode by it
        return self.name

    @property
    def plain(self) -> bool:
        """Only a trade-matching mode, named by it: what --modes makes."""
        return self == Scenario(self.name, self.trade_matching) and self.trade_matching is not None and self.name == self.trade_matching.value

    def config(self, base: EngineConfig) -> EngineConfig:
        changed = {name: getattr(self, name) for name in ("trade_matching", "resting", "queue", "queue_power", "fill_ratio", "seed", "mark", "limit_penalty", "delay", "fee", "fee_bps", "maker_fee", "maker_fee_bps", "deplete", "max_orders", "max_actions", "max_resting", "order_fee", "print_share")}
        return replace(base, **{name: value for name, value in changed.items() if value is not None})


def plain(mode: TradeMatching) -> Scenario:
    return Scenario(mode.value, mode)


def config_for(base: EngineConfig, mode: Scenario | TradeMatching) -> EngineConfig:
    """The engine config a mode runs under: a scenario's settings, or a trade-matching mode alone."""
    return mode.config(base) if isinstance(mode, Scenario) else replace(base, trade_matching=mode)


def rivals_for(default: list, mode: Scenario | TradeMatching) -> list:
    """The rivals a mode runs against: a scenario's own, or the run's --vs."""
    return list(mode.rivals) if isinstance(mode, Scenario) and mode.rivals is not None else list(default)


KEYS = {"match", "resting", "queue", "power", "fill", "seed", "mark", "penalty", "vs", "delay", "fee", "bps", "mfee", "mbps", "deplete", "cap", "acap", "rcap", "ofee", "share"}


def parse_scenario(text: str) -> Scenario:
    name, sep, items = text.partition(":")
    if not sep:
        name, items = text, text
    if not name or not items:
        raise ValueError(f"--scenario {text!r}: expected NAME:ITEM,ITEM,... (e.g. tight:match=worse,resting,queue=back,fill=0.7)")
    found: dict = {}
    rivals: list[Rival] | None = None
    for item in items.split(","):
        key, has_value, value = item.strip().partition("=")
        if key not in KEYS:
            raise ValueError(f"--scenario {name}: unknown item {key!r} (known: {', '.join(sorted(KEYS))})")
        if key == "vs":
            rivals = rivals or []
            if value != "none":
                rivals.append(parse_rival(value))
            continue
        if key in found:
            raise ValueError(f"--scenario {name}: {key} given twice")
        try:
            if key in ("resting", "deplete"):
                if value not in ("", "yes", "no"):
                    raise ValueError
                found[key] = value != "no"
            elif not has_value:
                raise ValueError
            elif key == "match":
                found[key] = TradeMatching(value)
            elif key == "queue":
                found[key] = QueueModel(value)
            elif key in ("seed", "delay", "cap", "acap", "rcap"):
                found[key] = int(value)
                if key in ("delay", "cap", "acap", "rcap") and found[key] < 0:
                    raise ValueError
            elif key == "mark":
                found[key] = Mark(value)
            elif key in ("penalty", "fee", "bps", "ofee"):
                found[key] = float(value)
                if found[key] < 0:
                    raise ValueError
            else:
                found[key] = float(value)
        except ValueError:
            raise ValueError(f"--scenario {name}: bad {item.strip()!r}") from None
    if found.get("fill", 1.0) <= 0 or found.get("fill", 1.0) > 1:
        raise ValueError(f"--scenario {name}: fill must be in (0, 1]")
    if found.get("share", 1.0) <= 0 or found.get("share", 1.0) > 1:
        raise ValueError(f"--scenario {name}: share must be in (0, 1]")
    return Scenario(name, found.get("match"), found.get("resting"), found.get("queue"), found.get("power"), found.get("fill"), found.get("seed"),
                    None if rivals is None else tuple(rivals), found.get("mark"), found.get("penalty"), found.get("delay"),
                    found.get("fee"), found.get("bps"), found.get("mfee"), found.get("mbps"), found.get("deplete"), found.get("cap"),
                    found.get("acap"), found.get("rcap"), found.get("ofee"), found.get("share"))


def add_scenario_argument(parser) -> None:
    parser.add_argument("--scenario", dest="scenarios", action="append", default=[], metavar="NAME:ITEM,...",
                        help="score every run under this fill model too, after the --modes: match=all|worse|none, resting[=no], "
                        "queue=back|prob|front, power=N, fill=RATIO, seed=N, mark=mid|touch|last, penalty=RATE, delay=TICKS, fee=PER_LOT, bps=BPS, mfee=PER_LOT, mbps=BPS (a maker's, negative a rebate), ofee=PER_ORDER, share=SHARE (of each print), deplete[=no], cap=N (new orders a tick), acap=N (orders and cancels a tick), rcap=N (orders working a product), vs=FILE[@PATH=VALUE...] (repeatable; vs=none for no rivals). "
                        "Repeatable; with one, the summary adds the worst case over all of them (python/arena/scenario.py)")


def scenarios_from(modes_text: str | None, scenario_texts: list[str], default: TradeMatching) -> list[Scenario]:
    """--modes as plain scenarios (without it, the run's --match-trades), then each --scenario."""
    modes = [TradeMatching(m.strip()) for m in modes_text.split(",")] if modes_text else [default]
    found = [plain(m) for m in modes] + [parse_scenario(text) for text in scenario_texts]
    names = [s.name for s in found]
    if len(set(names)) != len(names):
        raise ValueError("--modes and --scenario name a scenario twice: " + ", ".join(sorted({n for n in names if names.count(n) > 1})))
    return found


def every_rival(default: list, scenarios: list) -> list[Path]:
    """Every rival file a run loads, for the Rust twin check."""
    paths = [getattr(r, "path", r) for r in default]
    for s in scenarios:
        if isinstance(s, Scenario) and s.rivals:
            paths += [r.path for r in s.rivals]
    return list(dict.fromkeys(paths))
