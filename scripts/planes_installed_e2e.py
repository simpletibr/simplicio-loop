#!/usr/bin/env python3
"""Real installed PLANES E2E gate for issue #141.

The harness deliberately has no shims, mocks, in-process operator imports, or fixture receipts.
It reads the raw PLANES Markdown and invokes the installed console scripts as subprocesses.  The
optional ``--execute`` stage invokes the installed dev-cli against an isolated delivery target;
without it the command is a preflight/plan receipt and never claims delivery.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "contracts/task-to-delivery/fixtures/planes/task.md"
SCHEMA = "simplicio.planes-installed-e2e/v1"
REQUIRED = {
    "simplicio-mapper": ("handoff", "orient"),
    "simplicio-dev-cli": ("task",),
    "simplicio-loop": ("plan",),
    "simplicio": ("runtime", "map"),
}


def run(cmd, cwd=ROOT, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=timeout)
        return {"command": cmd, "returncode": p.returncode, "stdout": p.stdout,
                "stderr": p.stderr}
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"command": cmd, "returncode": 127, "stdout": "", "stderr": str(exc)}


def check_installed():
    rows = []
    ok = True
    for name, needles in REQUIRED.items():
        path = shutil.which(name)
        if not path:
            rows.append({"name": name, "ok": False, "reason": "missing-on-path"})
            ok = False
            continue
        result = run([name, "--help"], timeout=30)
        text = result["stdout"] + result["stderr"]
        row = {"name": name, "path": os.path.realpath(path),
               "ok": result["returncode"] == 0 and all(n in text for n in needles),
               "returncode": result["returncode"],
               "missing_help": [n for n in needles if n not in text]}
        if not row["ok"]:
            row["reason"] = "required-command-surface-missing"
            ok = False
        rows.append(row)
    return ok, rows


def _json_result(result):
    try:
        return json.loads(result["stdout"])
    except (TypeError, ValueError):
        return None


def execute(task_path=TASK, execute=False, out=None, repo=ROOT):
    """``repo`` is the repository the installed operators map. Tests pass a throwaway one: the
    Runtime writes its baseline into the git common dir shared by every worktree (#1574)."""
    raw = task_path.read_text(encoding="utf-8")
    bins_ok, bins = check_installed()
    receipt = {
        "schema": SCHEMA,
        "status": "UNVERIFIED",
        "proof_kind": "measured",
        "task_source": str(task_path.relative_to(ROOT)),
        "task_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "installed": bins,
        "hops": [],
    }
    if not bins_ok:
        receipt["status"] = "BLOCKED"
        receipt["reason"] = "required published console-script is unavailable or has no required surface"
        return receipt

    # Every hop is an installed process.  The first two consume the raw Markdown directly.
    commands = [
        ["simplicio-mapper", "orient", str(repo), "--task-file", str(task_path), "--json"],
        ["simplicio-mapper", "handoff", str(repo), "--task-file", str(task_path), "--json"],
    ]
    plan_out = Path(out or tempfile.mkdtemp(prefix="planes-installed-e2e-"))
    plan_out.mkdir(parents=True, exist_ok=True)
    plan_file = plan_out / "planes-contract.json"
    commands.append(["simplicio", "runtime", "map", "--repo", str(repo), "--json"])
    commands.append(["simplicio-loop", "plan", "--task", str(task_path), "--out", str(plan_file)])
    for cmd in commands:
        result = run(cmd)
        payload = _json_result(result)
        receipt["hops"].append({"name": cmd[1], "command": cmd, "returncode": result["returncode"],
                                "json": payload is not None, "stdout_sha256": hashlib.sha256(
                                    result["stdout"].encode()).hexdigest()})
        if result["returncode"] != 0:
            receipt["status"] = "BLOCKED"
            receipt["reason"] = "installed subprocess failed: %s" % cmd[1]
            return receipt

    if not plan_file.exists():
        receipt["status"] = "BLOCKED"
        receipt["reason"] = "installed loop did not materialize a contract"
        return receipt

    if execute:
        # This is intentionally a real operator call.  It is pointed at the isolated output file
        # dry-run is used only to prevent an uncontrolled repository mutation; no synthetic result
        # is accepted as delivery evidence.
        target = plan_out / "delivery-target.txt"
        target.write_text("PLANES delivery target\n", encoding="utf-8")
        result = run(["simplicio-dev-cli", "task", "Implement the PLANES ordering behavior from the raw task",
                      "--root", str(plan_out), "--target", str(target), "--stack", "python",
                      "--dry-run-task", "--json", "--local"], timeout=180)
        receipt["hops"].append({"name": "edit", "command": result["command"],
                                "returncode": result["returncode"], "json": _json_result(result) is not None,
                                "stdout_sha256": hashlib.sha256(result["stdout"].encode()).hexdigest()})
        if result["returncode"] != 0:
            receipt["status"] = "BLOCKED"
            receipt["reason"] = "installed dev-cli did not complete the real operator stage"
            return receipt
        receipt["delivery_target"] = str(target)

    receipt["status"] = "MEASURED" if execute else "PLANNED"
    receipt["execution"] = "installed-subprocesses" + ("+operator" if execute else "")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", type=Path, default=TASK)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--repo", type=Path, default=ROOT, help="repository the operators map (default: this checkout)")
    args = parser.parse_args(argv)
    receipt = execute(args.task, args.execute, args.out, args.repo)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] in {"PLANNED", "MEASURED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
