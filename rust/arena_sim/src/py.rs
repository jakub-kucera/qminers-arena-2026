//! What the simulator gets from CPython and Rust must copy exactly: `repr(float)` (pnl.csv, result.json),
//! `f"{x:.2f}"` (the CLI's lines), `round()` (the CSV's times) and `statistics.stdev` (pnl_se), which is
//! exact: the variance of the floats as fractions, then its square root correctly rounded.

/// `repr(x)` of a finite float: the shortest digits that round-trip, fixed notation for 1e-4 <= |x| < 1e16,
/// else `d.ddde+XX`.
pub fn repr(x: f64) -> String {
    if x.is_nan() {
        return "nan".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() { "-0.0".into() } else { "0.0".into() };
    }
    // Rust's `{:e}` is the shortest round-trip digits too: "-1.2345e3", "1e16", "5e-324".
    let s = format!("{:e}", x);
    let (neg, s) = match s.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, s.as_str()),
    };
    let (mantissa, exp) = s.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let decpt = exp + 1; // x = 0.DIGITS * 10^decpt
    let mut out = String::new();
    if neg {
        out.push('-');
    }
    if decpt <= -4 || decpt > 16 {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        out.push(if exp < 0 { '-' } else { '+' });
        out.push_str(&format!("{:02}", exp.abs()));
    } else if decpt <= 0 {
        out.push_str("0.");
        for _ in 0..(-decpt) {
            out.push('0');
        }
        out.push_str(&digits);
    } else {
        let d = decpt as usize;
        if digits.len() <= d {
            out.push_str(&digits);
            for _ in digits.len()..d {
                out.push('0');
            }
            out.push_str(".0");
        } else {
            out.push_str(&digits[..d]);
            out.push('.');
            out.push_str(&digits[d..]);
        }
    }
    out
}

/// `f"{x:.2f}"`: the exact binary value rounded half to even, as Rust's `{:.2}` does.
pub fn fixed2(x: f64) -> String {
    format!("{:.2}", x)
}

/// `int(round(x))` of a float: ties to even.
pub fn round_int(x: f64) -> i64 {
    x.round_ties_even() as i64
}

// ---------------------------------------------------------------------------- exact stdev

/// A minimal unsigned big integer, little-endian u64 limbs, enough for the exact variance.
#[derive(Clone, Debug, PartialEq, Eq)]
struct Big(Vec<u64>);

