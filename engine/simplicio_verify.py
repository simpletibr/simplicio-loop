#!/usr/bin/env python3
"""simplicio_verify — one-command self-check of the Simplicio token economy.

Answers "is the whole Simplicio mechanism working?" by probing every component
of the stack and printing a PASS / WARN / FAIL table plus an overall verdict.
Stdlib only. Network access is limited to localhost HTTP on the two local ports.

Exit code: 0 when no check FAILs (WARN is tolerated), 1 otherwise.

Checks
  1. capture_proxy   socket-connect 127.0.0.1:<SIMPLICIO_PROXY_PORT|8788>;
                     if up, GET /health and assert JSON {"engine":"simplicio"}.
  2. token_monitor   socket-connect 127.0.0.1:<SIMPLICIO_MONITOR_PORT|9090>;
                     if up, GET /api/status and assert JSON with a "runtimes" key.
  3. savings_file    $SIMPLICIO_HOME/proxy_savings.json exists, parses, and has
                     lifetime.tokens_saved (the number is reported).
  4. native_engine   `simplicio_engine.py --version` exits 0 and prints a version.
  5. compression     import the sibling compress module, shrink a verbose string,
                     assert it shrinks; report the % saved.
  6. memory_module   `simplicio_memory.py stats` exits 0.
  7. mcp_module      pipe a JSON-RPC `initialize` into simplicio_tools_server.py and
                     assert serverInfo.name == "simplicio".
  8. det_operator    is `simplicio-dev-cli` on PATH? (WARN if absent, not FAIL).

Each check is isolated: one raising does not abort the rest.

Usage
  python3 engine/simplicio_verify.py          # human table
  python3 engine/simplicio_verify.py --json    # machine-readable JSON
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

# This file lives in the engine dir; the engine dir is its parent.
ENGINE_DIR = Path(__file__).resolve().parent

DEFAULT_PROXY_PORT = 8788
DEFAULT_MONITOR_PORT = 9090

CONNECT_TIMEOUT = 0.75  # seconds for the bare socket probe
HTTP_TIMEOUT = 2.0      # seconds for the localhost HTTP GET
SUBPROC_TIMEOUT = 15.0  # seconds for a child engine process


def _simplicio_home():
    """Resolve the Simplicio data dir, honoring SIMPLICIO_HOME."""
    return Path(os.environ.get("SIMPLICIO_HOME", Path(os.path.expanduser("~")) / ".simplicio"))


def _env_port(name, default):
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _port_open(host, port):
    """True if a TCP connect to host:port succeeds within CONNECT_TIMEOUT."""
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def _http_get_json(host, port, path):
    """GET http://host:port/path and parse the body as JSON. Localhost only."""
    url = "http://{}:{}{}".format(host, port, path)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310 (localhost only)
        body = resp.read().decode("utf-8", "replace")
    return json.loads(body)


def _run(cmd, **kwargs):
    """Run a child process, capturing text output; never raises on non-zero."""
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=SUBPROC_TIMEOUT,
        **kwargs,
    )


# --- individual checks ---------------------------------------------------------
# Each returns (status, detail). They must never raise; the harness also wraps
# them defensively, but keeping them clean keeps details meaningful.

def check_capture_proxy():
    port = _env_port("SIMPLICIO_PROXY_PORT", DEFAULT_PROXY_PORT)
    host = "127.0.0.1"
    if not _port_open(host, port):
        return WARN, "port {} closed (proxy not running)".format(port)
    try:
        data = _http_get_json(host, port, "/health")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return FAIL, "port {} up but /health failed: {}".format(port, exc)
    if isinstance(data, dict) and data.get("engine") == "simplicio":
        return PASS, "port {} up, /health engine=simplicio".format(port)
    return FAIL, "port {} up but /health engine != simplicio ({!r})".format(
        port, (data.get("engine") if isinstance(data, dict) else data)
    )


def check_token_monitor():
    port = _env_port("SIMPLICIO_MONITOR_PORT", DEFAULT_MONITOR_PORT)
    host = "127.0.0.1"
    if not _port_open(host, port):
        return WARN, "port {} closed (monitor not running)".format(port)
    try:
        data = _http_get_json(host, port, "/api/status")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return FAIL, "port {} up but /api/status failed: {}".format(port, exc)
    if isinstance(data, dict) and "runtimes" in data:
        return PASS, "port {} up, /api/status has runtimes".format(port)
    return FAIL, "port {} up but /api/status missing 'runtimes' key".format(port)


