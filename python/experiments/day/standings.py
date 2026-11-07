"""A standings calculator for the last round: our rank distribution after it, under each way the
rounds may combine, for each scale of our bot's risk, and the relative hedge that best keeps our place.

usage (from the repo root):
  uv run python -m experiments.day.standings --rounds data/arena/round1/leaderboard.json data/arena/round2/leaderboard.json \\
      data/arena/round3/leaderboard.json --team NAME --ours results/grid.csv [--where PARAMS.P.KEY=V] [--days-per-round N]
  uv run python -m experiments.day.standings --synthetic     # a synthetic field (IDEAS.md, "A standings calculator for round 4")

Qminers' 2024 winner simulated the final against rivals with weaker, correlated models, picked the
stake with the most first places, and halved it in the last round while far ahead
(references/wiki/concepts/risk-and-protecting-a-lead.md). This does that from the leaderboards.

Inputs:
  --rounds   each round's leaderboard as the page receives it (experiments.day.leaderboard_curves'
             layout: rank, teamName, isTie, pnl, pnlSeries of elapsedS and pnl), rounds 1..R in order.
  --team     our team's name on them.
  --ours     our PnL distribution in round R+1, from backtests on its data: numbers (1200,1500,...),
             a file of numbers, or an arena.grid --out CSV (its per-day PnL under the first mode, of
             the row --where picks, else the best by that mode's PnL). Its mean and sd, times
             --days-per-round (sum of that many days), are our round's PnL at risk multiplier 1.

The next round, simulated --sims times (seeded):
  - every other team's PnL is median + sd × (ρ·skill + √(1−ρ²)·(√c·b·F + √(1−c·b²)·e)), with the
    median and sd of the last round's PnL (× --growth), skill the team's mean z-score over the rounds
    so far (standardised), ρ how well the earlier rounds' mean predicted the last round's (the
    persistence), F the field's bet (one draw a simulation, shared by every team) and e the team's own
    luck. c, the field's bet's share of a team's variance, and b, each team's loading on it (mean 1),
    are read from the last round's curves: the field's bet is the mean of the teams' PnL changes,
    b a team's regression on it, c its variance over the mean team's (no curves: c 0, b 1).
  - ours is k^p × mean + k × sd × η + (h + our loading) × the field's bet's PnL for a team of
    loading 1 + h × --hedge-edge: k is the risk multiplier (make_size, stop_loss, bets on or off),
    scaling the mean and sd together unless --mean-power p is below 1 (a larger size that fills less
    per lot, a bet with a thin edge), h the relative hedge, the share of the field's bet we hold although we
    don't trade it for its own sake (Frankfurt Hedgehogs kept mean-reversion exposure they no longer
    believed in because several top teams traded only that; ON_THE_DAY.md, "How is PnL scored?").

The rounds combine in four ways, since the Technical Rules aren't out: PnL summed; PnL weighted
(--weights, the site's unconfirmed 10/20/30/40%); and each round's PnL over the round's largest
|PnL| (a score that doesn't let the biggest round's scale decide), weighted and equal. For each:
our rank now, then after the next round for each k (the hedge at 0) and each h (at --k), as the
mean rank, the chance of 1st, of the top 3, and of losing a place (a worse rank than now).
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from experiments.day import leaderboard_curves as lc

WEIGHTS = (0.1, 0.2, 0.3, 0.4)  # the site's unconfirmed round weights (ON_THE_DAY.md, "Known so far")
MULTIPLIERS = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5)
HEDGES = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5)
SIMS = 5000
MAX_PERSISTENCE = 0.95
SYNTHETIC_DAYS = (20_000.0, 30_000.0, 35_000.0, 40_000.0, 50_000.0)  # --synthetic's ours: mean 35k, sd 11k, near the field's top in round 3


# ---------------------------------------------------------------------------- the rounds so far


@dataclass
class Board:
    teams: list[str]
    pnl: list[list[float]]  # [round][team], 0 for a team missing from a round
    curves: list[dict[str, list[float]]]  # per round, the aligned PnL curves (leaderboard_curves.aligned)


def load_rounds(paths: list[Path]) -> Board:
    rounds = [lc.load_leaderboard(path) for path in paths]
    return board_of(rounds)


def board_of(rounds: list[list[lc.Team]]) -> Board:
    names: list[str] = []
    for teams in rounds:
        for team in teams:
            if team.name not in names:
                names.append(team.name)
    pnl = []
    for teams in rounds:
        by = {team.name: team.pnl for team in teams}
        pnl.append([by.get(name, 0.0) for name in names])
    curves = [lc.aligned([t for t in teams if t.series]) for teams in rounds]
    return Board(names, pnl, curves)


# ---------------------------------------------------------------------------- the scorings


@dataclass(frozen=True)
class Scoring:
    name: str
    weights: tuple[float, ...]  # one per round, the next one's last
    normalise: bool  # each round's PnL over the round's largest |PnL|


def scorings(weights: tuple[float, ...]) -> list[Scoring]:
    shown = "/".join(f"{w * 100:g}" for w in weights)
    ones = tuple(1.0 for _ in weights)
    return [Scoring("pnl summed", ones, False), Scoring(f"pnl {shown}", weights, False),
            Scoring(f"score {shown}", weights, True), Scoring("score equal", ones, True)]


def round_score(values: list[float], normalise: bool) -> list[float]:
    if not normalise:
        return list(values)
    top = max((abs(v) for v in values), default=0.0)
    return [v / top for v in values] if top > 0 else [0.0 for _ in values]


def totals(board: Board, scoring: Scoring) -> list[float]:
    """Each team's total over the rounds so far under the scoring."""
    out = [0.0] * len(board.teams)
    for r, values in enumerate(board.pnl):
        for i, s in enumerate(round_score(values, scoring.normalise)):
            out[i] += scoring.weights[r] * s
    return out


