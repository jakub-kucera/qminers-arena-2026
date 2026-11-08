"""Time-split tests of ladder arrival intensity, size and cancellation mechanics.

Uses gen_ladders' identified subset, not a claim to identify every extra G order.
All intensity predictors use strictly prior book events. Labels were discovered
on the whole public tape in an earlier session; the temporal holdout validates
fitted rates, not an independent discovery of the model class.

Cancellation exposure starts when an exact 2-ms link first identifies an order,
ends at its first complete fill, cancel, or tape end, and uses the book state
before a cancel. Complete fills are competing-risk censoring, not cancellation
events. Scheduled cancels after a fill are excluded. Piecewise constant hazard
models are fit on the first half and evaluated on the second half; they are
descriptive cause-specific hazards, not proof of the organisers' causal policy.

    uv run python -m experiments.day.gen_ladder_mechanics data/arena/round3/round3_public.csv \
        --cache data/arena/gen/gen_v3_r3_ladders.npz \
        --fills-cache data/arena/gen/ladder_mechanics/r3_fills.npz \
        --out data/arena/gen/ladder_mechanics/r3_mechanics.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.optimize import minimize

from experiments.day.gen_inventory import integer_us
from experiments.day.gen_ladders import chains, links, load
from experiments.day import tape_book

AGE_EDGES = np.array([.02, .05, .1, .25, .5, 1., 2., 5., 10.])
OFFSET_LABELS = ["negative", "0", "1", "2-4", "5", "6", "7", "8+", "missing"]
ACTIVITY_EDGES = np.array([2., 4., 8., 16., 32.])
DIMENSIONS = (2, 10, 9, 6, 6)  # size group, age, current offset, initial offset, lagged 1-s activity
FEATURES = ["intercept", "log1p_mid_changes_per_s_1s", "log1p_mid_changes_per_s_5s",
            "log1p_mid_changes_per_s_30s", "log1p_absolute_move_per_s_5s", "log1p_spread"]


def book_features(data, now):
    """Strictly prior book history; a future event cannot alter a feature row."""
    now = np.asarray(now, dtype=np.int64)
    valid = (data["bid"] > 0) & (data["ask"] > 0)
    tt = data["touch_us"][valid]
    bid, ask = data["bid"][valid], data["ask"][valid]
    mid = (bid + ask) / 2
    dm = np.r_[0., np.diff(mid)]
    count = np.r_[0., np.cumsum(dm != 0)]
    move = np.r_[0., np.cumsum(np.abs(dm))]
    hi = np.searchsorted(tt, now, side="left")
    cols = [np.ones(len(now))]
    for seconds in (1, 5, 30):
        lo = np.searchsorted(tt, now - seconds * 1_000_000, side="left")
        cols.append(np.log1p((count[hi] - count[lo]) / seconds))
    lo = np.searchsorted(tt, now - 5_000_000, side="left")
    cols.append(np.log1p((move[hi] - move[lo]) / 5))
    spread = np.zeros(len(now))
    present = hi > 0
    spread[present] = ask[hi[present] - 1] - bid[hi[present] - 1]
    cols.append(np.log1p(spread))
    return np.column_stack(cols)


def recognition_times(data):
    left, right = links(data, 2000)
    members = np.unique(np.r_[left, right])
    known = np.full(len(data["time_us"]), np.iinfo(np.int64).max)
    np.minimum.at(known, left, data["time_us"][right])
    np.minimum.at(known, right, data["time_us"][right])
    return members, known, chains(len(known), left, right)


def fill_times(path, data, cache=None):
    """First complete fill time for identified G orders, using the replay's fill list."""
    book_hash = hashlib.sha256(Path(tape_book.__file__).read_bytes()).hexdigest()
    identity = json.dumps([1, str(data["sha256"]), book_hash])
    if cache and cache.exists():
        with np.load(cache, allow_pickle=False) as saved:
            if str(saved["identity"]) != identity:
                raise ValueError("fill cache source or book version differs; choose a fresh path")
            return saved["fill_us"]
    members, _, _ = recognition_times(data)
    lookup = {int(data["oid"][i]): i for i in members}
    filled = np.full(len(data["oid"]), -1, dtype=np.int64)
    book = tape_book.Book()
    with Path(path).open() as fh:
        next(fh)
        for row in fh:
            ts, op, oid, side, qty, price, life = row.strip().split(",")
            oid = int(oid)
            if op == "Cancel":
                book.cancel(oid)
                continue
            fills = []
            book.insert(oid, 0 if side == "B" else 1, int(price), int(qty), life == "F", fills)
            if fills:
                now = integer_us(ts)
                for maker, _, _ in fills:
                    i = lookup.get(maker)
                    if i is not None and maker not in book.orders:
                        filled[i] = now
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, identity=np.array(identity), fill_us=filled)
    return filled


