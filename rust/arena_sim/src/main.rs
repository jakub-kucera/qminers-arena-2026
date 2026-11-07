//! arena-sim: the Arena's exchange simulator in Rust.
//!
//!   arena-sim --backtest FILE.csv --strategy trend_follower|fallback_maker [--params '{"QUOTE": 5}']
//!             [--log-dir DIR] [--no-logs] [--public-depth 20] [--repeat N]
//!       one run, printing simulator.main's lines; with --log-dir also result.json and pnl.csv, byte for byte
//!       as theirs (--no-logs is accepted: the run logs are never written). --repeat times N runs on stderr.
//!   arena-sim batch --backtest FILE.csv [--backtest FILE2.csv ...] --strategy NAME --tasks TASKS.jsonl
//!             [--threads N] [--public-depth 20]
//!       every task (one JSON parameter object per line) on every file, on N threads, one JSON line per run
//!       to stdout in task-then-file order (python/arena/qsim_rust.py's grid reads them).

use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use std::time::Instant;

use arena_sim::data::{self, Tape};
use arena_sim::params::Params;
use arena_sim::sim::{Config, ExchangeSimulator, Outcome};
use arena_sim::strategies;

struct Args {
    batch: bool,
    backtests: Vec<PathBuf>,
    strategy: String,
    params: String,
    log_dir: Option<PathBuf>,
    public_depth: i64,
    repeat: usize,
    tasks: Option<PathBuf>,
    threads: usize,
}

fn parse_args() -> Result<Args, String> {
    let mut args = Args {
        batch: false,
        backtests: Vec::new(),
        strategy: String::new(),
        params: String::new(),
        log_dir: None,
        public_depth: 20,
        repeat: 0,
        tasks: None,
        threads: std::thread::available_parallelism().map_or(1, |n| n.get()),
    };
    let mut it = std::env::args().skip(1).peekable();
    if it.peek().map(String::as_str) == Some("batch") {
        args.batch = true;
        it.next();
    }
    while let Some(flag) = it.next() {
        let mut value = || it.next().ok_or_else(|| format!("{flag} needs a value"));
        match flag.as_str() {
            "--backtest" => args.backtests.push(PathBuf::from(value()?)),
            "--strategy" => args.strategy = value()?,
            "--params" => args.params = value()?,
            "--log-dir" => args.log_dir = Some(PathBuf::from(value()?)),
            "--no-logs" => {}
            "--public-depth" => args.public_depth = value()?.parse().map_err(|_| "--public-depth takes an integer")?,
            "--repeat" => args.repeat = value()?.parse().map_err(|_| "--repeat takes an integer")?,
            "--tasks" => args.tasks = Some(PathBuf::from(value()?)),
            "--threads" => args.threads = value()?.parse().map_err(|_| "--threads takes an integer")?,
            "-h" | "--help" => return Err(USAGE.into()),
            other => return Err(format!("unknown argument {other:?}\n{USAGE}")),
        }
    }
    if args.backtests.is_empty() || args.strategy.is_empty() {
        return Err(format!("--backtest and --strategy are required\n{USAGE}"));
    }
    if args.public_depth <= 0 {
        return Err("--public-depth must be positive".into());
    }
    Ok(args)
}

const USAGE: &str = "usage: arena-sim [batch] --backtest FILE.csv --strategy trend_follower|fallback_maker [--params JSON] [--log-dir DIR] [--no-logs] [--public-depth N] [--repeat N] [--tasks TASKS.jsonl --threads N]";

fn run_once(tape: &Tape, strategy: &str, params: &Params, config: &Config) -> Result<Outcome, String> {
    let mut strat = strategies::make(strategy, params)?;
    Ok(ExchangeSimulator::new(config.clone()).run(&tape.rows, strat.as_mut()))
}

