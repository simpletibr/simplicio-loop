#!/usr/bin/env python3
"""Operational Dev CLI flow for QLT-001: standalone, mapper, and Loop."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.dev-cli.qlt001-operational-flow/v1"
QLT001_TARGET = "src/simplicio_loop_quality/loop_invoker.py"
QLT001_GOAL = "QLT-001 enforce quality-extension architecture boundary"
DEVCLI_REPO = Path(__file__).resolve().parents[1]
SIBLING_QUALITY = DEVCLI_REPO.parent / "simplicio-loop-quality"


def _which(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"missing_operator:{name}")
    return found


def _run(command: list[str], *, cwd: Path, timeout: float = 180.0) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    stdout = completed.stdout.strip()
    payload: Any = None
    if stdout:
        try:
            payload = json.loads(stdout[stdout.find("{") :])
        except json.JSONDecodeError:
            payload = {"raw": stdout[-2000:]}
    return {
        "argv": command,
        "returncode": completed.returncode,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "payload": payload,
        "stderr": (completed.stderr or "")[-1500:],
    }


def _step(name: str, ok: bool, **fields: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, **fields}


def _write_plan(root: Path, *, apply_kind: str) -> Path:
    target = root / "scratch_qlt001.py"
    original = "value = 1\n"
    target.write_text(original, encoding="utf-8")
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
    if apply_kind == "mechanical":
        plan = {
            "schema": "simplicio.mechanical-edit/v1",
            "touched_files": ["scratch_qlt001.py"],
            "operations": [
                {
                    "op": "replace_range",
                    "path": "scratch_qlt001.py",
                    "start_line": 1,
                    "end_line": 1,
                    "text": "value = 2\n",
                    "file_sha256": digest,
                    "range_sha256": digest,
                }
            ],
        }
    else:
        plan = {
            "schema": "simplicio.fast.changeset/v2",
            "changeset_id": "qlt001-operational",
            "correlation_id": "qlt001",
            "generation": "gen-qlt001",
            "allowlist": ["created_qlt001.py"],
            "operations": [
                {
                    "kind": "create",
                    "path": "created_qlt001.py",
                    "content": "value = 2\n",
                }
            ],
        }
    path = root / f"{apply_kind}-plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def run_flow(repo: Path) -> dict[str, Any]:
    cli = _which("simplicio-dev-cli")
    mapper = _which("simplicio-mapper")
    loop = _which("simplicio-loop")
    steps: list[dict[str, Any]] = []

    smoke = _run([cli, "smoke", "--json", "--root", str(repo)], cwd=repo)
    smoke_payload = smoke["payload"] if isinstance(smoke["payload"], dict) else {}
    smoke_config_missing = "set SIMPLICIO_MODEL" in smoke["stderr"]
    steps.append(
        _step(
            "devcli_smoke",
            (smoke["returncode"] == 0 and bool(smoke_payload.get("ok"))) or smoke_config_missing,
            returncode=smoke["returncode"],
            elapsed_ms=smoke["elapsed_ms"],
            schema=smoke_payload.get("schema"),
            status="verified" if smoke["returncode"] == 0 else "skipped_no_provider_config",
        )
    )

    inspect = _run(
        [
            cli,
            "inspect",
            QLT001_TARGET,
            "--root",
            str(repo),
            "--goal",
            QLT001_GOAL,
            "--json",
        ],
        cwd=repo,
        timeout=180,
    )
    inspect_payload = inspect["payload"] if isinstance(inspect["payload"], dict) else {}
    steps.append(
        _step(
            "devcli_inspect_mapper",
            inspect["returncode"] == 0
            and inspect_payload.get("schema") == "simplicio.dev-cli.inspect/v1"
            and inspect_payload.get("target") == QLT001_TARGET,
            returncode=inspect["returncode"],
            elapsed_ms=inspect["elapsed_ms"],
            schema=inspect_payload.get("schema"),
        )
    )

    verify = _run(
        [
            cli,
            "task",
            QLT001_GOAL,
            "--root",
            str(repo),
            "--target",
            QLT001_TARGET,
            "--verify-only",
            "--json",
        ],
        cwd=repo,
        timeout=180,
    )
    verify_payload = verify["payload"] if isinstance(verify["payload"], dict) else {}
    steps.append(
        _step(
            "devcli_verify_only_inferred",
            verify_payload.get("schema") == "simplicio.dev-cli.verification-only/v1"
            and verify_payload.get("status") in {"verified", "failed"}
            and verify_payload.get("status") != "blocked",
            returncode=verify["returncode"],
            elapsed_ms=verify["elapsed_ms"],
            status=verify_payload.get("status"),
            reason_code=verify_payload.get("reason_code"),
        )
    )

    dry = _run(
        [
            cli,
            "task",
            QLT001_GOAL,
            "--root",
            str(repo),
            "--target",
            QLT001_TARGET,
            "--stack",
            "python",
            "--dry-run-task",
            "--json",
            "--mode",
            "standalone",
        ],
        cwd=repo,
        timeout=180,
    )
    dry_payload = dry["payload"] if isinstance(dry["payload"], dict) else {}
    steps.append(
        _step(
            "devcli_task_no_contract_receipt",
            isinstance(dry_payload, dict) and bool(dry_payload.get("schema")),
            returncode=dry["returncode"],
            elapsed_ms=dry["elapsed_ms"],
            schema=dry_payload.get("schema"),
            status=dry_payload.get("status"),
        )
    )

    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        mechanical_plan = _write_plan(scratch, apply_kind="mechanical")
        mechanical = _run(
            [
                cli,
                "mechanical-edit",
                "--root",
                str(scratch),
                "--plan",
                str(mechanical_plan),
                "--dry-run",
                "--json",
            ],
            cwd=scratch,
        )
        mechanical_payload = mechanical["payload"] if isinstance(mechanical["payload"], dict) else {}
        steps.append(
            _step(
                "devcli_mechanical_edit_no_contract",
                mechanical["returncode"] == 0,
                returncode=mechanical["returncode"],
                elapsed_ms=mechanical["elapsed_ms"],
                schema=mechanical_payload.get("schema"),
                status=mechanical_payload.get("status") or mechanical_payload.get("ok"),
            )
        )

        changeset_plan = _write_plan(scratch, apply_kind="changeset")
        changeset = _run(
            [
                cli,
                "changeset",
                "--root",
                str(scratch),
                "--plan",
                str(changeset_plan),
                "--mode",
                "standalone",
                "--json",
            ],
            cwd=scratch,
        )
        changeset_payload = changeset["payload"] if isinstance(changeset["payload"], dict) else {}
        steps.append(
            _step(
                "devcli_changeset_standalone",
                changeset["returncode"] == 0
                and (
                    changeset_payload.get("status") in {"ok", "dry-run", "ready"}
                    or changeset_payload.get("execution_mode", {}).get("route") == "standalone"
                ),
                returncode=changeset["returncode"],
                elapsed_ms=changeset["elapsed_ms"],
                status=changeset_payload.get("status"),
                route=(changeset_payload.get("execution_mode") or {}).get("route"),
                stderr=changeset["stderr"][-400:],
            )
        )

    mapper_scan = _run(
        [mapper, "scan", str(repo), "--json"],
        cwd=repo,
        timeout=120,
    )
    mapper_payload = mapper_scan["payload"] if isinstance(mapper_scan["payload"], dict) else {}
    steps.append(
        _step(
            "mapper_default_route",
            mapper_scan["returncode"] == 0 and mapper_payload.get("schema") == "simplicio.map-job/v1",
            returncode=mapper_scan["returncode"],
            elapsed_ms=mapper_scan["elapsed_ms"],
            route=mapper_payload.get("route"),
            phase=mapper_payload.get("phase"),
        )
    )

    preflight = _run([loop, "preflight", "--strict", "--json"], cwd=repo)
    preflight_payload = preflight["payload"] if isinstance(preflight["payload"], dict) else {}
    operators = {
        item.get("name"): item for item in preflight_payload.get("operators") or [] if isinstance(item, dict)
    }
    steps.append(
        _step(
            "loop_preflight_devcli_bound",
            preflight["returncode"] == 0 and bool((operators.get("simplicio-dev-cli") or {}).get("present")),
            returncode=preflight["returncode"],
            elapsed_ms=preflight["elapsed_ms"],
            present=(operators.get("simplicio-dev-cli") or {}).get("present"),
            version=(operators.get("simplicio-dev-cli") or {}).get("version"),
        )
    )

    failed = [step["name"] for step in steps if not step["ok"]]
    return {
        "schema": SCHEMA,
        "repo": str(repo),
        "status": "pass" if not failed else "fail",
        "failed": failed,
        "steps": steps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=SIBLING_QUALITY)
    args = parser.parse_args(argv)
    try:
        report = run_flow(args.repo)
    except Exception as error:  # noqa: BLE001
        report = {
            "schema": SCHEMA,
            "status": "fail",
            "failed": ["runner"],
            "error": f"{type(error).__name__}:{error}",
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
