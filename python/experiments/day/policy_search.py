"""Day tool: the forecast taker's execution policy tuned for PnL directly, many knobs at once. A CMA-ES in numpy over a
box of `ridge_maker` knobs (the take bar, the jump rule, the gap and flip rules, the quote switch, the dead zone), each
generation one `arena-sim batch` on the training tapes (Rust first: data/arena/round3/HANDOVER.md), started at the base
(R3-F5 by default); then the best point's one-knob neighbours (a plateau check) and, with `--hold`, the base against the
best on held-out tapes, paired over 500-s segments (`experiments.day.paired_rust`).

    uv run python -m experiments.day.policy_search --train PUBLIC.csv:0.75 --train GEN1.csv:0.34 --train GEN2.csv:0.34
        [--hold PUBLIC.csv --hold GEN3.csv ...] [--base F5] [--evals 200] [--pop 12] [--sigma 0.15] [--threads 6]
        [--seed 1] [--fix K=V ...] [--out results/policy_search]

`--train TAPE[:FRAC]` runs only the tape's first FRAC of time (a copy cut in the out folder): the public tape's first
75% keeps its last 25% held out. The objective is the mean over the training tapes of the PnL's gain over the base, in
percent of the base's PnL on that tape (each tape weighs the same). Every evaluation goes to OUT/evals.csv (the knobs,
each tape's PnL, the objective); the best point's `--set` line and the paired_rust command for the held-out check are
printed at the end. Deterministic: the same seed and tapes give the same search.

Round 4's recipe (IDEAS.md, "R3-P1"): the new public tape's first 75% plus three of the generator's look-alike draws
cut to a third, the rest held out; the quote knobs fixed (the generator's makers are unvalidated: on round 3 a lower
QS_RATE with a longer QS_US halved the fills on the draws and raised them on the real tape) and FT_FLIP_M off (its
active band lost on every tape and took most of a free search's samples):

    uv run python -m experiments.day.policy_search --train data/round4.csv:0.75 --train GEN/seed401.csv:0.34
        --train GEN/seed402.csv:0.34 --train GEN/seed403.csv:0.34 --hold data/round4.csv --hold GEN/seed404.csv
        --hold GEN/seed405.csv --base F5 --fix FT_FLIP_M=99.0 --fix QS_RATE=2.5 --fix QS_US=5000000
        --fix DEAD_ZONE=0.18 --fix KEEP_TH=0.3 --evals 132 --threads 8 --out results/policy_r4

About 90 s a generation of 11 on 8 threads (four 4,000-4,500-s tapes). `ARENA_SIM_BIN=path` runs another arena-sim
build instead of building this checkout's. numpy only beyond the standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from arena import qgrid, qsim_rust
from experiments.day import paired_rust
from experiments.day.family_rust import FAMILY

F3 = FAMILY["B1"] + " --set FILTER=1"
F5 = F3 + " --set FT_EDGE=0.25 --set FT_JUMP=3 --set FT_JUMP_HOLD_MS=5000 --set FT_JUMP_EDGE=0.15"
BASES = {"F3": F3, "F5": F5}


@dataclass
class Knob:
    """One searched knob: u in [0, 1] maps to [lo, hi] (log-scaled if `log`, rounded if `step`); with `off` set, u above
    `off_at` gives that value instead (the knob switched off) and [0, off_at] spans [lo, hi]."""

    name: str
    lo: float
    hi: float
    log: bool = False
    step: float = 0.0
    off: float | None = None
    off_at: float = 0.8
    integer: bool = False

    def value(self, u: float):
        u = min(1.0, max(0.0, float(u)))
        if self.off is not None:
            if u > self.off_at:
                return self.off
            u = u / self.off_at
        x = math.exp(math.log(self.lo) + u * (math.log(self.hi) - math.log(self.lo))) if self.log else self.lo + u * (self.hi - self.lo)
        if self.step:
            x = round(x / self.step) * self.step
        return int(round(x)) if self.integer else round(x, 6)

    def unit(self, x: float) -> float:
        """The u of a value (the start point); an `off` value sits midway in the off band."""
        if self.off is not None and x == self.off:
            return (1.0 + self.off_at) / 2
        x = min(self.hi, max(self.lo, x))
        u = (math.log(x) - math.log(self.lo)) / (math.log(self.hi) - math.log(self.lo)) if self.log else (x - self.lo) / (self.hi - self.lo)
        return u * self.off_at if self.off is not None else u


# The policy space (ridge_maker.rs's doc comment; bounds from IDEAS.md's one-knob grids on R3-F3 / R3-F5). Left out as
# known losers: FT_THRU 1, FT_SZ under 200, FT_EXIT*, QS_PULL, QUOTE_GAP, FT_MAXSPREAD 2, burst sizing over the limit.
SPACE = [
    Knob("FT_EDGE", 0.10, 0.40),
    Knob("FT_JUMP", 2.0, 6.0, step=0.5, off=0.0, off_at=0.85),
    Knob("FT_JUMP_MS", 50, 1000, log=True, integer=True),
    Knob("FT_JUMP_HOLD_MS", 1000, 20000, log=True, integer=True),
    Knob("FT_JUMP_EDGE", 0.0, 0.30),
    Knob("FT_LGAP", 1.0, 5.0, off=99.0),
    Knob("FT_LGAP_EDGE", 0.0, 0.30),
    Knob("FT_FLIP_M", 0.0, 0.8, off=99.0),
    Knob("FT_GAP_MS", 25, 120, log=True, integer=True),
    Knob("QS_RATE", 1.5, 5.0),
    Knob("QS_US", 2_000_000, 15_000_000, log=True, integer=True),
    Knob("DEAD_ZONE", 0.05, 0.40),
    Knob("KEEP_TH", 0.0, 1.0),
    # R3-P1's two new states of the take bar (ridge_maker.rs, off by default)
    Knob("FT_EDGE_FLIP", 0.05, 0.45, off=-1.0),
    Knob("FT_SD", 0.3, 2.0, off=99.0),
    Knob("FT_SD_EDGE", 0.0, 0.30),
]
DEFAULTS = {"FT_JUMP": 0.0, "FT_JUMP_MS": 200, "FT_JUMP_HOLD_MS": 5000, "FT_JUMP_EDGE": 0.15, "FT_LGAP": 99.0,
            "FT_LGAP_EDGE": 0.15, "FT_FLIP_M": 99.0, "FT_GAP_MS": 100, "QS_RATE": 0.0, "QS_US": 5_000_000,
            "DEAD_ZONE": 0.0, "KEEP_TH": 99.0, "FT_EDGE": 1.0, "FT_EDGE_FLIP": -1.0, "FT_SD": 99.0, "FT_SD_EDGE": 0.15}


def cut_tape(path: Path, frac: float, out_dir: Path) -> Path:
    """The tape's first `frac` of its time as a plain CSV in out_dir (reused if there)."""
    if frac >= 1.0:
        return path
    target = out_dir / f"{path.stem}_first{int(round(frac * 100))}.csv"
    if target.exists():
        return target
    with path.open() as f:
        lines = f.readlines()
    end = float(lines[-1].split(",", 1)[0])
    cut = frac * end
    tmp = target.with_suffix(".tmp")
    with tmp.open("w") as g:
        g.write(lines[0])
        for line in lines[1:]:
            if float(line.split(",", 1)[0]) > cut:
                break
            g.write(line)
    tmp.rename(target)
    return target


