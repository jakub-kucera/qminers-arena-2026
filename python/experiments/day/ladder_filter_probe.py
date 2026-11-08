"""Does causal identification of G ladders improve the real-tape latent forecast?

Replay the existing LatentFilter at F3's fixed settings (impact_scale=3, depth=6)
on identical market events. Arms: baseline; omit only the current G when a valid
same-side predecessor occurred exactly 2 ms ago; omit every G 2-7 ticks behind
own touch; omit full-chain members (explicitly NONCAUSAL oracle diagnostic); and
a 1-ms clock control. An explicitly exploratory extension, added after seeing
the primary holdout, delays all filter messages by2ms so earlier batch children
can be identified causally; it has an equally delayed baseline. Omitted observations still enter the market book, and all
filters still advance/recenter identically. No bot or Rust strategy is changed.

Sample every 50 ms before the event at that timestamp. Regressions are fitted on
the first half, purging labels that cross its boundary, then frozen. Predict
0.4/1-s mid changes on the second half. Primary F3-style regression has intercept,
touch imbalance, gap, gap*abs(gap)/3 and posterior sd. Also report a gap-only
linear calibration and raw-gap correlations. Paired errors use 300-s holdout
blocks, with a block bootstrap interval; no trading-profit claim is made.

    uv run python -m experiments.day.ladder_filter_probe data/arena/round3/round3_public.csv \
        --ladder-cache data/arena/gen/gen_v3_r3_ladders.npz \
        --out data/arena/gen/ladder_mechanics/filter_r3.json \
        --rows-out data/arena/gen/ladder_mechanics/filter_r3_rows.npz

The oracle arm uses future chain membership and must never be used as an online
feature. No mask uses size, cancellation time, future price or future return.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from experiments.day.gen_inventory import integer_us
from experiments.day.gen_ladders import links, load
from experiments.day.latent_filter import LatentFilter
from experiments.day.tape_book import Book

PRIMARY_ARMS = ("baseline", "clock_2ms", "band_2_7", "oracle_chain", "clock_1ms")
ARMS = PRIMARY_ARMS + ("delayed_baseline_2ms", "delayed_clock_2ms")
FILTER_PARAMS = {"impact_scale": 3.0, "depth": 6}
STEP_US = 50_000


class CausalClock:
    """Current-order recognition only; no earlier observation is retroactively removed."""

    def __init__(self, gap_us=2000):
        if gap_us <= 0:
            raise ValueError("gap_us must be positive")
        self.gap_us = gap_us
        self.seen = {}
        self.times = deque()
        self.last = -1

    def observe(self, now_us, side, offset):
        if now_us < self.last:
            raise ValueError("timestamps decrease")
        self.last = now_us
        prior = now_us - self.gap_us
        while self.times and self.times[0] < prior:
            del self.seen[self.times.popleft()]
        valid = offset is not None and 2 <= offset <= 7
        recognized = valid and side in self.seen.get(prior, ())
        if valid:
            if now_us not in self.seen:
                self.seen[now_us] = set()
                self.times.append(now_us)
            self.seen[now_us].add(side)
        return recognized


class DelayedFilters:
    """Exploratory causal lookback: hold all filter messages for exactly 2 ms.

