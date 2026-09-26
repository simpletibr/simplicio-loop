"""Resource measurement helpers: wall clock, CPU (getrusage), peak RSS."""
from __future__ import annotations

import resource
import subprocess
import threading
import time


def measure_call(fn, *args, **kwargs):
    """Measure an in-process call. CPU/RSS reflect the whole process
    (RUSAGE_SELF is cumulative, so these deltas are lower bounds for the
    call itself but exact for total process growth)."""
    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    t0 = time.time()
    result = fn(*args, **kwargs)
    t1 = time.time()
    ru1 = resource.getrusage(resource.RUSAGE_SELF)
    metrics = {
        "wall_s": round(t1 - t0, 4),
        "cpu_s": round((ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime), 4),
        "peak_rss_mb": round(ru1.ru_maxrss / 1024.0, 2),
    }
    return result, metrics


def _poll_peak_rss(pid, holder, stop_event):
    peak = 0
    path = f"/proc/{pid}/status"
    while not stop_event.is_set():
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith("VmHWM:"):
                        kb = int(line.split()[1])
                        peak = max(peak, kb)
                        break
        except Exception:
            pass
        time.sleep(0.02)
    holder["peak_kb"] = peak


def run_subprocess(cmd, cwd=None, timeout=120, env=None):
    """Run a subprocess, capture stdout/stderr, and measure wall/CPU/peak RSS.

    CPU is measured via RUSAGE_CHILDREN delta (this process's children,
    cumulative across all subprocesses so far); peak RSS is polled live via
    /proc/<pid>/status VmHWM for the subprocess tree root only.
    """
    ru0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.time()
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace",
    )
    holder = {"peak_kb": 0}
    stop_event = threading.Event()
    poller = threading.Thread(target=_poll_peak_rss, args=(proc.pid, holder, stop_event))
    poller.start()
    try:
        out, _ = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        rc = -9
    finally:
        stop_event.set()
        poller.join()
    t1 = time.time()
    ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    metrics = {
        "wall_s": round(t1 - t0, 4),
        "cpu_s": round((ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime), 4),
        "peak_rss_mb": round(holder["peak_kb"] / 1024.0, 2),
        "returncode": rc,
    }
    return out, metrics
