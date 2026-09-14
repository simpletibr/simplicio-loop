#!/usr/bin/env python3
"""Hot-path e2e for loop#1284: mapper -> fast -> edit -> test on checkers.html."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from simplicio.mapper_binding import build_mapper_binding
from simplicio.mechanical_edit import TextEdit, build_edit_plan

ROOT = Path("/tmp/checkers-1284")
VENV = Path("/tmp/stack1284/bin")
SRC = Path("/projetos/ai/_matrix/batch")
FIND = "Captures are not implemented in this build."
REPLACE = "Captures are enabled for loop-1284 e2e."


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{VENV}:/usr/local/bin:/usr/bin:/bin"
    for key in list(env):
        if key.startswith("SIMPLICIO_"):
            env.pop(key, None)
    env["SIMPLICIO_TEST_CMD"] = (
        "python3 -c \"import pathlib,sys; sys.exit(0 if 'loop-1284 e2e' in pathlib.Path('site/checkers.html').read_text() else 1)\""
    )
    return env


def _run(args: list[str], *, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args[:8]))
    proc = subprocess.run(args, cwd=ROOT, env=_env(), capture_output=True, text=True, timeout=timeout)
    print("exit", proc.returncode)
    if proc.stdout:
        print("stdout", proc.stdout[-2000:])
    if proc.stderr:
        print("stderr", proc.stderr[-1200:])
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def main() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    shutil.copytree(SRC, ROOT)
    (ROOT / "simplicio-runtime.toml").unlink(missing_ok=True)
    (ROOT / "README.md").write_text("Checkers fixture for loop#1284 hot path.\n", encoding="utf-8")
    subprocess.check_call(["/usr/bin/git", "init", "-q"], cwd=ROOT)
    subprocess.check_call(["/usr/bin/git", "add", "-A"], cwd=ROOT)
    subprocess.check_call(["/usr/bin/git", "commit", "-qm", "seed"], cwd=ROOT)

    mapper = str(VENV / "simplicio-mapper")
    fast = str(VENV / "simplicio-fast")
    cli = str(VENV / "simplicio-dev-cli")
    _run([mapper, "scan", str(ROOT), "--json", "--target", "site/checkers.html"])
    _run([mapper, "inspect", str(ROOT), "--json", "--await", "--timeout", "60"], timeout=90)
    hand = _run(
        [
            mapper,
            "handoff",
            str(ROOT),
            "--goal",
            "Edit site/checkers.html for loop-1284 e2e",
            "--target",
            "site/checkers.html",
            "--token-budget",
            "4000",
            "--json",
        ]
    )
    handoff_path = ROOT / "handoff.json"
    handoff_path.write_text(hand.stdout, encoding="utf-8")
    try:
        payload = json.loads(hand.stdout)
    except json.JSONDecodeError:
        payload = {"ready": False}
    print("handoff_ready", payload.get("ready"), "reason", payload.get("reason"), "chars", len(hand.stdout))
    ingest = _run(
        [fast, "ingest", str(ROOT), "--mapper-handoff", str(handoff_path), "--json"],
        check=False,
    )

    html = (ROOT / "site" / "checkers.html").read_text(encoding="utf-8")
    if FIND not in html:
        raise SystemExit("fixture missing expected hint text")
    sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
    binding = build_mapper_binding(
        "wesleysimplicio/checkers-1284",
        "generation-1",
        "tree-1284",
        {"site/checkers.html": sha},
    )
    plan = build_edit_plan(
        [TextEdit("site/checkers.html", FIND, REPLACE, sha)],
        mapper_binding=binding,
    )
    plan_path = ROOT / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    edit = _run([cli, "edit", "--root", str(ROOT), "--plan", str(plan_path), "--apply", "--json", "--no-runtime"])
    edit_payload = json.loads(edit.stdout)
    print("edit_applied", edit_payload.get("applied"), "verify", edit_payload.get("verify"))
    if edit_payload.get("applied") is not True:
        raise SystemExit("edit did not apply")
    if REPLACE not in (ROOT / "site" / "checkers.html").read_text(encoding="utf-8"):
        raise SystemExit("html missing applied marker")

    test = _run(
        [
            cli,
            "test",
            "run",
            "--json",
            "--cmd",
            sys.executable,
            "--",
            "-c",
            "import pathlib,sys; sys.exit(0 if 'loop-1284 e2e' in pathlib.Path('site/checkers.html').read_text() else 1)",
        ],
        check=False,
    )
    watcher = _run([sys.executable, str(ROOT / "scripts" / "watcher_verify.py"), "verify"], check=False)
    browser = _run(
        [
            "/usr/local/bin/node",
            "/projetos/ai/benchmark-checkers-v2-support/browser/validate_checkers.mjs",
            "--site",
            str(ROOT / "site" / "checkers.html"),
            "--task",
            "TASK-CHECKERS-001",
            "--json",
        ],
        check=False,
    )
    call_graph = json.loads((ROOT / ".simplicio" / "call-graph.json").read_text())
    excepts = [edge for edge in call_graph.get("edges", []) if edge.get("queried_symbol") == "except"]
    unknowns = [
        edge for edge in call_graph.get("edges", []) if edge.get("resolution_status") in {None, "unknown"}
    ]
    summary = {
        "handoff_ready": payload.get("ready"),
        "handoff_chars": len(hand.stdout),
        "ingest_exit": ingest.returncode,
        "edit_applied": edit_payload.get("applied"),
        "verify": edit_payload.get("verify"),
        "test_exit": test.returncode,
        "watcher_exit": watcher.returncode,
        "browser_exit": browser.returncode,
        "except_edges": len(excepts),
        "unknown_edges": len(unknowns),
        "prompt_pkg": subprocess.run(
            [sys.executable, "-m", "pip", "show", "simplicio-prompt"],
            capture_output=True,
        ).returncode,
        "runtime_bin": shutil.which("simplicio", path=str(VENV)),
    }
    print("MEASURED_FLOW", json.dumps(summary, sort_keys=True))
    if not edit_payload.get("applied"):
        raise SystemExit(1)
    if summary["except_edges"]:
        raise SystemExit(2)
    if summary["prompt_pkg"] == 0:
        raise SystemExit(3)
    if summary["runtime_bin"]:
        raise SystemExit(4)
    if summary["ingest_exit"] != 0:
        raise SystemExit(5)
    if summary["test_exit"] != 0:
        raise SystemExit(6)
    if summary["browser_exit"] != 0:
        raise SystemExit(7)


if __name__ == "__main__":
    main()