def rank_of(values: list[float], i: int) -> int:
    """1 + the teams strictly ahead of team i."""
    return 1 + sum(v > values[i] for k, v in enumerate(values) if k != i)


# ---------------------------------------------------------------------------- the next round's field


@dataclass
class Field:
    median: float
    sd: float
    persistence: float
    common: float  # the field's bet's share of a team's variance
    skill: list[float]  # per team, standardised mean z-score over the rounds
    loading: list[float]  # per team, its loading on the field's bet (mean 1)


def _z(values: list[float]) -> list[float]:
    sd = statistics.pstdev(values) if len(values) > 1 else 0.0
    mid = statistics.median(values)
    return [(v - mid) / sd if sd > 0 else 0.0 for v in values]


def _standardise(values: list[float]) -> list[float]:
    mean = statistics.fmean(values)
    sd = statistics.pstdev(values)
    return [(v - mean) / sd if sd > 0 else 0.0 for v in values]


def _correlation(x: list[float], y: list[float]) -> float:
    if len(x) < 3 or statistics.pstdev(x) == 0 or statistics.pstdev(y) == 0:
        return 0.0
    return statistics.correlation(x, y)


def proxy_growth(old: tuple[str, list[str]], new: tuple[str, list[str]], bots: list[Path], format_name: str = "prosperity",
                 engine: str = "python") -> float:
    """The next round's scale against the last's, from a proxy field: the spread (sd across the bots)
    of each bot's PnL alone, a day, on the new round's data over that on the last round's. The
    leaderboards can't show it, and it decides most of the next round's ranks (IDEAS.md, "A standings
    calculator for round 4"). old and new are (data, day specs)."""
    from arena.cli import backtest, backtest_days
    from arena.engine import EngineConfig

    def spread(data: str, specs: list[str]) -> float:
        per_day = []
        for day in backtest_days(data, specs, engine, format_name):
            pnl = []
            for path in bots:
                (result,) = backtest(day, [("bot", path, {}, False)], EngineConfig(), engine, fields=("pnl",), format_name=format_name)
                pnl.append(sum(series[-1] for series in result.pnl.values() if series))
            per_day.append(statistics.pstdev(pnl))
        return statistics.fmean(per_day)

    before = spread(*old)
    return spread(*new) / before if before > 0 else 1.0


