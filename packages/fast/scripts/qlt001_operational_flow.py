#!/usr/bin/env python3
"""Operational Mapper + Fast flow for QLT-001 (architecture-boundary issue).

Happy path: mapper survey -> Fast ingest/doctor/understand/plan/query/context/impact.
Failure path: unknown symbol stays empty; missing snapshot fails closed.
Idempotence: second ingest reports no_change when the tree is unchanged.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

SCHEMA = "simplicio.fast.qlt001-operational-flow/v1"
QLT001_TASK = (
    "QLT-001 enforce quality-extension architecture boundary in "
    "src/simplicio_loop_quality/loop_invoker.py and "
    "tests/integration/test_architecture_boundary.py"
)
QLT001_TARGET = "src/simplicio_loop_quality/loop_invoker.py"
QLT001_SYMBOL = "LoopInvoker"
FAST_REPO = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = FAST_REPO / "fixtures" / "qlt001"
SIBLING_QUALITY = FAST_REPO.parent / "simplicio-loop-quality"


def default_repo() -> Path:
    sibling = SIBLING_QUALITY
    if (
        sibling.is_dir()
        and (sibling / "src" / "simplicio_loop_quality" / "loop_invoker.py").is_file()
    ):
        return sibling
    return DEFAULT_FIXTURE


def _which(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"missing_operator:{name}")
    return found


def _run_json(
    command: list[str], *, cwd: Path, timeout: float = 180.0
) -> dict[str, Any]:
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
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    stdout = completed.stdout.strip()
    payload: Any = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"raw": stdout[:2000]}
    return {
        "argv": command,
        "returncode": completed.returncode,
        "elapsed_ms": elapsed_ms,
        "payload": payload,
        "stderr": completed.stderr[-2000:] if completed.stderr else "",
    }


def _step(name: str, ok: bool, **fields: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, **fields}


def run_live(repo: Path) -> dict[str, Any]:
    fast = _which("simplicio-fast")
    mapper = _which("simplicio-mapper")
    steps: list[dict[str, Any]] = []

    mapper_handoff = _run_json(
        [
            mapper,
            "handoff",
            str(repo),
            "--goal",
            QLT001_TASK,
            "--target",
            QLT001_TARGET,
            "--json",
        ],
        cwd=repo,
    )
    handoff_payload = (
        mapper_handoff["payload"] if isinstance(mapper_handoff["payload"], dict) else {}
    )
    steps.append(
        _step(
            "mapper_handoff",
            mapper_handoff["returncode"] == 0 and bool(handoff_payload.get("ready")),
            returncode=mapper_handoff["returncode"],
            elapsed_ms=mapper_handoff["elapsed_ms"],
            ready=handoff_payload.get("ready"),
            gate=(handoff_payload.get("gate_precedence") or {}).get("outcome"),
        )
    )

    ingest = _run_json([fast, "ingest", str(repo), "--json"], cwd=repo)
    ingest_payload = ingest["payload"] if isinstance(ingest["payload"], dict) else {}
    steps.append(
        _step(
            "fast_ingest",
            ingest["returncode"] == 0
            and ingest_payload.get("schema") == "simplicio.fast.ingest/v2",
            returncode=ingest["returncode"],
            elapsed_ms=ingest["elapsed_ms"],
            schema=ingest_payload.get("schema"),
            mapper_status=(ingest_payload.get("mapper") or {}).get("status"),
            files=(ingest_payload.get("metrics") or {}).get("files"),
            cpu_ms=(ingest_payload.get("metrics") or {}).get("cpu_ms"),
            wall_ms=(ingest_payload.get("metrics") or {}).get("wall_ms"),
        )
    )

    doctor = _run_json([fast, "doctor", "--json"], cwd=repo)
    doctor_payload = doctor["payload"] if isinstance(doctor["payload"], dict) else {}
    mapper_ok = ((doctor_payload.get("integration") or {}).get("mapper") or {}).get(
        "compatible"
    )
    steps.append(
        _step(
            "fast_doctor",
            doctor["returncode"] == 0 and bool(doctor_payload.get("ready")),
            returncode=doctor["returncode"],
            elapsed_ms=doctor["elapsed_ms"],
            ready=doctor_payload.get("ready"),
            mapper_compatible=mapper_ok,
            mapper_version=(
                (doctor_payload.get("integration") or {}).get("mapper") or {}
            ).get("version"),
        )
    )

    understand = _run_json(
        [fast, "understand", "--root", str(repo), QLT001_TASK], cwd=repo
    )
    understand_payload = (
        understand["payload"] if isinstance(understand["payload"], dict) else {}
    )
    files = understand_payload.get("files") or []
    symbols = understand_payload.get("symbols") or []
    steps.append(
        _step(
            "fast_understand",
            understand["returncode"] == 0
            and QLT001_TARGET in files
            and QLT001_SYMBOL in symbols,
            returncode=understand["returncode"],
            elapsed_ms=understand["elapsed_ms"],
            files=files,
            symbols=symbols[:12],
        )
    )

    plan = _run_json([fast, "plan", "--root", str(repo), QLT001_TASK], cwd=repo)
    plan_payload = plan["payload"] if isinstance(plan["payload"], dict) else {}
    node_ids = [node.get("id") for node in plan_payload.get("nodes") or []]
    steps.append(
        _step(
            "fast_plan",
            plan["returncode"] == 0
            and plan_payload.get("schema") == "simplicio.fast.plandag/v2"
            and node_ids == ["orient", "modify", "validate", "refresh"],
            returncode=plan["returncode"],
            elapsed_ms=plan["elapsed_ms"],
            schema=plan_payload.get("schema"),
            nodes=node_ids,
            handles=len(plan_payload.get("context_handles") or []),
        )
    )

    query = _run_json(
        [fast, "query", QLT001_SYMBOL, "--limit", "8", "--json"], cwd=repo
    )
    query_payload = query["payload"] if isinstance(query["payload"], dict) else {}
    matches = query_payload.get("matches") or []
    query_files = {item.get("file") for item in matches if isinstance(item, dict)}
    steps.append(
        _step(
            "fast_query",
            query["returncode"] == 0
            and query_payload.get("schema") == "simplicio.fast.query/v1"
            and QLT001_TARGET in query_files,
            returncode=query["returncode"],
            elapsed_ms=query["elapsed_ms"],
            match_count=len(matches),
            files=sorted(path for path in query_files if isinstance(path, str)),
        )
    )

    context = _run_json(
        [
            fast,
            "context",
            "--root",
            str(repo),
            QLT001_SYMBOL,
            "--max-results",
            "4",
            "--json",
        ],
        cwd=repo,
    )
    context_payload = context["payload"] if isinstance(context["payload"], dict) else {}
    spans = (
        context_payload.get("spans")
        or context_payload.get("results")
        or context_payload.get("context")
        or []
    )
    steps.append(
        _step(
            "fast_context",
            context["returncode"] == 0 and bool(spans),
            returncode=context["returncode"],
            elapsed_ms=context["elapsed_ms"],
            span_count=len(spans) if isinstance(spans, list) else 0,
            schema=context_payload.get("schema"),
        )
    )

    impact = _run_json(
        [fast, "impact", QLT001_SYMBOL, "--limit", "10", "--json"], cwd=repo
    )
    impact_payload = impact["payload"] if isinstance(impact["payload"], dict) else {}
    relations = impact_payload.get("relations") or []
    steps.append(
        _step(
            "fast_impact",
            impact["returncode"] == 0
            and impact_payload.get("schema") == "simplicio.fast.impact/v1"
            and bool(relations),
            returncode=impact["returncode"],
            elapsed_ms=impact["elapsed_ms"],
            relation_count=len(relations),
        )
    )

    miss = _run_json(
        [fast, "query", "__no_such_symbol_qlt001__", "--limit", "8", "--json"], cwd=repo
    )
    miss_payload = miss["payload"] if isinstance(miss["payload"], dict) else {}
    miss_matches = miss_payload.get("matches") or []
    steps.append(
        _step(
            "fast_query_unknown_empty",
            miss["returncode"] == 0 and miss_matches == [],
            returncode=miss["returncode"],
            elapsed_ms=miss["elapsed_ms"],
            match_count=len(miss_matches),
        )
    )

    ingest_again = _run_json([fast, "ingest", str(repo), "--json"], cwd=repo)
    again_payload = (
        ingest_again["payload"] if isinstance(ingest_again["payload"], dict) else {}
    )
    reason_codes = (again_payload.get("metrics") or {}).get("reason_codes") or []
    steps.append(
        _step(
            "fast_ingest_idempotent",
            ingest_again["returncode"] == 0 and "no_change" in reason_codes,
            returncode=ingest_again["returncode"],
            elapsed_ms=ingest_again["elapsed_ms"],
            reason_codes=reason_codes,
        )
    )

    missing = _run_json(
        [
            fast,
            "doctor",
            "--json",
            "-s",
            str(repo / ".simplicio" / "fast" / "missing.sfast"),
        ],
        cwd=repo,
    )
    missing_payload = missing["payload"] if isinstance(missing["payload"], dict) else {}
    steps.append(
        _step(
            "fast_doctor_missing_snapshot_fails_closed",
            missing_payload.get("ready") is False,
            returncode=missing["returncode"],
            elapsed_ms=missing["elapsed_ms"],
            ready=missing_payload.get("ready"),
        )
    )

    failed = [step["name"] for step in steps if not step["ok"]]
    return {
        "schema": SCHEMA,
        "mode": "live",
        "repo": str(repo),
        "task": QLT001_TASK,
        "status": "pass" if not failed else "fail",
        "failed": failed,
        "steps": steps,
    }


def run_inprocess(repo: Path) -> dict[str, Any]:
    from simplicio_fast.processor import ProjectProcessor

    snapshot = repo / ".simplicio" / "fast" / "project.sfast"
    processor = ProjectProcessor(repo, snapshot)
    started = time.perf_counter()
    ingest = processor.ingest()
    ingest_ms = round((time.perf_counter() - started) * 1000, 3)
    understanding = processor.understand(QLT001_TASK)
    plan = processor.plan(QLT001_TASK)
    files = (
        list(understanding.files)
        if hasattr(understanding, "files")
        else list(understanding.get("files", []))
    )
    symbols = list(
        getattr(understanding, "symbols", None) or understanding.get("symbols", [])
    )
    node_ids = [node.get("id") for node in plan.get("nodes") or []]
    steps = [
        _step(
            "inprocess_ingest",
            ingest.get("schema") == "simplicio.fast.ingest/v2",
            elapsed_ms=ingest_ms,
            files=(ingest.get("metrics") or {}).get("files"),
        ),
        _step(
            "inprocess_understand",
            QLT001_TARGET in files and QLT001_SYMBOL in symbols,
            files=files,
            symbols=symbols[:12],
        ),
        _step(
            "inprocess_plan",
            plan.get("schema") == "simplicio.fast.plandag/v2"
            and node_ids == ["orient", "modify", "validate", "refresh"],
            nodes=node_ids,
        ),
    ]
    failed = [step["name"] for step in steps if not step["ok"]]
    return {
        "schema": SCHEMA,
        "mode": "inprocess",
        "repo": str(repo),
        "task": QLT001_TASK,
        "status": "pass" if not failed else "fail",
        "failed": failed,
        "steps": steps,
    }


def evaluate(repo: Path | None = None, *, mode: str = "live") -> dict[str, Any]:
    target = Path(repo) if repo is not None else default_repo()
    if mode == "inprocess":
        return run_inprocess(target)
    return run_live(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--mode", choices=("live", "inprocess"), default="live")
    parser.add_argument("--json", action="store_true", default=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.repo, mode=args.mode)
    except Exception as error:  # noqa: BLE001 — CLI must emit a receipt
        report = {
            "schema": SCHEMA,
            "mode": args.mode,
            "status": "fail",
            "failed": ["runner"],
            "error": f"{type(error).__name__}:{error}",
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
