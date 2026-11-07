//! The backtest CSV as `ExchangeSimulator.iter_backtest` reads it: `Time` in seconds to µs by
//! `int(round(float(t) * 1_000_000))`, `Insert`/`Cancel`, `B`/`A`, `Lifespan` `F` = IOC, anything else (or no
//! column) a resting limit order. Read once, shared by every run of a grid.

use std::collections::HashMap;
use std::path::Path;

/// Market order ids: the tape's decimal ids as their number; any other spelling interned with this bit.
pub const INTERNED_BIT: u64 = 1 << 62;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Side {
    Buy,
    Sell,
}

impl Side {
    pub fn sign(self) -> i64 {
        match self {
            Side::Buy => 1,
            Side::Sell => -1,
        }
    }
    pub fn index(self) -> usize {
        match self {
            Side::Buy => 0,
            Side::Sell => 1,
        }
    }
    pub fn opposite(self) -> Side {
        match self {
            Side::Buy => Side::Sell,
            Side::Sell => Side::Buy,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Row {
    pub ts: i64,
    pub id: u64,
    pub price: i64,
    pub volume: i64,
    pub side: Side,
    pub insert: bool,
    pub ioc: bool,
}

pub struct Tape {
    pub rows: Vec<Row>,
    /// the interned ids' spellings, by index
    pub names: Vec<String>,
}

fn order_key(id: &str, interned: &mut HashMap<String, u64>, names: &mut Vec<String>) -> u64 {
    let canonical = !id.is_empty() && id.len() <= 18 && id.bytes().all(|b| b.is_ascii_digit()) && (id == "0" || !id.starts_with('0'));
    if canonical {
        return id.parse().unwrap();
    }
    if let Some(&k) = interned.get(id) {
        return k;
    }
    let k = INTERNED_BIT | names.len() as u64;
    names.push(id.to_string());
    interned.insert(id.to_string(), k);
    k
}

fn int(field: &str, what: &str, line: usize) -> Result<i64, String> {
    field.trim().parse::<i64>().map_err(|_| format!("line {line}: bad {what} {field:?}"))
}

pub fn parse(text: &str) -> Result<Tape, String> {
    let mut lines = text.split('\n');
    let header = match lines.next() {
        Some(h) if !h.trim_end_matches('\r').is_empty() => h.trim_end_matches('\r'),
        _ => return Ok(Tape { rows: Vec::new(), names: Vec::new() }),
    };
    let columns: Vec<&str> = header.split(',').collect();
    let find = |name: &str| columns.iter().position(|c| *c == name);
    let col = |name: &str| find(name).ok_or_else(|| format!("no column {name:?} in the header"));
    let (time_i, op_i, id_i, side_i, vol_i, price_i) =
        (col("Time")?, col("Operation")?, col("OrderId")?, col("Side")?, col("Volume")?, col("Price")?);
    let life_i = find("Lifespan");
    let mut interned = HashMap::new();
    let mut names = Vec::new();
    let mut rows = Vec::with_capacity(text.len() / 32);
    let mut fields: Vec<&str> = Vec::with_capacity(columns.len());
    for (n, raw) in lines.enumerate() {
        let line = raw.trim_end_matches('\r');
        if line.is_empty() {
            continue;
        }
        let lineno = n + 2;
        fields.clear();
        fields.extend(line.split(','));
        let get = |i: usize| fields.get(i).copied().ok_or_else(|| format!("line {lineno}: too few fields"));
        let seconds: f64 = get(time_i)?.trim().parse().map_err(|_| format!("line {lineno}: bad Time"))?;
        let ts = crate::py::round_int(seconds * 1_000_000.0);
        let id = order_key(get(id_i)?, &mut interned, &mut names);
        match get(op_i)? {
            "Insert" => {
                let side = match get(side_i)? {
                    "B" => Side::Buy,
                    "A" => Side::Sell,
                    other => return Err(format!("line {lineno}: bad Side {other:?}")),
                };
                let volume = int(get(vol_i)?, "Volume", lineno)?;
                let price = int(get(price_i)?, "Price", lineno)?;
                if ts < 0 || volume <= 0 || price <= 0 {
                    return Err(format!("line {lineno}: Invalid MarketEvent fields"));
                }
                let ioc = life_i.map_or(false, |i| fields.get(i) == Some(&"F"));
                rows.push(Row { ts, id, price, volume, side, insert: true, ioc });
            }
            "Cancel" => {
                if ts < 0 {
                    return Err(format!("line {lineno}: Invalid MarketEvent fields"));
                }
                rows.push(Row { ts, id, price: 0, volume: 0, side: Side::Buy, insert: false, ioc: false });
            }
            other => return Err(format!("Unsupported operation: {other}")),
        }
    }
    Ok(Tape { rows, names })
}

pub fn load(path: &Path) -> Result<Tape, String> {
    let bytes = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    if bytes.starts_with(&[0x1f, 0x8b]) {
        return Err(format!("{}: gzipped; the simulator reads plain CSV (gunzip -k it first)", path.display()));
    }
    let text = String::from_utf8(bytes).map_err(|e| format!("{}: {e}", path.display()))?;
    parse(&text)
}
