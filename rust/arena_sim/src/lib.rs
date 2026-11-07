//! The Arena's exchange simulator (`simulator/simulator.py` at the repo root) in Rust, giving the same
//! `result.json` and `pnl.csv` to the bit, and Rust versions of Python strategies behind the `Strategy` trait.
//! See ../README.md, "arena_sim".

pub mod data;
pub mod params;
pub mod py;
pub mod sim;
pub mod strategies;

use std::fmt::Write;

/// result.json as `json.dump(result.model_dump(mode='json'), file, indent=2)` writes it.
pub fn result_json(o: &sim::Outcome) -> String {
    let se = o.pnl_se.map_or("null".to_string(), py::repr);
    format!(
        "{{\n  \"fills\": {},\n  \"traded_volume\": {},\n  \"inventory\": {},\n  \"cash\": {},\n  \"mark_price\": {},\n  \"breach_penalty\": {},\n  \"pnl\": {},\n  \"pnl_se\": {},\n  \"abs_inventory_q50\": {},\n  \"abs_inventory_q68\": {},\n  \"abs_inventory_q95\": {},\n  \"abs_inventory_q997\": {}\n}}",
        o.fills,
        o.traded_volume,
        o.inventory,
        py::repr(o.cash),
        py::repr(o.mark_price),
        py::repr(o.breach_penalty),
        py::repr(o.pnl),
        se,
        o.abs_inventory_q50,
        o.abs_inventory_q68,
        o.abs_inventory_q95,
        o.abs_inventory_q997
    )
}

/// pnl.csv as simulator.main writes it: elapsed seconds from the first point, and the PnL.
pub fn pnl_csv(o: &sim::Outcome) -> String {
    let mut out = String::from("elapsed_s,pnl\n");
    let start = o.curve[0].0;
    for &(ts, pnl) in &o.curve {
        let _ = writeln!(out, "{},{}", py::repr((ts - start) as f64 / 1_000_000.0), py::repr(pnl));
    }
    out
}

/// The lines simulator.main prints after a run (without `log_dir=`).
pub fn summary_lines(o: &sim::Outcome) -> String {
    let se = o.pnl_se.map_or("none".to_string(), py::fixed2);
    format!(
        "Simulation complete\nfills={}\ntraded_volume={}\ninventory={}\ncash={}\nmark_price={}\nbreach_penalty={}\npnl={}\npnl_se={}\nabs_inventory_q50={}\nabs_inventory_q68={}\nabs_inventory_q95={}\nabs_inventory_q997={}",
        o.fills,
        o.traded_volume,
        o.inventory,
        py::fixed2(o.cash),
        py::fixed2(o.mark_price),
        py::fixed2(o.breach_penalty),
        py::fixed2(o.pnl),
        se,
        o.abs_inventory_q50,
        o.abs_inventory_q68,
        o.abs_inventory_q95,
        o.abs_inventory_q997
    )
}

/// One run, as a JSON line for `arena-sim batch` (python/arena/qsim_rust.py reads it).
pub fn run_json(task: usize, file: usize, o: &sim::Outcome, seconds: f64) -> String {
    let mut out = String::with_capacity(64 * o.curve.len() + 512);
    let se = o.pnl_se.map_or("null".to_string(), py::repr);
    let _ = write!(
        out,
        "{{\"task\":{task},\"file\":{file},\"fills\":{},\"traded_volume\":{},\"inventory\":{},\"cash\":{},\"mark_price\":{},\"breach_penalty\":{},\"pnl\":{},\"pnl_se\":{se},\"abs_inventory_q50\":{},\"abs_inventory_q68\":{},\"abs_inventory_q95\":{},\"abs_inventory_q997\":{},\"rejected\":{},\"cancel_rejected\":{},\"seconds\":{},\"curve\":[",
        o.fills,
        o.traded_volume,
        o.inventory,
        py::repr(o.cash),
        py::repr(o.mark_price),
        py::repr(o.breach_penalty),
        py::repr(o.pnl),
        o.abs_inventory_q50,
        o.abs_inventory_q68,
        o.abs_inventory_q95,
        o.abs_inventory_q997,
        o.rejected,
        o.cancel_rejected,
        py::repr(seconds)
    );
    for (i, &(ts, pnl)) in o.curve.iter().enumerate() {
        let _ = write!(out, "{}[{ts},{}]", if i > 0 { "," } else { "" }, py::repr(pnl));
    }
    out.push_str("],\"error\":null}");
    out
}

pub fn error_json(task: usize, file: usize, error: &str) -> String {
    let escaped: String = error.chars().map(|c| if c == '"' || c == '\\' || c.is_control() { ' ' } else { c }).collect();
    format!("{{\"task\":{task},\"file\":{file},\"error\":\"{escaped}\"}}")
}
