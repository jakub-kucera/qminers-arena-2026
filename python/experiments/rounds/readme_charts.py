"""The README's charts: the forecast against what happened, a jump second by second, the forecast by the generator's
regime, and each round's private PnL against the field's.

usage (from the repository's root; matplotlib comes with the analysis group):
  # 1. the forecast's numbers: R4-W2's Rust twin on round 4's private tape, as the organisers published it after the
  #    event with the generator's fair price and regimes (market_data/, not in this repository). The twin makes the
  #    server's 1,659,546 on it exactly.
  RIDGE_WARM=data/arena/round4/r4_stats.txt RIDGE_PRED_LOG=PRED.csv RIDGE_PRED_EXTRA=1 uv run python -m arena.qsim_rust \\
      ridge_maker market_data/round4/round4_private.csv <F5's --set line, experiments.rounds.family_rust.F5> \\
      --set PRIOR_MASS=10000 --threads 1
  uv run python -m experiments.rounds.readme_charts forecast PRED.csv \\
      --fair market_data/round4/round4_private.fair.csv --regime market_data/round4/round4_private.regime.csv
  # 2. the charts (from the committed docs/img/data/forecast.json, data/arena/field_curves.json and the private runs'
  #    pnl.csv); macOS's Avenir Next and Menlo when present, else DejaVu
  uv run --group analysis python -m experiments.rounds.readme_charts render

Step 2 needs only committed files. The prediction log has a row per book event: time (µs), mid, prediction (the 400-ms
mid move, ticks), skew, spread, position, the latent filter's gap and the quote switch's speed. Without the published
tapes, step 1 also runs on a private tape rebuilt from the server's logs (experiments.tape.tape_from_logs), within
0.21% of the server's PnL, and without --fair / --regime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "docs" / "img" / "data"
IMG = ROOT / "docs" / "img"
HORIZON_US = 400_000
PRIVATE = {1: "round1/r1_C12_v6_private_res", 2: "round2/r2_L9_taker_huber_private_res",
           3: "round3/r3_F5_jump_bar_private_res", 4: "round4/r4_W2_warm10k_private_res"}
FINALS = {1: "R1-C12", 2: "R2-L9", 3: "R3-F5", 4: "R4-W2"}


REGIME_NAMES = {"none": "no episode", "s3_turbulent": "turbulent", "reserve_A": "reserve A", "reserve_B": "reserve B",
                "meta_A": "meta A", "meta_B": "meta B", "s2_burst_A": "burst A", "s2_burst_B": "burst B",
                "s2_thinning": "thinning"}


def _regime_labels(t, path):
    """Each event's innermost active episode (episodes nest: bursts inside turbulent stretches), else 'none'."""
    import csv
    import numpy as np
    rows = [(float(a) * 1e6, float(b) * 1e6, lab) for a, b, lab in list(csv.reader(open(path)))[1:]]
    labels = np.full(len(t), "none", dtype=object)
    for start, end, lab in sorted(rows, key=lambda r: r[0] - r[1]):  # longest first, the shortest painted last
        labels[np.searchsorted(t, start, side="left"):np.searchsorted(t, end, side="left")] = lab
    return labels