def poisson_fit(x, y):
    initial = np.zeros(x.shape[1])
    initial[0] = np.log(max(float(y.mean()), 1e-8))
    def objective(beta):
        eta = x @ beta
        # Convex linear continuation above 30 keeps the objective and gradient
        # consistent during line search without exponential overflow.
        mu = np.exp(np.minimum(eta, 30))
        loss = np.sum(mu + np.exp(30) * np.maximum(eta - 30, 0) - y * eta) + .01 * np.sum(beta[1:] ** 2)
        gradient = x.T @ (mu - y)
        gradient[1:] += .02 * beta[1:]
        return loss, gradient
    result = minimize(objective, initial, jac=True, method="L-BFGS-B", options={"maxiter": 500, "ftol": 1e-12})
    if not result.success:
        raise RuntimeError(f"intensity fit failed: {result.message}")
    return result.x


def block_interval(numerators, denominators, seed=37):
    """Paired 300-s block bootstrap; conditional on this tape, not independent runs."""
    a, b = np.asarray(numerators), np.asarray(denominators)
    if not len(a) or b.sum() <= 0:
        return None
    rng = np.random.default_rng(seed)
    ix = rng.integers(len(a), size=(2000, len(a)))
    den = b[ix].sum(axis=1)
    val = a[ix].sum(axis=1)[den > 0] / den[den > 0]
    return np.quantile(val, [.025, .975]).tolist()