def check_savings_file():
    path = _simplicio_home() / "proxy_savings.json"
    if not path.exists():
        return WARN, "no savings file at {}".format(path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return FAIL, "savings file unreadable: {}".format(exc)
    lifetime = data.get("lifetime") if isinstance(data, dict) else None
    if not isinstance(lifetime, dict) or "tokens_saved" not in lifetime:
        return FAIL, "savings file lacks lifetime.tokens_saved"
    saved = lifetime.get("tokens_saved")
    return PASS, "lifetime.tokens_saved = {}".format(saved)


def check_native_engine():
    engine = ENGINE_DIR / "simplicio_engine.py"
    if not engine.exists():
        return FAIL, "engine missing at {}".format(engine)
    try:
        proc = _run([sys.executable, str(engine), "--version"])
    except (OSError, subprocess.SubprocessError) as exc:
        return FAIL, "engine --version did not run: {}".format(exc)
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if proc.returncode != 0:
        return FAIL, "engine --version exit {}: {}".format(proc.returncode, out[:120])
    if not out:
        return FAIL, "engine --version printed nothing"
    return PASS, out.splitlines()[0][:80]


def check_compression():
    # Import the sibling module without permanently polluting sys.path tail.
    sys.path.insert(0, str(ENGINE_DIR))
    try:
        import simplicio_compress  # noqa: PLC0415 (intentional local import)
    except Exception as exc:  # ImportError or anything during import
        return FAIL, "cannot import simplicio_compress: {}".format(exc)
    finally:
        try:
            sys.path.remove(str(ENGINE_DIR))
        except ValueError:
            pass
    # A deliberately verbose string the deterministic algos can shrink:
    # trailing whitespace, 5+ blank lines, and a duplicated line.
    sample = (
        "alpha line   \n"
        "alpha line   \n"
        "\n\n\n\n\n\n"
        "beta\t\t\n"
        "gamma value here   \n"
    )
    try:
        out = simplicio_compress.compress(sample)
    except Exception as exc:
        return FAIL, "compress() raised: {}".format(exc)
    before, after = len(sample), len(out)
    if after >= before:
        return FAIL, "compress() did not shrink ({} -> {} chars)".format(before, after)
    pct = round((before - after) / before * 100, 1)
    return PASS, "shrank {} -> {} chars ({}% on sample)".format(before, after, pct)


def check_memory_module():
    mem = ENGINE_DIR / "simplicio_memory.py"
    if not mem.exists():
        return FAIL, "memory module missing at {}".format(mem)
    try:
        proc = _run([sys.executable, str(mem), "stats"])
    except (OSError, subprocess.SubprocessError) as exc:
        return FAIL, "memory stats did not run: {}".format(exc)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return FAIL, "memory stats exit {}: {}".format(proc.returncode, err[:120])
    first = (proc.stdout or "").strip().splitlines()
    return PASS, "stats ok ({})".format(first[0] if first else "no output")


def check_mcp_module():
    mcp = ENGINE_DIR / "simplicio_tools_server.py"
    if not mcp.exists():
        return FAIL, "mcp module missing at {}".format(mcp)
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }) + "\n"
    try:
        proc = _run([sys.executable, str(mcp)], input=request)
    except (OSError, subprocess.SubprocessError) as exc:
        return FAIL, "mcp did not run: {}".format(exc)
    if proc.returncode != 0:
        return FAIL, "mcp exit {}: {}".format(proc.returncode, (proc.stderr or "").strip()[:120])
    name = None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        info = ((msg.get("result") or {}).get("serverInfo") or {})
        if isinstance(info, dict) and info.get("name"):
            name = info.get("name")
            break
    if name == "simplicio":
        return PASS, "initialize -> serverInfo.name=simplicio"
    return FAIL, "initialize did not yield serverInfo.name=simplicio (got {!r})".format(name)


def check_det_operator():
    binpath = shutil.which("simplicio-dev-cli")
    if binpath:
        return PASS, "simplicio-dev-cli at {}".format(binpath)
    return WARN, "simplicio-dev-cli not on PATH (deterministic operator absent)"


CHECKS = [
    ("capture_proxy", "capture proxy", check_capture_proxy),
    ("token_monitor", "token monitor", check_token_monitor),
    ("savings_file", "savings file", check_savings_file),
    ("native_engine", "native engine", check_native_engine),
    ("compression", "compression module", check_compression),
    ("memory_module", "memory module", check_memory_module),
    ("mcp_module", "mcp module", check_mcp_module),
    ("det_operator", "deterministic operator", check_det_operator),
]


def run_all():
    """Run every check defensively; return a list of result dicts."""
    results = []
    for key, label, fn in CHECKS:
        try:
            status, detail = fn()
        except Exception as exc:  # a check must never abort the run
            status, detail = FAIL, "check crashed: {}".format(exc)
        results.append({
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
        })
    return results


def _verdict(results):
    if any(r["status"] == FAIL for r in results):
        return FAIL
    if any(r["status"] == WARN for r in results):
        return WARN
    return PASS


def _render_table(results):
    label_w = max(len(r["label"]) for r in results)
    label_w = max(label_w, len("component"))
    lines = []
    header = "  {:<{w}}  {:<5}  {}".format("COMPONENT", "STATE", "DETAIL", w=label_w)
    rule = "  " + "-" * (label_w + 5 + len("DETAIL") + 4 + 30)
    lines.append("Simplicio token-economy self-check")
    lines.append(header)
    lines.append(rule)
    for r in results:
        lines.append("  {:<{w}}  {:<5}  {}".format(
            r["label"], r["status"], r["detail"], w=label_w))
    lines.append(rule)
    verdict = _verdict(results)
    counts = {PASS: 0, WARN: 0, FAIL: 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines.append("  VERDICT: {}   ({} pass, {} warn, {} fail)".format(
        verdict, counts[PASS], counts[WARN], counts[FAIL]))
    return "\n".join(lines)


def main(argv):
    as_json = "--json" in argv
    results = run_all()
    verdict = _verdict(results)
    exit_code = 1 if verdict == FAIL else 0
    if as_json:
        print(json.dumps({
            "verdict": verdict,
            "exit_code": exit_code,
            "checks": results,
        }, ensure_ascii=False, indent=2))
    else:
        print(_render_table(results))
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