def forecast(pred_log: str, out: Path, fair_path: str | None = None, regime_path: str | None = None, bins: int = 20) -> None:
    import numpy as np

    a = np.loadtxt(pred_log, delimiter=",", usecols=(0, 1, 2, 5, 6))
    t, mid, pred, pos, gap = a.T
    ahead = np.searchsorted(t, t + HORIZON_US, side="right") - 1
    ok = t[ahead] >= t + HORIZON_US - 100_000  # a book event in the last 100 ms before the horizon
    real = mid[ahead] - mid
    p, r = pred[ok], real[ok]
    corr = float(np.corrcoef(p, r)[0, 1])
    r2 = float(1 - np.sum((r - p) ** 2) / np.sum((r - r.mean()) ** 2))
    order = np.argsort(p, kind="stable")
    groups = np.array_split(order, bins)  # equal-count bins (the cap at +-2 ties many values, so not by quantile edges)
    table = [{"pred": float(p[g].mean()), "real": float(r[g].mean()), "n": int(len(g))} for g in groups]
    result = {"events": int(len(t)), "used": int(ok.sum()), "corr": round(corr, 4), "r2": round(r2, 4), "bins": table}

    fair = None
    if fair_path:  # the generator's own fair price, published after the event
        f = np.loadtxt(fair_path, delimiter=",", skiprows=1)
        fair = f[np.clip(np.searchsorted(f[:, 0] * 1e6, t, side="right") - 1, 0, len(f) - 1), 1]
        latent = mid + gap
        result["fair"] = {"mid_mae": round(float(np.mean(np.abs(mid - fair))), 4),
                          "filter_mae": round(float(np.mean(np.abs(latent - fair))), 4),
                          "oracle_corr": round(float(np.corrcoef((fair - mid)[ok], r)[0, 1]), 4)}
    if regime_path:
        lab = _regime_labels(t, regime_path)[ok]
        rows = []
        for name in REGIME_NAMES:
            m = lab == name
            if m.sum() < 1000:
                continue
            pp, rr = p[m], r[m]
            rows.append({"regime": name, "label": REGIME_NAMES[name], "share": round(float(m.mean()), 4),
                         "corr": round(float(np.corrcoef(pp, rr)[0, 1]), 4), "move_sd": round(float(rr.std()), 3)})
        result["regimes"] = rows

    # the window: a typical jump (3+ ticks within 0.2 s, IDEAS.md's definition), the median-sized one among those after
    # 20 s without another (the kind the generator announced), from 10 s before it to 10 s after, on a 50-ms grid
    after = np.searchsorted(t, t + 200_000, side="right") - 1
    move = mid[after] - mid
    starts, last = [], -1e18
    for i in np.flatnonzero(np.abs(move) >= 3):
        if t[i] - last > 5_000_000:
            starts.append(i)
        last = t[i]
    quiet = [i for j, i in enumerate(starts) if j == 0 or t[i] - t[starts[j - 1]] > 20_000_000]
    sizes = np.abs(move[quiet])
    k = quiet[int(np.argmin(np.abs(sizes - np.median(sizes))))]
    t0 = t[k]
    grid = np.arange(t0 - 10_000_000, t0 + 10_000_000, 50_000)
    at = np.clip(np.searchsorted(t, grid, side="right") - 1, 0, len(t) - 1)
    made = np.clip(np.searchsorted(t, grid - HORIZON_US, side="right") - 1, 0, len(t) - 1)
    window = {"rule": "the median-sized jump (3+ ticks in 0.2 s) after 20 s without one", "jump_ticks": float(move[k]),
              "jumps_after_quiet": len(quiet), "t0_s": round(float(t0) / 1e6, 2),
              "t_s": [round(float(x - t0) / 1e6, 2) for x in grid],
              "mid": [float(x) for x in mid[at]],
              "forecast": [round(float(mid[i] + pred[i]), 3) for i in made],  # made 0.4 s earlier, for this time
              "latent": [round(float(mid[i] + gap[i]), 3) for i in at],
              "position": [int(x) for x in pos[at]]}
    if fair is not None:
        window["fair"] = [round(float(fair[i]), 3) for i in at]
    result["window"] = window
    result["source"] = ("R4-W2's Rust twin on round 4's private tape as the organisers published it (the server's "
                        "1,659,546 exactly)" if fair_path else "R4-W2's Rust twin on a private tape rebuilt from the logs")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"{ok.sum():,} of {len(t):,} events; corr {corr:.3f}, R^2 {r2:.3f}; window at {t0 / 1e6:,.1f} s;",
          result.get("fair"), [(x["label"], x["corr"]) for x in result.get("regimes", [])])


def _private_pnl_at(r: int, step: int = 200) -> list[float]:
    rows = (ROOT / "data" / "arena" / PRIVATE[r] / "pnl.csv").read_text().split("\n")[1:]
    pnl = {}
    for row in rows:
        if row:
            s, v = row.split(",")
            pnl[int(float(s))] = float(v)
    last, out = 0.0, []
    for s in range(0, 12001, step):
        last = pnl.get(s, pnl.get(s - 1, last))
        out.append(last / 1000)
    return out


# One dark "terminal" look for every chart (a single image reads on GitHub's light and dark pages alike). The three
# hues sit in OKLCH L 0.64-0.66 and pass the dataviz skill's validator on this surface (CVD ΔE >= 10.8, contrast >= 3:1).
STYLE = {"bg": "#0b0f14", "ink": "#e6edf3", "sub": "#8b949e", "grid": "#1c232c", "axis": "#30363d",
         "us": "#00ae7b", "winner": "#cb7f00", "violet": "#8d75eb", "field": "#8b949e", "mid": "#c9d1d9",
         "sans": ["Avenir Next", "Helvetica Neue", "DejaVu Sans"], "mono": ["Menlo", "DejaVu Sans Mono"]}


