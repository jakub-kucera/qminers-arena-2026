"""The statistics arena.grid judges a search by: Bailey et al.'s CSCV (PBO), Bailey and Lopez de
Prado's deflated Sharpe ratio and its number of independent trials, Hansen's SPA test with
Politis and Romano's stationary bootstrap, and Romano and Wolf's StepM. python/arena/grid.py's docstring
says what each one answers; the formulas are cited where they are computed.

rust/src/arena/stats.rs is this module's twin, the same to the bit (rust/twins.json): the parts whose
cost grows with the cells (cscv, mean_correlation, snooping), which arena.grid --engine rust runs
there. Standard library only.
"""

from __future__ import annotations

import functools
import itertools
import math
import random
import statistics
from dataclasses import dataclass
from operator import itemgetter, mul

MAX_SPLITS = 4000  # halvings of the blocks to score; sampled (seeded) when there are more
EULER_GAMMA = 0.5772156649015329
ALPHA = 0.05  # StepM's familywise error, and SPA's size, that the tests aim at
# The level SPA and StepM are read at. At ALPHA itself they named a noise cell in 5.9-8.3% of 1,000 null grids a row
# (each resample studentized by its own omega); at 0.04 in 4.5-5.2%, and 7.0% where the gains are AR(1) 0.8, for
# 47.7% power against 51.1% (experiments.study.snooping_null_rates; IDEAS.md, "Bootstrap tests of the best cell").
TEST_ALPHA = 0.04
STUDENTIZE = ("resample", "fixed")  # how SPA and StepM studentize each resample: by its own omega (default), or the original's


@dataclass(frozen=True)
class Cscv:
    pbo: float  # share of halvings where the in-sample best is at or below the out-of-sample median
    loss: float  # share of halvings where it loses money out of sample
    rank: float  # its mean relative rank w out of sample: near 1 the top, 0.5 the median
    splits: int  # halvings scored
    of: int  # halvings there are


