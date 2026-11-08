//! R4-PG, the profit gate (8 Nov; Rust only, off by default: R3-F5's 515670.00 unchanged): a second online ridge in
//! ridge_maker whose label is what a take decision earns, not the mid move. For a moment t with direction
//! d = sign(signal) (the forecast net of the skew, the take's own signal), the label is
//! d * (mid(t + PG_H_MS) - mid(t)) - half the spread at t (PG_HOLD 1: the mid at the first opposite take signal after t
//! instead, capped at PG_CAP_MS; PG_BIN 1: the indicator of a positive label, a linear-probability P(net > 0)). Its
//! features are the main model's times d, d * signal, the half spread, d * inventory / EXPOSURE, the jump bar's state
//! and a constant; an observation every PG_OBS_MS (20) while |signal| - half spread >= PG_TMIN (-99: always), learned
//! once its label matures (the main model's decay, ridge and FIT_US). `PG` (0: off): 1 a gate, a take fires only while
//! the gate's prediction that way is above PG_G; 2 a vote, each side's bar lowered by PG_K * (prediction - PG_G),
//! never below 0. Until MIN_LABELS labels the gate passes everything. `PG_STATS` 1: one stderr line at the end with
//! the forecast takes, their lots and the gate's vetoes (appended to the file in env PG_STATS_FILE when set; works
//! with PG 0, for the base's counts).

use std::collections::VecDeque;

use crate::params::Params;

pub const KEYS: [&str; 12] =
    ["PG", "PG_H_MS", "PG_G", "PG_K", "PG_BIN", "PG_HOLD", "PG_CAP_MS", "PG_TMIN", "PG_OBS_MS", "PG_STATS", "PG_TAG", "PG_UNSIGNED"];

const NG: usize = 72;

pub struct ProfitGate {
    pub mode: i64,
    /// PG_UNSIGNED (0: R4-PG as tested): a bitmask of main-model features that enter the gate as x, not d * x (the
    /// direction-free ones; on R3-F5's 39: 2^24 + 2^29 + 2^30 + 2^38 = 276505296896, FLOWGRP's volume share, LIQ's
    /// young share and young x dispersion, the filter's sd), so they can lower or raise a take's value either way
    pub unsigned: u64,
    h_us: i64,
    pub g: f64,
    pub k: f64,
    bin: bool,
    hold: bool,
    cap_us: i64,
    tmin: f64,
    obs_us: i64,
    min_labels: i64,
    memory_us: i64,
    ridge_min: f64,
    ridge_frac: f64,
    fit_us: i64,
    stats: bool,
    tag: i64,
    /// (time, mid, d, half spread, features); in PG_HOLD the matured ones wait in `ready` with their label
    pending: VecDeque<(i64, f64, i64, f64, [f64; NG])>,
    ready: VecDeque<(f64, [f64; NG])>,
    last_obs: i64,
    last_label: Option<i64>,
    last_fit: Option<i64>,
    labels: i64,
    mass: f64,
    xx: Vec<[f64; NG]>,
    xy: [f64; NG],
    weights: [f64; NG],
    pub takes: i64,
    pub lots: i64,
    pub vetoes: i64,
}

impl ProfitGate {
    pub fn new(params: &Params) -> Result<ProfitGate, String> {
        Ok(ProfitGate {
            mode: params.int("PG", 0)?,
            h_us: params.int("PG_H_MS", 1000)? * 1000,
            unsigned: params.int("PG_UNSIGNED", 0)? as u64,
            g: params.float("PG_G", 0.0)?,
            k: params.float("PG_K", 0.0)?,
            bin: params.int("PG_BIN", 0)? > 0,
            hold: params.int("PG_HOLD", 0)? > 0,
            cap_us: params.int("PG_CAP_MS", 30_000)? * 1000,
            tmin: params.float("PG_TMIN", -99.0)?,
            obs_us: params.int("PG_OBS_MS", 20)? * 1000,
            min_labels: params.int("MIN_LABELS", 200)?,
            memory_us: params.int("MODEL_MEMORY_US", 30_000_000)?,
            ridge_min: params.float("RIDGE_MIN", 10.0)?,
            ridge_frac: params.float("RIDGE_FRAC", 0.001)?,
            fit_us: params.int("FIT_US", 1_000_000)?,
            stats: params.int("PG_STATS", 0)? > 0,
            tag: params.int("PG_TAG", 0)?,
            pending: VecDeque::new(),
            ready: VecDeque::new(),
            last_obs: i64::MIN / 2,
            last_label: None,
            last_fit: None,
            labels: 0,
            mass: 0.0,
            xx: vec![[0.0; NG]; NG],
            xy: [0.0; NG],
            weights: [0.0; NG],
            takes: 0,
            lots: 0,
            vetoes: 0,
        })
    }

    pub fn ready(&self) -> bool {
        self.labels >= self.min_labels
    }

    /// the gate's features for direction d: d * x, d * signal, half spread, d * inventory / exposure, jump, 1
    pub fn feats(x: &[f64], d: f64, signal: f64, hs: f64, inv: f64, jump: bool, unsigned: u64) -> [f64; NG] {
        let mut g = [0.0; NG];
        let n = x.len();
        for i in 0..n {
            g[i] = if i < 64 && (unsigned >> i) & 1 == 1 { x[i] } else { d * x[i] };
        }
        g[n] = d * signal;
        g[n + 1] = hs;
        g[n + 2] = d * inv;
        g[n + 3] = if jump { 1.0 } else { 0.0 };
        g[n + 4] = 1.0;
        g
    }

