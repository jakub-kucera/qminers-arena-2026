"""Searching a grid's cells without running all of them: arena.grid's --search.

A cell is an index tuple, one position per axis. A Search charges each of a cell's pieces (one
backtest each: a day under a mode) once, up to a budget of whole cells, and scores a cell by an
objective once all its pieces are in. The searches (experiments.study.search_methods compares them with
random cells, halving and a Gaussian process; IDEAS.md, "Searching a big grid without running all
of it"):
  coord  coordinate descent from the space's start: each axis in turn (seeded order), every value
         along it, moving to the best; a sweep with no move restarts from a random cell
  tpe    a tree-structured Parzen estimator (Bergstra et al. 2011, Optuna's default): each axis's
         values weighted by the best GAMMA of the cells so far against the rest, 24 draws a pick,
         BATCH picks a round
"""

from __future__ import annotations

import math
import random

BATCH = 14  # tpe's cells a round (fixed, so a search doesn't depend on the cores it runs on)
GAMMA = 0.1  # tpe: the share of the cells so far that count as good (Optuna: ceil(0.1 n), at most 25)


def unrank(k: int, sizes: list[int]) -> tuple[int, ...]:
    """The k-th combination in itertools.product's order (the last axis fastest)."""
    index = []
    for n in reversed(sizes):
        k, j = divmod(k, n)
        index.append(j)
    return tuple(reversed(index))


class Space:
    """The axes' sizes, and the cell a search that starts somewhere starts from."""

    def __init__(self, sizes: list[int], start: tuple[int, ...]):
        self.sizes, self.base = list(sizes), tuple(start)
        self.total = math.prod(self.sizes)

    def draw(self, rng: random.Random, count: int) -> list[tuple]:
        return [unrank(k, self.sizes) for k in rng.sample(range(self.total), min(count, self.total))]

    def neighbours(self, cell: tuple) -> list[tuple]:
        out = []
        for i, n in enumerate(self.sizes):
            for j in (cell[i] - 1, cell[i] + 1):
                if 0 <= j < n:
                    out.append(cell[:i] + (j,) + cell[i + 1:])
        return out


class Spent(Exception):
    """The budget ran out."""


class Search:
    """What a search sees: `pieces(wanted)` runs [(cell, k)] (k: 0..count-1) and returns {(cell, k):
    result}, each charged once; `objective(results)` scores a cell from its count results in order
    (higher is better). `budget` is in whole cells."""

    def __init__(self, space: Space, pieces, count: int, budget: float, objective):
        self.space, self._pieces, self.count, self.objective = space, pieces, count, objective
        self.limit, self.spent = budget * count, 0
        self.known: dict[tuple, object] = {}
        self.seen: dict[tuple, float] = {}  # cell -> objective, in the order they were completed

    def piece(self, cells: list[tuple], k: int) -> list:
        return self._ask([(c, k) for c in cells])

    def whole(self, cells: list[tuple]) -> list[float]:
        self._ask([(c, k) for c in cells for k in range(self.count)])
        return [self.seen[c] for c in cells]

    def _ask(self, wanted: list[tuple]) -> list:
        new = [w for w in dict.fromkeys(wanted) if w not in self.known]
        room = self.limit - self.spent
        short = len(new) > room
        if short:  # whole cells first, in order, as far as the budget goes
            new = new[: max(0, int(room))]
        if new:
            self.known.update(self._pieces(new))
            self.spent += len(new)
            for cell in dict.fromkeys(c for c, _ in new):
                if cell not in self.seen and all((cell, k) in self.known for k in range(self.count)):
                    self.seen[cell] = self.objective([self.known[(cell, k)] for k in range(self.count)])
        if short:
            raise Spent
        return [self.known[w] for w in wanted]

    def best(self, first: int | None = None) -> tuple | None:
        """The best cell seen (among the first `first` completed); ties to the earlier."""
        items = list(self.seen.items())[:first]
        return max(items, key=lambda item: item[1])[0] if items else None

    def found_at(self) -> int:
        """How many cells had completed when the best one did (1-based)."""
        best = self.best()
        return list(self.seen).index(best) + 1 if best is not None else 0


def coord(s: Search, rng: random.Random) -> None:
    current = s.space.base
    (value,) = s.whole([current])
    while True:
        moved = False
        for i in rng.sample(range(len(s.space.sizes)), len(s.space.sizes)):
            line = [current[:i] + (j,) + current[i + 1:] for j in range(s.space.sizes[i])]
            values = s.whole(line)
            best = max(range(len(line)), key=lambda j: values[j])
            if values[best] > value:
                current, value, moved = line[best], values[best], True
        if not moved:
            fresh = [c for c in s.space.draw(rng, 50) if c not in s.seen]
            if not fresh:
                return
            current = fresh[0]
            (value,) = s.whole([current])


def tpe(s: Search, rng: random.Random) -> None:
    sizes = s.space.sizes
    s.whole(s.space.draw(rng, BATCH))
    while True:
        ranked = sorted(s.seen, key=lambda c: -s.seen[c])
        good, bad = ranked[: min(max(1, math.ceil(GAMMA * len(ranked))), 25)], ranked[min(max(1, math.ceil(GAMMA * len(ranked))), 25):] or ranked
        weights = []
        for i, n in enumerate(sizes):
            def density(cells, i=i, n=n):
                w = [1.0 / n] * n  # the prior, one cell's weight
                for c in cells:
                    for j in range(n):
                        w[j] += math.exp(-0.5 * (j - c[i]) ** 2)
                total = sum(w)
                return [x / total for x in w]
            weights.append((density(good), density(bad)))
        picks: list[tuple] = []
        for _ in range(BATCH):
            draws = [tuple(rng.choices(range(n), weights[i][0])[0] for i, n in enumerate(sizes)) for _ in range(24)]
            draws = [d for d in draws if d not in s.seen and d not in picks] or [c for c in s.space.draw(rng, 50) if c not in s.seen and c not in picks]
            if not draws:
                break
            picks.append(max(draws, key=lambda d: sum(math.log(weights[i][0][j] / weights[i][1][j]) for i, j in enumerate(d))))
        if not picks:
            return
        s.whole(picks)


SEARCHES = {"coord": coord, "tpe": tpe}


def run(method: str, s: Search, seed: int) -> Search:
    """The search to its budget, or until it has tried every cell it would."""
    try:
        SEARCHES[method](s, random.Random(seed))
    except Spent:
        pass
    return s
