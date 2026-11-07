"""Charts and fill statistics for backtest output (the CSVs from `arena.backtest --out`).

Needs the dev dependencies (pandas, matplotlib). In a notebook:

    from arena import analysis
    run = analysis.load_run("results", "r1d0")
    analysis.plot_pnl(run)
    analysis.plot_product(run, "KELP", start=200_000, end=230_000)
    analysis.markouts(run)                          # against the mark (the data's mid)
    analysis.markouts(run, reference="wall_mid")    # against the market maker's quotes
    analysis.pnl_split(run)                         # PnL = spread captured + inventory carry
    analysis.trade_impact(run)                      # how the price moves after market trades

From the command line, saving PNGs to <results>/plots/ and printing the tables:

    uv run python -m arena.analysis results/                # every day in the folder
    uv run python -m arena.analysis results/ r1d0 --start 200000 --end 230000
    uv run python -m arena.analysis results/ --reference wall_mid
    uv run python -m arena.analysis --grid results/grid.csv

Markouts measure adverse selection. For each fill, take the reference price h ticks later minus
the fill price (flipped for sells), per unit. If it shrinks as h grows, prices tend to move
against you right after you trade: the fills you get are the ones better-informed traders wanted
to give you.

The reference is the mark (what PnL is valued at; in the Prosperity format, the data's mid) or the
wall mid (the midpoint of the largest level on each side). On Prosperity data the mid is mostly
noise at one tick and the wall mid much less so (references/wiki/concepts/price-impact.md), so a
markout against the mid mixes that noise into what looks like adverse selection.
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib as mpl
import numpy as np
import pandas as pd
from cycler import cycler
from matplotlib.colors import LinearSegmentedColormap, Normalize, TwoSlopeNorm, to_rgb
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import FuncFormatter

# Ticks after a fill. Not 0: the mid at the fill tick still contains the order you just took.
DEFAULT_HORIZONS = (1, 2, 5, 10, 20, 50, 100, 200, 500)
SOURCES = {"book": "took", "trade": "passive", "cross": "passive"}  # Fill.source -> fill type
TYPES = ("took", "passive")
REFERENCES = ("mark", "wall_mid")  # prices fills and trades are measured against
IMPACT_HORIZONS = (1, 2, 5, 20, 50)
MAX_SERIES = 7  # products drawn individually; the rest fold into "other"

# Categorical slots validated (CVD and contrast) with the dataviz palette checker, per theme.
# Three light-mode slots sit below 3:1 contrast, so every chart keeps a legend and the tables
# (fill_summary, markouts) carry the values.
THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "midpoint": "#f0efec",
        "series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
        "ramp": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
        "loss": "#e34948",
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#ffffff",
        "secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "midpoint": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
        "ramp": ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
        "loss": "#e66767",
    },
}
_theme = "light"


def set_theme(name: str) -> None:
    """Switch every chart drawn afterwards to the "light" or "dark" theme."""
    global _theme
    if name not in THEMES:
        raise ValueError(f"theme must be one of {', '.join(THEMES)}")
    _theme = name


def _t() -> dict:
    return THEMES[_theme]


class Chart(Figure):
    """A matplotlib Figure that shows itself in notebooks without pyplot, in the theme it was drawn in."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rc = _rc_params()

    def savefig(self, *args, **kwargs):
        kwargs.setdefault("facecolor", self.get_facecolor())
        with mpl.rc_context(self._rc):
            return super().savefig(*args, **kwargs)

    def _repr_png_(self):
        dpi = self._rc["figure.dpi"]
        buffer = io.BytesIO()
        self.savefig(buffer, format="png", dpi=dpi * 2)  # 2x for sharp display on high-density screens
        width, height = self.get_size_inches() * dpi
        return buffer.getvalue(), {"width": int(width), "height": int(height)}


# ---------------------------------------------------------------------------- loading


