//! A strategy's parameters: a flat JSON object of numbers (`{"QUOTE": 5, "LIMIT": 50}`), the keys the Python
//! file's module globals are named by, so arena.qgrid's `--grid` keys work unchanged.

use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Int(i64),
    Float(f64),
    Bool(bool),
    Str(String),
}

#[derive(Clone, Debug, Default)]
pub struct Params(pub BTreeMap<String, Value>);

struct Parser<'a> {
    s: &'a [u8],
    i: usize,
}

impl<'a> Parser<'a> {
    fn ws(&mut self) {
        while self.i < self.s.len() && self.s[self.i].is_ascii_whitespace() {
            self.i += 1;
        }
    }
    fn eat(&mut self, c: u8) -> Result<(), String> {
        self.ws();
        if self.s.get(self.i) == Some(&c) {
            self.i += 1;
            Ok(())
        } else {
            Err(format!("expected {:?} at byte {}", c as char, self.i))
        }
    }
    fn string(&mut self) -> Result<String, String> {
        self.eat(b'"')?;
        let start = self.i;
        while self.i < self.s.len() && self.s[self.i] != b'"' {
            if self.s[self.i] == b'\\' {
                return Err("escapes in parameter strings are not supported".into());
            }
            self.i += 1;
        }
        let out = String::from_utf8(self.s[start..self.i].to_vec()).map_err(|e| e.to_string())?;
        self.eat(b'"')?;
        Ok(out)
    }
    fn value(&mut self) -> Result<Value, String> {
        self.ws();
        match self.s.get(self.i) {
            Some(b'"') => Ok(Value::Str(self.string()?)),
            Some(b't') if self.s[self.i..].starts_with(b"true") => {
                self.i += 4;
                Ok(Value::Bool(true))
            }
            Some(b'f') if self.s[self.i..].starts_with(b"false") => {
                self.i += 5;
                Ok(Value::Bool(false))
            }
            _ => {
                let start = self.i;
                while self.i < self.s.len() && matches!(self.s[self.i], b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9') {
                    self.i += 1;
                }
                let text = std::str::from_utf8(&self.s[start..self.i]).unwrap();
                if let Ok(n) = text.parse::<i64>() {
                    Ok(Value::Int(n))
                } else {
                    text.parse::<f64>().map(Value::Float).map_err(|_| format!("bad value {text:?}"))
                }
            }
        }
    }
}

impl Params {
    pub fn parse(text: &str) -> Result<Params, String> {
        let mut p = Parser { s: text.as_bytes(), i: 0 };
        let mut out = BTreeMap::new();
        p.ws();
        if p.i == p.s.len() {
            return Ok(Params(out));
        }
        p.eat(b'{')?;
        p.ws();
        if p.s.get(p.i) == Some(&b'}') {
            p.i += 1;
        } else {
            loop {
                let key = p.string()?;
                p.eat(b':')?;
                let value = p.value()?;
                out.insert(key, value);
                p.ws();
                match p.s.get(p.i) {
                    Some(b',') => p.i += 1,
                    Some(b'}') => {
                        p.i += 1;
                        break;
                    }
                    _ => return Err(format!("expected ',' or '}}' at byte {}", p.i)),
                }
            }
        }
        p.ws();
        if p.i != p.s.len() {
            return Err(format!("trailing text at byte {}", p.i));
        }
        Ok(Params(out))
    }

    /// Fails on a key the strategy doesn't have, so a typo in a grid isn't a silent no-op.
    pub fn check_keys(&self, known: &[&str]) -> Result<(), String> {
        for key in self.0.keys() {
            if !known.contains(&key.as_str()) {
                return Err(format!("unknown parameter {key:?} (known: {})", known.join(", ")));
            }
        }
        Ok(())
    }

    pub fn int(&self, key: &str, default: i64) -> Result<i64, String> {
        match self.0.get(key) {
            None => Ok(default),
            Some(Value::Int(n)) => Ok(*n),
            Some(Value::Float(x)) if x.fract() == 0.0 => Ok(*x as i64),
            Some(v) => Err(format!("{key}: expected an integer, got {v:?}")),
        }
    }

    pub fn float(&self, key: &str, default: f64) -> Result<f64, String> {
        match self.0.get(key) {
            None => Ok(default),
            Some(Value::Int(n)) => Ok(*n as f64),
            Some(Value::Float(x)) => Ok(*x),
            Some(v) => Err(format!("{key}: expected a number, got {v:?}")),
        }
    }
}