class CMA:
    """(mu/mu_w, lambda)-CMA-ES (Hansen's tutorial), maximising, in [0, 1]^n: a point outside the box is evaluated
    at its clip and penalised by its squared distance from it."""

    def __init__(self, start: np.ndarray, sigma: float, pop: int, seed: int):
        n = len(start)
        self.n, self.mean, self.sigma, self.pop = n, start.astype(float), sigma, pop
        self.mu = pop // 2
        w = np.log(self.mu + 0.5) - np.log(np.arange(1, self.mu + 1))
        self.w = w / w.sum()
        self.mueff = 1.0 / (self.w ** 2).sum()
        self.cc = (4 + self.mueff / n) / (n + 4 + 2 * self.mueff / n)
        self.cs = (self.mueff + 2) / (n + self.mueff + 5)
        self.c1 = 2 / ((n + 1.3) ** 2 + self.mueff)
        self.cmu = min(1 - self.c1, 2 * (self.mueff - 2 + 1 / self.mueff) / ((n + 2) ** 2 + self.mueff))
        self.damps = 1 + 2 * max(0.0, math.sqrt((self.mueff - 1) / (n + 1)) - 1) + self.cs
        self.chin = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
        self.pc, self.ps = np.zeros(n), np.zeros(n)
        self.B, self.D, self.C = np.eye(n), np.ones(n), np.eye(n)
        self.gen = 0
        self.rng = np.random.default_rng(seed)

    def ask(self) -> np.ndarray:
        z = self.rng.standard_normal((self.pop, self.n))
        return self.mean + self.sigma * (z * self.D) @ self.B.T

    def tell(self, xs: np.ndarray, scores: np.ndarray) -> None:
        order = np.argsort(-scores)
        top = xs[order[: self.mu]]
        old = self.mean
        self.mean = self.w @ top
        yw = (self.mean - old) / self.sigma
        inv_sqrt = self.B @ np.diag(1 / self.D) @ self.B.T
        self.ps = (1 - self.cs) * self.ps + math.sqrt(self.cs * (2 - self.cs) * self.mueff) * inv_sqrt @ yw
        self.gen += 1
        hsig = np.linalg.norm(self.ps) / math.sqrt(1 - (1 - self.cs) ** (2 * self.gen)) / self.chin < 1.4 + 2 / (self.n + 1)
        self.pc = (1 - self.cc) * self.pc + hsig * math.sqrt(self.cc * (2 - self.cc) * self.mueff) * yw
        art = (top - old) / self.sigma
        self.C = ((1 - self.c1 - self.cmu) * self.C + self.c1 * (np.outer(self.pc, self.pc) + (1 - hsig) * self.cc * (2 - self.cc) * self.C)
                  + self.cmu * art.T @ np.diag(self.w) @ art)
        self.sigma *= math.exp((self.cs / self.damps) * (np.linalg.norm(self.ps) / self.chin - 1))
        self.C = np.triu(self.C) + np.triu(self.C, 1).T
        d2, self.B = np.linalg.eigh(self.C)
        self.D = np.sqrt(np.maximum(d2, 1e-20))