@dataclass
class Run:
    """One backtested day, as written by `arena.backtest --out`."""

    day: str
    timeline: pd.DataFrame  # timestamp, product, position, mark, pnl, best_bid, best_ask, limit
    fills: pd.DataFrame  # timestamp, product, price, quantity, source, counterparty, order_id
    orders: pd.DataFrame  # timestamp, id, product, price, quantity
    trades: pd.DataFrame  # the data's market trades: timestamp, product, price, quantity, buyer, seller

    @property
    def colors(self) -> dict[str, str]:
        """Product -> series color, the same in every chart of the run.

        The MAX_SERIES products with the largest |pnl| get a slot, in alphabetical order; charts
        fold the rest into "other".
        """
        final = self.final_pnl()
        ranked = sorted(self.products, key=lambda p: (-abs(final.get(p, 0.0)), p))
        return {product: _t()["series"][i] for i, product in enumerate(sorted(ranked[:MAX_SERIES]))}

    @property
    def products(self) -> list[str]:
        """Products that traded or held a position."""
        held = self.timeline.loc[self.timeline["position"] != 0, "product"]
        return sorted(set(self.fills["product"]) | set(held))

    def series(self, product: str, start: int | None = None, end: int | None = None) -> pd.DataFrame:
        """One product's timeline, indexed by timestamp, optionally cut to [start, end]."""
        rows = self.timeline[self.timeline["product"] == product].set_index("timestamp").sort_index()
        return rows.loc[start:end]

    def final_pnl(self) -> dict[str, float]:
        last = self.timeline.sort_values("timestamp").groupby("product")["pnl"].last()
        return last.to_dict()


def days_in(out_dir: str | Path) -> list[str]:
    return sorted(path.name.removesuffix("_timeline.csv") for path in Path(out_dir).glob("*_timeline.csv"))


def load_run(out_dir: str | Path, day: str) -> Run:
    out_dir = Path(out_dir)
    orders_path, trades_path = out_dir / f"{day}_orders.csv", out_dir / f"{day}_trades.csv"
    return Run(
        day=day,
        timeline=pd.read_csv(out_dir / f"{day}_timeline.csv"),
        fills=pd.read_csv(out_dir / f"{day}_fills.csv", keep_default_na=False),
        orders=pd.read_csv(orders_path) if orders_path.exists() else pd.DataFrame(columns=["timestamp", "id", "product", "price", "quantity"]),
        trades=(
            pd.read_csv(trades_path, keep_default_na=False)
            if trades_path.exists()
            else pd.DataFrame(columns=["timestamp", "product", "price", "quantity", "buyer", "seller"])
        ),
    )


# ---------------------------------------------------------------------------- tables


def fill_summary(run: Run, reference: str = "mark") -> pd.DataFrame:
    """Per product and fill type: fills, volume, and the average edge per unit against the arrival reference."""
    fills = _with_marks(run, reference)
    if fills.empty:
        return pd.DataFrame(columns=["fills", "volume", "bought", "sold", "edge"])
    fills["bought"] = fills["volume"].where(fills["quantity"] > 0, 0)
    fills["sold"] = fills["volume"].where(fills["quantity"] < 0, 0)
    fills["edge_total"] = fills["edge"] * fills["volume"]
    fills["edge_volume"] = fills["volume"].where(fills["edge"].notna(), 0)  # the first tick has no prior mid
    table = fills.groupby(["product", "type"]).agg(
        fills=("volume", "size"),
        volume=("volume", "sum"),
        bought=("bought", "sum"),
        sold=("sold", "sum"),
        edge_total=("edge_total", "sum"),
        edge_volume=("edge_volume", "sum"),
    )
    table["edge"] = table.pop("edge_total") / table.pop("edge_volume")
    return table.round({"edge": 2})


def markouts(run: Run, horizons=DEFAULT_HORIZONS, reference: str = "mark") -> pd.DataFrame:
    """Average markout per unit, by product and fill type (rows) and ticks after the fill (columns).

    Measured against `reference` ("mark" or "wall_mid"). Fills too close to the end of the day for
    a horizon are left out of that horizon.
    """
    rows = []
    prices = _with_reference(run.timeline, reference)
    for product, fills in run.fills.groupby("product"):
        timeline = prices[prices["product"] == product].set_index("timestamp").sort_index()
        timestamps, marks = timeline.index.to_numpy(), timeline["ref"].to_numpy()
        at = np.searchsorted(timestamps, fills["timestamp"].to_numpy())
        sign, volume = np.sign(fills["quantity"].to_numpy()), np.abs(fills["quantity"].to_numpy())
        price, kind = fills["price"].to_numpy(), fills["source"].map(SOURCES).to_numpy()
        for horizon in horizons:
            later = at + horizon
            valid = later < len(marks)
            per_unit = sign[valid] * (marks[later[valid]] - price[valid])
            for label in TYPES:
                mask = kind[valid] == label
                if mask.any():
                    weights = volume[valid][mask]
                    rows.append((product, label, horizon, float(np.average(per_unit[mask], weights=weights))))
    if not rows:
        return pd.DataFrame()
    table = pd.DataFrame(rows, columns=["product", "type", "horizon", "markout"])
    table = table.pivot_table(index=["product", "type"], columns="horizon", values="markout")
    return table.reindex(columns=list(horizons)).round(2)