def growth_spread(board: Board) -> float:
    """The sd of the log of the field's spread from one round to the next (0 with fewer than three rounds):
    how much a round's scale has changed, for --growth-sd."""
    sds = [statistics.pstdev(values) for values in board.pnl]
    logs = [math.log(b / a) for a, b in zip(sds, sds[1:]) if a > 0 and b > 0]
    return statistics.pstdev(logs) if len(logs) > 1 else 0.0


def persistence(board: Board) -> float:
    """How well the earlier rounds' mean z-score predicts the last round's: their correlation, in [0, MAX_PERSISTENCE]."""
    if len(board.pnl) < 2:
        return 0.0
    zs = [_z(values) for values in board.pnl]
    earlier = [statistics.fmean(z[i] for z in zs[:-1]) for i in range(len(board.teams))]
    return min(MAX_PERSISTENCE, max(0.0, _correlation(earlier, zs[-1])))


def field_bet(curves: dict[str, list[float]], teams: list[str]) -> tuple[float, list[float]]:
    """From one round's aligned curves: the field's bet's share of a team's variance, and each team's
    loading on it (mean 1 over the teams with curves; 1 for a team without one). The bet is the mean
    of the teams' PnL changes; a loading is a team's regression on it."""
    names = [t for t in teams if t in curves and len(curves[t]) > 2]
    if len(names) < 3:
        return 0.0, [1.0] * len(teams)
    changes = {t: [b - a for a, b in zip(curves[t], curves[t][1:])] for t in names}
    steps = len(next(iter(changes.values())))
    bet = [statistics.fmean(changes[t][s] for t in names) for s in range(steps)]
    var_bet = statistics.pvariance(bet)
    if var_bet <= 0:
        return 0.0, [1.0] * len(teams)
    mean_bet = statistics.fmean(bet)
    loading = {}
    for t in names:
        mean_t = statistics.fmean(changes[t])
        loading[t] = sum((x - mean_t) * (f - mean_bet) for x, f in zip(changes[t], bet)) / steps / var_bet
    common = min(1.0, var_bet / statistics.fmean(statistics.pvariance(changes[t]) for t in names))
    return common, [loading.get(t, 1.0) for t in teams]


def field_model(board: Board, growth: float = 1.0, rho: float | None = None, common: float | None = None) -> Field:
    last = board.pnl[-1]
    zs = [_z(values) for values in board.pnl]
    skill = _standardise([statistics.fmean(z[i] for z in zs) for i in range(len(board.teams))])
    measured, loading = field_bet(board.curves[-1], board.teams) if board.curves else (0.0, [1.0] * len(board.teams))
    return Field(statistics.median(last) * growth, statistics.pstdev(last) * growth, persistence(board) if rho is None else rho,
                 measured if common is None else common, skill, loading)


# ---------------------------------------------------------------------------- our distribution


def read_ours(text: str, where: list[str] | None = None) -> list[float]:
    """Our per-day PnL: numbers, a file of numbers, or an arena.grid --out CSV's per-day PnL under its first mode."""
    path = Path(text)
    if not path.exists():
        return [float(x) for x in text.replace(";", ",").split(",") if x.strip()]
    head = path.read_text().splitlines()[:1]
    if head and "pnl_" in head[0]:
        return grid_days(path, where or [])
    return [float(x) for x in path.read_text().replace(",", " ").split()]


def grid_days(path: Path, where: list[str]) -> list[float]:
    """The per-day PnL under the first mode of the grid CSV's row that `where` (PATH=VALUE, all of them)
    picks, else of its best row by that mode's PnL. The day columns are the first pnl_<mode>_* columns
    after nbhd_<mode> whose sum is the mode's PnL on every row (the product columns follow them)."""
    rows = list(csv.DictReader(path.open()))
    columns = list(rows[0])
    total = next(c for c in columns if c.startswith("pnl_") and c.count("_") == 1)
    mode = total.removeprefix("pnl_")
    start = columns.index(f"nbhd_{mode}") + 1
    run = []
    for c in columns[start:]:
        if not c.startswith(f"pnl_{mode}_"):
            break
        run.append(c)
    days = next((run[:n] for n in range(1, len(run) + 1)
                 if all(abs(sum(float(row[c]) for c in run[:n]) - float(row[total])) <= 1e-6 * max(1.0, abs(float(row[total]))) for row in rows)), None)
    if not days:
        raise ValueError(f"{path}: no per-day columns under {mode} add up to {total}")
    picked = rows
    for condition in where:
        key, _, value = condition.partition("=")
        if key not in columns:
            raise ValueError(f"{path}: no column {key!r}")
        picked = [row for row in picked if row[key] == value]
    if not picked:
        raise ValueError(f"{path}: no row with {' and '.join(where)}")
    row = max(picked, key=lambda r: float(r[total]))
    return [float(row[c]) for c in days]