class Evaluator:
    """Runs knob settings on the training tapes (one arena-sim batch a call), caches them by their decoded values and
    logs every one to evals.csv."""

    def __init__(self, base: dict, space: list[Knob], tapes: list[Path], threads: int, log: Path):
        self.base, self.space, self.tapes, self.threads = base, space, tapes, threads
        self.cache: dict[tuple, list[float]] = {}
        self.base_pnl: list[float] = []
        self.log = log
        self.count = 0
        new = not log.exists()
        self.file = log.open("a", newline="")
        self.writer = csv.writer(self.file)
        if new:
            self.writer.writerow(["eval", "gen", *(k.name for k in space), *(t.stem for t in tapes), "objective", "params"])

    def params(self, values: tuple) -> dict:
        p = dict(self.base)
        p.update({k.name: v for k, v in zip(self.space, values)})
        return p

    def objective(self, pnls: list[float]) -> float:
        return 100.0 * float(np.mean([(p - b) / abs(b) for p, b in zip(pnls, self.base_pnl)]))

    def run(self, settings: list[tuple], gen: int) -> list[list[float]]:
        todo = list(dict.fromkeys(s for s in settings if s not in self.cache))
        if todo:
            runs = qsim_rust.run_batch("ridge_maker", [self.params(s) for s in todo], self.tapes, self.threads)
            for s, row in zip(todo, runs):
                if any(r.get("error") for r in row):
                    raise RuntimeError(f"arena-sim: {[r.get('error') for r in row]}")
                self.cache[s] = [r["pnl"] for r in row]
        out = []
        for s in settings:
            pnls = self.cache[s]
            if self.base_pnl:
                self.count += 1
                self.writer.writerow([self.count, gen, *s, *(f"{p:.2f}" for p in pnls), f"{self.objective(pnls):.4f}",
                                      json.dumps({k.name: v for k, v in zip(self.space, s)})])
            out.append(pnls)
        self.file.flush()
        return out


def set_line(values: dict) -> str:
    return " ".join(f"--set {k}={v}" for k, v in values.items())


def load(a: argparse.Namespace) -> tuple[dict, list[Knob]]:
    base = paired_rust.overrides(BASES.get(a.base, a.base))
    fixed = dict(paired_rust.overrides(" ".join(f"--set {f}" for f in a.fix)))
    base.update(fixed)
    space = [k for k in SPACE if k.name not in fixed]
    return base, space


def start_point(base: dict, space: list[Knob]) -> np.ndarray:
    return np.array([k.unit(base.get(k.name, DEFAULTS[k.name])) for k in space])