def pnl_split(run: Run, reference: str = "mark") -> pd.DataFrame:
    """Per product: PnL as spread captured on fills plus inventory carried through price moves.

    capture_took, capture_passive: the sum over fills of quantity × (reference at the fill tick − price)
    carry: the sum over ticks of the position held into the tick × the reference's change
    end_gap: final position × (mark − reference) at the end; zero for the mark itself

    The four add up to the PnL exactly: valued at the mark, PnL changes each tick by the carry plus,
    for each fill, quantity × (mark − price). Against the wall mid, the gap between the mark and the
    wall mid only survives at the end, where the position is valued at the mark.
    """
    prices = _with_reference(run.timeline, reference).sort_values(["product", "timestamp"])
    held = prices.groupby("product")["position"].shift(1).fillna(0)
    prices["carry"] = held * prices.groupby("product")["ref"].diff().fillna(0)
    fills = run.fills.merge(prices[["timestamp", "product", "ref"]], on=["timestamp", "product"], how="left")
    fills["capture"] = fills["quantity"] * (fills["ref"] - fills["price"])
    fills["type"] = fills["source"].map(SOURCES)
    last = prices.groupby("product").last()
    table = pd.DataFrame(index=sorted(set(prices["product"])))
    table.index.name = "product"
    for label in TYPES:
        captured = fills[fills["type"] == label].groupby("product")["capture"].sum()
        table[f"capture_{label}"] = captured.reindex(table.index, fill_value=0.0)
    table["carry"] = prices.groupby("product")["carry"].sum()
    table["end_gap"] = last["position"] * (last["mark"] - last["ref"])
    table["pnl"] = last["pnl"]
    active = run.products
    return table.loc[[p for p in table.index if p in active]].round(2)


def trade_impact(runs: Run | list[Run], horizons=IMPACT_HORIZONS) -> pd.DataFrame:
    """How the price moves after the data's market trades, per product and reference price.

    Give one day, or a list of days to pool their trades (each trade's moves stay within its day).

    A trade at or above the best ask of its tick's book was a buy (+1); at or below the best bid,
    a sell (−1); trades inside the spread are counted in `inside` and left out. Trades on a tick
    with an empty side are skipped, as `arena.diagnose` does: the side that's there could classify
    some, but the reference at such a tick isn't a price to measure moves from. The trades of a tick
    print against that tick's book (checked on Prosperity 3: 96–97% are at one of its prices).
    For each reference: `taker_edge` is the mean of sign × (reference − price), so negative means
    the taker paid; the horizon columns are the mean of sign × (reference h ticks later − reference
    now). A move that stays above zero is permanent impact: trades carry information. Means are per
    trade, not per unit.
    """
    runs = [runs] if isinstance(runs, Run) else runs
    pooled: dict[tuple[str, str], dict] = {}  # (product, reference) -> counts and lists of values
    for run in runs:
        for reference in REFERENCES:
            if run.trades.empty or reference not in run.timeline:
                continue
            prices = _with_reference(run.timeline, reference)
            for product, trades in run.trades.groupby("product"):
                timeline = prices[prices["product"] == product].set_index("timestamp").sort_index()
                at = timeline.index.get_indexer(trades["timestamp"])
                at, price = at[at >= 0], trades["price"].to_numpy()[at >= 0]
                bid, ask = timeline["best_bid"].to_numpy()[at], timeline["best_ask"].to_numpy()[at]
                two_sided = ~(np.isnan(bid) | np.isnan(ask))
                at, price, bid, ask = at[two_sided], price[two_sided], bid[two_sided], ask[two_sided]
                sign = np.where(price >= ask, 1, np.where(price <= bid, -1, 0))
                keep = sign != 0
                at, price, sign = at[keep], price[keep], sign[keep]
                ref = timeline["ref"].to_numpy()
                entry = pooled.setdefault((product, reference), {"trades": 0, "inside": 0, "edge": [], **{h: [] for h in horizons}})
                entry["trades"] += int(keep.sum())
                entry["inside"] += int((~keep).sum())
                entry["edge"].append(sign * (ref[at] - price))
                for horizon in horizons:
                    later = at + horizon
                    valid = later < len(ref)
                    entry[horizon].append(sign[valid] * (ref[later[valid]] - ref[at[valid]]))
    if not pooled:
        return pd.DataFrame()

    def mean(parts):
        values = np.concatenate(parts) if parts else np.array([])
        return float(values.mean()) if len(values) else np.nan

    rows = [
        {"product": product, "reference": reference, "trades": e["trades"], "inside": e["inside"],
         "taker_edge": mean(e["edge"]), **{h: mean(e[h]) for h in horizons}}
        for (product, reference), e in sorted(pooled.items())
    ]
    return pd.DataFrame(rows).set_index(["product", "reference"]).round(3)