def our_round(days: list[float], days_per_round: int) -> tuple[float, float]:
    """Our round's PnL at multiplier 1: the mean and sd of the sum of `days_per_round` days."""
    mean = statistics.fmean(days)
    sd = statistics.stdev(days) if len(days) > 1 else 0.0
    return mean * days_per_round, sd * math.sqrt(days_per_round)


# ---------------------------------------------------------------------------- the simulation


@dataclass
class Tally:
    sims: int = 0
    rank_sum: float = 0.0
    first: int = 0
    top3: int = 0
    lost: int = 0  # a worse rank than now

    def add(self, rank: int, now: int) -> None:
        self.sims += 1
        self.rank_sum += rank
        self.first += rank == 1
        self.top3 += rank <= 3
        self.lost += rank > now

    @property
    def mean_rank(self) -> float:
        return self.rank_sum / self.sims

    def share(self, n: int) -> float:
        return n / self.sims


@dataclass
class Result:
    scorings: list[Scoring]
    now: dict[str, int]  # our rank now under each scoring
    gap: dict[str, tuple[float, float]]  # our lead over the next team and our gap to the one ahead (0 if none)
    risk: dict[tuple[str, float], Tally]  # (scoring, k) with the hedge at 0
    hedge: dict[tuple[str, float], Tally]  # (scoring, h) at multiplier `k`
    k: float


def simulate(board: Board, us: int, ours: tuple[float, float], field: Field, weights: tuple[float, ...], multipliers=MULTIPLIERS,
             hedges=HEDGES, k: float = 1.0, hedge_edge: float = 0.0, our_loading: float = 0.0, sims: int = SIMS, seed: int = 0,
             mean_power: float = 1.0, growth_sd: float = 0.0) -> Result:
    """Our rank now and after the next round, per scoring, for each multiplier (hedge 0) and each hedge (at
    multiplier k). A multiplier m scales our mean by m ** mean_power and our sd by m. With growth_sd, the
    other teams' PnL is scaled each simulation by exp(N(0, growth_sd)): a next round bigger or smaller
    than the last, which our own distribution (backtests on the next round's data) already knows."""
    rounds = len(board.pnl)
    if len(weights) < rounds + 1:
        raise ValueError(f"{rounds} rounds so far need {rounds + 1} weights, not {len(weights)}")
    chosen = scorings(tuple(weights[: rounds + 1]))
    past = {s.name: totals(board, s) for s in chosen}
    now = {s.name: rank_of(past[s.name], us) for s in chosen}
    gap = {}
    for s in chosen:
        others = sorted((v for i, v in enumerate(past[s.name]) if i != us), reverse=True)
        mine = past[s.name][us]
        behind = [v for v in others if v <= mine]
        ahead = [v for v in others if v > mine]
        gap[s.name] = (mine - behind[0] if behind else 0.0, ahead[-1] - mine if ahead else 0.0)
    rng = random.Random(seed)
    others = [i for i in range(len(board.teams)) if i != us]
    rho, c = field.persistence, field.common
    luck = math.sqrt(1 - rho**2)
    own = [math.sqrt(max(0.0, 1 - c * field.loading[i] ** 2)) for i in others]
    mean, sd = ours
    risk = {(s.name, m): Tally() for s in chosen for m in multipliers}
    hedged = {(s.name, h): Tally() for s in chosen for h in hedges}
    configs = [("risk", m, m, 0.0) for m in multipliers] + [("hedge", h, k, h) for h in hedges]
    w_next = {s.name: s.weights[rounds] for s in chosen}
    for _ in range(sims):
        bet = rng.gauss(0, 1)
        scale = math.exp(rng.gauss(0, growth_sd)) if growth_sd else 1.0
        x = [scale * (field.median + field.sd * (rho * field.skill[i] + luck * (math.sqrt(c) * field.loading[i] * bet + e * rng.gauss(0, 1))))
             for i, e in zip(others, own)]
        bet_pnl = scale * field.sd * luck * math.sqrt(c) * bet  # what the field's bet makes for a team of loading 1
        eta = rng.gauss(0, 1)
        top = max((abs(v) for v in x), default=0.0)
        fixed = {}
        for s in chosen:
            denominator = top if s.normalise else 1.0
            fixed[s.name] = sorted(past[s.name][i] + w_next[s.name] * (v / denominator if denominator > 0 else 0.0)
                                   for i, v in zip(others, x))
        for kind, key, mult, h in configs:
            y = mult**mean_power * mean + mult * sd * eta + (h + our_loading) * bet_pnl + h * hedge_edge
            for s in chosen:
                if s.normalise and abs(y) > top:  # we set the round's scale: everyone's score moves
                    theirs = sorted(past[s.name][i] + w_next[s.name] * v / abs(y) for i, v in zip(others, x))
                    mine = past[s.name][us] + w_next[s.name] * y / abs(y)
                else:
                    theirs = fixed[s.name]
                    mine = past[s.name][us] + w_next[s.name] * (y / top if s.normalise and top > 0 else (0.0 if s.normalise else y))
                rank = 1 + len(theirs) - bisect.bisect_right(theirs, mine)
                (risk if kind == "risk" else hedged)[(s.name, key)].add(rank, now[s.name])
    return Result(chosen, now, gap, risk, hedged, k)


