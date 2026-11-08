//! R4-C1, the take's speed calibration (8 Nov; off by default: R3-F5's 1029443.00 on round4_public and 515670.00 on
//! round3_public unchanged). The statistics agent found F5's forecast miscalibrated by market speed on every real tape:
//! the slope of the realised 400-ms move on the forecast is ~1.35-1.6 in the fastest speed tercile and ~0.83-0.87 in the
//! slowest (speed: L8's QS_RATE rate, `qs_rate`). This layer rescales the take's forecast (before the skew comes off);
//! the quotes and every other path keep the raw forecast.
//!
//! `CAL` (0: off):
//! - 1, online: K speed bins (`CAL_E1` < `CAL_E2`, ticks/s; `CAL_E1` < 0: tercile edges learned online from a histogram
//!   of the speed at every observation, refreshed every 2,000), each with a running regression of the realised move over
//!   `CAL_H_US` (HORIZON_US) on the forecast, an observation at every book event once the ridge is warm, learned when
//!   its label matures (causal), decayed over `CAL_MEM_US` (0: no decay), Huber-weighted (`CAL_HUBER`, 0: off) on the
//!   residual, with a prior slope 1 at `CAL_PRIOR` observations (of the mean squared forecast). The take uses
//!   slope_bin x forecast (+ intercept_bin with `CAL_ICEPT` 1, its prior 0 at the same mass), the slope clipped to
//!   [`CAL_LO`, `CAL_HI`]. `CAL_REL` 1: slope_bin / slope_all (the all-bins regression), so the bar keeps its average
//!   meaning and only the bins' relative calibration moves the takes; 2: over the middle bin's slope. `CAL_W` (1): the
//!   factor shrunk toward 1, 1 + W x (slope - 1).
//! - 2, fixed: forecast x clip(1 + `CAL_A` x (speed - `CAL_S0`), `CAL_FLO`, `CAL_FHI`).
//! - 3, online continuous: a running regression of the move on [forecast, forecast x (speed - `CAL_S0`)] (same labels,
//!   decay, Huber and prior: slope 1, speed term 0), the take using b0 x forecast + b1 x forecast x (speed - `CAL_S0`),
//!   its factor clipped to [`CAL_LO`, `CAL_HI`]; with `CAL_REL` 1, divided by the all-bins slope.
//! `CAL_RAW` 1 (default): the forecast observed and rescaled is the ridge's before its +-2 clamp (the clamp biases the
//! fast bin's slope up); `CAL_XMIN` / `CAL_XMAX` (0 / 99): only observations with |forecast| in that range are learned
//! (the take's decisions turn on forecasts near the bar, 0.75). `CAL_STATS` 1: one stderr line at the end (each bin's slope, mass and edges; appended to env CAL_STATS_FILE when set).

use std::collections::VecDeque;

use crate::params::Params;

pub const KEYS: [&str; 20] = [
    "CAL", "CAL_H_US", "CAL_MEM_US", "CAL_PRIOR", "CAL_LO", "CAL_HI", "CAL_E1", "CAL_E2", "CAL_ICEPT", "CAL_HUBER",
    "CAL_REL", "CAL_A", "CAL_S0", "CAL_FLO", "CAL_FHI", "CAL_STATS", "CAL_RAW", "CAL_XMIN", "CAL_XMAX", "CAL_W",
];

const NB: usize = 3;
const HB: usize = 4000; // histogram bins of 0.025 ticks/s up to 100
const HW: f64 = 0.025;

#[derive(Clone, Copy, Default)]
struct Reg {
    s1: f64,
    sx: f64,
    sy: f64,
    sxx: f64,
    sxy: f64,
    // mode 3: z = x * (speed - s0)
    sxz: f64,
    szz: f64,
    szy: f64,
    last: Option<i64>,
}

pub struct Calib {
    pub mode: i64,
    h_us: i64,
    mem_us: f64,
    prior: f64,
    lo: f64,
    hi: f64,
    edges: [f64; 2],
    online_edges: bool,
    icept: bool,
    huber: f64,
    rel: i64,
    w: f64,
    a: f64,
    s0: f64,
    flo: f64,
    fhi: f64,
    stats: bool,
    /// CAL_RAW 1 (default): the forecast before the ridge's +-2 clamp, recomputed from its weights (F5's take source)
    pub raw: bool,
    xmin: f64,
    xmax: f64,
    /// (time, mid, forecast, speed, bin)
    pending: VecDeque<(i64, f64, f64, f64, usize)>,
    bins: [Reg; NB],
    all: Reg,
    /// the undecayed mean squared forecast's sums (the prior's scale)
    gx2: f64,
    gn: f64,
    hist: Vec<u32>,
    hist_n: u64,
    labels: i64,
    pub takes: i64,
    pub lots: i64,
}