def _with_reference(timeline: pd.DataFrame, reference: str) -> pd.DataFrame:
    """The timeline with a `ref` column: the mark, or the wall mid carried over ticks where a side was empty."""
    if reference not in REFERENCES:
        raise ValueError(f"reference must be one of {', '.join(REFERENCES)}")
    if reference not in timeline:
        raise ValueError(f"no {reference} column: these CSVs predate it, so run the backtest again")
    timeline = timeline.sort_values(["product", "timestamp"])
    ref = timeline[reference] if reference == "mark" else timeline.groupby("product")["wall_mid"].ffill()
    return timeline.assign(ref=ref.fillna(timeline["mark"]))


def _with_marks(run: Run, reference: str = "mark") -> pd.DataFrame:
    """Fills with their edge per unit against the reference one tick before the fill (the arrival price).

    Not the price at the fill tick: an order you take is part of that tick's book, so it drags the
    mid toward its own price and makes taking look worse than it is.
    """
    timeline = _with_reference(run.timeline, reference)
    prior = timeline.assign(prior_mark=timeline.groupby("product")["ref"].shift(1))
    fills = run.fills.merge(prior[["timestamp", "product", "prior_mark"]], on=["timestamp", "product"], how="left")
    fills["type"] = fills["source"].map(SOURCES)
    fills["volume"] = fills["quantity"].abs()
    fills["edge"] = np.sign(fills["quantity"]) * (fills["prior_mark"] - fills["price"])
    return fills


# ---------------------------------------------------------------------------- charts


def plot_pnl(run: Run) -> Chart:
    """PnL over the day: total, each product, and the folded rest."""
    t = _t()
    pnl = run.timeline.pivot(index="timestamp", columns="product", values="pnl")
    total = pnl.sum(axis=1)
    shown = list(run.colors)
    other = [p for p in run.products if p not in run.colors]

    with _style():
        fig = Chart(figsize=(11, 4.2), layout="constrained")
        ax = fig.subplots()
        ax.axhline(0, color=t["axis"], linewidth=0.8)
        series = [(product, pnl[product], run.colors[product], 1.5) for product in shown]
        if other:
            series.append((f"other ({len(other)})", pnl[other].sum(axis=1), t["muted"], 1.5))
        if len(series) > 1:
            series.append(("total", total, t["ink"], 2.0))
        for label, values, color, width in series:
            ax.plot(values.index, values, color=color, linewidth=width, label=label)
        if len(series) <= 4:
            _end_labels(ax, [(label, values.iloc[-1], color) for label, values, color, _ in series])
        if len(series) > 1:
            ax.legend(loc="upper left", ncols=min(len(series), 4))
        ax.set_title(f"PnL · {run.day} · total {total.iloc[-1]:,.0f}")
        ax.yaxis.set_major_formatter(_thousands)
        _time_axis(ax)
    return fig