fn single(args: &Args, config: &Config) -> Result<(), String> {
    if args.backtests.len() != 1 {
        return Err("one --backtest for a single run (batch takes several)".into());
    }
    let params = Params::parse(&args.params)?;
    let t0 = Instant::now();
    let tape = data::load(&args.backtests[0])?;
    let parse_s = t0.elapsed().as_secs_f64();
    let t1 = Instant::now();
    let outcome = run_once(&tape, &args.strategy, &params, config)?;
    let run_s = t1.elapsed().as_secs_f64();
    if args.repeat > 0 {
        let t2 = Instant::now();
        for _ in 0..args.repeat {
            std::hint::black_box(run_once(&tape, &args.strategy, &params, config)?);
        }
        let per = t2.elapsed().as_secs_f64() / args.repeat as f64;
        eprintln!("{} rows: parse {:.2} ms, first run {:.2} ms, {} runs at {:.3} ms each", tape.rows.len(), parse_s * 1e3, run_s * 1e3, args.repeat, per * 1e3);
    }
    println!("{}", arena_sim::summary_lines(&outcome));
    if let Some(dir) = &args.log_dir {
        std::fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
        std::fs::write(dir.join("result.json"), arena_sim::result_json(&outcome)).map_err(|e| e.to_string())?;
        std::fs::write(dir.join("pnl.csv"), arena_sim::pnl_csv(&outcome)).map_err(|e| e.to_string())?;
        println!("log_dir={}", dir.display());
    }
    Ok(())
}

fn batch(args: &Args, config: &Config) -> Result<(), String> {
    let tasks_path = args.tasks.as_ref().ok_or("batch needs --tasks")?;
    let text = std::fs::read_to_string(tasks_path).map_err(|e| format!("{}: {e}", tasks_path.display()))?;
    let tasks: Vec<Result<Params, String>> = text.lines().filter(|l| !l.trim().is_empty()).map(Params::parse).collect();
    let tapes: Vec<Tape> = args.backtests.iter().map(|p| data::load(p)).collect::<Result<_, _>>()?;
    let jobs: Vec<(usize, usize)> = (0..tasks.len()).flat_map(|t| (0..tapes.len()).map(move |f| (t, f))).collect();
    let next = AtomicUsize::new(0);
    let results: Mutex<Vec<Option<String>>> = Mutex::new(vec![None; jobs.len()]);
    // A panicking run is that run's error, not the batch's.
    std::panic::set_hook(Box::new(|_| {}));
    std::thread::scope(|scope| {
        for _ in 0..args.threads.max(1).min(jobs.len().max(1)) {
            scope.spawn(|| loop {
                let j = next.fetch_add(1, Ordering::Relaxed);
                if j >= jobs.len() {
                    break;
                }
                let (t, f) = jobs[j];
                let line = match &tasks[t] {
                    Err(e) => arena_sim::error_json(t, f, e),
                    Ok(params) => {
                        let start = Instant::now();
                        let run = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| run_once(&tapes[f], &args.strategy, params, config)));
                        match run {
                            Ok(Ok(o)) => arena_sim::run_json(t, f, &o, start.elapsed().as_secs_f64()),
                            Ok(Err(e)) => arena_sim::error_json(t, f, &e),
                            Err(p) => {
                                let msg = p.downcast_ref::<String>().cloned().or_else(|| p.downcast_ref::<&str>().map(|s| s.to_string()));
                                arena_sim::error_json(t, f, &format!("panic: {}", msg.unwrap_or_default()))
                            }
                        }
                    }
                };
                results.lock().unwrap()[j] = Some(line);
            });
        }
    });
    let out = results.into_inner().unwrap();
    let mut stdout = String::new();
    for line in out.into_iter().flatten() {
        stdout.push_str(&line);
        stdout.push('\n');
    }
    print!("{stdout}");
    Ok(())
}

fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    let config = Config { public_depth: args.public_depth, ..Config::default() };
    let result = if args.batch { batch(&args, &config) } else { single(&args, &config) };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
