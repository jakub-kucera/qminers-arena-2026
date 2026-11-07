"""How much of a strategy's PnL on the Arena's simulator comes from replay artefacts (the gray area, ON_THE_DAY.md).

    uv run python -m experiments.qsim_gray BOT DATA.csv [--set NAME=VALUE ...] [--no-created] [--out DIR]

Runs `BOT` through `simulator.simulator.ExchangeSimulator` at the rules' settings (arena.qgrid.config), with two additions:
- **Counts** of our maker fills by their taker: an `F` (IOC) or `G` (resting) tape insert that also crosses the market's own
  best opposite price ("real": in the recorded market it traded too) or crosses only our order ("created": a quote of ours
  inside the spread, which the tape's insert, passive in reality, trades against as a taker first, simulator.py:926); our
  taker fills; and the lots of a tape `G` taker's remainder that rests beyond what it would have rested without us
  ("ghost": liquidity we consumed first, simulator.py:1063).
- `--no-created`: the counterfactual in which a tape insert that does not cross the market's own best does not trade
  with our orders either (an `F` row is dropped, a `G` row rests), so the PnL difference against a plain run is what the
  created-liquidity fills are worth.
`--out DIR` writes result.json and pnl.csv (1-s samples) as exchange-simulator does, for experiments.pnl_segments.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arena.botfile import BotFile, parse_override
from arena.qgrid import config, strategy_class


def make_sim(strategy, no_created: bool):
    from simulator.models import LiveOrder, MarketOperation, OrderType, Side
    from simulator.simulator import ExchangeSimulator

    class GraySim(ExchangeSimulator):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.stats = {k: 0 for k in ("F_real", "G_real", "F_created", "G_created", "user_taker", "ghost_lots", "skipped")}
            self._class = None

        def _process_market_event(self, event):
            if event.operation != MarketOperation.INSERT:
                return super()._process_market_event(event)
            order = LiveOrder(order_id=event.order_id, owner="market", side=event.side, price=event.price,
                              initial_quantity=event.volume, remaining_quantity=event.volume,
                              order_type=event.order_type, created_at_us=event.timestamp_us)
            # What it would do against the market's own orders: whether it crosses, and the lots it would rest.
            opposite = Side.SELL if order.side == Side.BUY else Side.BUY
            left = order.remaining_quantity
            crosses_market = False
            for maker in self.book.iter_levels(opposite):
                if maker.owner != "market":
                    continue
                if not (order.price >= maker.price if order.side == Side.BUY else order.price <= maker.price):
                    break
                crosses_market = True
                left -= min(left, maker.remaining_quantity)
                if left == 0:
                    break
            kind = "F" if order.order_type == OrderType.IOC else "G"
            self._class = f"{kind}_{'real' if crosses_market else 'created'}"
            if no_created and not crosses_market:
                if self.book.best_opposite_order(order.side, allow_user_orders=True) is not None and \
                        self._would_cross_user(order):
                    self.stats["skipped"] += 1
            else:
                self._execute_taker(order)
            self._class = None
            if order.order_type == OrderType.LIMIT and order.remaining_quantity > 0:
                if order.remaining_quantity > left:
                    self.stats["ghost_lots"] += order.remaining_quantity - left
                self._rest(order)

        def _would_cross_user(self, order):
            maker = self.book.best_opposite_order(order.side, allow_user_orders=True)
            return order.price >= maker.price if order.side == Side.BUY else order.price <= maker.price

        def _notify_fill(self, order, quantity, price):
            if order.owner == "user":
                if self._class is None:
                    self.stats["user_taker"] += quantity
                else:
                    self.stats[self._class] += quantity
            super()._notify_fill(order, quantity, price)

    return GraySim(strategy=strategy, config=config())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bot", type=Path)
    parser.add_argument("data", type=Path)
    parser.add_argument("--set", action="append", default=[], type=parse_override, dest="overrides")
    parser.add_argument("--no-created", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    module = BotFile(args.bot, {}, dict(args.overrides)).load()
    sim = make_sim(strategy_class(module)(), args.no_created)
    result = sim.run(args.data)
    print(f"pnl {result.pnl:,.0f}  penalty {result.breach_penalty:,.0f}  fills {result.fills:,}  volume {result.traded_volume:,}")
    print("our lots by taker:", ", ".join(f"{k} {v:,}" for k, v in sim.stats.items()))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "result.json").write_text(json.dumps(result.model_dump(mode="json"), indent=2))
        start = None
        lines = ["elapsed_s,pnl"]
        for ts_us, pnl in sim.pnl_curve(result.pnl):
            start = ts_us if start is None else start
            lines.append(f"{(ts_us - start) / 1e6},{pnl}")
        (args.out / "pnl.csv").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