def plot_product(
    run: Run, product: str, start: int | None = None, end: int | None = None, quotes: bool | None = None
) -> Chart:
    """Price with the book spread, your fills (and quotes), then position and PnL, on one time axis.

    Fills: blue triangles up are buys, orange down are sells; solid means you took liquidity,
    hollow means a resting quote was filled. Quotes are shown when the window is short enough to
    read them (or force with quotes=True/False).
    """
    t = _t()
    timeline = run.series(product, start, end)
    if timeline.empty:
        raise ValueError(f"no data for {product} in that window")
    first, last = timeline.index[0], timeline.index[-1]
    fills = run.fills[(run.fills["product"] == product) & run.fills["timestamp"].between(first, last)]
    orders = run.orders[(run.orders["product"] == product) & run.orders["timestamp"].between(first, last)]
    if quotes is None:
        quotes = len(timeline) <= 1500
    buy_color, sell_color = t["series"][0], t["series"][1]
    limit = int(timeline["limit"].iloc[0])

    with _style():
        fig = Chart(figsize=(11, 7.5), layout="constrained")
        ax_price, ax_position, ax_pnl = fig.subplots(3, 1, sharex=True, height_ratios=[3, 1.1, 1.1])

        ax_price.fill_between(
            timeline.index, timeline["best_bid"], timeline["best_ask"], step="post",
            color=t["muted"], alpha=0.16, linewidth=0,
        )
        ax_price.plot(timeline.index, timeline["mark"], color=t["secondary"], linewidth=1.2, drawstyle="steps-post")
        walls = "wall_mid" in timeline and timeline["wall_mid"].notna().any()
        if walls:
            ax_price.plot(timeline.index, timeline["wall_mid"], color=t["ink"], linewidth=1.0, linestyle=(0, (4, 2)), drawstyle="steps-post")
        if quotes and not orders.empty:
            for side, color in ((orders["quantity"] > 0, buy_color), (orders["quantity"] < 0, sell_color)):
                ax_price.scatter(orders.loc[side, "timestamp"], orders.loc[side, "price"], marker="_", s=30, linewidths=1.2, color=color, alpha=0.55)
        size = 42 if len(fills) <= 400 else 16
        for is_buy, color, marker in ((True, buy_color, "^"), (False, sell_color, "v")):
            for kind, hollow in (("took", False), ("passive", True)):
                rows = fills[((fills["quantity"] > 0) == is_buy) & (fills["source"].map(SOURCES) == kind)]
                ax_price.scatter(
                    rows["timestamp"], rows["price"], marker=marker, s=size, zorder=3,
                    facecolors=t["surface"] if hollow else color,
                    edgecolors=color if hollow else t["surface"],
                    linewidths=1.2 if hollow else 0.8,
                )
        handles = _product_legend(quotes and not orders.empty, walls)
        ax_price.legend(handles=handles, loc="lower left", bbox_to_anchor=(0, 1.0), ncols=len(handles), borderaxespad=0.3)
        # Over the window: from the PnL just before it (its first tick's fills count).
        before = run.series(product).loc[: first - 1, "pnl"] if start is not None else []
        pnl = timeline["pnl"].iloc[-1] - (before.iloc[-1] if len(before) else 0)
        window = "" if start is None and end is None else f" · {first:,}–{last:,}"
        _figure_title(fig, f"{product} · {run.day}{window} · pnl {pnl:,.0f} · {len(fills):,} fills")
        ax_price.ticklabel_format(axis="y", useOffset=False, style="plain")
        ax_price.set_ylabel("price")

        ax_position.step(timeline.index, timeline["position"], where="post", color=buy_color)
        for bound in (limit, -limit):
            ax_position.axhline(bound, color=t["muted"], linewidth=0.8, linestyle=(0, (4, 3)))
        ax_position.text(1.0, limit, " limit", transform=ax_position.get_yaxis_transform(), va="center", color=t["muted"], fontsize=8)
        ax_position.axhline(0, color=t["axis"], linewidth=0.8)
        ax_position.set_ylim(-limit * 1.15, limit * 1.15)
        ax_position.set_ylabel("position")

        if timeline["pnl"].min() <= 0 <= timeline["pnl"].max():
            ax_pnl.axhline(0, color=t["axis"], linewidth=0.8)
        ax_pnl.plot(timeline.index, timeline["pnl"], color=buy_color)
        ax_pnl.yaxis.set_major_formatter(_thousands)
        ax_pnl.set_ylabel("pnl")
        _time_axis(ax_pnl)
    return fig