# ---------------------------------------------------------------------------- output


def _num(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.3g}"


def format_result(board: Board, us: int, ours: tuple[float, float], field: Field, result: Result) -> str:
    rounds, n = len(board.pnl), len(board.teams)
    lines = [f"{n} teams, {rounds} rounds so far; {board.teams[us]}'s PnL by round: " + " · ".join(_num(values[us]) for values in board.pnl)]
    for s in result.scorings:
        lead, behind = result.gap[s.name]
        where = f"lead {_num(lead)} over the next" if result.now[s.name] == 1 else f"{_num(behind)} behind the team ahead, {_num(lead)} ahead of the next"
        lines.append(f"  {s.name:<18} rank {result.now[s.name]} ({where})")
    lines.append(f"round {rounds + 1}'s field: median {_num(field.median)}, sd {_num(field.sd)} (round {rounds}'s); persistence {field.persistence:.2f}; "
                 f"the field's bet {field.common:.0%} of a team's variance, loadings {min(field.loading):.2f} to {max(field.loading):.2f}"
                 f" ({board.teams[us]}: {field.loading[us]:.2f})")
    lines.append(f"ours at multiplier 1: mean {_num(ours[0])}, sd {_num(ours[1])}")

    def table(title: str, tallies: dict, keys, label: str) -> list[str]:
        out = [title, f"  {'scoring':<18} {label:>5}  {'mean rank':>9}  {'1st':>5}  {'top 3':>5}  {'lose a place':>12}"]
        for s in result.scorings:
            for key in keys:
                t = tallies[(s.name, key)]
                out.append(f"  {s.name:<18} {key:>5g}  {t.mean_rank:>9.2f}  {t.share(t.first):>5.0%}  {t.share(t.top3):>5.0%}  {t.share(t.lost):>12.0%}")
            best_keep = min(keys, key=lambda q: (tallies[(s.name, q)].lost, -tallies[(s.name, q)].first))
            best_win = max(keys, key=lambda q: (tallies[(s.name, q)].first, -tallies[(s.name, q)].lost))
            out.append(f"  {'':<18} least chance of losing a place at {label} {best_keep:g}; most 1st places at {best_win:g}")
        return out

    multipliers = sorted({key for _, key in result.risk})
    hedges = sorted({key for _, key in result.hedge})
    lines += table(f"risk multiplier k on our PnL's mean and sd (the hedge at 0), {next(iter(result.risk.values())).sims:,} simulations:",
                   result.risk, multipliers, "k")
    lines += table(f"relative hedge h, the share of the field's bet held (k {result.k:g}):", result.hedge, hedges, "h")
    return "\n".join(lines)


