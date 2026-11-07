"""Generate a dense/deep tape and measure each candidate in a fresh process.

python -m scripts.perf_check --rows 1000000 --output logs/performance
This is a throughput/memory/risk test, not a profitability benchmark.
"""
import argparse
import json
import platform
import random
import subprocess
import sys
from pathlib import Path

from scripts.benchmark import digest, evaluate
from simulator.main import load_strategy_from_file
from simulator.simulator import ExchangeSimulator


def peak_rss_bytes():
    """Peak process working set on Windows; ru_maxrss on POSIX."""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                    'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss*(1 if platform.system() == 'Darwin' else 1024)


def generate_dense(path,rows):
    rng=random.Random(817)
    slots=[]
    index=0
    with path.open('w') as file:
        file.write('Time,Operation,OrderId,Side,Volume,Price,Lifespan\n')
        for side in ('B','A'):
            for level in range(100):
                for k in range(10):
                    price=9999-level if side=='B' else 10001+level
                    order_id=f'm{index}'
                    file.write(f'{index/10000:.6f},Insert,{order_id},{side},10,{price},G\n')
                    slots.append([order_id,side,price])
                    index+=1
        cycle=0
        while index<rows:
            aggressive=cycle%10==0
            cycle+=1
            if aggressive:
                side=rng.choice(('B','A'))
                price=10001 if side=='B' else 9999
                file.write(f'{index/10000:.6f},Insert,t{index},{side},2,{price},F\n')
                index+=1
            else:
                slot=slots[rng.randrange(len(slots))]
                file.write(f'{index/10000:.6f},Cancel,{slot[0]},,,,\n')
                index+=1
                if index>=rows:
                    break
                slot[0]=f'm{index}'
                file.write(f'{index/10000:.6f},Insert,{slot[0]},{slot[1]},10,{slot[2]},G\n')
                index+=1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rows',type=int,default=1_000_000)
    p.add_argument('--output',type=Path,default=Path('logs/performance'))
    p.add_argument('--worker',action='store_true')
    p.add_argument('--backtest',type=Path)
    p.add_argument('--strategy',type=Path)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if args.worker:
        strategy=load_strategy_from_file(args.strategy)
        result=evaluate(strategy,args.backtest,args.output,900)
        rows=ExchangeSimulator.count_backtest_rows(args.backtest)
        result['rows']=rows
        result['events_per_second']=rows/result['runtime_seconds']
        result['peak_rss_bytes']=peak_rss_bytes()
        result['strategy_sha256']=digest(args.strategy)
        if result['result']['breach_penalty'] or result['max_potential_inventory_at_submission']>strategy.POSITION_LIMIT:
            raise AssertionError('risk invariant failure')
        print(json.dumps(result))
        return
    if args.rows<2000:
        p.error('--rows must be at least 2000')
    tape=args.output/'dense.csv'
    generate_dense(tape,args.rows)
    results={}
    for name in ('arena','guarded','passive'):
        source=Path('strategies')/(name+'_strategy.py')
        completed=subprocess.run([sys.executable,'-m','scripts.perf_check','--worker',
            '--backtest',str(tape),'--strategy',str(source),'--output',str(args.output/name)],
            check=True,capture_output=True,text=True)
        run=json.loads(completed.stdout)
        results[name]=run
        print(f'{name}: {run["events_per_second"]:,.0f} events/s; '
              f'peak RSS {run["peak_rss_bytes"]/2**20:.1f} MiB; '
              f'max inventory {run["max_abs_inventory"]}; penalty {run["result"]["breach_penalty"]}',flush=True)
    (args.output/'performance.json').write_text(json.dumps({
        'platform':platform.platform(),'python':platform.python_version(),
        'data_sha256':digest(tape),'generator_sha256':digest(__file__),
        'limitation':'Synthetic stationary deep book; throughput depends on book shape and hardware. PnL has no research meaning here.',
        'strategies':results},indent=2)+'\n')


if __name__=='__main__':
    main()