The current child's arrival can mark its queued predecessor before that older
message is processed. Samples BEFORE a current event flush only deadlines
strictly earlier than the sample; the event cannot label its predecessor early.
Both filters receive identical old book references/trades and the same delay.
"""

    def __init__(self, delay_us=2000):
        self.delay_us = delay_us
        self.filters = [LatentFilter(**FILTER_PARAMS) for _ in range(2)]
        self.pending, self.lookup = deque(), {}
        self.recognized = self.dropped = 0

    def insert(self, now_us, side, price, bid, ask, recognized):
        if recognized:
            prior = self.lookup.get((now_us - self.delay_us, side))
            if prior is None:
                raise RuntimeError("predecessor was processed before its identifying child arrived")
            prior[6] = True
        row = [now_us, "G", side, price, bid, ask, bool(recognized)]
        self.pending.append(row)
        self.lookup[(now_us, side)] = row

    def trade(self, now_us, side, lots):
        if lots:
            self.pending.append([now_us, "F", side, lots, None, None, False])

    def flush(self, until_us, inclusive):
        while self.pending:
            deadline = self.pending[0][0] + self.delay_us
            if deadline > until_us or (deadline == until_us and not inclusive):
                break
            now, kind, side, value, bid, ask, masked = self.pending.popleft()
            if kind == "G":
                del self.lookup[(now, side)]
                self.recognized += int(masked)
                if bid is None or ask is None or bid >= ask:
                    continue
                own = bid if side == 0 else ask
                for i, filt in enumerate(self.filters):
                    if filt.p is None:
                        filt.reset(bid)
                    filt.advance(now / 1e6)
                    filt.recenter(bid)
                    if abs(value - own) <= filt.depth:
                        if i == 1 and masked:
                            self.dropped += 1
                        else:
                            filt.insert(side, value, bid, ask)
            else:
                for filt in self.filters:
                    if filt.p is not None:
                        filt.advance(now / 1e6)
                        filt.trade(1 if side == 0 else -1, value)


def replay(path: Path, oracle_ids: set[int]):
    book = Book()
    filters = [LatentFilter(**FILTER_PARAMS) for _ in PRIMARY_ARMS]
    delayed = DelayedFilters()
    all_filters = filters + delayed.filters
    clock, control = CausalClock(2000), CausalClock(1000)
    dropped = {arm: 0 for arm in ARMS}
    recognized = {arm: 0 for arm in ARMS}
    rows, next_us, g_orders, end_us = [], STEP_US, 0, -1
    source_hash = hashlib.sha256()
    with path.open("rb") as fh:
        header = next(fh)
        source_hash.update(header)
        if header.strip() != b"Time,Operation,OrderId,Side,Volume,Price,Lifespan":
            raise ValueError("unexpected tape header")
        for line in fh:
            source_hash.update(line)
            t, op, oid, side, qty, price, life = line.decode().strip().split(",")
            now_us = integer_us(t)
            if now_us <= end_us:
                raise ValueError("this causal clock probe requires strictly increasing tape timestamps")
            end_us = now_us
            bb, ba = book.best
            while next_us <= now_us:
                delayed.flush(next_us, inclusive=False)
                if bb is not None and ba is not None and bb < ba and all(f.p is not None for f in all_filters):
                    mid = (bb + ba) / 2
                    bq, aq = book.depth(0, bb), book.depth(1, ba)
                    marks = []
                    for filt in all_filters:
                        mean, sd = filt.moments()
                        marks.extend((mean + .5 - mid, sd))
                    rows.append((next_us, mid, (bq - aq) / (bq + aq), ba - bb, *marks))
                next_us += STEP_US
            oid = int(oid)
            if op == "Insert":
                sd, p, q = 0 if side == "B" else 1, int(price), int(qty)
                if life == "F":
                    lots = book.insert(oid, sd, p, q, True)
                    delayed.trade(now_us, sd, lots)
                    if lots and filters[0].p is not None:
                        for filt in filters:
                            filt.advance(now_us / 1e6)
                            filt.trade(1 if sd == 0 else -1, lots)
                elif life == "G":
                    g_orders += 1
                    own = bb if sd == 0 else ba
                    off = ((own - p) if sd == 0 else (p - own)) if own is not None else None
                    masks = (False, clock.observe(now_us, sd, off), off is not None and 2 <= off <= 7,
                             oid in oracle_ids, control.observe(now_us, sd, off))
                    delayed.insert(now_us, sd, p, bb, ba, masks[1])
                    for arm, masked in zip(PRIMARY_ARMS, masks):
                        recognized[arm] += int(masked)
                    if bb is not None and ba is not None and bb < ba:
                        for arm, filt, masked in zip(PRIMARY_ARMS, filters, masks):
                            if filt.p is None:
                                filt.reset(bb)
                            filt.advance(now_us / 1e6)
                            filt.recenter(bb)
                            if abs(p - own) <= filt.depth:
                                if masked:
                                    dropped[arm] += 1
                                else:
                                    filt.insert(sd, p, bb, ba)
                    book.insert(oid, sd, p, q, False)
                else:
                    raise ValueError(f"unexpected lifespan {life}")
            elif op == "Cancel":
                book.cancel(oid)
            else:
                raise ValueError(f"unexpected operation {op}")
            delayed.flush(now_us, inclusive=True)
    recognized["delayed_clock_2ms"] = delayed.recognized
    dropped["delayed_clock_2ms"] = delayed.dropped
    info = {"source_sha256": source_hash.hexdigest(), "duration_s": end_us / 1e6, "g_orders": g_orders,
            "recognized_g": recognized, "dropped_observations": dropped,
            "observed_g": {arm: filt.n_obs for arm, filt in zip(ARMS, all_filters)}}
    return np.asarray(rows), info


def targets(rows, horizon_us, split_us, warmup_us=10_000_000):
    """Exact timestamps avoid silently shifting labels if a sample had an empty book."""
    stamps = rows[:, 0].astype(np.int64)
    j = np.searchsorted(stamps, stamps + horizon_us)
    i = np.flatnonzero(j < len(stamps))
    j = j[i]
    ok = (stamps[j] == stamps[i] + horizon_us) & (stamps[i] >= warmup_us)
    i, j = i[ok], j[ok]
    y = rows[j, 1] - rows[i, 1]
    train = stamps[j] < split_us  # purge target windows crossing the train boundary
    test = stamps[i] >= split_us
    return i, y, train, test


def correlation(a, b):
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 1 and np.std(a) and np.std(b) else None


def metrics(y, prediction):
    error = prediction - y
    mse = float(np.mean(error ** 2))
    return {"n": len(y), "mse": mse, "rmse": mse ** .5,
            "r2": float(1 - mse / np.var(y)) if np.var(y) else None,
            "corr": correlation(prediction, y), "bias": float(error.mean())}


def paired_blocks(times_us, errors, baseline, block_s=300, bootstrap_seed=731):
    block_ids = (times_us / (block_s * 1e6)).astype(int)
    unique = np.unique(block_ids)
    rows = []
    for block in unique:
        take = block_ids == block
        delta = errors[take] ** 2 - baseline[take] ** 2
        rows.append({"start_s": int(block * block_s), "n": int(take.sum()), "delta_mse": float(delta.mean())})
    delta = np.array([row["delta_mse"] for row in rows])
    weights = np.array([row["n"] for row in rows])
    rng = np.random.default_rng(bootstrap_seed)
    draws = rng.integers(len(rows), size=(4000, len(rows)))
    boot = np.sum(delta[draws] * weights[draws], axis=1) / np.sum(weights[draws], axis=1)
    return {"delta_mse": float(np.mean(errors ** 2 - baseline ** 2)),
            "blocks": rows, "blocks_improved": int((delta < 0).sum()),
            "block_mean_se": float(delta.std(ddof=1) / len(delta) ** .5) if len(delta) > 1 else None,
            "block_bootstrap_ci95": np.quantile(boot, [.025, .975]).tolist(),
            "caution": "Dependent 50-ms samples are grouped in 300-s blocks; few blocks limit interval precision."}


def evaluate(rows, duration_s, split_fraction=.5):
    if not 0 < split_fraction < 1:
        raise ValueError("split_fraction must be in (0, 1)")
    split_us = int(duration_s * split_fraction * 1e6)
    report = {"split_s": split_us / 1e6, "train_fraction": split_fraction, "horizons": {}}
    for horizon in (.4, 1.):
        ix, y, train, test = targets(rows, round(horizon * 1e6), split_us)
        if train.sum() < 20 or test.sum() < 20:
            raise ValueError("insufficient samples in both halves after target purge")
        answer = {"train_n": int(train.sum()), "test_n": int(test.sum()), "arms": {}}
        baseline_errors, delayed_errors = {}, {}
        for arm_index, arm in enumerate(ARMS):
            gap, sd = rows[ix, 4 + 2 * arm_index], rows[ix, 5 + 2 * arm_index]
            imb = rows[ix, 2]
            models = {"gap_only": np.column_stack([np.ones(len(ix)), gap]),
                      "f3_style": np.column_stack([np.ones(len(ix)), imb, gap, gap * abs(gap) / 3, sd])}
            scores = {"gap_corr_train": correlation(gap[train], y[train]),
                      "gap_corr_holdout": correlation(gap[test], y[test])}
            for name, x in models.items():
                beta, *_ = np.linalg.lstsq(x[train], y[train], rcond=None)
                prediction = x @ beta
                error = prediction[test] - y[test]
                score = {"coefficients_train_only": beta.tolist(), "train": metrics(y[train], prediction[train]),
                         "holdout": metrics(y[test], prediction[test])}
                if arm == "baseline":
                    baseline_errors[name] = error
                score["paired_vs_baseline"] = paired_blocks(rows[ix[test], 0], error, baseline_errors[name])
                if arm == "delayed_baseline_2ms":
                    delayed_errors[name] = error
                if arm == "delayed_clock_2ms":
                    score["paired_vs_delayed_baseline"] = paired_blocks(rows[ix[test], 0], error, delayed_errors[name])
                scores[name] = score
            answer["arms"][arm] = scores
        report["horizons"][str(horizon)] = answer
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tape", type=Path)
    parser.add_argument("--ladder-cache", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rows-out", type=Path)
    args = parser.parse_args(argv)
    started = time.monotonic()
    data = load(args.tape, args.ladder_cache)
    left, right = links(data, 2000)
    members = np.unique(np.r_[left, right])
    oracle_ids = set(map(int, data["oid"][members]))
    rows, info = replay(args.tape, oracle_ids)
    if info["source_sha256"] != str(data["sha256"]):
        raise ValueError("source changed since the ladder replay; choose a fresh ladder cache")
    report = {"source": str(args.tape), **info, "arms": list(ARMS), "filter_params": FILTER_PARAMS,
              "sampling_step_s": STEP_US / 1e6, "oracle_noncausal": "oracle_chain",
              "exploratory_after_primary_results": ["delayed_baseline_2ms", "delayed_clock_2ms"],
              "caution": "Forecast ablation, not bot PnL or private-tape evidence. Coefficients use first-half training only; the fixed 2-ms detection rule was discovered previously using the full public tape.",
              "evaluation": evaluate(rows, info["duration_s"]), "elapsed_s": time.monotonic() - started}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if args.rows_out:
        args.rows_out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.rows_out, rows=rows, source_sha256=np.array(info["source_sha256"]),
                            arms=np.array(ARMS), columns=np.array(["time_us", "mid", "imbalance", "spread"]
                            + [f"{arm}_{mark}" for arm in ARMS for mark in ("gap", "sd")]))
    for horizon, result in report["evaluation"]["horizons"].items():
        print(f"horizon={horizon}s, train={result['train_n']}, holdout={result['test_n']}")
        for arm, score in result["arms"].items():
            model = score["f3_style"]
            print(arm, json.dumps({"raw_gap_corr": score["gap_corr_holdout"], **model["holdout"],
                                  "delta_mse": model["paired_vs_baseline"]["delta_mse"],
                                  "ci95": model["paired_vs_baseline"]["block_bootstrap_ci95"]}))
    print(f"elapsed={report['elapsed_s']:.1f}s; {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