def _setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": STYLE["sans"], "font.size": 9, "text.color": STYLE["ink"],
        "figure.facecolor": STYLE["bg"], "axes.facecolor": STYLE["bg"], "savefig.facecolor": STYLE["bg"],
        "axes.edgecolor": STYLE["axis"], "axes.labelcolor": STYLE["sub"], "axes.labelsize": 8.5,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": STYLE["grid"], "grid.linewidth": 0.8,
        "xtick.color": STYLE["axis"], "ytick.color": STYLE["axis"], "xtick.labelcolor": STYLE["sub"],
        "ytick.labelcolor": STYLE["sub"], "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "ytick.major.size": 0,
        "legend.frameon": False, "legend.fontsize": 8.5, "lines.solid_capstyle": "round"})
    return plt


def _mono(ax):
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontfamily(STYLE["mono"])


def _heading(fig, title, subtitle, y=0.955):
    fig.text(0.02, y, title, fontsize=15, fontweight="bold", color=STYLE["ink"], va="top")
    fig.text(0.02, y - 0.075, subtitle, fontsize=9, color=STYLE["sub"], va="top")


def _glow(line, width=4.5):
    import matplotlib.patheffects as pe
    line.set_path_effects([pe.Stroke(linewidth=width, foreground=line.get_color(), alpha=0.16), pe.Normal()])


def _money(v, _=None):
    return "0" if v == 0 else f"{v / 1000:g}M" if abs(v) >= 1000 else f"{v:g}k"


def _legend(fig, items, y=0.77):
    """A legend row of line samples, the labels in the subtitle's ink: identity never by colour alone."""
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=color, lw=width) for color, _, width in items]
    leg = fig.legend(handles, [label for _, label, _ in items], loc="center left", bbox_to_anchor=(0.012, y),
                     ncols=len(items), handlelength=1.8, handletextpad=0.6, columnspacing=1.8, fontsize=8.5)
    for text in leg.get_texts():
        text.set_color(STYLE["sub"])


def _pnl_panels(plt, field, scale):
    import numpy as np
    from matplotlib.ticker import FuncFormatter
    fig, axes = plt.subplots(1, 4, figsize=(10.5, 4.0))
    xs = np.arange(0, 12001, field["step_s"])
    for r, ax in zip((1, 2, 3, 4), axes):
        rows = np.array(field["rounds"][str(r)], float)
        ox, oy = _private_curve(r)
        fx = xs
        if scale == "log":
            keep, okeep = xs >= 200, ox >= 100
            fx, rows, ox, oy = xs[keep], rows[keep], ox[okeep], oy[okeep]
        X = (lambda v: v) if scale == "log" else (lambda v: v / 1000)
        low = np.maximum(rows[:, 0], 0.5) if scale == "log" else rows[:, 0]
        ax.fill_between(X(fx), low, rows[:, 2], color=STYLE["field"], alpha=0.14, lw=0)
        ax.plot(X(fx), rows[:, 1], color=STYLE["field"], lw=1.1)
        ax.plot(X(fx), rows[:, 3], color=STYLE["winner"], lw=1.6)
        line, = ax.plot(X(ox), oy, color=STYLE["us"], lw=2.1)
        _glow(line)
        if scale == "log":
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_xlim(100, 12000)
            ax.set_ylim(1, 3000)
            ax.grid(True, axis="both", which="major")
            ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}" if v < 1000 else f"{v / 1000:g}k"))
            ax.set_xlabel("seconds (log)")
        else:
            ax.set_xticks([0, 4, 8, 12])
            ax.set_xlabel("thousand seconds")
        ax.yaxis.set_major_formatter(FuncFormatter(_money))
        ax.set_title(f"Round {r}  ·  {FINALS[r]}", loc="left", fontsize=10, fontweight="bold", color=STYLE["ink"], pad=8)
        _mono(ax)
    return fig, axes


def _private_curve(r):
    import numpy as np
    rows = (ROOT / "data" / "arena" / PRIVATE[r] / "pnl.csv").read_text().split("\n")[1:]
    pts = sorted((int(float(a)), float(b) / 1000) for a, b in (row.split(",") for row in rows if row))
    return np.array([p[0] for p in pts]), np.array([p[1] for p in pts])