def plot_markouts(run: Run, horizons=DEFAULT_HORIZONS, reference: str = "mark") -> Chart:
    """Average markout per unit against ticks after the fill: one panel per fill type."""
    t = _t()
    table = markouts(run, horizons, reference)
    with _style():
        fig = Chart(figsize=(11, 4.2), layout="constrained")
        axes = fig.subplots(1, 2, sharey=True)
        positions = np.arange(len(horizons))
        for ax, label in zip(axes, TYPES):
            ax.axhline(0, color=t["axis"], linewidth=0.8)
            drawn = 0
            for product, color in run.colors.items():
                if (product, label) in table.index:
                    values = table.loc[(product, label)].reindex(horizons)
                    ax.plot(positions, values, color=color, marker="o", markersize=5, markeredgecolor=t["surface"], label=product)
                    drawn += 1
            if not drawn:
                ax.text(0.5, 0.5, "no fills", transform=ax.transAxes, ha="center", color=t["muted"])
            ax.set_xticks(positions, [str(h) for h in horizons])
            ax.set_xlabel("ticks after the fill")
            ax.set_title(f"{'took liquidity' if label == 'took' else 'passive fills (quotes hit)'}")
            ax.grid(axis="x", visible=False)
        axes[0].set_ylabel("markout per unit")
        if len(run.colors) > 1:
            axes[0].legend(loc="best")
        against = "" if reference == "mark" else " · against the wall mid"
        _figure_title(fig, f"Markouts · {run.day} · average profit per unit, some ticks after each fill{against}")
    return fig