    pub fn width(n: usize) -> usize {
        n + 5
    }

    pub fn predict(&self, g: &[f64; NG], w: usize) -> f64 {
        let mut s = 0.0;
        for i in 0..w {
            s += self.weights[i] * g[i];
        }
        s
    }

    /// an observation every PG_OBS_MS while the signal is near enough a take
    pub fn observe(&mut self, now: i64, mid: f64, signal: f64, hs: f64, g: [f64; NG]) {
        if self.mode <= 0 || now - self.last_obs < self.obs_us || signal == 0.0 {
            return;
        }
        if signal.abs() - hs < self.tmin {
            return;
        }
        self.last_obs = now;
        let d = if signal > 0.0 { 1 } else { -1 };
        self.pending.push_back((now, mid, d, hs, g));
    }

    fn label(&self, d: i64, mid0: f64, hs: f64, mid: f64) -> f64 {
        let net = (d as f64 * (mid - mid0) - hs).clamp(-20.0, 20.0);
        if self.bin {
            if net > 0.0 {
                1.0
            } else {
                0.0
            }
        } else {
            net
        }
    }

    /// PG_HOLD: a take signal `sign` now closes every pending observation the other way at this mid
    pub fn on_signal(&mut self, sign: i64, mid: f64) {
        if self.mode <= 0 || !self.hold {
            return;
        }
        let mut keep = VecDeque::with_capacity(self.pending.len());
        while let Some(p) = self.pending.pop_front() {
            if p.2 == -sign {
                let y = self.label(p.2, p.1, p.3, mid);
                self.ready.push_back((y, p.4));
            } else {
                keep.push_back(p);
            }
        }
        self.pending = keep;
    }

    fn update(&mut self, now: i64, y: f64, g: &[f64; NG], w: usize) {
        let elapsed = match self.last_label {
            None => 0,
            Some(t) => now - t,
        };
        let decay = ((-(elapsed.max(0))) as f64 / self.memory_us as f64).exp();
        self.last_label = Some(now);
        self.mass = self.mass * decay + 1.0;
        for i in 0..w {
            self.xy[i] = self.xy[i] * decay + g[i] * y;
            for j in 0..w {
                self.xx[i][j] = self.xx[i][j] * decay + g[i] * g[j];
            }
        }
        self.labels += 1;
    }

    /// the matured labels into the sums, then a refit at most every FIT_US
    pub fn learn(&mut self, now: i64, mid: f64, w: usize) {
        if self.mode <= 0 {
            return;
        }
        if self.hold {
            while let Some(&(t, mid0, d, hs, g)) = self.pending.front() {
                if now - t < self.cap_us {
                    break;
                }
                self.pending.pop_front();
                let y = self.label(d, mid0, hs, mid);
                self.ready.push_back((y, g));
            }
            while let Some((y, g)) = self.ready.pop_front() {
                self.update(now, y, &g, w);
            }
        } else {
            while let Some(&(t, mid0, d, hs, g)) = self.pending.front() {
                if t + self.h_us > now {
                    break;
                }
                self.pending.pop_front();
                if now - t > self.h_us + 1_000_000 {
                    continue;
                }
                let y = self.label(d, mid0, hs, mid);
                self.update(now, y, &g, w);
            }
        }
        if self.labels < self.min_labels {
            return;
        }
        if let Some(t) = self.last_fit {
            if now - t < self.fit_us {
                return;
            }
        }
        self.last_fit = Some(now);
        let r = self.ridge_frac * self.mass;
        let ridge = if r > self.ridge_min { r } else { self.ridge_min };
        let mut a = vec![[0.0f64; NG + 1]; w];
        for i in 0..w {
            a[i][..w].copy_from_slice(&self.xx[i][..w]);
            a[i][w] = self.xy[i];
            a[i][i] += ridge;
        }
        for col in 0..w {
            let pivot = a[col][col];
            if !pivot.is_finite() || pivot <= 1e-12 {
                return;
            }
            for j in col..=w {
                a[col][j] /= pivot;
            }
            for i in 0..w {
                if i == col {
                    continue;
                }
                let factor = a[i][col];
                if factor == 0.0 {
                    continue;
                }
                for j in col..=w {
                    a[i][j] -= factor * a[col][j];
                }
            }
        }
        let mut weights = [0.0; NG];
        for i in 0..w {
            weights[i] = a[i][w];
        }
        if weights.iter().all(|x| x.is_finite()) {
            self.weights = weights;
        }
    }
}

impl Drop for ProfitGate {
    fn drop(&mut self) {
        if self.stats {
            let line = format!(
                "PG_STATS tag={} mode={} h_ms={} g={} k={} bin={} hold={} tmin={} takes={} lots={} vetoes={} labels={}\n",
                self.tag, self.mode, self.h_us / 1000, self.g, self.k, self.bin as i64, self.hold as i64, self.tmin,
                self.takes, self.lots, self.vetoes, self.labels
            );
            match std::env::var("PG_STATS_FILE") {
                Ok(path) => {
                    use std::io::Write;
                    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
                        let _ = f.write_all(line.as_bytes());
                    }
                }
                Err(_) => eprint!("{line}"),
            }
        }
    }
}