# ---------------------------------------------------------------------------- a synthetic field


def synthetic_rounds(teams: int = 30, rounds: int = 3, seed: int = 0, common: float = 0.5, rho: float = 0.7,
                     scales: tuple[float, ...] = (5_000.0, 10_000.0, 20_000.0), lead: float = 2.5, steps: int = 200,
                     us: str = "us") -> list[list[dict]]:
    """Leaderboards in the page's layout for a field with persistent skill (correlation rho between a team's
    rounds), a field's bet with loadings 0, 1 or 2 (mean 1) that is `common` of a team's variance, and
    our team `us` with skill `lead` sds above the mean and no loading on the bet. Round r's median and
    sd are scales[r]; each curve has `steps` points."""
    rng = random.Random(seed)
    names = [us] + [f"team{k:02d}" for k in range(1, teams)]
    skill = [lead] + [rng.gauss(0, 1) for _ in range(teams - 1)]
    loading = [0.0] + [rng.choice((0.0, 1.0, 2.0)) for _ in range(teams - 1)]
    boards = []
    for r in range(rounds):
        scale = scales[min(r, len(scales) - 1)]
        bet = [rng.gauss(0, 1) / math.sqrt(steps) for _ in range(steps)]
        rows = []
        for name, z, b in zip(names, skill, loading):
            own = math.sqrt(max(0.0, 1 - common * b * b))
            drift = scale + scale * rho * z
            changes = [drift / steps + scale * math.sqrt(1 - rho**2) * (math.sqrt(common) * b * f + own * rng.gauss(0, 1) / math.sqrt(steps))
                       for f in bet]
            pnl, series = 0.0, []
            for s, change in enumerate(changes):
                pnl += change
                series.append({"elapsedS": float(s + 1), "pnl": round(pnl, 2)})
            rows.append({"teamName": name, "pnl": round(pnl, 2), "isTie": False, "pnlSeries": series})
        rows.sort(key=lambda row: -row["pnl"])
        for k, row in enumerate(rows, 1):
            row["rank"] = k
        boards.append(rows)
    return boards


def teams_of(boards: list[list[dict]]) -> list[list[lc.Team]]:
    out = []
    for rows in boards:
        out.append([lc.Team(row["teamName"], row.get("rank"), bool(row.get("isTie")), float(row["pnl"]),
                            sorted((float(p["elapsedS"]), float(p["pnl"])) for p in row.get("pnlSeries") or []))
                    for row in rows])
    return out


