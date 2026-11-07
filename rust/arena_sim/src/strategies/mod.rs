//! Rust versions of Python strategies, each line for line with its file. `make` builds one by name from its
//! parameters (the Python file's module globals by name; a Rust-only knob is named in the strategy's docs).

pub mod fallback_maker;
pub mod probe;
pub mod room_maker;
pub mod trend_follower;

use crate::params::Params;
use crate::sim::Strategy;

pub const NAMES: [&str; 7] =
    ["trend_follower", "fallback_maker", "room_maker", "shrink_maker", "alloc_maker", "signal_maker", "probe"];

pub fn make(name: &str, params: &Params) -> Result<Box<dyn Strategy + Send>, String> {
    match name {
        "trend_follower" => Ok(Box::new(trend_follower::TrendFollower::new(params)?)),
        "fallback_maker" => Ok(Box::new(fallback_maker::FallbackMaker::new(params)?)),
        "room_maker" | "shrink_maker" | "alloc_maker" | "signal_maker" => {
            Ok(Box::new(room_maker::RoomMaker::new(name, params)?))
        }
        "probe" => Ok(Box::new(probe::Probe::new(params)?)),
        _ => Err(format!("unknown strategy {name:?} (known: {})", NAMES.join(", "))),
    }
}