def render() -> None:
    import numpy as np
    from matplotlib.ticker import FuncFormatter

    plt = _setup()
    fc = json.loads((DATA / "forecast.json").read_text())
    field = json.loads((ROOT / "data" / "arena" / "field_curves.json").read_text())
    IMG.mkdir(parents=True, exist_ok=True)
    legend = [(STYLE["us"], "us", 2.1), (STYLE["winner"], "the round's winner", 1.6),
              (STYLE["field"], "the other teams' median", 1.1)]

    # 1. private PnL against the field, linear
    fig, axes = _pnl_panels(plt, field, "linear")
    _heading(fig, "Private PnL through each round",
             "Each round's 12,000-s private tape, as the leaderboard showed it; the grey band is the other teams' "
             "10th-90th percentile")
    _legend(fig, legend)
    fig.subplots_adjust(top=0.64, bottom=0.13, left=0.05, right=0.985, wspace=0.3)
    fig.savefig(IMG / "pnl_vs_field.png", dpi=180)
    plt.close(fig)

    # 2. the same on log-log axes: a constant earning rate is a straight line, the first minutes become visible
    fig, axes = _pnl_panels(plt, field, "log")
    _heading(fig, "The same curves on log–log axes",
             "A constant earning rate is a straight line here, and the gap between two lines is the ratio of their rates")
    _legend(fig, legend)
    fig.subplots_adjust(top=0.64, bottom=0.14, left=0.05, right=0.985, wspace=0.3)
    fig.savefig(IMG / "pnl_loglog.png", dpi=180)
    plt.close(fig)

    # 3. the forecast against what happened
    fig, ax = plt.subplots(figsize=(7.4, 4.9))
    pred = np.array([b["pred"] for b in fc["bins"]])
    real = np.array([b["real"] for b in fc["bins"]])
    lo, hi = -4.1, 4.1
    ax.plot([lo, hi], [lo, hi], color=STYLE["sub"], lw=1, ls=(0, (3, 3)), zorder=1)
    ax.text(-2.9, -3.25, "a perfect forecast", color=STYLE["sub"], fontsize=8, rotation=38, ha="center")
    ax.axvspan(2, hi, color=STYLE["field"], alpha=0.07, lw=0)
    ax.axvspan(lo, -2, color=STYLE["field"], alpha=0.07, lw=0)
    ax.text(2.12, -3.85, "beyond the forecast's\n±2-tick cap: the jumps", color=STYLE["sub"], fontsize=8, va="bottom")
    line, = ax.plot(pred, real, color=STYLE["us"], lw=2, marker="o", ms=6.5, mfc=STYLE["us"], mec=STYLE["bg"], mew=1.6, zorder=3)
    _glow(line, 6)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.grid(True, axis="both")
    ax.set_xlabel("the forecast 400-ms move of the mid, ticks (each bin's mean)")
    ax.set_ylabel("the move that followed, ticks")
    _mono(ax)
    _heading(fig, "The forecast against what happened",
             f"R4-W2 on round 4's private tape, which it had never seen · {fc['used'] / 1e6:.2f}M book events in 20 bins "
             f"· correlation {fc['corr']:.2f} · R² {fc['r2']:.2f}", y=0.96)
    fig.subplots_adjust(top=0.82, bottom=0.11, left=0.1, right=0.97)
    fig.savefig(IMG / "forecast_calibration.png", dpi=180)
    plt.close(fig)

    # 4. a typical jump, second by second
    w = fc["window"]
    fig, (ax, axp) = plt.subplots(2, 1, sharex=True, figsize=(7.4, 5.2), gridspec_kw={"height_ratios": [3, 1], "hspace": 0.12})
    ax.plot(w["t_s"], w["mid"], color=STYLE["mid"], lw=1.3, drawstyle="steps-post", zorder=3)
    ax.plot(w["t_s"], w["latent"], color=STYLE["violet"], lw=1.3, alpha=0.9, zorder=2)
    if "fair" in w:
        ax.plot(w["t_s"], w["fair"], color=STYLE["ink"], lw=1.1, ls=(0, (2, 2)), zorder=5)
    line, = ax.plot(w["t_s"], w["forecast"], color=STYLE["us"], lw=1.9, zorder=4)
    _glow(line)
    ax.axvline(0, color=STYLE["axis"], lw=1, zorder=1)
    ax.set_ylabel("price, ticks")
    axp.fill_between(w["t_s"], 0, w["position"], step="post", color=STYLE["us"], alpha=0.35, lw=0)
    axp.plot(w["t_s"], w["position"], color=STYLE["us"], lw=1.2, drawstyle="steps-post")
    axp.axhline(0, color=STYLE["axis"], lw=0.8)
    axp.set_ylim(-115, 115)
    axp.set_yticks([-100, 0, 100])
    axp.set_ylabel("position, lots")
    axp.set_xlabel("seconds from the jump")
    for a in (ax, axp):
        _mono(a)
    _heading(fig, "A typical jump, second by second",
             f"Round 4's private tape: the median-sized jump after 20 s without one ({abs(w['jump_ticks']):.0f} ticks "
             f"in 0.2 s, {w['t0_s']:.0f} s in)", y=0.965)
    items = [(STYLE["mid"], "the mid", 1.3), (STYLE["us"], "the forecast, made 0.4 s earlier", 1.9),
             (STYLE["violet"], "our filter's hidden price", 1.3)]
    _legend(fig, items, y=0.82)
    if "fair" in w:
        from matplotlib.lines import Line2D
        leg = fig.legend([Line2D([], [], color=STYLE["ink"], lw=1.1, ls=(0, (2, 2)))],
                         ["the generator's true hidden price (published after the event)"], loc="center left",
                         bbox_to_anchor=(0.012, 0.785), fontsize=8.5)
        for text in leg.get_texts():
            text.set_color(STYLE["sub"])
    fig.subplots_adjust(top=0.74, bottom=0.1, left=0.11, right=0.97)
    fig.savefig(IMG / "jump_window.png", dpi=180)
    plt.close(fig)
    # 5. the forecast by the generator's regime (its labels, published after the event)
    if fc.get("regimes"):
        rows = sorted(fc["regimes"], key=lambda r: r["corr"])
        fig, ax = plt.subplots(figsize=(7.4, 4.6))
        ys = np.arange(len(rows))
        ax.barh(ys, [r["corr"] for r in rows], height=0.62, color=STYLE["us"], zorder=3)
        ax.set_yticks(ys, [r["label"] for r in rows])
        for y, r in zip(ys, rows):
            ax.text(1.03, y, f"{r['corr']:5.2f}   {r['share']:5.1%}   ±{r['move_sd']:.1f}", transform=ax.get_yaxis_transform(),
                    va="center", fontsize=8, color=STYLE["sub"], fontfamily=STYLE["mono"], clip_on=False)
        ax.text(1.03, len(rows) - 0.45, " corr   time   move", transform=ax.get_yaxis_transform(), fontsize=7.5,
                color=STYLE["sub"], fontfamily=STYLE["mono"], clip_on=False)
        for x, label, ypos in ((fc["corr"], f"overall {fc['corr']:.2f}", len(rows) - 0.35),
                               (fc["fair"]["oracle_corr"], f"the true hidden price {fc['fair']['oracle_corr']:.2f}", len(rows) - 0.35)):
            ax.axvline(x, color=STYLE["sub"], lw=1, ls=(0, (3, 3)), zorder=2)
        ax.text(fc["corr"] - 0.01, len(rows) - 0.45, f"overall {fc['corr']:.2f}", ha="right", fontsize=7.5, color=STYLE["sub"])
        ax.text(fc["fair"]["oracle_corr"] + 0.008, len(rows) - 0.45, f"true price {fc['fair']['oracle_corr']:.2f}",
                fontsize=7.5, color=STYLE["sub"])
        ax.set_xlim(-0.05, 0.75)
        ax.set_ylim(-0.6, len(rows) - 0.1)
        ax.grid(True, axis="x")
        ax.grid(False, axis="y")
        ax.set_xlabel("correlation of the 400-ms forecast with the move that followed")
        ax.tick_params(axis="y", labelsize=8.5, labelcolor=STYLE["ink"])
        _mono(ax)
        for label in ax.get_yticklabels():
            label.set_fontfamily(STYLE["sans"])
        _heading(fig, "Where the forecast worked",
                 "R4-W2 on round 4's private tape, by the generator's own regime labels (published after the event)", y=0.96)
        fig.text(0.02, 0.025, "time: the share of the tape in that regime · move: the sd of the 400-ms move that followed, ticks",
                 fontsize=7.5, color=STYLE["sub"])
        fig.subplots_adjust(top=0.83, bottom=0.15, left=0.15, right=0.74)
        fig.savefig(IMG / "forecast_by_regime.png", dpi=180)
        plt.close(fig)
    print(f"charts in {IMG.relative_to(ROOT)}/")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forecast", help="the forecast's numbers from a RIDGE_PRED_LOG file")
    f.add_argument("pred_log")
    f.add_argument("--fair", help="the generator's fair price (market_data/round4/round4_private.fair.csv)")
    f.add_argument("--regime", help="the generator's regime episodes (market_data/round4/round4_private.regime.csv)")
    f.add_argument("--out", default=str(DATA / "forecast.json"))
    sub.add_parser("render", help="the charts, from the committed data")
    args = parser.parse_args(argv)
    if args.cmd == "forecast":
        forecast(args.pred_log, Path(args.out), args.fair, args.regime)
    else:
        render()
    return 0


if __name__ == "__main__":
    sys.exit(main())
