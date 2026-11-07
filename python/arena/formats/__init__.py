"""Competition formats: the only code that knows a competition's data files and bot API.

Each format module provides:

    PROVIDED_MODULES: set[str]
        Modules the competition makes importable for bots (e.g. "datamodel").
    resolve_data_dir(arg: str) -> Path
        Turns the --data argument into a folder.
    load_days(data_dir: Path, specs: list[str]) -> list[Day]
        Loads the requested days into engine types.
    load_bot(path, overrides, strict, fresh_each_tick=False) -> engine.Bot
        Wraps a bot file so the engine can call it. With fresh_each_tick the bot file is
        reloaded every tick, which shows whether it keeps state outside the competition's
        official state mechanism.
    check_source(tree: ast.Module) -> list[str]
        Problems with the bot's entry point (empty list if fine).

Optional:

    RESTING: bool
        True if the competition's orders rest until cancelled; the tools then run as with
        --resting.
    ENGINE: dict[str, object]
        The engine settings the competition's rules fix, as EngineConfig fields: e.g.
        {"queue": "prob", "fee": 1, "maker_fee": 0, "mark": "touch", "trade_matching": "worse"}.
        Every tool starts from them (arena.cli.format_config); a flag given on the command line
        overrides its field. Without it, Prosperity's settings (EngineConfig's defaults).
    CREDITS: float
        The credits a lot one unit of the competition's quoted prices is worth, where it isn't 1 (a
        contract multiplier: points worth 2 credits a lot). experiments.day.calibrate and --metrics turn
        the engine's figures into the portal's credits with it (arena.cli.credits_per_unit). A fee or
        penalty the rules give in credits goes into ENGINE divided by it: ENGINE's are in price units.

    REPLAY: bool
        False for a format with no loader here (its resolve_data_dir, load_days and load_bot raise):
        arena.validate then runs the file and static checks only, without --data.

The Arena's format is qminers.py, registered as `--format qminers`: since 7 Nov only its source checks
(check_source, PROVIDED_MODULES, SANDBOX; REPLAY = False), as the Arena's bots run on the organisers'
simulator. The other skeletons stay as shapes for a format that needs our engine: snapshots.py (book
snapshots in CSV, a bot answering a state with orders), orderlog.py (an order-by-order event log, with
the drill's bot API) or drill.py (book changes, a callback API, decimal prices, orders that rest).
"""

from types import ModuleType

from arena.formats import drill, orderlog, prosperity, qminers, snapshots

FORMATS: dict[str, ModuleType] = {"prosperity": prosperity, "drill": drill, "snapshots": snapshots, "orderlog": orderlog,
                              "qminers": qminers}
