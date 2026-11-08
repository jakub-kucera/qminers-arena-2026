"""Identify scheduled limit-order ladders and their joint cancellation mechanics.

One market-book replay collects every G insert, its own-touch offset, existing
depth, scheduled cancel, and the book-touch timeline. Exact same-side timestamp
links at --gap-us (default 2,000) reveal candidate batches without a size model;
nearby lags are coincidence controls. These are identified subsets, not a claim
that every extra G order belongs to a detected chain. Singletons remain unlabelled.

Report size/lifetime dependence, sibling correlations, and the delay from the
first exit from a 2-7 tick placement band to cancellation. The exit check uses only
orders still resting at cancellation, so a previously filled order is not mistaken
for a cancellation policy. Sample selection and timing coincidences are explicit.
Cache metadata binds the source path, size, mtime and measurement version; reports
also include a SHA256 of the original CSV. No strategy runs or latent model needed.

    uv run python -m experiments.day.gen_ladders data/arena/round3/round3_public.csv \
        --cache data/arena/gen/r3_ladders.npz --json data/arena/gen/r3_ladders.json
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from experiments.day.gen_inventory import integer_us, quantiles
from experiments.day.tape_book import Book

VERSION = 1


def collect(path: Path) -> dict:
    book, active = Book(), {}
    names = ("time_us", "oid", "side", "qty", "price", "own", "opposite", "depth", "cancel_us", "cancel_offset", "cancel_remaining")
    out = {key: array("q") for key in names}
    touch = {key: array("q") for key in ("touch_us", "bid", "ask")}
    previous = (None, None)
    digest = hashlib.sha256()
    end_us = 0
    with path.open("rb") as fh:
        header = next(fh)
        if header.strip() != b"Time,Operation,OrderId,Side,Volume,Price,Lifespan":
            raise ValueError("unexpected tape header")
        digest.update(header)
        for line in fh:
            digest.update(line)
            t, op, oid, side, qty, price, life = line.decode().strip().split(",")
            now, oid = integer_us(t), int(oid)
            if now < end_us:
                raise ValueError("tape timestamps decrease")
            end_us = now
            if op == "Insert":
                sd, p, q = 0 if side == "B" else 1, int(price), int(qty)
                if life == "G":
                    i = len(out["time_us"])
                    active[oid] = i
                    vals = (now, oid, sd, q, p, book.best[sd] or 0, book.best[1 - sd] or 0,
                            book.depth(sd, p), -1, 0, -1)
                    for key, value in zip(names, vals):
                        out[key].append(value)
                book.insert(oid, sd, p, q, life == "F")
            elif op == "Cancel":
                i = active.pop(oid, None)
                if i is not None:
                    sd, p = out["side"][i], out["price"][i]
                    own = book.best[sd]
                    out["cancel_us"][i] = now
                    out["cancel_offset"][i] = ((own - p) if sd == 0 else (p - own)) if own is not None else -10**9
                removed = book.cancel(oid)
                if i is not None:
                    out["cancel_remaining"][i] = removed[2] if removed else 0
            else:
                raise ValueError(f"unsupported operation: {op}")
            current = tuple(book.best)
            if current != previous:
                touch["touch_us"].append(now)
                touch["bid"].append(current[0] or 0)
                touch["ask"].append(current[1] or 0)
                previous = current
    result = {key: np.asarray(value) for key, value in {**out, **touch}.items()}
    result["end_us"] = np.array(end_us)
    result["sha256"] = np.array(digest.hexdigest())
    return result


def load(path: Path, cache: Path | None) -> dict:
    stat = path.stat()
    key = json.dumps([VERSION, str(path.resolve()), stat.st_size, stat.st_mtime_ns])
    if cache and cache.exists():
        with np.load(cache, allow_pickle=False) as z:
            if "cache_key" in z and str(z["cache_key"]) == key:
                return {name: z[name] for name in z.files if name != "cache_key"}
        raise ValueError(f"cache does not match source/version: {cache}; choose a fresh cache path")
    result = collect(path)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, cache_key=np.array(key), **result)
    return result


def links(data: dict, gap_us: int, band_only: bool = True):
    if gap_us <= 0:
        raise ValueError("gap_us must be positive")
    t, side, price, own = (data[key] for key in ("time_us", "side", "price", "own"))
    j = np.searchsorted(t, t + gap_us)
    i = np.flatnonzero(j < len(t))
    j = j[i]
    keep = (t[j] - t[i] == gap_us) & (side[i] == side[j])
    if band_only:
        off = np.where(side == 0, own - price, price - own)
        valid = (own > 0) & (off >= 2) & (off <= 7)
        keep &= valid[i] & valid[j]
    return i[keep], j[keep]


def chains(n: int, left, right) -> list[np.ndarray]:
    previous, following = np.full(n, -1), np.full(n, -1)
    previous[right], following[left] = left, right
    out = []
    for start in left[previous[left] < 0]:
        chain = [start]
        nxt = following[start]
        while nxt >= 0:
            chain.append(nxt)
            nxt = following[nxt]
        out.append(np.array(chain, dtype=np.int64))
    return out


def corr(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    return float(np.corrcoef(x[ok], y[ok])[0, 1]) if ok.sum() > 1 and x[ok].std() and y[ok].std() else None


def pmf(a):
    return {str(k): int(v) for k, v in sorted(Counter(map(int, a)).items())}


def exit_delays(data: dict, indices, low: int = 2, high: int = 7) -> dict:
    """First observed out-of-band touch strictly after insertion, before cancel.