def load_grid(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def grid_axes(grid: pd.DataFrame) -> list[str]:
    """The parameter columns of an `arena.grid --out` CSV: everything before the first pnl column."""
    columns = list(grid.columns)
    first = next(i for i, column in enumerate(columns) if column.startswith("pnl_"))
    return columns[:first]


def plot_grid(grid: pd.DataFrame, metric: str | None = None, x: str | None = None, y: str | None = None) -> Chart:
    """A heatmap of one metric over two parameters, or a line over one.

    With more than two parameters, each cell shows the best value over the others. Combinations
    with errors or limit breaches are left out, as the grid summary leaves them out.
    """
    t = _t()
    axes = grid_axes(grid)
    counts = [column for column in ("errors", "limit_breaches") if column in grid]
    if counts:
        grid = grid[(grid[counts] == 0).all(axis=1)]
    if grid.empty:
        raise ValueError("every combination failed (errors or limit breaches): nothing to chart")
    metric = metric or next(c for c in grid.columns if c.startswith("pnl_"))
    x = x or axes[0]
    y = y if y is not None else next((a for a in axes if a != x), None)
    rest = [a for a in axes if a not in (x, y)]
    note = f" (best over {', '.join(_short(a) for a in rest)})" if rest else ""

    with _style():
        if y is None:
            fig = Chart(figsize=(8, 4), layout="constrained")
            ax = fig.subplots()
            modes = [c for c in grid.columns if c.startswith("pnl_") and c.count("_") == 1]
            values = grid.groupby(x)[modes].max()
            positions = np.arange(len(values))
            for column, color in zip(modes, t["series"]):
                ax.plot(positions, values[column], color=color, marker="o", markersize=6, markeredgecolor=t["surface"], label=_metric_label(column))
            ax.set_xticks(positions, [str(v) for v in values.index])
            ax.set_xlabel(_short(x))
            ax.yaxis.set_major_formatter(_thousands)
            if len(modes) > 1:
                ax.legend(loc="best")
            ax.set_title(f"total pnl by {_short(x)}{note}")
            return fig

        table = grid.groupby([y, x])[metric].max().unstack(x)
        fig = Chart(figsize=(1.2 * len(table.columns) + 3, 0.7 * len(table.index) + 2), layout="constrained")
        ax = fig.subplots()
        values = table.to_numpy(dtype=float)
        cmap, norm = _value_scale(values)
        image = ax.imshow(values, cmap=cmap, norm=norm, aspect="auto", origin="lower")
        ax.set_xticks(range(len(table.columns)), [str(v) for v in table.columns])
        ax.set_yticks(range(len(table.index)), [str(v) for v in table.index])
        ax.set_xlabel(_short(x))
        ax.set_ylabel(_short(y))
        ax.grid(False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        # Surface-colored gaps between cells instead of drawn borders.
        ax.set_xticks(np.arange(-0.5, len(table.columns)), minor=True)
        ax.set_yticks(np.arange(-0.5, len(table.index)), minor=True)
        ax.grid(which="minor", color=t["surface"], linewidth=2)
        ax.tick_params(which="minor", length=0)
        ax.tick_params(which="major", length=0)
        if values.size <= 150:
            for (row, column), value in np.ndenumerate(values):
                if not np.isnan(value):
                    ax.text(column, row, _compact(value), ha="center", va="center", fontsize=8, color=_text_on(cmap(norm(value))))
        best = np.unravel_index(np.nanargmax(values), values.shape)
        ax.add_patch(Rectangle((best[1] - 0.5, best[0] - 0.5), 1, 1, fill=False, edgecolor=t["ink"], linewidth=2))
        colorbar = fig.colorbar(image, ax=ax, shrink=0.85, format=_thousands)
        colorbar.outline.set_visible(False)
        colorbar.set_label(_metric_label(metric), color=t["secondary"])
        ax.set_title(f"{_metric_label(metric)}{note}")
    return fig


# ---------------------------------------------------------------------------- styling helpers


def _style():
    return mpl.rc_context(_rc_params())


def _rc_params() -> dict:
    t = _t()
    return {
        "figure.facecolor": t["surface"],
        "axes.facecolor": t["surface"],
        "savefig.facecolor": t["surface"],
        "axes.edgecolor": t["axis"],
        "axes.linewidth": 0.8,
        "axes.labelcolor": t["secondary"],
        "axes.labelsize": 9,
        "axes.titlecolor": t["ink"],
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.prop_cycle": cycler(color=t["series"]),
        "grid.color": t["grid"],
        "grid.linewidth": 0.6,
        "grid.linestyle": "-",
        "xtick.color": t["axis"],
        "ytick.color": t["axis"],
        "xtick.labelcolor": t["secondary"],
        "ytick.labelcolor": t["secondary"],
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "legend.labelcolor": t["secondary"],
        "text.color": t["secondary"],
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "lines.linewidth": 1.5,
        "lines.solid_capstyle": "round",
        "lines.solid_joinstyle": "round",
        "figure.dpi": 110,
        "savefig.dpi": 150,
    }


def _figure_title(fig: Chart, text: str) -> None:
    fig.suptitle(text, x=0.01, ha="left", fontweight="bold", fontsize=11, color=_t()["ink"])


def _product_legend(with_quotes: bool, with_walls: bool = False) -> list:
    t = _t()
    buy, sell = t["series"][0], t["series"][1]

    def marker(symbol, color, hollow):
        return Line2D([], [], linestyle="", marker=symbol, markersize=7, color=color,
                      markerfacecolor=t["surface"] if hollow else color, markeredgecolor=color)

    handles = [
        Patch(color=t["muted"], alpha=0.25, label="book spread"),
        Line2D([], [], color=t["secondary"], linewidth=1.2, label="mid"),
        marker("^", buy, False), marker("^", buy, True), marker("v", sell, False), marker("v", sell, True),
    ]
    labels = ["buy, took", "buy, passive", "sell, took", "sell, passive"]
    for handle, label in zip(handles[2:], labels):
        handle.set_label(label)
    if with_walls:
        handles.insert(2, Line2D([], [], color=t["ink"], linewidth=1.0, linestyle=(0, (4, 2)), label="wall mid"))
    if with_quotes:
        handles += [
            Line2D([], [], linestyle="", marker="_", markersize=9, color=buy, label="your bids"),
            Line2D([], [], linestyle="", marker="_", markersize=9, color=sell, label="your asks"),
        ]
    return handles


def _end_labels(ax, items: list[tuple[str, float, str]]) -> None:
    """Value labels at the right end of each line, nudged apart so they don't overlap."""
    t = _t()
    low, high = ax.get_ylim()
    gap = (high - low) * 0.07
    placed: list[float] = []
    for label, value, color in sorted(items, key=lambda item: item[1]):
        y = value if not placed else max(value, placed[-1] + gap)
        placed.append(y)
        ax.plot([1.0], [value], transform=ax.get_yaxis_transform(), marker="o", markersize=5,
                color=color, markeredgecolor=t["surface"], clip_on=False)
        ax.text(1.012, y, f"{label} {value:,.0f}", transform=ax.get_yaxis_transform(),
                va="center", fontsize=8, color=t["secondary"])


def _time_axis(ax) -> None:
    ax.xaxis.set_major_formatter(_thousands)
    ax.set_xlabel("timestamp")
    ax.margins(x=0)


def _value_scale(values: np.ndarray):
    t = _t()
    low, high = np.nanmin(values), np.nanmax(values)
    if low < 0 < high:
        cmap = LinearSegmentedColormap.from_list("pnl", [t["loss"], t["midpoint"], t["series"][0]])
        return cmap, TwoSlopeNorm(vmin=low, vcenter=0, vmax=high)
    cmap = LinearSegmentedColormap.from_list("magnitude", t["ramp"])
    if high <= 0:
        cmap = cmap.reversed()
    return cmap, Normalize(vmin=low, vmax=high if high > low else low + 1)


def _text_on(rgba) -> str:
    r, g, b = to_rgb(rgba)
    return "#ffffff" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.5 else "#0b0b0b"


def _compact(value: float) -> str:
    for size, suffix in ((1e6, "M"), (1e3, "k")):
        if abs(value) >= size:
            return f"{value / size:.1f}{suffix}"
    return f"{value:.0f}"


def _metric_label(column: str) -> str:
    """pnl_worse -> "pnl, worse fills"; nbhd_all -> "neighbourhood mean pnl, all fills"."""
    kind, _, mode = column.partition("_")
    names = {"pnl": "pnl", "nbhd": "neighbourhood mean pnl", "min": "worst day pnl"}
    if kind == "min":
        mode = mode.removeprefix("day_")
    return f"{names.get(kind, kind)}, {mode} fills" if mode else column


def _short(column: str) -> str:
    return column.removeprefix("PARAMS.")


_thousands = FuncFormatter(lambda value, _: f"{value:,.0f}")


# ---------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m arena.analysis", description="Save charts and print fill statistics for backtest output."
    )
    parser.add_argument("results", type=Path, nargs="?", help="folder written by arena.backtest --out")
    parser.add_argument("days", nargs="*", help="days to chart (default: every day in the folder)")
    parser.add_argument("--start", type=int, help="first timestamp of the product charts")
    parser.add_argument("--end", type=int, help="last timestamp of the product charts")
    parser.add_argument("--grid", type=Path, help="chart a CSV from arena.grid --out instead")
    parser.add_argument("--reference", choices=REFERENCES, default="mark", help="price fills are measured against (default: mark)")
    parser.add_argument("--dark", action="store_true", help="dark theme")
    parser.add_argument("--out", type=Path, help="folder for the PNGs (default: plots/ next to the input)")
    args = parser.parse_args(argv)
    if args.dark:
        set_theme("dark")

    if args.grid:
        grid = load_grid(args.grid)
        out = args.out or args.grid.parent / "plots"
        out.mkdir(parents=True, exist_ok=True)
        for metric in [c for c in grid.columns if c.startswith(("pnl_", "nbhd_")) and c.count("_") == 1]:
            path = out / f"{args.grid.stem}_{metric}.png"
            try:
                _save(plot_grid(grid, metric), path)
            except ValueError as error:
                parser.error(str(error))
        print(f"charts written to {out}/")
        return 0

    if not args.results:
        parser.error("give a results folder, or --grid")
    days = args.days or days_in(args.results)
    if not days:
        parser.error(f"no *_timeline.csv files in {args.results}")
    out = args.out or args.results / "plots"
    out.mkdir(parents=True, exist_ok=True)
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        runs = []
        for day in days:
            run = load_run(args.results, day)
            runs.append(run)
            ref = args.reference
            _save(plot_pnl(run), out / f"{day}_pnl.png")
            _save(plot_markouts(run, reference=ref), out / f"{day}_markouts.png")
            for product in run.products:
                _save(plot_product(run, product, args.start, args.end), out / f"{day}_{product}.png")
            against = f"against the {'wall mid' if ref == 'wall_mid' else 'mark'}"
            print(f"{day}\n\nfills (edge {against})\n{fill_summary(run, ref)}")
            print(f"\nmarkouts (per unit, by ticks after the fill, {against})\n{markouts(run, reference=ref)}")
            print(f"\npnl split ({against})\n{pnl_split(run, ref)}")
            impact = trade_impact(run)
            if not impact.empty:
                print(f"\nmarket trades: taker's edge and the signed move after them, by ticks (per trade)\n{impact}")
            print()
        if len(runs) > 1 and not (impact := trade_impact(runs)).empty:
            print(f"market trades over all {len(runs)} days\n{impact}\n")
    print(f"charts written to {out}/")
    return 0


def _save(fig: Chart, path: Path) -> None:
    fig.savefig(path)


if __name__ == "__main__":
    sys.exit(main())
