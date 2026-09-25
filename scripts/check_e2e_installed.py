#!/usr/bin/env python3
"""Installed/isolated E2E harness for simplicio-loop issue #141.

This harness is intentionally stricter than the generic selftests:
  - it resolves the required console-scripts from PATH (`simplicio-mapper`,
    `simplicio-dev-cli`, `simplicio-loop`) and executes them as real subprocesses;
  - it fail-closes if the capstone E2E receipts contain any stand-in/simulated hop;
  - it never imports the operators in-process and never fabricates a pass.

Two entrypoints:
  probe  Validate PATH executables + audit an existing e2e-demo events file strictly.
  run    Execute `scripts/e2e_demo.py run --require-measured` into an isolated output dir, then
         probe the resulting receipts.
  selftest  Offline deterministic test: uses fake PATH shims + fixture receipts, no network.

Usage:
    python3 scripts/check_e2e_installed.py probe --events FILE [--json]
    python3 scripts/check_e2e_installed.py run [--repo PATH] [--out DIR] [--json] [--no-network]
    python3 scripts/check_e2e_installed.py selftest
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
E2E_DEMO = os.path.join(HERE, "e2e_demo.py")
FIXTURE_EVENTS = os.path.join(
    REPO, "contracts", "e2e-demo", "v1", "fixtures", "fully-measured", "events.jsonl")
REQUIRED_BINS = (
    ("simplicio-mapper", "--help", ("handoff",)),
    ("simplicio-dev-cli", "--help", ("edit",)),
    ("simplicio-loop", "--help", ()),
)


def _run(cmd, cwd=None, env=None, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or REPO, env=env,
                              timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        # OSError (not just FileNotFoundError) covers Windows WinError 1920/1921
        # ("cannot be resolved by the system"), raised when CreateProcess is asked
        # to launch a .cmd/.bat shim directly without going through cmd.exe. A
        # toolchain-resolution failure must degrade to a diagnostic row, never an
        # unhandled traceback (issue #291: "nunca produz traceback enganoso").
        return e


def _probe_bins(env=None, isolate_path=None):
    rows = []
    ok = True
    isolate_norm = os.path.normcase(os.path.abspath(isolate_path)) if isolate_path else None
    for name, flag, needles in REQUIRED_BINS:
        resolved = shutil.which(name, path=(env or os.environ).get("PATH"))
        row = {"name": name, "path": resolved, "ok": False}
        if not resolved:
            row["reason"] = "missing-on-path"
            rows.append(row)
            ok = False
            continue
        if isolate_norm:
            resolved_norm = os.path.normcase(os.path.abspath(resolved))
            if not resolved_norm.startswith(isolate_norm):
                row["reason"] = "resolved-outside-isolated-path"
                rows.append(row)
                ok = False
                continue
        r = _run([name, flag], env=env, timeout=30)
        if isinstance(r, Exception):
            row["reason"] = str(r)
            rows.append(row)
            ok = False
            continue
        body = (r.stdout or "") + (r.stderr or "")
        missing = [needle for needle in needles if needle not in body]
        row.update({
            "returncode": r.returncode,
            "ok": r.returncode == 0 and not missing,
            "missing_help_needles": missing,
        })
        if not row["ok"]:
            row["reason"] = "bad-help-surface"
            ok = False
        rows.append(row)
    return ok, rows


def _audit_events(events_path, env=None):
    r = _run([sys.executable, E2E_DEMO, "audit", "--events", events_path, "--require-measured"],
             env=env, timeout=30)
    if isinstance(r, Exception):
        return False, {"ok": False, "reason": str(r), "events_file": events_path}, 2
    try:
        payload = json.loads(r.stdout)
    except ValueError:
        payload = {"ok": False, "reason": "audit stdout not json", "stdout": r.stdout[:200],
                   "events_file": events_path}
    return bool(payload.get("ok")), payload, r.returncode


def cmd_probe(opts):
    env = dict(os.environ)
    if opts.get("no-network"):
        env["SIMPLICIO_E2E_NO_NETWORK"] = "1"
    events = opts.get("events")
    if not events:
        print(json.dumps({"ok": False, "reason": "--events is required"}, indent=2))
        return 2
    bins_ok, bins = _probe_bins(env=env, isolate_path=opts.get("isolate-path"))
    audit_ok, audit, audit_rc = _audit_events(events, env=env)
    payload = {"ok": bins_ok and audit_ok, "bins": bins, "audit": audit, "events_file": events}
    if opts.get("json"):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else max(2, audit_rc)


def cmd_run(opts):
    env = dict(os.environ)
    if opts.get("no-network"):
        env["SIMPLICIO_E2E_NO_NETWORK"] = "1"
    repo = opts.get("repo", REPO)
    out_dir = opts.get("out") or tempfile.mkdtemp(prefix="simplicio-installed-e2e-")
    r = _run([sys.executable, E2E_DEMO, "run", "--repo", repo, "--out", out_dir,
              "--require-measured", "--json"], env=env, timeout=180)
    if isinstance(r, Exception):
        print(json.dumps({"ok": False, "reason": str(r), "out": out_dir}, indent=2))
        return 2
    events = os.path.join(out_dir, "e2e-demo-events.jsonl")
    bins_ok, bins = _probe_bins(env=env, isolate_path=opts.get("isolate-path"))
    audit_ok, audit, audit_rc = _audit_events(events, env=env)
    payload = {
        "ok": r.returncode == 0 and bins_ok and audit_ok,
        "run_returncode": r.returncode,
        "run_stdout": r.stdout[:400],
        "run_stderr": r.stderr[:400],
        "out": out_dir,
        "bins": bins,
        "audit": audit,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else max(2, r.returncode, audit_rc)


def cmd_selftest(_opts):
    checks = []

    def chk(name, cond):
        checks.append((name, bool(cond)))

    tmp = tempfile.mkdtemp(prefix="check-e2e-installed-")
    try:
        bin_dir = os.path.join(tmp, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        is_win = os.name == "nt"
        ext = ".cmd" if is_win else ""
        mapper = "@echo off\necho Usage: simplicio-mapper inspect handoff ask sync drift\n"
        devcli = "@echo off\necho Usage: simplicio-dev-cli edit --plan --apply --dry-run --json\n"
        loop = "@echo off\necho Usage: simplicio-loop install doctor dashboard\n"
        if not is_win:
            mapper = "#!/bin/sh\necho 'Usage: simplicio-mapper inspect handoff ask sync drift'\n"
            devcli = "#!/bin/sh\necho 'Usage: simplicio-dev-cli edit --plan --apply --dry-run --json'\n"
            loop = "#!/bin/sh\necho 'Usage: simplicio-loop install doctor dashboard'\n"
        for name, body in (("simplicio-mapper", mapper), ("simplicio-dev-cli", devcli),
                           ("simplicio-loop", loop)):
            path = os.path.join(bin_dir, name + ext)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            if not is_win:
                os.chmod(path, 0o755)
        env = dict(os.environ)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        bins_ok, bins = _probe_bins(env=env, isolate_path=bin_dir)
        chk("path bins probe passes with shims", bins_ok is True and all(b["ok"] for b in bins))
        audit_ok, audit, audit_rc = _audit_events(FIXTURE_EVENTS, env=env)
        chk("strict audit passes measured fixture", audit_ok is True and audit_rc == 0)
        probe = _run([sys.executable, os.path.join(HERE, "check_e2e_installed.py"),
                      "probe", "--events", FIXTURE_EVENTS, "--json"], env=env, timeout=30)
        chk("probe command returns 0", not isinstance(probe, Exception) and probe.returncode == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = all(v for _, v in checks)
    for name, v in checks:
        print("  [%s] %s" % ("ok" if v else "XX", name))
    print("check_e2e_installed selftest: %s (%d/%d)" % (
        "PASS" if ok else "FAIL", sum(1 for _, v in checks if v), len(checks)))
    return 0 if ok else 1


def _parse(args):
    opts = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                opts[key] = args[i + 1]
                i += 2
            else:
                opts[key] = True
                i += 1
        else:
            i += 1
    return opts


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__)
        raise SystemExit(2)
    if argv[0] == "--describe-cli":
        print(json.dumps({
            "verbs": ["probe", "run", "selftest"],
            "flags": ["--events", "--isolate-path", "--json", "--no-network", "--out", "--repo"],
        }))
        raise SystemExit(0)
    sub, rest = argv[0], argv[1:]
    opts = _parse(rest)
    if sub == "probe":
        raise SystemExit(cmd_probe(opts))
    if sub == "run":
        raise SystemExit(cmd_run(opts))
    if sub == "selftest":
        raise SystemExit(cmd_selftest(opts))
    print("unknown command %r. choices: probe run selftest" % sub)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