def arrivals(data, split_us):
    _, _, batches = recognition_times(data)
    if len(batches) < 100:
        return {"status": "insufficient identified batches", "batches": len(batches)}
    n = int(data["end_us"] // 1_000_000)
    grid = np.arange(n) * 1_000_000
    recognized = np.array([data["time_us"][b[1]] for b in batches])
    y = np.histogram(recognized, bins=np.arange(n + 1) * 1_000_000)[0]
    raw = book_features(data, grid)
    train, test = (grid >= 30_000_000) & (grid < split_us), grid >= split_us
    mean, scale = raw[train].mean(axis=0), raw[train].std(axis=0)
    mean[0], scale[0] = 0., 1.
    scale[scale < 1e-8] = 1.
    x = (raw - mean) / scale
    beta = poisson_fit(x[train], y[train])
    pred = np.exp(np.clip(x @ beta, -30, 30))
    constant = float(y[train].mean())
    improvement = y * np.log(pred / constant) - pred + constant
    blocks = grid // 300_000_000
    labels = np.unique(blocks[test])
    gains = [float(improvement[test & (blocks == b)].sum()) for b in labels]
    durations = [int(np.sum(test & (blocks == b))) for b in labels]
    starts = np.array([b[0] for b in batches])
    sx = (book_features(data, data["time_us"][starts]) - mean) / scale
    sq = np.log(data["qty"][starts])
    st = data["time_us"][starts]
    tr, te = (st >= 30_000_000) & (recognized < split_us), st >= split_us
    qb = np.linalg.lstsq(sx[tr], sq[tr], rcond=None)[0]
    qerror = (sq[te] - sx[te] @ qb) ** 2
    qbase = (sq[te] - sq[tr].mean()) ** 2
    return {"features": FEATURES, "standardization_mean": mean.tolist(), "standardization_scale": scale.tolist(),
            "poisson_beta": beta.tolist(), "train_mean_batches_per_s": constant,
            "test_observed_batches_per_s": float(y[test].mean()), "test_predicted_batches_per_s": float(pred[test].mean()),
            "heldout_log_score_gain_per_s": float(improvement[test].mean()),
            "heldout_log_score_gain_ci95_300s_blocks": block_interval(gains, durations),
            "test_residual_dispersion": float(np.mean((y[test] - pred[test]) ** 2 / pred[test])),
            "test_constant_residual_dispersion": float(np.mean((y[test] - constant) ** 2 / constant)),
            "log_size_beta": qb.tolist(), "test_log_size_mse_constant": float(qbase.mean()),
            "test_log_size_mse_activity": float(qerror.mean()),
            "blocks_300s": [{"start_s": int(b * 300), "log_score_gain": gain, "seconds": dur}
                            for b, gain, dur in zip(labels, gains, durations)]}


def offset_bin(offset, own):
    d = np.asarray(offset)
    return np.where(own <= 0, 8, np.where(d < 0, 0, np.where(d < 2, d + 1,
                    np.where(d <= 4, 3, np.where(d <= 7, d - 1, 7))))).astype(int)


def risk_cells(data, filled, block_s=60):
    members, known, _ = recognition_times(data)
    end_us = int(data["end_us"])
    n_blocks = end_us // (block_s * 1_000_000) + 1
    shape = (n_blocks, *DIMENSIONS)
    exposure, events = np.zeros(shape), np.zeros(shape)
    grid = np.arange(end_us // 1_000_000 + 1) * 1_000_000
    activity = np.searchsorted(ACTIVITY_EDGES, np.rint(np.expm1(book_features(data, grid)[:, 1])), side="right")
    tt = data["touch_us"]
    summary = {"detected_orders": len(members), "at_risk_orders": 0, "cancel_events": 0,
               "filled_censors": 0, "end_censors": 0, "ended_before_recognition": 0}
    for i in members:
        inserted, entry, cancel, fill = int(data["time_us"][i]), int(known[i]), int(data["cancel_us"][i]), int(filled[i])
        end = min(cancel if cancel >= 0 else end_us, fill if fill >= 0 else end_us, end_us)
        if end <= entry:
            summary["ended_before_recognition"] += 1
            continue
        cancelled = cancel == end and (fill < 0 or fill > cancel) and data["cancel_remaining"][i] > 0
        summary["at_risk_orders"] += 1
        summary["cancel_events" if cancelled else "filled_censors" if fill == end else "end_censors"] += 1
        lo, hi = np.searchsorted(tt, [entry, end], side="right")
        ages = inserted + (AGE_EDGES * 1e6).astype(np.int64)
        inner_grid = np.arange(entry // 1_000_000 + 1, end // 1_000_000 + 1) * 1_000_000
        boundaries = np.unique(np.r_[entry, tt[lo:hi], ages[(ages > entry) & (ages < end)], inner_grid, end])
        boundaries = boundaries[(boundaries >= entry) & (boundaries <= end)]
        start, stop = boundaries[:-1], boundaries[1:]
        book_index = np.searchsorted(tt, start, side="right") - 1
        own = data["bid" if data["side"][i] == 0 else "ask"][book_index]
        sign = 1 if data["side"][i] == 0 else -1
        offset = sign * (own - data["price"][i])
        size = int(data["qty"][i] >= 80)
        initial = int(sign * (data["own"][i] - data["price"][i])) - 2
        block = start // (block_s * 1_000_000)
        age = np.searchsorted(AGE_EDGES, (start - inserted) / 1e6, side="right")
        state = (block, np.full(len(start), size), age, offset_bin(offset, own),
                 np.full(len(start), initial), activity[start // 1_000_000])
        np.add.at(exposure, state, (stop - start) / 1e6)
        if cancelled:
            # Left-limit state: the cancellation must not cause its own predictor.
            event_state = (end // (block_s * 1_000_000), *(int(a[-1]) for a in state[1:]))
            events[event_state] += 1
    return exposure, events, summary


def cancellation_models(exposure, events, split_us, block_s=60):
    models = {"constant": (), "size": (0,), "size_age": (0, 1), "size_initial_offset": (0, 3),
              "size_current_offset": (0, 2), "size_current_offset_activity": (0, 2, 4),
              "size_age_current_offset_activity": (0, 1, 2, 4)}
    split_block = int(split_us // (block_s * 1_000_000))
    if exposure[:split_block].sum() <= 0 or events[:split_block].sum() <= 0 or events[split_block:].sum() <= 0:
        return {"status": "insufficient cancellation exposure/events in both temporal folds", "models": {}}
    pooled = float(events[:split_block].sum() / exposure[:split_block].sum())
    scores, reports = {}, {}
    for name, keep in models.items():
        summed = tuple(1 + axis for axis in range(len(DIMENSIONS)) if axis not in keep)
        e, d = exposure.sum(axis=summed), events.sum(axis=summed)
        train_e, train_d = e[:split_block].sum(axis=0), d[:split_block].sum(axis=0)
        rate = (train_d + .5) / (train_e + .5 / pooled)
        likelihood = d * np.log(rate) - e * rate
        if likelihood.ndim > 1:
            likelihood = likelihood.sum(axis=tuple(range(1, likelihood.ndim)))
        scores[name] = likelihood[split_block:]
        expected = float((e[split_block:] * rate).sum())
        reports[name] = {"test_log_score": float(scores[name].sum()),
                         "test_expected_cancels": expected, "rate_per_s": np.asarray(rate).tolist()}
    # Keep only sufficiently observed holdout blocks; the last subsecond block has no meaningful exposure.
    counts = events[split_block:].sum(axis=tuple(range(1, events.ndim)))
    for name, report in reports.items():
        for baseline in ("constant", "size_age"):
            delta = scores[name] - scores[baseline]
            groups = np.arange(len(delta)) // max(1, 300 // block_s)
            nums = [float(delta[groups == g].sum()) for g in np.unique(groups)]
            dens = [float(counts[groups == g].sum()) for g in np.unique(groups)]
            report[f"gain_over_{baseline}_nats_per_cancel"] = float(delta.sum() / counts.sum())
            report[f"gain_over_{baseline}_ci95_300s_blocks"] = block_interval(nums, dens)
    return {"offset_bins": OFFSET_LABELS, "age_upper_edges_s": AGE_EDGES.tolist(),
            "activity_edges_changes_per_s": ACTIVITY_EDGES.tolist(), "size_groups": ["below80", "80plus"],
            "train_cancels": int(events[:split_block].sum()), "test_cancels": int(counts.sum()),
            "prior": "Half a cancellation per fitted cell, at pooled training rate",
            "models": reports,
            "current_offset_diagnostics": {
                part: {"exposure_s": exposure[sl].sum(axis=(0, 2, 4, 5)).tolist(),
                       "cancels": events[sl].sum(axis=(0, 2, 4, 5)).astype(int).tolist()}
                for part, sl in (("train", slice(None, split_block)), ("test", slice(split_block, None)))}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tape", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--fills-cache", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    started = time.monotonic()
    data = load(args.tape, args.cache)
    # A minute boundary keeps the risk exposure split exact.
    split_us = round(int(data["end_us"]) / 120_000_000) * 60_000_000
    if split_us < 300_000_000:
        parser.error("mechanism holdout needs at least 600 seconds")
    report = {"source": str(args.tape), "source_sha256": str(data["sha256"]), "split_s": split_us / 1e6,
              "caution": "Identified subset and hypotheses discovered on the full tape; temporal holdout tests fitted coefficients. Fills censor cancellation exposure. Conditional hazards do not establish an original causal policy.",
              "arrivals": arrivals(data, split_us)}
    filled = fill_times(args.tape, data, args.fills_cache)
    e, d, summary = risk_cells(data, filled)
    report["risk_population"] = summary
    report["cancellation"] = cancellation_models(e, d, split_us)
    report["elapsed_s"] = time.monotonic() - started
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cancellation"}, indent=2))
    for name, model in report["cancellation"]["models"].items():
        print(name, json.dumps({k: v for k, v in model.items() if k != "rate_per_s"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
