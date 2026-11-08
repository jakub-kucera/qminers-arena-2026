"""A forecast taker's quote and take fills by the state at the fill (8 Nov, round 3's audit of R3-F3's order handling).

Inputs: a full-logs run of the Arena simulator (`exchange-simulator --strategy FILE --backtest TAPE --log-dir DIR`, no
--no-logs: trades.csv and events.csv) and the Rust twin's RIDGE_PRED_LOG of the same bot on the same tape with
RIDGE_PRED_EXTRA set (each book event's time, mid, prediction, skew, spread, inventory, the latent filter's gap and
QS_RATE's speed; the twin is byte-identical, so the events line up):

    RIDGE_PRED_LOG=pred.csv RIDGE_PRED_EXTRA=1 rust/target/release/arena-sim --backtest TAPE --strategy ridge_maker \
        --params '<the bot as JSON>' --log-dir DIR2
    uv run python -m experiments.day.quote_audit DIR pred.csv [--qs-rate 2.5]

For each of our fills (trades.csv: a maker fill is a quote, a taker fill a take), the state at the last book event
before it; per bucket the fills, lots, the edge at the fill against the mid and the markout (mid h s later minus the
price, our way) a lot and in all at 1 / 5 / 30 s. Quote buckets: the filter's gap our way, QS_RATE's switch (a quote
filled while the speed is at or above QS_RATE rests from before the switch turned off), the forecast our way, the
spread, whether the fill adds to or reduces the position. Fills after our cancel was sent (the cancel lost the race)
are a bucket of their own. Standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from collections import defaultdict

HORIZONS = (1.0, 5.0, 30.0)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("log_dir")
    ap.add_argument("pred")
    ap.add_argument("--qs-rate", type=float, default=2.5)
    a = ap.parse_args(argv)
    t_, mid_, pred_, skew_, spread_, inv_, gap_, qs_ = ([] for _ in range(8))
    with open(a.pred) as f:
        for line in f:
            r = line.rstrip().split(",")
            if len(r) < 8:
                raise SystemExit("the pred log needs RIDGE_PRED_EXTRA=1 (8 columns)")
            t_.append(int(r[0])); mid_.append(float(r[1])); pred_.append(float(r[2])); skew_.append(float(r[3]))
            spread_.append(int(float(r[4]))); inv_.append(int(r[5])); gap_.append(float(r[6])); qs_.append(float(r[7]))

    def mid_at(t: int) -> float:
        return mid_[max(0, bisect.bisect_right(t_, t) - 1)]

    cancel_sent: dict[str, int] = {}
    with open(f"{a.log_dir}/events.csv") as f:
        for row in csv.DictReader(f):
            if row["source"] == "user" and row["operation"] == "cancel_sent":
                cancel_sent.setdefault(row["order_id"], int(row["timestamp_us"]))
    agg: dict[tuple[str, str], list] = defaultdict(lambda: [0, 0, 0.0, [0.0] * len(HORIZONS)])

    def add(key: tuple[str, str], t: int, price: int, lots: int, side: int) -> None:
        row = agg[key]
        row[0] += 1
        row[1] += lots
        row[2] += lots * side * (mid_at(t) - price)
        for j, h in enumerate(HORIZONS):
            row[3][j] += lots * side * (mid_at(t + int(h * 1e6)) - price)

    with open(f"{a.log_dir}/trades.csv") as f:
        for row in csv.DictReader(f):
            maker, taker = row["maker_owner"] == "user", row["taker_owner"] == "user"
            if not (maker or taker):
                continue
            t, price, lots = int(row["timestamp_us"]), int(row["price"]), int(row["quantity"])
            taker_buys = row["taker_side"] == "B"
            side = (1 if taker_buys else -1) if taker else (-1 if taker_buys else 1)
            role = "take" if taker else "quote"
            i = bisect.bisect_left(t_, t) - 1
            if i < 0:
                continue
            add((role, "all"), t, price, lots, side)
            oid = row["taker_order_id"] if taker else row["maker_order_id"]
            if oid in cancel_sent and cancel_sent[oid] <= t:
                add((role, "after our cancel"), t, price, lots, side)
            if taker:
                continue
            g = gap_[i] * side
            add((role, "gap " + ("with >0.5" if g > 0.5 else "with 0-0.5" if g > 0 else
                                 "against 0-0.5" if g > -0.5 else "against >0.5")), t, price, lots, side)
            add((role, "switch " + ("off (resting)" if qs_[i] >= a.qs_rate else "on")), t, price, lots, side)
            fc = (pred_[i] - skew_[i]) * side
            add((role, "forecast " + ("with >0.18" if fc > 0.18 else "within 0.18" if fc >= -0.18 else
                                      "against >0.18")), t, price, lots, side)
            add((role, f"spread {min(spread_[i], 3)}"), t, price, lots, side)
            add((role, "position " + ("reducing" if inv_[i] * side < 0 else "adding" if inv_[i] * side > 0 else
                                      "flat")), t, price, lots, side)
    print(f"{'role':6} {'bucket':22} {'fills':>7} {'lots':>8} {'edge/lot':>9} "
          + " ".join(f"{'%gs/lot' % h:>8} {'%gs all' % h:>9}" for h in HORIZONS))
    for key in sorted(agg):
        n, lots, edge, moves = agg[key]
        print(f"{key[0]:6} {key[1]:22} {n:7d} {lots:8d} {edge / lots:9.3f} "
              + " ".join(f"{m / lots:8.3f} {m:9.0f}" for m in moves))


if __name__ == "__main__":
    main()
