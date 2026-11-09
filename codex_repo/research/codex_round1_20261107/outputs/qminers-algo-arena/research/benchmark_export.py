"""Run exported files without research callback wrappers; measure process resources."""
import argparse
import ctypes
import json
import time
from ctypes import wintypes
from pathlib import Path
from run_study import ROOT, OUT, config, dump
from simulator.main import load_strategy_from_file
from simulator.simulator import ExchangeSimulator


def peak_working_set():
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
            ('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),
            ('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),
            ('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),
            ('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
    c=Counters()
    c.cb=ctypes.sizeof(c)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(c),c.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return c.PeakWorkingSetSize


def main():
    p=argparse.ArgumentParser()
    p.add_argument('file')
    p.add_argument('--expected',type=float,required=True)
    args=p.parse_args()
    wall,cpu=time.perf_counter(),time.process_time()
    bot=load_strategy_from_file(ROOT/'strategies'/args.file)
    result=ExchangeSimulator(bot,config()).run(ROOT/'data/sample_v2.csv')
    record=dict(file=args.file,wall_seconds=time.perf_counter()-wall,cpu_seconds=time.process_time()-cpu,
                peak_working_set_bytes=peak_working_set(),result=result.model_dump(mode='json'),
                note='Windows process measurement, includes Python and local harness imports; not the remote Linux sandbox.')
    assert result.pnl==args.expected,(result.pnl,args.expected)
    dump(OUT/('benchmark_'+Path(args.file).stem+'.json'),record)
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    main()
