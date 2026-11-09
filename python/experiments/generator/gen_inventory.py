"""Raw generator invariants and discrete size-law fits, without a book or latent-price model.

Read each tape once: insert IDs, timestamp resolution/ties, arrivals, sizes, sides,
and insert-to-cancel lifetimes (including right-censored orders at the tape end).
Compare integer lognormal laws (floor/round/ceil, clipped at one), a rounded Lomax
(Pareto II), a geometric law, and a bounded uniform law by exact discrete likelihood,
AIC and CDF distance. Lognormal confidence intervals assume iid, correctly specified
sizes; they do not account for mixture misspecification or dependence.
The temporal half split checks stability; AIC alone does not establish a law.
No finite empirical size table can extrapolate the tail beyond its largest order.

Round-one private reconstructions have imputed cancels and incomplete IOC sizes:
mark them with --reconstructed LABEL and do not use them to identify those laws.
Samples are structure checks, never strategy-selection data. Numpy and scipy are
used only for measurements/fitting; tape_gen needs no scipy to draw fitted laws.

    uv run python -m experiments.generator.gen_inventory r1=data/arena/round1/round1.csv \
        r2=data/arena/round2/round2_public.csv r3=data/arena/round3/round3_public.csv \
        --out data/arena/gen/inventory.json [--summary-out docs/GENERATOR_COMPONENTS.json]
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import minimize
from scipy.special import ndtr


def integer_us(text: str) -> int:
    """Parse six-decimal seconds exactly; reject sub-microsecond input explicitly."""
    whole, _, fraction = text.partition(".")
    if len(fraction) > 6 and any(c != "0" for c in fraction[6:]):
        raise ValueError(f"sub-microsecond timestamp: {text}")
    return int(whole) * 1_000_000 + int(fraction[:6].ljust(6, "0"))


def quantiles(values) -> dict:
    a = np.asarray(values)
    return dict(zip(("min", "p01", "p10", "p50", "p90", "p99", "max"),
                    map(float, np.quantile(a, [0, .01, .1, .5, .9, .99, 1])))) if len(a) else {}


def size_bounds(q, rounding: str):
    """The continuous preimage of max(1, rounding(X)), X > 0."""
    shift = {"floor": 0.0, "round": -.5, "ceil": -1.0}[rounding]
    lo = np.where(q <= 1, 0.0, q + shift)
    return lo, q + shift + 1.0


def lognormal_mass(q, mu: float, sigma: float, rounding: str):
    lo, hi = size_bounds(q, rounding)
    with np.errstate(divide="ignore"):
        zl, zh = (np.log(lo) - mu) / sigma, (np.log(hi) - mu) / sigma
    # Survival differences avoid cancellation in the right tail.
    return np.where(zl > 0, ndtr(-zl) - ndtr(-zh), ndtr(zh) - ndtr(zl))


def fit_sizes(counts: Counter) -> list[dict]:
    if not counts:
        return []
    q = np.array(sorted(counts), dtype=float)
    w = np.array([counts[int(v)] for v in q], dtype=float)
    n = w.sum()
    empirical = np.cumsum(w) / n
    results = []
    for rounding in ("floor", "round", "ceil"):
        mean = float(w @ np.log(q) / n)
        sd = max(.1, float(np.sqrt(w @ (np.log(q) - mean) ** 2 / n)))

        def loss(x):
            p = lognormal_mass(q, x[0], math.exp(x[1]), rounding)
            return float(-w @ np.log(np.maximum(p, 1e-300)) / n)

        opt = minimize(loss, [mean, math.log(sd)], method="L-BFGS-B",
                       bounds=[(-10, 30), (-5, 4)], options={"ftol": 1e-14, "gtol": 1e-8})
        mu, sigma = float(opt.x[0]), math.exp(float(opt.x[1]))
        lo, hi = size_bounds(q, rounding)
        with np.errstate(divide="ignore"):
            cdf_lo, cdf_hi = ndtr((np.log(lo) - mu) / sigma), ndtr((np.log(hi) - mu) / sigma)
        distance = max(np.max(abs(cdf_hi - empirical)), np.max(abs(cdf_lo - (empirical - w / n))))
        # Observed information on (mu, log sigma); conditional on iid draws and
        # this law being correct. Half fits below are the stability check.
        h = 1e-4
        basis = np.eye(2) * h
        curvature = np.empty((2, 2))
        for i in range(2):
            for j in range(2):
                curvature[i, j] = (loss(opt.x + basis[i] + basis[j]) - loss(opt.x + basis[i] - basis[j])
                                   - loss(opt.x - basis[i] + basis[j]) + loss(opt.x - basis[i] - basis[j])) / (4 * h * h)
        ci = None
        eigenvalues = np.linalg.eigvalsh(curvature)
        if n >= 30 and len(q) >= 3 and eigenvalues[0] > 1e-6 * max(1, eigenvalues[-1]):
            se = np.sqrt(np.diag(np.linalg.inv(curvature)) / n)
            ci = {"mu": [mu - 1.96 * se[0], mu + 1.96 * se[0]],
                  "sigma": [sigma * math.exp(-1.96 * se[1]), sigma * math.exp(1.96 * se[1])]}
        results.append({"law": "lognormal", "rounding": rounding, "mu": mu, "sigma": sigma,
                        "loglik": -float(opt.fun) * n, "aic": 2 * n * float(opt.fun) + 4,
                        "cdf_distance": float(distance), "converged": bool(opt.success), "iid_ci95": ci})
    # A rounded, lower-clipped Lomax (Pareto II): a genuine power-law tail.
    lo, hi = size_bounds(q, "round")

    def lomax_parts(x):
        scale, alpha = np.exp(x)
        log_sl = -alpha * np.log1p(lo / scale)
        log_sh = -alpha * np.log1p(hi / scale)
        mass = np.exp(log_sl) * -np.expm1(log_sh - log_sl)
        return mass, -np.expm1(log_sl), -np.expm1(log_sh)

    def lomax_loss(x):
        mass, _, _ = lomax_parts(x)
        return float(-w @ np.log(np.maximum(mass, 1e-300)) / n)

    opt = minimize(lomax_loss, np.log([max(1, q[np.searchsorted(empirical, .5)]), 1.5]),
                   method="L-BFGS-B", bounds=[(-8, 20), (-4, 8)], options={"ftol": 1e-13})
    _, cdf_lo, cdf_hi = lomax_parts(opt.x)
    results.append({"law": "lomax", "rounding": "round", "scale": math.exp(opt.x[0]),
                    "alpha": math.exp(opt.x[1]), "aic": 2 * n * float(opt.fun) + 4,
                    "loglik": -n * float(opt.fun), "converged": bool(opt.success),
                    "cdf_distance": float(max(np.max(abs(cdf_hi - empirical)),
                                              np.max(abs(cdf_lo - (empirical - w / n)))))})
    p = float(n / (w @ q))
    ll = 0.0 if p == 1 else float(n * math.log(p) + w @ (q - 1) * math.log1p(-p))
    cdf_hi, cdf_lo = 1 - (1 - p) ** q, 1 - (1 - p) ** (q - 1)
    results.append({"law": "geometric", "p": p, "loglik": ll, "aic": 2 - 2 * ll,
                    "cdf_distance": float(max(np.max(abs(cdf_hi - empirical)),
                                              np.max(abs(cdf_lo - (empirical - w / n)))))})
    width = q[-1] - q[0] + 1
    ll = -float(n * math.log(width))
    results.append({"law": "uniform", "low": int(q[0]), "high": int(q[-1]), "loglik": ll,
                    "aic": 4 - 2 * ll, "cdf_distance": float(max(
                        np.max(abs((q - q[0] + 1) / width - empirical)),
                        np.max(abs((q - q[0]) / width - (empirical - w / n)))))})
    return sorted(results, key=lambda r: r["aic"])


def arrivals(times, start: float, end: float) -> dict:
    times = np.asarray(times, dtype=float) / 1e6
    dt = np.diff(times)
    span = end - start
    out = {"n": len(times), "rate_per_s": len(times) / span if span > 0 else None,
           "gap_s": quantiles(dt), "gap_cv": float(dt.std() / dt.mean()) if len(dt) and dt.mean() > 0 else None}
    out["count_dispersion"] = {}
    for width in (1, 10, 60):
        bins = int(span // width)
        if bins < 2:
            continue
        c, _ = np.histogram(times, bins=start + np.arange(bins + 1) * width)
        out["count_dispersion"][str(width)] = float(c.var() / c.mean()) if c.mean() else None
    return out


def inventory(path: Path, reconstructed: bool = False) -> dict:
    times = {k: array("q") for k in ("G", "F", "Cancel")}
    sizes = {k: array("q") for k in ("G", "F")}
    sides = {k: Counter() for k in ("G", "F")}
    parity = {k: Counter() for k in ("G", "F")}
    lives, canceled_sizes = array("d"), array("q")
    active = {}
    id_gaps, decimal_places, tick_gaps = Counter(), Counter(), Counter()
    life_codes, operations = Counter(), Counter()
    first_id = last_id = None
    first_t = last_t = None
    unknown_cancels = reused_live_ids = 0
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        header = next(fh)
        digest.update(header)
        if header.strip() != b"Time,Operation,OrderId,Side,Volume,Price,Lifespan":
            raise ValueError(f"unexpected tape header: {path}")
        for raw in fh:
            digest.update(raw)
            t, op, oid, side, q, price, life = raw.decode().strip().split(",")
            us, oid = integer_us(t), int(oid)
            decimal_places[len(t.partition(".")[2])] += 1
            operations[op] += 1
            if last_t is not None:
                gap = us - last_t
                tick_gaps[gap if gap <= 10 else "over_10_us"] += 1
                if gap < 0:
                    raise ValueError(f"non-monotone tape time at {t}: {path}")
            first_t = us if first_t is None else first_t
            last_t = us
            if op == "Insert":
                life_codes[life] += 1
                if life not in sizes or int(q) <= 0 or side not in ("B", "A"):
                    raise ValueError(f"unsupported insert: {raw!r}")
                first_id = oid if first_id is None else first_id
                if last_id is not None:
                    id_gaps[oid - last_id] += 1
                last_id = oid
                times[life].append(us)
                sizes[life].append(int(q))
                sides[life][side] += 1
                parity[life][oid % 2] += 1
                if life == "G":
                    reused_live_ids += oid in active
                    active[oid] = (us, int(q))
            elif op == "Cancel":
                times[op].append(us)
                birth = active.pop(oid, None)
                if birth is None:
                    unknown_cancels += 1
                else:
                    lives.append((us - birth[0]) / 1e6)
                    canceled_sizes.append(birth[1])
            else:
                raise ValueError(f"unsupported operation {op!r}")
    if first_t is None or first_id is None:
        raise ValueError(f"no inserts: {path}")
    end, start = last_t / 1e6, first_t / 1e6
    report = {"source": str(path), "sha256": digest.hexdigest(), "reconstructed": reconstructed,
              "duration_s": end - start, "operations": dict(operations), "lifespan_codes": dict(life_codes),
              "ids": {"first": first_id, "last": last_id, "insert_delta_counts": dict(id_gaps),
                      "reused_live_g_ids": reused_live_ids, "unmatched_cancels": unknown_cancels},
              "time": {"decimal_places": dict(decimal_places), "adjacent_gap_us_counts": dict(tick_gaps)},
              "streams": {}}
    for k in ("G", "F"):
        values = np.asarray(sizes[k])
        counts = Counter(map(int, values))
        half = np.searchsorted(np.asarray(times[k]), (first_t + last_t) / 2)
        fits = fit_sizes(counts)
        report["streams"][k] = {**arrivals(times[k], start, end), "buy_share": sides[k]["B"] / max(1, len(values)),
            "id_parity": dict(parity[k]), "size_quantiles": quantiles(values), "distinct_sizes": len(counts),
            "size_counts": dict(sorted(counts.items())), "size_fits": fits,
            "half_fits": [fit_sizes(Counter(map(int, a)))[:1] for a in (values[:half], values[half:])]}
    observed = np.asarray(lives)
    censored = (last_t - np.array([birth for birth, _ in active.values()], dtype=float)) / 1e6
    all_ages = np.r_[observed, censored]
    hazard = []
    for lo, hi in zip((0, .05, .1, .2, .4, .8, 1.6, 3.2), (.05, .1, .2, .4, .8, 1.6, 3.2, 6.4)):
        # Piecewise exponential MLE: events divided by exposure; include censoring.
        exposure = float(np.clip(all_ages - lo, 0, hi - lo).sum())
        events = int(((observed >= lo) & (observed < hi)).sum())
        hazard.append({"age_s": [lo, hi], "events": events, "exposure_s": exposure,
                       "hazard_per_s": events / exposure if exposure else None})
    report["cancels"] = {"matched": len(observed), "right_censored": len(censored),
                         "observed_lifetime_s": quantiles(observed), "age_hazard": hazard}
    report["cancels"]["size_by_observed_lifetime"] = []
    cq = np.asarray(canceled_sizes)
    for lo, hi in ((0, .1), (.1, 1), (1, 3), (3, 10), (10, math.inf)):
        selected = cq[(observed >= lo) & (observed < hi)]
        report["cancels"]["size_by_observed_lifetime"].append({
            "age_s": [lo, hi if math.isfinite(hi) else None], "n": len(selected),
            "size_quantiles": quantiles(selected)})
    if reconstructed:
        report["caution"] = "Imputed cancels and missing/unfilled IOC quantities: not evidence for original size/lifetime laws."
    return report


def show(label: str, report: dict) -> None:
    print(f"{label}: {report['duration_s']:.2f}s; insert ID deltas {report['ids']['insert_delta_counts']}")
    for k, s in report["streams"].items():
        fit = s["size_fits"][0] if s["size_fits"] else {}
        params = {key: fit[key] for key in ("law", "rounding", "mu", "sigma", "low", "high", "cdf_distance") if key in fit}
        print(f"  {k}: {s['n']:,}, rate {s['rate_per_s']:.3f}/s, gap CV {s['gap_cv']}; size {params}")
    print(f"  cancels: {report['cancels']['observed_lifetime_s']}; censored {report['cancels']['right_censored']}")
    if report.get("caution"):
        print(f"  {report['caution']}")


def component_summary(reports: dict) -> dict:
    """Small, committable parameter table, retaining source hashes and fit failures."""
    out = {"scope": "Raw streams and marginal size laws only; not a calibrated full-generator preset.",
           "ci_assumptions": "95% observed-information intervals, conditional on iid sizes and a correct lognormal law.",
           "tapes": {}}
    for label, r in reports.items():
        record = {key: r[key] for key in ("source", "sha256", "reconstructed", "duration_s", "ids")}
        record["streams"] = {}
        for kind, s in r["streams"].items():
            record["streams"][kind] = {key: s[key] for key in ("n", "rate_per_s", "gap_cv", "count_dispersion",
                                                             "size_quantiles", "half_fits")}
            if s["size_fits"]:
                best = s["size_fits"][0]
                record["streams"][kind]["best_size_fit"] = best
                record["streams"][kind]["alternative_delta_aic"] = {
                    f"{d['law']}_{d.get('rounding', 'integer')}": d["aic"] - best["aic"] for d in s["size_fits"][1:]}
        record["cancels"] = {key: r["cancels"][key] for key in ("matched", "right_censored", "observed_lifetime_s",
                                                             "size_by_observed_lifetime")}
        out["tapes"][label] = record
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tapes", nargs="+", help="LABEL=path.csv (or a path, labelled by its stem)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, help="also write a compact parameter table without size counts")
    parser.add_argument("--reconstructed", default="", help="comma-separated labels of reconstructed tapes")
    args = parser.parse_args(argv)
    reports = {}
    for spec in args.tapes:
        label, sep, filename = spec.partition("=")
        path = Path(filename if sep else spec)
        label = label if sep else path.stem
        if label in reports:
            parser.error(f"duplicate label: {label}")
        reports[label] = inventory(path, label in args.reconstructed.split(","))
        show(label, reports[label])
        sys.stdout.flush()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(reports, indent=2, allow_nan=False) + "\n")
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(component_summary(reports), indent=2, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