# ---------------------------------------------------------------------------- CLI


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(x) for x in text.split(","))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.day.standings", description=__doc__.split("\n\n")[0])
    parser.add_argument("--rounds", nargs="+", type=Path, help="the leaderboards so far, round 1 first")
    parser.add_argument("--team", help="our team's name on them")
    parser.add_argument("--ours", help="our per-day PnL in the next round: numbers (a,b,c), a file of them, or an arena.grid --out CSV")
    parser.add_argument("--where", action="append", default=[], metavar="PATH=VALUE", help="the grid CSV's row (repeatable; default: its best by PnL)")
    parser.add_argument("--days-per-round", type=int, default=1, help="days the round's private run sums (default: 1)")
    parser.add_argument("--weights", type=_floats, default=WEIGHTS, help="the rounds' weights, the next round's last (default: 0.1,0.2,0.3,0.4)")
    parser.add_argument("--multipliers", type=_floats, default=MULTIPLIERS, help="risk multipliers k to try (default: 0.25 to 1.5)")
    parser.add_argument("--hedges", type=_floats, default=HEDGES, help="hedge shares h to try (default: 0 to 1.5)")
    parser.add_argument("--k", type=float, default=1.0, help="the risk multiplier the hedge table holds (default: 1)")
    parser.add_argument("--hedge-edge", type=float, default=0.0,
                        help="what holding one whole share of the field's bet makes on average in our view, in PnL (default: 0)")
    parser.add_argument("--our-loading", type=float, default=0.0,
                        help="the share of the field's bet our bot already holds (its backtest sd should then leave it out) (default: 0)")
    parser.add_argument("--mean-power", type=float, default=1.0,
                        help="a multiplier k scales our mean by k to this power and our sd by k: 1 when they scale together (default: 1)")
    parser.add_argument("--lead", type=float, default=2.5, help="with --synthetic, our skill in sds above the field's mean (default: 2.5)")
    parser.add_argument("--growth", type=float, default=1.0, help="the next round's median and sd over the last round's (default: 1)")
    parser.add_argument("--growth-from", nargs=2, metavar=("OLD", "NEW"),
                        help="set --growth from a proxy field (--proxy-bots) on the last round's data and the next one's, each DATA:DAY[,DAY...]")
    parser.add_argument("--proxy-bots", nargs="+", type=Path, help="the proxy field's bot files (default: python/bots/zoo/'s, Prosperity format)")
    parser.add_argument("--format", default="prosperity", help="the data's format for --growth-from (default: prosperity)")
    parser.add_argument("--engine", default="python", choices=("python", "rust"), help="the engine for --growth-from")
    parser.add_argument("--growth-sd", type=float, default=None,
                        help="the log-sd of the next round's scale against the last's, drawn each simulation (default: measured "
                        "across the rounds, at least 0.5 when the next round is harder or of another kind: IDEAS.md, \"A standings calculator for round 4\")")
    parser.add_argument("--persistence", type=float, help="override the persistence measured across the rounds")
    parser.add_argument("--common", type=float, help="override the field's bet's share of a team's variance read from the curves")
    parser.add_argument("--sims", type=int, default=SIMS, help=f"simulations (default: {SIMS})")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--synthetic", action="store_true",
                        help="a synthetic field of 30 teams over 3 rounds (rounds' medians and sds 5k, 10k, 20k), us --lead sds ahead with no "
                             "loading on the field's bet, which is half a team's variance (synthetic_rounds); --ours defaults to SYNTHETIC_DAYS")
    args = parser.parse_args(argv)
    try:
        if args.synthetic:
            board, team = board_of(teams_of(synthetic_rounds(seed=args.seed, lead=args.lead))), "us"
            days = read_ours(args.ours) if args.ours else list(SYNTHETIC_DAYS)
        else:
            if not (args.rounds and args.team and args.ours):
                parser.error("--rounds, --team and --ours are needed (or --synthetic)")
            board, team, days = load_rounds(args.rounds), args.team, read_ours(args.ours, args.where)
        if team not in board.teams:
            raise ValueError(f"no team named {team!r} on the leaderboards")
        us = board.teams.index(team)
        growth = args.growth
        if args.growth_from:
            from experiments.study.zoo import is_local, zoo_bots

            if args.format != "prosperity" and not args.proxy_bots:
                raise ValueError(f"--growth-from on the {args.format} format needs --proxy-bots: bots written for it (the zoo's are Prosperity bots)")

            parse = lambda text: (text.rsplit(":", 1)[0], text.rsplit(":", 1)[1].split(","))
            bots = args.proxy_bots or [p for p in zoo_bots() if not is_local(p)]
            growth = proxy_growth(parse(args.growth_from[0]), parse(args.growth_from[1]), bots, args.format, args.engine)
            print(f"the next round's scale from {len(bots)} proxy bots: {growth:.2f} (--growth)")
        field = field_model(board, growth, args.persistence, args.common)
        ours = our_round(days, args.days_per_round)
        growth_sd = growth_spread(board) if args.growth_sd is None else args.growth_sd
        result = simulate(board, us, ours, field, args.weights, args.multipliers, args.hedges, args.k, args.hedge_edge, args.our_loading,
                          args.sims, args.seed, args.mean_power, growth_sd)
    except (ValueError, OSError, ImportError, json.JSONDecodeError, KeyError, StopIteration) as error:
        parser.error(str(error))
    print(format_result(board, us, ours, field, result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