def cscv(columns: list[list[float]], max_splits: int = MAX_SPLITS, seed: int = 0) -> Cscv:
    """Bailey et al.'s combinatorially symmetric cross-validation (Algorithm 2.3, p. 11-12).

    `columns` holds each cell's PnL per block, the blocks in the same order for every cell. Each
    halving of the blocks is a training half and a test half; the cell with the best training PnL
    gets its test rank r in 1..N (higher is better, ties averaged), w = r / (N + 1), and the
    halving counts as overfit when the logit ln(w / (1 - w)) <= 0.
    """
    n, s = len(columns), len(columns[0])
    of = math.comb(s, s // 2)
    if of <= max_splits:
        halvings = list(itertools.combinations(range(s), s // 2))
    else:
        rng, seen = random.Random(seed), set()
        while len(seen) < max_splits:
            seen.add(tuple(sorted(rng.sample(range(s), s // 2))))
        halvings = sorted(seen)
    totals = [sum(column) for column in columns]
    overfit = losses = 0
    ranks = []
    for train in halvings:
        inside = [sum(column[i] for i in train) for column in columns]
        outside = [total - x for total, x in zip(totals, inside)]
        best = max(range(n), key=inside.__getitem__)
        mine = outside[best]
        rank = sum(1 for v in outside if v < mine) + (sum(1 for v in outside if v == mine) + 1) / 2
        w = rank / (n + 1)
        overfit += math.log(w / (1 - w)) <= 0
        losses += mine < 0
        ranks.append(w)
    return Cscv(overfit / len(halvings), losses / len(halvings), statistics.fmean(ranks), len(halvings), of)


def expected_max_sharpe(variance: float, trials: float) -> float:
    """SR0, the best Sharpe ratio expected from `trials` independent cells with no edge whose Sharpe
    ratios have this variance (Bailey and Lopez de Prado, eq. 1-2, p. 7-9). 0 below two trials."""
    if trials < 2:
        return 0.0
    z = statistics.NormalDist().inv_cdf
    return math.sqrt(variance) * ((1 - EULER_GAMMA) * z(1 - 1 / trials) + EULER_GAMMA * z(1 - 1 / (trials * math.e)))


def deflated_sharpe(sharpe: float, sharpe0: float, periods: int, skew: float, kurtosis: float) -> float | None:
    """DSR = Z[(SR - SR0) sqrt(T - 1) / sqrt(1 - skew SR + (kurtosis - 1) / 4 SR^2)] (eq. 2, p. 8-9);
    kurtosis is not excess (3 for a normal). None when the root's argument isn't positive."""
    spread = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2
    if spread <= 0 or periods < 2:
        return None
    return statistics.NormalDist().cdf((sharpe - sharpe0) * math.sqrt(periods - 1) / math.sqrt(spread))


def independent_trials(columns: list[list[float]], correlation=None) -> float:
    """N^ = rho + (1 - rho) M, rho the average pairwise correlation of the M cells' block PnL (eq. 9,
    p. 14-15). Cells with a constant PnL per block have no correlation and are left out of rho.
    `correlation` computes rho from the standardized columns (default mean_correlation; arena.rust's
    is its twin)."""
    m = len(columns)
    rho = (correlation or mean_correlation)(standardized(columns))
    return float(m) if rho is None else rho + (1 - rho) * m


def standardized(columns: list[list[float]]) -> list[list[float]]:
    """Each column with a spread, as (x - mean) / sd (population sd); constant columns left out."""
    scaled = []
    for column in columns:
        sd = statistics.pstdev(column)
        if sd > 0:
            mean = statistics.fmean(column)
            scaled.append([(x - mean) / sd for x in column])
    return scaled


def mean_correlation(scaled: list[list[float]]) -> float | None:
    """The mean over every pair of standardized columns of their correlation; None with fewer than two.

    As the identity sum over pairs of z_i . z_j = (||sum of z_i||^2 - sum of ||z_i||^2) / 2, so it
    costs O(cells x blocks) rather than a pass over every pair (a grid of 100,000 cells has 5e9),
    each sum exact (math.fsum), so rust/src/arena/stats.rs gives the same to the bit."""
    m = len(scaled)
    if m < 2:
        return None
    s = len(scaled[0])
    column_sums = [math.fsum(column[t] for column in scaled) for t in range(s)]
    total = math.fsum(x * x for x in column_sums)
    own = math.fsum(x * x for column in scaled for x in column)
    return (total - own) / (s * m * (m - 1))


def omega2(d: list[float], q: float) -> float:
    """Hansen's variance of sqrt(n) times the mean under the stationary bootstrap (p. 8):
    gamma_0 + 2 sum_i kappa(n, i) gamma_i, kappa(n, i) = (n-i)/n (1-q)^i + i/n (1-q)^(n-i)."""
    n, mean = len(d), statistics.fmean(d)
    c = [x - mean for x in d]
    total = sum(map(mul, c, c)) / n
    for i, twice in _kernel(n, q):
        total += twice * sum(map(mul, c, c[i:])) / n
    return total


@functools.lru_cache(maxsize=64)
def _kernel(n: int, q: float) -> tuple[tuple[int, float], ...]:
    """omega2's lags and their weights 2 kappa(n, i), those with kappa under 1e-12 left out."""
    out = []
    for i in range(1, n):
        kappa = (n - i) / n * (1 - q) ** i + i / n * (1 - q) ** (n - i)
        if kappa >= 1e-12:
            out.append((i, 2 * kappa))
    return tuple(out)


def resamples(n: int, q: float, boot: int, seed: int) -> list[list[int]]:
    """Each resample's indices, by Politis and Romano's stationary bootstrap (Hansen, p. 7): with
    probability q the next index is drawn afresh, else it follows the last, wrapping."""
    rng, out = random.Random(seed), []
    for _ in range(boot):
        idx, t = [], rng.randrange(n)
        for _ in range(n):
            idx.append(t)
            t = rng.randrange(n) if rng.random() < q else (t + 1) % n
        out.append(idx)
    return out


def bootstrap_means(d: list[list[float]], q: float, boot: int, seed: int) -> list[list[float]]:
    """Each resample's mean of every column (resamples)."""
    n = len(d[0])
    return [[sum(pick(column)) / n for column in d] for pick in (itemgetter(*idx) for idx in resamples(n, q, boot, seed))]


def bootstrap(d: list[list[float]], q: float, boot: int, seed: int) -> tuple[list[list[float]], list[list[float]]]:
    """Each resample's mean of every column, and its scale: sqrt(omega2) of that column's resample.

    Romano and Wolf studentize each resample by "the corresponding estimated standard deviations"
    computed "from each bootstrap data matrix" (Algorithm 4.2 step 3, p. 15), for time series by
    "applying the same algorithm to the bootstrap data matrix" (p. 15; both checked against the
    PDF). So the scale is _scales' estimator, omega2, run on the resample as on any series. They
    also mention Gotze and Kunsch's "natural" estimator, the blocks' centred sums squared, for
    bootstraps of fixed-length blocks. Ours draws blocks of geometric length, whose sums squared
    vary far more than omega2 does (relative variance about 5 / blocks drawn), so the resamples'
    statistics would have heavier tails than the data's: too conservative on short-memory gains,
    and no closer to the data's omega2 on long-memory ones (a quick prototype on
    experiments/study/snooping_null_rates.py's null grids agreed; it was not kept). The cost is every
    lag of every column of every resample, O(cells x resamples x blocks^2): about 0.8 s a cell
    at 1,000 resamples of 300 blocks in Python, so a grid of more than a few dozen cells wants
    --engine rust (rust/src/arena/stats.rs, on every core: 4,096 cells in about 10 s)."""
    n, means, scales = len(d[0]), [], []
    for idx in resamples(n, q, boot, seed):
        pick = itemgetter(*idx)
        picked = [pick(column) for column in d]
        means.append([sum(x) / n for x in picked])
        scales.append([math.sqrt(max(omega2(x, q), 1e-12)) for x in picked])
    return means, scales


def _scales(d: list[list[float]], q: float) -> list[float]:
    return [math.sqrt(max(omega2(c, q), 1e-12)) for c in d]


def _draws(d, q, boot, seed, studentize, omegas, draws, scales):
    """The original's scales, each resample's means, and the scales each resample is studentized by
    (each its own with "resample", the original's with "fixed")."""
    if studentize not in STUDENTIZE:
        raise ValueError(f"studentize is one of {', '.join(STUDENTIZE)}, not {studentize!r}")
    omegas = omegas or _scales(d, q)
    if studentize == "fixed":
        return omegas, draws or bootstrap_means(d, q, boot, seed), None
    if draws is None or scales is None:
        draws, scales = bootstrap(d, q, boot, seed)
    return omegas, draws, scales


def spa(d: list[list[float]], q: float, boot: int, seed: int = 0, *, studentize: str = "resample", omegas=None, draws=None,
        scales=None) -> dict[str, float]:
    """Hansen's SPA p-values for H0: no column of gains has a positive mean (p. 4 and 7-8). The
    bootstrap is recentred at mu_l = min(mean, 0), at mu_c (only means clearly below 0 kept, the
    consistent one) and at mu_u = 0 (the studentized Reality Check). With studentize "fixed" every
    resample is studentized by the original's omega, as Hansen does (p. 8); with "resample"
    (default; ours, after Romano and Wolf's StepM) each by its own (bootstrap). The test statistic
    and mu_c's threshold use the original's either way."""
    n = len(d[0])
    means = [statistics.fmean(c) for c in d]
    omegas, draws, scales = _draws(d, q, boot, seed, studentize, omegas, draws, scales)
    t = max(0.0, max(math.sqrt(n) * m / w for m, w in zip(means, omegas)))
    loglog = math.sqrt(2 * math.log(math.log(n)))
    shifts = {
        "l": [max(0.0, m) for m in means],
        "c": [m if m >= -w / math.sqrt(n) * loglog else 0.0 for m, w in zip(means, omegas)],
        "u": means,
    }
    out = {}
    for name, shift in shifts.items():
        above = sum(max(0.0, max(math.sqrt(n) * (x - s) / w for x, s, w in zip(draw, shift, ws))) > t
                    for draw, ws in zip(draws, scales or itertools.repeat(omegas)))
        out[name] = above / len(draws)
    return out


def stepm(d: list[list[float]], q: float, boot: int, alpha: float = TEST_ALPHA, seed: int = 1, *, studentize: str = "resample", omegas=None,
          draws=None, scales=None) -> list[int]:
    """Romano and Wolf's studentized step-down (Algorithms 4.1-4.2, p. 14-15): the columns whose
    mean gain is significantly positive, the familywise error held at alpha. z_k = sqrt(n) mean_k /
    omega_k; each resample's sqrt(n) (mean*_k - mean_k) / omega*_k, omega*_k its own (studentize
    "resample", the paper's, default) or the original's in every resample ("fixed", what this
    module did before 2026-10-26). On experiments/study/snooping_null_rates.py's null grids, at 5%, the
    original's named a noise cell in 9-22% of them, each its own in 6-8%; at TEST_ALPHA, the default
    since 2026-11-02, in 4.5-7% (IDEAS.md, "Bootstrap tests of the best cell")."""
    n = len(d[0])
    means = [statistics.fmean(c) for c in d]
    omegas, draws, scales = _draws(d, q, boot, seed, studentize, omegas, draws, scales)
    z = [math.sqrt(n) * m / w for m, w in zip(means, omegas)]
    centred = [[math.sqrt(n) * (x - m) / w for x, m, w in zip(draw, means, ws)] for draw, ws in zip(draws, scales or itertools.repeat(omegas))]
    active, rejected = set(range(len(d))), []
    while active:
        maxima = sorted(max(draw[k] for k in active) for draw in centred)
        c = maxima[min(len(maxima) - 1, math.ceil((1 - alpha) * len(maxima)) - 1)]
        newly = [k for k in active if z[k] > c]
        if not newly:
            break
        rejected += newly
        active -= set(newly)
    return sorted(rejected)


def snooping(d: list[list[float]], q: float, boot: int, alpha: float = TEST_ALPHA, seed: int = 0, studentize: str = "resample") -> tuple[dict[str, float], list[int]]:
    """SPA's p-values and StepM's columns on the same studentization and resamples, as arena.grid
    reports them."""
    omegas, draws, scales = _draws(d, q, boot, seed, studentize, None, None, None)
    common = {"studentize": studentize, "omegas": omegas, "draws": draws, "scales": scales}
    return spa(d, q, boot, **common), stepm(d, q, boot, alpha, **common)