impl Big {
    fn zero() -> Big {
        Big(Vec::new())
    }
    fn from_u128(x: u128) -> Big {
        let mut b = Big(vec![x as u64, (x >> 64) as u64]);
        b.trim();
        b
    }
    fn trim(&mut self) {
        while self.0.last() == Some(&0) {
            self.0.pop();
        }
    }
    fn is_zero(&self) -> bool {
        self.0.is_empty()
    }
    fn bits(&self) -> u32 {
        match self.0.last() {
            None => 0,
            Some(&top) => (self.0.len() as u32 - 1) * 64 + (64 - top.leading_zeros()),
        }
    }
    fn add(&mut self, other: &Big) {
        if self.0.len() < other.0.len() {
            self.0.resize(other.0.len(), 0);
        }
        let mut carry = 0u128;
        for i in 0..self.0.len() {
            let s = self.0[i] as u128 + *other.0.get(i).unwrap_or(&0) as u128 + carry;
            self.0[i] = s as u64;
            carry = s >> 64;
        }
        if carry > 0 {
            self.0.push(carry as u64);
        }
    }
    /// self - other, which must not be negative.
    fn sub(&mut self, other: &Big) {
        let mut borrow = 0i128;
        for i in 0..self.0.len() {
            let d = self.0[i] as i128 - *other.0.get(i).unwrap_or(&0) as i128 - borrow;
            if d < 0 {
                self.0[i] = (d + (1i128 << 64)) as u64;
                borrow = 1;
            } else {
                self.0[i] = d as u64;
                borrow = 0;
            }
        }
        assert!(borrow == 0 && other.0.len() <= self.0.len().max(other.0.len()), "negative big integer");
        self.trim();
    }
    fn cmp(&self, other: &Big) -> std::cmp::Ordering {
        if self.0.len() != other.0.len() {
            return self.0.len().cmp(&other.0.len());
        }
        for i in (0..self.0.len()).rev() {
            if self.0[i] != other.0[i] {
                return self.0[i].cmp(&other.0[i]);
            }
        }
        std::cmp::Ordering::Equal
    }
    fn mul(&self, other: &Big) -> Big {
        if self.is_zero() || other.is_zero() {
            return Big::zero();
        }
        let mut out = vec![0u64; self.0.len() + other.0.len()];
        for (i, &a) in self.0.iter().enumerate() {
            let mut carry = 0u128;
            for (j, &b) in other.0.iter().enumerate() {
                let t = out[i + j] as u128 + a as u128 * b as u128 + carry;
                out[i + j] = t as u64;
                carry = t >> 64;
            }
            let mut k = i + other.0.len();
            while carry > 0 {
                let t = out[k] as u128 + carry;
                out[k] = t as u64;
                carry = t >> 64;
                k += 1;
            }
        }
        let mut b = Big(out);
        b.trim();
        b
    }
    fn shl(&self, n: u32) -> Big {
        if self.is_zero() {
            return Big::zero();
        }
        let (words, bits) = ((n / 64) as usize, n % 64);
        let mut out = vec![0u64; words];
        let mut carry = 0u64;
        for &w in &self.0 {
            if bits == 0 {
                out.push(w);
            } else {
                out.push((w << bits) | carry);
                carry = w >> (64 - bits);
            }
        }
        if carry > 0 {
            out.push(carry);
        }
        let mut b = Big(out);
        b.trim();
        b
    }
    /// (self >> n, whether any bit shifted out was set)
    fn shr(&self, n: u32) -> (Big, bool) {
        let (words, bits) = ((n / 64) as usize, n % 64);
        if words >= self.0.len() {
            return (Big::zero(), !self.is_zero());
        }
        let mut lost = self.0[..words].iter().any(|&w| w != 0);
        if bits > 0 {
            lost |= self.0[words] & ((1u64 << bits) - 1) != 0;
        }
        let mut out = Vec::with_capacity(self.0.len() - words);
        for i in words..self.0.len() {
            let lo = self.0[i] >> bits;
            let hi = if bits > 0 && i + 1 < self.0.len() { self.0[i + 1] << (64 - bits) } else { 0 };
            out.push(lo | hi);
        }
        let mut b = Big(out);
        b.trim();
        (b, lost)
    }
    /// (self / d, self % d != 0)
    fn divrem_u64(&self, d: u64) -> (Big, bool) {
        let mut out = vec![0u64; self.0.len()];
        let mut rem = 0u128;
        for i in (0..self.0.len()).rev() {
            let cur = (rem << 64) | self.0[i] as u128;
            out[i] = (cur / d as u128) as u64;
            rem = cur % d as u128;
        }
        let mut b = Big(out);
        b.trim();
        (b, rem != 0)
    }
    fn to_u128(&self) -> u128 {
        assert!(self.0.len() <= 2);
        *self.0.first().unwrap_or(&0) as u128 | (*self.0.get(1).unwrap_or(&0) as u128) << 64
    }
}

fn isqrt_u128(n: u128) -> u128 {
    if n == 0 {
        return 0;
    }
    let mut x = (n as f64).sqrt() as u128;
    // Newton from the float estimate, then settle on floor(sqrt(n)).
    for _ in 0..4 {
        if x == 0 {
            x = 1;
        }
        x = (x + n / x) / 2;
    }
    while x.checked_mul(x).map_or(true, |sq| sq > n) {
        x -= 1;
    }
    while (x + 1).checked_mul(x + 1).map_or(false, |sq| sq <= n) {
        x += 1;
    }
    x
}

/// x * 2^k, exact while the result stays normal.
fn ldexp(mut x: f64, mut k: i32) -> f64 {
    while k > 1000 {
        x *= f64::from_bits(((1023 + 1000) as u64) << 52);
        k -= 1000;
    }
    while k < -1000 {
        x *= f64::from_bits(((1023 - 1000) as u64) << 52);
        k += 1000;
    }
    x * f64::from_bits(((1023 + k) as u64) << 52)
}

