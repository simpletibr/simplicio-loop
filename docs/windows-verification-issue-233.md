# Windows verification checklist — issue #233 (PyPI publish of the PR #232 timeout fix)

This checklist exists because the PR #232 / issue #201 / issue #231 fixes
(bounded synchronous scans, dead-owner lock recovery, and the
`stdin=DEVNULL` fix for `WinError 6` on Windows background/index/taskkill
subprocess calls) touch Windows-only code paths — `_winapi.DuplicateHandle`
stdin inheritance and `taskkill` — that cannot be exercised on Linux/macOS.
Everything below was already verified on Linux in this repo (build, twine
check, most of the regression matrix); this is the remaining ~5-minute
verification an operator runs once with real Windows + PyPI access.

Run every step from a plain `cmd.exe` or PowerShell prompt, not from inside
this repo checkout — the point is to prove the **installed** package
behaves correctly, matching what a real operator gets.

## 0. Confirm the install

```powershell
pip show simplicio-mapper
simplicio-mapper --version
```

Both must report `0.24.1` (or newer). If either reports `0.23.1` or
`0.24.0`, stop — the install itself is stale; reinstall first
(`pip install --force-reinstall simplicio-mapper==0.24.1`), per the
CHANGELOG's "How to upgrade" section, then restart this checklist.

## 1. Normal scan completes (no regression from the fix)

```powershell
mkdir %TEMP%\simplicio-win-check
cd %TEMP%\simplicio-win-check
echo {"name":"win-check"} > package.json
mkdir src
echo export function run() { return 1; } > src\index.js
simplicio-mapper scan . --sync --json --timeout 30 > scan-normal.json
type scan-normal.json
```

Expected: `"phase": "complete"`, `"exit_code": 0` (or no `exit_code` on
success paths — the point is no `"phase": "failed"` / `"timeout"`), and the
command itself exits 0 (`echo %ERRORLEVEL%` on cmd.exe / `$LASTEXITCODE` on
PowerShell).

## 2. `status --json` reports a clean, unlocked state afterward

```powershell
simplicio-mapper status . --json
```

Expected: `"lock": false`, `"terminal": true`, `"fresh": true`,
`"warnings": []`.

## 3. Closed/invalid stdin never raises `WinError 6` (the issue #231 repro)

This is the actual Windows-specific regression: a host with a captured or
closed stdin handle (Task Scheduler, a Windows Service, some CI/Codex/
PowerShell hosts) used to crash with `OSError: [WinError 6]` from
`_winapi.DuplicateHandle` the moment the background/index worker or the
`taskkill` recovery path spawned a subprocess, because the child tried to
inherit the parent's invalid stdin handle.

Save this as `winerror6_check.py` next to the scanned folder and run it —
it closes its own stdin (fd 0) in-process, the same failure mode as a
service host with no console, then drives the installed package exactly
like a real caller would:

```python
import subprocess
import sys

# Simulate a host with an invalid/closed inherited stdin handle
# (Task Scheduler / Windows Service / some CI runners hit this for real).
script = (
    "import os, sys, json;"
    "os.close(0);"
    "from simplicio_mapper.cli import main;"
    "code = main(['scan', '.', '--sync', '--json', '--timeout', '30']);"
    "sys.exit(code)"
)
result = subprocess.run(
    [sys.executable, "-c", script],
    cwd=".",
    capture_output=True,
    text=True,
)
print("exit code:", result.returncode)
print("stdout:", result.stdout)
print("stderr:", result.stderr)
assert "WinError 6" not in result.stderr, "WinError 6 regression reproduced!"
assert result.returncode == 0, "scan did not exit cleanly with closed stdin"
print("PASS: no WinError 6, clean exit with closed stdin")
```

```powershell
cd %TEMP%\simplicio-win-check
python winerror6_check.py
```

Expected: `PASS: no WinError 6, clean exit with closed stdin`. If
`WinError 6` (or any `OSError` mentioning `DuplicateHandle`) shows up in
`stderr`, the fix has regressed for this Windows host/Python combination —
capture the full `stderr` and file a new issue referencing #231/#233.

## 4. A genuinely slow/blocked scan produces a bounded timeout, not a hang

Only run this if you have (or can construct) a root that is slow enough to
exceed a short timeout — e.g. a directory tree with many thousands of
files, or a network-mounted path with high latency. Do not fabricate a
fake slow root just to force this; if none is available, skip this step
and note it as skipped rather than faking a pass.

```powershell
simplicio-mapper scan <slow-root> --sync --json --timeout 2 > scan-timeout.json
type scan-timeout.json
simplicio-mapper status <slow-root> --json
```

Expected: `scan-timeout.json` shows `"phase": "timeout"`,
`"failure_reason": "scan_timeout"`, `"exit_code": 1`; the follow-up
`status --json` shows `"lock": false` (no orphaned lock left behind).

## Reporting back

Whoever runs this should record, for each of steps 0-4: pass / fail /
skipped (with reason), the exact `simplicio-mapper --version` string, the
Windows version, and the Python version (`python --version`). That is the
missing piece issue #233 cannot close from a Linux sandbox — everything
else (version bump, build, `twine check`, changelog, the parts of the
regression matrix that do not require Windows) is already verified in this
repo.