def plateau(ev: Evaluator, space: list[Knob], best_u: np.ndarray, step: float, gen: int) -> list[tuple[str, float, object, float]]:
    """Each knob of the best point moved by +-step in u (one at a time), on the training tapes: (knob, du, value,
    objective)."""
    cells, rows = [], []
    for i, k in enumerate(space):
        for du in (-step, step):
            u = best_u.copy()
            u[i] = min(1.0, max(0.0, u[i] + du))
            if u[i] == best_u[i]:
                continue
            values = tuple(kk.value(x) for kk, x in zip(space, u))
            cells.append(values)
            rows.append((k.name, du, values[i]))
    pnls = ev.run(cells, gen)
    return [(name, du, v, ev.objective(p)) for (name, du, v), p in zip(rows, pnls)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--train", action="append", required=True, help="TAPE[:FRAC], the tape's first FRAC of time")
    ap.add_argument("--hold", action="append", default=[], help="held-out tapes, whole: base against best after the search")
    ap.add_argument("--base", default="F5", help="F3, F5 or a --set line")
    ap.add_argument("--fix", action="append", default=[], help="K=V: a knob held at V, out of the search")
    ap.add_argument("--evals", type=int, default=200)
    ap.add_argument("--pop", type=int, default=0, help="the population (0: 4 + 3 ln n)")
    ap.add_argument("--sigma", type=float, default=0.15, help="the first step, in the box's [0, 1] units")
    ap.add_argument("--plateau-step", type=float, default=0.1)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=Path("results/policy_search"))
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    base, space = load(a)
    tapes = []
    for spec in a.train:
        path, _, frac = spec.partition(":")
        if not Path(path).exists():
            raise SystemExit(f"no such tape: {path}")
        tapes.append(cut_tape(Path(path), float(frac) if frac else 1.0, a.out))
    if os.environ.get("ARENA_SIM_BIN"):  # another build of arena-sim (a twin worktree's), not rebuilt here
        qsim_rust.BINARY = Path(os.environ["ARENA_SIM_BIN"])
    else:
        qsim_rust.build()
    ev = Evaluator(base, space, tapes, a.threads, a.out / "evals.csv")
    start_u = start_point(base, space)
    start_v = tuple(k.value(u) for k, u in zip(space, start_u))
    ev.base_pnl = qsim_rust.run_batch("ridge_maker", [base], tapes, a.threads)[0]
    ev.base_pnl = [r["pnl"] for r in ev.base_pnl]
    print(f"base {a.base}: " + "  ".join(f"{t.stem} {p:,.0f}" for t, p in zip(tapes, ev.base_pnl)), flush=True)
    start_obj = ev.objective(ev.run([start_v], 0)[0])
    print(f"start point (the base decoded): objective {start_obj:+.3f}%  {json.dumps(dict(zip([k.name for k in space], start_v)))}", flush=True)
    pop = a.pop or 4 + int(3 * math.log(len(space)))
    cma = CMA(start_u, a.sigma, pop, a.seed)
    best = (start_obj, start_u.copy(), start_v)
    t0 = time.perf_counter()
    while ev.count < a.evals:
        xs = cma.ask()
        clipped = np.clip(xs, 0.0, 1.0)
        settings = [tuple(k.value(u) for k, u in zip(space, x)) for x in clipped]
        objs = np.array([ev.objective(p) for p in ev.run(settings, cma.gen + 1)])
        scores = objs - 100.0 * ((xs - clipped) ** 2).sum(axis=1)
        cma.tell(xs, scores)
        i = int(np.argmax(objs))
        if objs[i] > best[0]:
            best = (float(objs[i]), clipped[i].copy(), settings[i])
        print(f"gen {cma.gen:>2} evals {ev.count:>4} {time.perf_counter() - t0:>6.0f} s  best of gen {objs[i]:+.3f}%  "
              f"mean {objs.mean():+.3f}%  overall {best[0]:+.3f}%  sigma {cma.sigma:.3f}", flush=True)
    names = [k.name for k in space]
    best_vals = dict(zip(names, best[2]))
    print(f"\nbest objective {best[0]:+.3f}% over the base ({a.base}); its tapes: "
          + "  ".join(f"{t.stem} {p:,.0f} ({p - b:+,.0f})" for t, p, b in zip(tapes, ev.cache[best[2]], ev.base_pnl)))
    mean_vals = tuple(k.value(u) for k, u in zip(space, np.clip(cma.mean, 0, 1)))
    print(f"the search's final mean: objective {ev.objective(ev.run([mean_vals], cma.gen + 1)[0]):+.3f}%  "
          f"{json.dumps(dict(zip(names, mean_vals)))}")
    print("best: " + set_line(best_vals))
    (a.out / "best.json").write_text(json.dumps({"objective": best[0], "base": a.base, "knobs": best_vals,
                                                 "mean_knobs": dict(zip(names, mean_vals))}, indent=1))
    print(f"\nplateau: each knob of the best moved by +-{a.plateau_step} of its range (training tapes)")
    for name, du, value, obj in plateau(ev, space, best[1], a.plateau_step, cma.gen + 2):
        print(f"  {name:<16} {du:+.2f} -> {value!s:<10} {obj:+.3f}%  ({obj - best[0]:+.3f})")
    bots = [f"{a.base}=:{BASES.get(a.base, a.base)}", f"BEST=:{BASES.get(a.base, a.base)} {set_line(best_vals)}"]
    command = " ".join(["uv run python -m experiments.day.paired_rust", *a.hold] + [f"--bot {shlex.quote(b)}" for b in bots])
    print(f"\nheld-out check: {command}")
    if a.hold:
        qsim_rust.build = lambda: qsim_rust.BINARY
        paired_rust.main([*a.hold, *(x for b in bots for x in ("--bot", b)), "--threads", str(a.threads)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