/// A finite float as (negative, odd mantissa, exponent): |x| = m * 2^e. None for 0.
fn decompose(x: f64) -> Option<(bool, u64, i32)> {
    if x == 0.0 {
        return None;
    }
    assert!(x.is_finite(), "stdev of a non-finite PnL increment");
    let bits = x.to_bits();
    let neg = bits >> 63 == 1;
    let exp_bits = ((bits >> 52) & 0x7ff) as i32;
    let frac = bits & ((1u64 << 52) - 1);
    let (mut m, mut e) = if exp_bits == 0 { (frac, -1074) } else { (frac | (1u64 << 52), exp_bits - 1075) };
    let tz = m.trailing_zeros();
    m >>= tz;
    e += tz as i32;
    Some((neg, m, e))
}

/// `statistics.stdev(xs)` (n >= 2): the exact sample variance of the floats, its square root correctly rounded.
pub fn stdev(xs: &[f64]) -> f64 {
    let n = xs.len();
    assert!(n >= 2);
    let parts: Vec<(bool, u64, i32)> = xs.iter().filter_map(|&x| decompose(x)).collect();
    if parts.is_empty() {
        return 0.0;
    }
    let e_min = parts.iter().map(|p| p.2).min().unwrap();
    // S1 = sum(+-m 2^(e-E)) as positive and negative halves, S2 = sum(m^2 4^(e-E)).
    let (mut pos, mut negs, mut s2) = (Big::zero(), Big::zero(), Big::zero());
    for &(neg, m, e) in &parts {
        let shift = (e - e_min) as u32;
        let term = Big::from_u128(m as u128).shl(shift);
        if neg {
            negs.add(&term);
        } else {
            pos.add(&term);
        }
        s2.add(&Big::from_u128(m as u128 * m as u128).shl(2 * shift));
    }
    let s1 = if pos.cmp(&negs) == std::cmp::Ordering::Less {
        let mut d = negs.clone();
        d.sub(&pos);
        d
    } else {
        let mut d = pos.clone();
        d.sub(&negs);
        d
    };
    // var = 4^E * A / B with A = n*S2 - S1^2, B = n(n-1); stdev = 2^E * sqrt(A / B).
    let mut a = s2.mul(&Big::from_u128(n as u128));
    a.sub(&s1.mul(&s1));
    if a.is_zero() {
        return 0.0;
    }
    let b = (n as u64) * (n as u64 - 1);
    let l = a.bits() as i32 - (64 - b.leading_zeros()) as i32;
    // N = floor(A 4^t / B) with ~118 bits; its integer square root rounded to odd has ~59 bits, two more than a
    // float needs, so converting it rounds correctly.
    let t = (118 - l + 1).div_euclid(2);
    let (scaled, mut inexact) = if t >= 0 { (a.shl(2 * t as u32), false) } else { a.shr((-2 * t) as u32) };
    let (q, rem) = scaled.divrem_u64(b);
    inexact |= rem;
    let nq = q.to_u128();
    let root = isqrt_u128(nq);
    inexact |= root * root != nq;
    let odd = (root as u64) | inexact as u64;
    assert!(root < (1u128 << 64));
    ldexp(odd as f64, e_min - t)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reprs() {
        for (x, s) in [
            (0.0, "0.0"),
            (1.0, "1.0"),
            (3599.000003, "3599.000003"),
            (-1015.0, "-1015.0"),
            (1e16, "1e+16"),
            (1e15, "1000000000000000.0"),
            (1.5e-5, "1.5e-05"),
            (0.0001, "0.0001"),
            (0.1 + 0.2, "0.30000000000000004"),
            (123456789.125, "123456789.125"),
            (-2.5e-300, "-2.5e-300"),
        ] {
            assert_eq!(repr(x), s);
        }
    }

    #[test]
    fn fixed() {
        // CPython: f"{x:.2f}" for these
        for (x, s) in [(0.125, "0.12"), (0.375, "0.38"), (2.675, "2.67"), (1.005, "1.00"), (-0.0, "-0.00"), (102.365, "102.36")] {
            assert_eq!(fixed2(x), s, "{x}");
        }
        assert_eq!(format!("{:.0}", 2.5), "2");
    }

    #[test]
    fn stdevs() {
        // statistics.stdev in CPython 3.13
        assert_eq!(stdev(&[1.0, 2.0]), 0.7071067811865476);
        assert_eq!(stdev(&[0.1, 0.2, 0.3]), 0.09999999999999999);
        assert_eq!(stdev(&[1e10, -3.5, 0.000123, 7.0]), 4999999999.416646);
        assert_eq!(stdev(&[0.0, 0.0, 0.0]), 0.0);
    }
}