impl Calib {
    pub fn new(params: &Params, horizon_us: i64) -> Result<Calib, String> {
        let e1 = params.float("CAL_E1", -1.0)?;
        let e2 = params.float("CAL_E2", -1.0)?;
        Ok(Calib {
            mode: params.int("CAL", 0)?,
            h_us: params.int("CAL_H_US", horizon_us)?,
            mem_us: params.float("CAL_MEM_US", 0.0)?,
            prior: params.float("CAL_PRIOR", 2000.0)?,
            lo: params.float("CAL_LO", 0.5)?,
            hi: params.float("CAL_HI", 2.5)?,
            edges: [e1, e2],
            online_edges: e1 < 0.0,
            icept: params.int("CAL_ICEPT", 0)? > 0,
            huber: params.float("CAL_HUBER", 6.0)?,
            rel: params.int("CAL_REL", 0)?,
            w: params.float("CAL_W", 1.0)?,
            a: params.float("CAL_A", 0.0)?,
            s0: params.float("CAL_S0", 2.5)?,
            flo: params.float("CAL_FLO", 0.5)?,
            fhi: params.float("CAL_FHI", 2.0)?,
            stats: params.int("CAL_STATS", 0)? > 0,
            raw: params.int("CAL_RAW", 1)? > 0,
            xmin: params.float("CAL_XMIN", 0.0)?,
            xmax: params.float("CAL_XMAX", 99.0)?,
            pending: VecDeque::new(),
            bins: [Reg::default(); NB],
            all: Reg::default(),
            gx2: 0.0,
            gn: 0.0,
            hist: vec![0; HB],
            hist_n: 0,
            labels: 0,
            takes: 0,
            lots: 0,
        })
    }

    fn bin(&self, speed: f64) -> usize {
        if !(speed >= self.edges[0]) {
            0
        } else if !(speed >= self.edges[1]) {
            1
        } else {
            2
        }
    }

    fn refresh_edges(&mut self) {
        let n = self.hist_n as f64;
        let (t1, t2) = (n / 3.0, 2.0 * n / 3.0);
        let mut cum = 0.0;
        let mut e = [f64::NAN; 2];
        for (i, &c) in self.hist.iter().enumerate() {
            let next = cum + c as f64;
            if e[0].is_nan() && next >= t1 {
                e[0] = (i as f64 + 1.0) * HW;
            }
            if e[1].is_nan() && next >= t2 {
                e[1] = (i as f64 + 1.0) * HW;
                break;
            }
            cum = next;
        }
        if !e[1].is_nan() {
            self.edges = e;
        }
    }

    /// an observation at a book event: the take's forecast and the speed now; matured labels learned first
    pub fn observe(&mut self, now: i64, mid: f64, x: f64, speed: f64) {
        self.learn(now, mid);
        if self.online_edges {
            let i = ((speed / HW) as usize).min(HB - 1);
            self.hist[i] += 1;
            self.hist_n += 1;
            if self.hist_n % 2000 == 0 {
                self.refresh_edges();
            }
        }
        let b = if self.online_edges && self.hist_n < 2000 { 1 } else { self.bin(speed) };
        self.pending.push_back((now, mid, x, speed, b));
    }

    fn learn(&mut self, now: i64, mid: f64) {
        while let Some(&(t, m0, x, speed, b)) = self.pending.front() {
            if t + self.h_us > now {
                break;
            }
            self.pending.pop_front();
            if now - t > self.h_us + 1_000_000 {
                continue;
            }
            if !(x.abs() >= self.xmin && x.abs() <= self.xmax) {
                continue;
            }
            let y = (mid - m0).clamp(-20.0, 20.0);
            let z = x * (speed - self.s0);
            self.gx2 += x * x;
            self.gn += 1.0;
            self.labels += 1;
            let fit = if self.mode == 3 {
                self.factor3(speed) * x
            } else {
                let (sl, ic) = self.reg_slope(&self.bins[b]);
                sl * x + ic
            };
            let w = if self.huber > 0.0 { (self.huber / (y - fit).abs().max(1e-12)).min(1.0) } else { 1.0 };
            let mem = self.mem_us;
            for r in [&mut self.bins[b], &mut self.all] {
                let d = match (r.last, mem > 0.0) {
                    (Some(l), true) => (-((now - l).max(0) as f64) / mem).exp(),
                    _ => 1.0,
                };
                r.last = Some(now);
                r.s1 = r.s1 * d + w;
                r.sx = r.sx * d + w * x;
                r.sy = r.sy * d + w * y;
                r.sxx = r.sxx * d + w * x * x;
                r.sxy = r.sxy * d + w * x * y;
                r.sxz = r.sxz * d + w * x * z;
                r.szz = r.szz * d + w * z * z;
                r.szy = r.szy * d + w * z * y;
            }
        }
    }

