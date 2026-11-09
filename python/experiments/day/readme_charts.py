"""The README's charts: the forecast against what happened, a jump second by second, and each round's private PnL
against the field's.

usage (from the repository's root; matplotlib comes with the analysis group):
  # 1. the forecast's numbers, from R4-W2's Rust twin on round 4's private tape rebuilt from the server's logs
  uv run python -m experiments.day.tape_from_logs data/arena/round4/r4_W2_warm10k_private_res \\
      data/arena/round4/round4_public.csv data/arena/round4/round4_private_rebuilt.csv
  RIDGE_WARM=data/arena/round4/r4_stats.txt RIDGE_PRED_LOG=PRED.csv RIDGE_PRED_EXTRA=1 uv run python -m arena.qsim_rust \\
      ridge_maker data/arena/round4/round4_private_rebuilt.csv <F5's --set line, experiments.day.family_rust.F5> \\
      --set PRIOR_MASS=10000 --threads 1
  uv run python -m experiments.day.readme_charts forecast PRED.csv        # writes docs/img/data/forecast.json
  # 2. the charts (from the committed docs/img/data/forecast.json, data/arena/field_curves.json and the private runs'
  #    pnl.csv), light and dark
  uv run --group analysis python -m experiments.day.readme_charts render

The tapes are the organisers' and are not in the repository; step 2 needs only committed files. The prediction log has
a row per book event: time (µs), mid, prediction (the 400-ms mid move, ticks), skew, spread, position, the latent
filter's gap and the quote switch's speed.
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


def forecast(pred_log: str, out: Path, bins: int = 20) -> None:
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
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "R4-W2's Rust twin on round 4's private tape rebuilt from the server's logs "
                                         "(1,656,080 there against the server's 1,659,546)",
                               "events": int(len(t)), "used": int(ok.sum()), "corr": round(corr, 4), "r2": round(r2, 4),
                               "bins": table, "window": window}, indent=1) + "\n")
    print(f"{ok.sum():,} of {len(t):,} events; corr {corr:.3f}, R^2 {r2:.3f}; window at {t0 / 1e6:,.1f} s")


def _private_pnl(r: int, step: int = 200) -> list[float]:
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


def render(themes: list[str]) -> None:
    import numpy as np
    from arena import analysis as an

    fc = json.loads((DATA / "forecast.json").read_text())
    field = json.loads((ROOT / "data" / "arena" / "field_curves.json").read_text())
    IMG.mkdir(parents=True, exist_ok=True)
    thousands = an.FuncFormatter(lambda v, _: "0" if v == 0 else f"{v / 1000:.1f}M" if abs(v) >= 1000 else f"{v:.0f}k")

    def heading(fig, title, subtitle, top=0.97):
        fig.text(0.02, top, title, fontsize=11.5, fontweight="bold", color=c["ink"], va="top")
        fig.text(0.02, top - 0.065, subtitle, fontsize=8.5, color=c["secondary"], va="top")

    for theme in themes:
        an.set_theme(theme)
        c = an._t()
        blue, orange, aqua = c["series"][0], c["series"][1], c["series"][2]
        with an.mpl.rc_context(an._rc_params()):
            # 1. the forecast against what happened
            fig = an.Chart(figsize=(7.2, 4.6))
            ax = fig.add_subplot()
            pred = [b["pred"] for b in fc["bins"]]
            real = [b["real"] for b in fc["bins"]]
            lo, hi = min(pred + real) - 0.3, max(pred + real) + 0.3
            ax.plot([lo, hi], [lo, hi], color=c["muted"], lw=1, ls=(0, (4, 3)), zorder=1)
            ax.text(-1.15, -0.55, "a perfect forecast", color=c["muted"], fontsize=8, rotation=35, ha="center")
            for cap in (-2, 2):
                ax.axvline(cap, color=c["axis"], lw=0.8, zorder=1)
            ax.text(2.06, lo + 0.25, "the forecast is capped at\n±2 ticks; beyond it are\nthe jumps", color=c["secondary"],
                    fontsize=8, va="bottom")
            ax.plot(pred, real, color=blue, lw=2, marker="o", ms=6, mec=c["surface"], mew=1.5, zorder=3)
            ax.set_xlim(lo, hi)
            ax.set_ylim(lo, hi)
            ax.set_xlabel("the forecast 400-ms move of the mid (ticks), each bin's mean")
            ax.set_ylabel("the move that followed (ticks)")
            heading(fig, "The forecast against what happened",
                    f"R4-W2 on round 4's private tape, which it had never seen: {fc['used'] / 1e6:.2f}M book events in 20 "
                    f"equal bins; correlation {fc['corr']:.2f}, R² {fc['r2']:.2f}")
            fig.subplots_adjust(top=0.83, bottom=0.12, left=0.1, right=0.97)
            fig.savefig(IMG / f"forecast_calibration-{theme}.png", dpi=200)

            # 2. a typical jump, second by second
            w = fc["window"]
            fig = an.Chart(figsize=(7.2, 4.9))
            ax, axp = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1], "hspace": 0.1})
            ax.plot(w["t_s"], w["mid"], color=c["ink"], lw=1.4, drawstyle="steps-post", label="the mid", zorder=3)
            ax.plot(w["t_s"], w["latent"], color=orange, lw=1.4, label="the filter's hidden price", zorder=2)
            ax.plot(w["t_s"], w["forecast"], color=blue, lw=1.8, label="the forecast made 0.4 s earlier", zorder=4)
            ax.set_ylabel("price (ticks)")
            ax.legend(loc="lower left", fontsize=8, ncols=3, bbox_to_anchor=(0, 1.0), borderaxespad=0.3)
            axp.plot(w["t_s"], w["position"], color=aqua, lw=1.6, drawstyle="steps-post")
            axp.axhline(0, color=c["axis"], lw=0.8)
            axp.set_ylim(-115, 115)
            axp.set_yticks([-100, 0, 100])
            axp.set_ylabel("our position")
            axp.set_xlabel("seconds from the jump")
            heading(fig, "A typical jump, second by second",
                    f"Round 4's private tape: the median-sized jump that came after 20 s without one "
                    f"({abs(w['jump_ticks']):.0f} ticks in 0.2 s, {w['t0_s']:.0f} s into the tape)")
            fig.subplots_adjust(top=0.82, bottom=0.1, left=0.1, right=0.97)
            fig.savefig(IMG / f"jump_window-{theme}.png", dpi=200)

            # 3. each round's private PnL against the field's
            fig = an.Chart(figsize=(9, 3.6))
            axes = fig.subplots(1, 4)
            xs = np.arange(0, 12001, field["step_s"]) / 1000
            for r, axr in zip((1, 2, 3, 4), axes):
                rows = np.array(field["rounds"][str(r)])
                axr.fill_between(xs, rows[:, 0], rows[:, 2], color=c["muted"], alpha=0.2, lw=0,
                                 label="the other teams, 10th-90th percentile")
                axr.plot(xs, rows[:, 1], color=c["muted"], lw=1.2, label="their median")
                axr.plot(xs, rows[:, 3], color=orange, lw=1.6, label="the round's winner")
                axr.plot(xs, _private_pnl(r, field["step_s"]), color=blue, lw=2.2, label="us")
                axr.set_title(f"Round {r}: {FINALS[r]}", fontsize=9.5, loc="left")
                axr.set_xticks([0, 4, 8, 12])
                axr.set_xlabel("thousand seconds")
                axr.yaxis.set_major_formatter(thousands)
            handles, labels = axes[0].get_legend_handles_labels()
            fig.legend(handles[::-1], labels[::-1], loc="upper left", ncols=4, fontsize=8, bbox_to_anchor=(0.012, 0.87))
            heading(fig, "Private PnL through each round: us against the field",
                    "Each round's private tape, 12,000 s, as the leaderboard showed it", top=0.985)
            fig.subplots_adjust(top=0.69, bottom=0.15, left=0.06, right=0.99, wspace=0.3)
            fig.savefig(IMG / f"pnl_vs_field-{theme}.png", dpi=200)
        print(f"{theme}: charts in {IMG.relative_to(ROOT)}/")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forecast", help="the forecast's numbers from a RIDGE_PRED_LOG file")
    f.add_argument("pred_log")
    f.add_argument("--out", default=str(DATA / "forecast.json"))
    r = sub.add_parser("render", help="the charts, from the committed data")
    r.add_argument("--theme", choices=["light", "dark", "both"], default="both")
    args = parser.parse_args(argv)
    if args.cmd == "forecast":
        forecast(args.pred_log, Path(args.out))
    else:
        render(["light", "dark"] if args.theme == "both" else [args.theme])
    return 0


if __name__ == "__main__":
    sys.exit(main())
