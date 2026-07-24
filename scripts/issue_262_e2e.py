#!/usr/bin/env python3
"""Executable local evidence runner for dev-cli issue #262.

The runner deliberately produces Markdown and HBP only. It exercises the
binary cache, legacy migration, CLI surfaces, source/archive boundary gate,
and installed-package probe. External Runtime/Mapper release evidence is
reported as ``UNVERIFIED`` with a reason when the corresponding installed
artifact is unavailable; the process exits non-zero so release cannot pass on
missing evidence.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio._cache import CacheEntry, CompletionCache, make_key  # noqa: E402
from simplicio.hbp import HbpError, HbpEvidenceLedger  # noqa: E402


@dataclass(frozen=True)
class Case:
    case_id: str
    status: str
    duration_ms: float | None
    detail: str
    command: str


def _command(command: list[str], *, cwd: Path = ROOT) -> tuple[int, float, str]:
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, (time.perf_counter() - started) * 1000, str(exc)
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode, (time.perf_counter() - started) * 1000, output[-1000:]


def _cache_case(work: Path) -> Case:
    started = time.perf_counter()
    cache = CompletionCache(work / "cache")
    key = make_key("fixture", "fixture", "issue-262")
    if cache.get(key) is not None:
        return Case(
            "cache-cold-miss", "FAIL", 0.0, "cache was warm before the cold probe", "CompletionCache.get"
        )
    cache.put(key, CacheEntry("binary-cache-value", provider_id="fixture", model="fixture"))
    entry = cache.get(key)
    files = list((work / "cache").rglob("*"))
    json_files = [path for path in files if path.is_file() and path.suffix in {".json", ".jsonl", ".ndjson"}]
    if entry is None or entry.completion != "binary-cache-value":
        status, detail = "FAIL", "warm read did not preserve the cached value"
    elif json_files:
        status, detail = "FAIL", "cache recreated internal JSON: " + ", ".join(str(p) for p in json_files)
    else:
        status, detail = "PASS", f"misses={cache.misses}; hits={cache.hits}; bytes={cache.stats()['bytes']}"
    return Case(
        "cache-cold-warm", status, (time.perf_counter() - started) * 1000, detail, "CompletionCache.get/put"
    )


def _migration_case(work: Path) -> Case:
    started = time.perf_counter()
    legacy = work / "legacy-events.jsonl"
    legacy.write_text('{"event":"task_complete","payload":{"files":2}}\n', encoding="utf-8")
    ledger = HbpEvidenceLedger(work / "hbp", file_name="events.hbp")
    try:
        migrated = ledger.migrate_jsonl(legacy)
        rows = ledger.verify()
        retry = ledger.migrate_jsonl(legacy)
    except (OSError, HbpError, ValueError) as exc:
        return Case(
            "legacy-migration",
            "FAIL",
            (time.perf_counter() - started) * 1000,
            str(exc),
            "HbpEvidenceLedger.migrate_jsonl",
        )
    if migrated != 1 or retry != 0 or len(rows) != 1 or legacy.exists():
        detail = f"migrated={migrated}; retry={retry}; rows={len(rows)}; legacy_present={legacy.exists()}"
        status = "FAIL"
    else:
        detail, status = "atomic, idempotent, source archived", "PASS"
    return Case(
        "legacy-migration",
        status,
        (time.perf_counter() - started) * 1000,
        detail,
        "HbpEvidenceLedger.migrate_jsonl",
    )


def _cli_case(case_id: str, args: list[str]) -> Case:
    code, duration, output = _command(
        [
            sys.executable,
            "-c",
            "from simplicio.cli import main; raise SystemExit(main(__import__('sys').argv[1:]))",
            *args,
        ]
    )
    status = "PASS" if code == 0 else "FAIL"
    detail = "help surface available" if status == "PASS" else f"exit={code}; output={output}"
    return Case(case_id, status, duration, detail, "simplicio.cli " + " ".join(args))


def _scanner_case(artifact_dir: Path | None) -> Case:
    command = [sys.executable, "scripts/check_json_boundaries.py", "--strict"]
    if artifact_dir is not None:
        command.extend(["--artifact-dir", str(artifact_dir)])
    code, duration, output = _command(command)
    status = "PASS" if code == 0 else "FAIL"
    return Case("strict-boundary-scan", status, duration, output or "no findings", " ".join(command))


def _external_case(case_id: str, executable: str, expected: str) -> Case:
    path = shutil.which(executable)
    if not path:
        return Case(
            case_id, "UNVERIFIED", None, f"{executable} executable is unavailable", "which " + executable
        )
    return Case(
        case_id,
        "UNVERIFIED",
        None,
        f"{path} is not proven to be {expected}; live handshake required",
        "runtime handshake",
    )


def _write_evidence(cases: list[Case], markdown: Path, hbp: Path, *, commit: str) -> None:
    markdown.parent.mkdir(parents=True, exist_ok=True)
    ledger = HbpEvidenceLedger(hbp.parent, file_name=hbp.name)
    for case in cases:
        ledger.record_fields(
            "issue-262-e2e",
            {
                "case": case.case_id,
                "command": case.command,
                "commit": commit,
                "duration_ms": "null" if case.duration_ms is None else f"{case.duration_ms:.3f}",
                "status": case.status,
            },
            "simplicio-dev-cli/issue-262-e2e",
        )
    lines = [
        "# Issue #262 E2E evidence",
        "",
        f"- commit: `{commit}`",
        "- evidence format: Markdown + Runtime-compatible HBP; no JSON evidence is generated",
        "- release rule: `PASS` requires every case to pass; `UNVERIFIED` is a blocking state",
        "",
        "| Case | Status | Duration (ms) | Detail | Command |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for case in cases:
        duration = "null" if case.duration_ms is None else f"{case.duration_ms:.3f}"
        detail = case.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{case.case_id}` | `{case.status}` | {duration} | {detail} | `{case.command}` |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "A missing runtime or published adjacent package is recorded as `UNVERIFIED` with a reason. "
            "It is not represented as zero and does not satisfy the release gate.",
            "",
            f"HBP receipt ledger: `{hbp.name}`",
            "",
        ]
    )
    markdown.write_text("\n".join(lines), encoding="utf-8")


def run(*, artifact_dir: Path | None = None, markdown: Path, hbp: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="simplicio-262-") as temporary:
        work = Path(temporary)
        cases = [
            _cache_case(work),
            _migration_case(work),
            _cli_case("run-surface", ["run", "--help"]),
            _cli_case("edit-surface", ["edit", "--help"]),
            _cli_case("task-surface", ["task", "--help"]),
            _cli_case("gate-surface", ["gate", "--help"]),
            _scanner_case(artifact_dir),
            _external_case("runtime-installed-e2e", "simplicio", "simplicio-runtime"),
            _external_case("mapper-installed-e2e", "simplicio-mapper", "simplicio-mapper"),
        ]
    commit = _git_commit()
    _write_evidence(cases, markdown, hbp, commit=commit)
    return 0 if all(case.status == "PASS" for case in cases) else 1


def _git_commit() -> str:
    code, _, output = _command(["git", "rev-parse", "HEAD"])
    return output.splitlines()[-1] if code == 0 and output else "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--markdown", type=Path, default=ROOT / "docs/evidence/issue-262-e2e.md")
    parser.add_argument("--hbp", type=Path, default=ROOT / "docs/evidence/issue-262-e2e.hbp")
    args = parser.parse_args(argv)
    return run(artifact_dir=args.artifact_dir, markdown=args.markdown, hbp=args.hbp)


if __name__ == "__main__":
    raise SystemExit(main())