    fn reg_slope(&self, r: &Reg) -> (f64, f64) {
        let pm = self.prior * if self.gn > 0.0 { self.gx2 / self.gn } else { 1.0 };
        if self.icept && r.s1 > 0.0 {
            let cxx = r.sxx - r.sx * r.sx / r.s1;
            let cxy = r.sxy - r.sx * r.sy / r.s1;
            let slope = (cxy + pm) / (cxx + pm);
            (slope, (r.sy - slope * r.sx) / (r.s1 + self.prior))
        } else {
            ((r.sxy + pm) / (r.sxx + pm), 0.0)
        }
    }

    fn slope_icept(&self, b: usize) -> (f64, f64) {
        let (s, i) = self.reg_slope(&self.bins[b]);
        // CAL_REL 1: over the all-bins slope; 2: over the middle bin's; CAL_W: the factor shrunk toward 1
        let s = match self.rel {
            1 => s / self.reg_slope(&self.all).0.max(1e-6),
            2 => s / self.reg_slope(&self.bins[1]).0.max(1e-6),
            _ => s,
        };
        ((1.0 + self.w * (s - 1.0)).clamp(self.lo, self.hi), self.w * i)
    }

    /// mode 3: the factor b0 + b1 (speed - s0) from the 2x2 ridge with prior (1, 0)
    fn factor3(&self, speed: f64) -> f64 {
        let r = &self.all;
        let pm = self.prior * if self.gn > 0.0 { self.gx2 / self.gn } else { 1.0 };
        // prior: pm pseudo-mass on b0 = 1, pm on b1 = 0 (the z scale taken as x's)
        let (a11, a12, a22) = (r.sxx + pm, r.sxz, r.szz + pm);
        let (c1, c2) = (r.sxy + pm, r.szy);
        let det = a11 * a22 - a12 * a12;
        if det.abs() < 1e-12 {
            return 1.0;
        }
        let b0 = (c1 * a22 - c2 * a12) / det;
        let b1 = (a11 * c2 - a12 * c1) / det;
        let f = b0 + b1 * (speed - self.s0);
        let f = if self.rel > 0 { f / ((r.sxy + pm) / (r.sxx + pm)).max(1e-6) } else { f };
        (1.0 + self.w * (f - 1.0)).clamp(self.lo, self.hi)
    }

    /// the take's calibrated forecast
    pub fn apply(&self, x: f64, speed: f64) -> f64 {
        match self.mode {
            1 => {
                let b = if self.online_edges && self.hist_n < 2000 { 1 } else { self.bin(speed) };
                let (s, i) = self.slope_icept(b);
                s * x + i
            }
            2 => x * (1.0 + self.a * (speed - self.s0)).clamp(self.flo, self.fhi),
            3 => x * self.factor3(speed),
            _ => x,
        }
    }
}

impl Drop for Calib {
    fn drop(&mut self) {
        if self.stats {
            let s: Vec<String> = (0..NB)
                .map(|b| {
                    let (sl, ic) = self.slope_icept(b);
                    format!("{:.3}/{:.3}/{:.0}", sl, ic, self.bins[b].s1)
                })
                .collect();
            let (g, _) = self.reg_slope(&self.all);
            let line = format!(
                "CAL_STATS mode={} raw={} xmin={} xmax={} rel={} w={} prior={} mem_us={} lo={} hi={} icept={} a={} s0={} flo={} fhi={} takes={} lots={} edges={:.3},{:.3} bins(slope/icept/mass)={} all={:.3} labels={}\n",
                self.mode, self.raw as i64, self.xmin, self.xmax, self.rel, self.w, self.prior, self.mem_us, self.lo, self.hi, self.icept as i64, self.a, self.s0,
                self.flo, self.fhi, self.takes, self.lots, self.edges[0], self.edges[1], s.join(" "), g, self.labels
            );
            match std::env::var("CAL_STATS_FILE") {
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