Touch updates at the cancellation timestamp are excluded: the cancel itself may
move the touch. NaNs/missing sides do not define a band exit.
"""
    tt, bids, asks = (data[k] for k in ("touch_us", "bid", "ask"))
    selected = indices[(data["cancel_remaining"][indices] > 0) & (data["cancel_us"][indices] >= 0)]
    delay, no_exit = [], 0
    for i in selected:
        lo = np.searchsorted(tt, data["time_us"][i], side="right")
        hi = np.searchsorted(tt, data["cancel_us"][i], side="left")
        side, price = data["side"][i], data["price"][i]
        own = bids[lo:hi] if side == 0 else asks[lo:hi]
        offset = own - price if side == 0 else price - own
        outside = np.flatnonzero((own > 0) & ((offset < low) | (offset > high)))
        if len(outside):
            delay.append((data["cancel_us"][i] - tt[lo + outside[0]]) / 1e6)
        else:
            no_exit += 1
    delay = np.array(delay)
    return {"band": [low, high], "resting_cancels": len(selected), "no_prior_exit": no_exit,
            "delay_after_first_exit_s": quantiles(delay),
            "cancel_within_0.2s_of_first_exit_share": float((delay <= .2).sum() / len(selected)) if len(selected) else None}


def measure(data: dict, gap_us: int = 2000) -> dict:
    if not len(data["time_us"]):
        raise ValueError("tape has no G orders")
    t, s, q, p, own, cancel = (data[k] for k in ("time_us", "side", "qty", "price", "own", "cancel_us"))
    duration = (int(data["end_us"]) - t[0]) / 1e6
    if duration <= 0:
        raise ValueError("tape must have positive duration")
    off = np.where(s == 0, own - p, p - own)
    life = np.where(cancel >= 0, (cancel - t) / 1e6, np.nan)
    left, right = links(data, gap_us)
    batches = chains(len(t), left, right)
    members = np.unique(np.r_[left, right])
    out = {"source_sha256": str(data["sha256"]), "duration_s": duration, "g_orders": len(t),
           "gap_us": gap_us, "timing_controls": {}, "candidate_chains": len(batches),
           "candidate_orders": len(members), "chain_length_counts": pmf([len(b) for b in batches]),
           "chain_start_offsets": pmf(off[[b[0] for b in batches]]) if batches else {},
           "candidate_insert_offset_counts": pmf(off[members]),
           "caution": "Exact same-side 2-7 tick links identify subsets, with coincidence controls; singletons and broken chains remain unlabelled."}
    for lag in sorted({1000, 2000, 3000, 4000, 5000, 6000, 8000, 10000, gap_us}):
        a, b = links(data, lag)
        aa, bb = links(data, lag, band_only=False)
        out["timing_controls"][str(lag)] = {"all_same_side_pairs": len(aa), "band_pairs": len(a)}
    if not len(members):
        return out
    out["pairs"] = {"n": len(left), "outward_price_step_counts": pmf(np.where(s[left] == 0, p[left] - p[right], p[right] - p[left])),
                    "log_size_correlation": corr(np.log(q[left]), np.log(q[right])),
                    "lifetime_correlation": corr(life[left], life[right]),
                    "log_size_difference_sd": float(np.std(np.log(q[left]) - np.log(q[right]))) }
    out["populations"] = {}
    for label, indices in (("all", members), ("size_below_80", members[q[members] < 80]),
                           ("size_at_least_80", members[q[members] >= 80])):
        if not len(indices):
            continue
        ended = indices[cancel[indices] >= 0]
        c_off = data["cancel_offset"][ended]
        out["populations"][label] = {
            "n": len(indices), "rate_per_s": len(indices) / duration,
            "qty": quantiles(q[indices]), "lifetime_s": quantiles(life[ended]),
            "preexisting_depth": quantiles(data["depth"][indices]),
            "quantity_vs_preexisting_depth_corr": corr(q[indices], data["depth"][indices]),
            "right_censored": len(indices) - len(ended),
            "still_resting_at_cancel_share": float((data["cancel_remaining"][ended] > 0).mean()) if len(ended) else None,
            "cancel_offset_counts": pmf(c_off),
            "exit_check": exit_delays(data, indices)}
    out["segments_60s"] = []
    starts = np.array([b[0] for b in batches])
    for lo in range(0, int(data["end_us"] / 1e6), 60):
        ix = members[(t[members] >= lo * 1e6) & (t[members] < (lo + 60) * 1e6)]
        st = starts[(t[starts] >= lo * 1e6) & (t[starts] < (lo + 60) * 1e6)]
        out["segments_60s"].append({"start_s": lo, "candidate_orders": len(ix), "candidate_starts": len(st),
                                    "qty_median": float(np.median(q[ix])) if len(ix) else None,
                                    "large_share": float((q[ix] >= 80).mean()) if len(ix) else None})
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tape", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--gap-us", type=int, default=2000)
    args = parser.parse_args(argv)
    if args.gap_us <= 0:
        parser.error("--gap-us must be positive")
    report = measure(load(args.tape, args.cache), args.gap_us)
    report["source"] = str(args.tape)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("segments_60s", "populations")}, indent=2))
    for label, p in report.get("populations", {}).items():
        print(label, json.dumps({k: v for k, v in p.items() if k != "cancel_offset_counts"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
