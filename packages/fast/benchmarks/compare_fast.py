"""Reproducible end-to-end baseline versus Python Fast measurement.

This benchmark measures the same bounded-context task two ways: a direct source
scan on every repetition and a single Fast snapshot followed by repeated mmap
queries. Token values are explicitly deterministic estimates unless a caller
provides an observable tokenizer; they are never presented as provider usage.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import random
import json
import math
import os
import platform
import py_compile
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from simplicio_fast.delivery import DeliveryEngine
from simplicio_fast.engine import select_engine
from simplicio_fast.rust_session import RustCoreSession, RustSessionError
from simplicio_fast.snapshot import Snapshot, build_snapshot


SCHEMA = "simplicio.fast.e2e-benchmark/v1"
ENVIRONMENT_SCHEMA = "simplicio.fast.environment/v1"


def environment_receipt() -> dict[str, Any]:
    return {
        "schema": ENVIRONMENT_SCHEMA,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine() or None,
        "processor": platform.processor() or None,
        "executable": sys.executable,
        "cpu_count": os.cpu_count(),
    }


def corpus_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in _source_paths(root):
        relative = path.name.encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def source_commit_receipt() -> tuple[str | None, str | None]:
    repository = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--verify", "HEAD^{commit}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "git_unavailable"
    commit = completed.stdout.strip()
    if completed.returncode != 0 or not commit:
        return None, "not_a_git_checkout"
    return commit, None


def estimate_tokens(text: str) -> int:
    return max(1, len(text.split())) if text else 0


def make_workload(
    root: Path, *, files: int, functions: int, compact_symbols: bool = False
) -> str:
    for index in range(files):
        if compact_symbols:
            lines = []
            suffix = ".rs"
        else:
            lines = [f"class Service{index}:\n"]
            suffix = ".py"
        for function in range(functions):
            if compact_symbols:
                lines.extend(
                    [
                        f"pub fn task_{function}(value: i32) -> i32 {{\n",
                        "    return value;\n",
                        "}\n",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"    def task_{function}(self, value):\n",
                        "        return value\n",
                    ]
                )
        (root / f"service_{index}{suffix}").write_text(
            "".join(lines), encoding="utf-8"
        )
    return "task_7"


def _source_paths(root: Path) -> list[Path]:
    return sorted([*root.glob("*.py"), *root.glob("*.rs")])


def direct_context(root: Path, term: str, *, max_lines: int = 8) -> str:
    snippets: list[str] = []
    for path in _source_paths(root):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if term.casefold() in line.casefold():
                start = max(0, index - 2)
                end = min(len(lines), index + max_lines - 2)
                snippets.append(f"# {path.name}\n" + "\n".join(lines[start:end]))
    return "\n".join(snippets)


def ast_context(root: Path, term: str, *, max_lines: int = 8) -> str:
    if any(path.suffix == ".rs" for path in _source_paths(root)):
        return direct_context(root, term, max_lines=max_lines)
    snippets: list[str] = []
    for path in _source_paths(root):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        lines = text.splitlines()
        for node in ast.walk(tree):
            name = getattr(node, "name", "")
            if term.casefold() not in name.casefold():
                continue
            line = max(1, getattr(node, "lineno", 1))
            start = max(0, line - 3)
            end = min(len(lines), start + max_lines)
            snippets.append(f"# {path.name}\n" + "\n".join(lines[start:end]))
    return "\n".join(snippets)


def direct_target(root: Path, term: str) -> Path:
    for path in _source_paths(root):
        if term.casefold() in path.read_text(encoding="utf-8").casefold():
            return path
    raise LookupError(f"target not found: {term}")


def apply_deterministic_change(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    marker, replacement = (
        ("return value;\n", "return value + 1;\n")
        if path.suffix == ".rs"
        else ("return value\n", "return value + 1\n")
    )
    changed = source.replace(marker, replacement, 1)
    if changed == source:
        raise ValueError(f"change marker not found: {path}")
    path.write_text(changed, encoding="utf-8")
    # A stable __pycache__ target is prone to WinError 5 when repeated edits
    # overlap with antivirus/indexer handles. Use a sibling artifact per edit.
    compiled = path.with_name(f".{path.name}.{time.perf_counter_ns()}.pyc")
    try:
        if path.suffix == ".py":
            py_compile.compile(str(path), cfile=str(compiled), doraise=True)
    finally:
        compiled.unlink(missing_ok=True)


def timed_edit(
    call: Callable[[], str],
    root: Path,
    term: str,
    snapshot: Path | None,
    repetitions: int,
    *,
    refresh: bool,
) -> dict[str, Any]:
    durations: list[float] = []
    contexts: list[str] = []
    target = direct_target(root, term)
    original = target.read_text(encoding="utf-8")
    for _ in range(repetitions):
        start = time.perf_counter_ns()
        context = call()
        durations.append((time.perf_counter_ns() - start) / 1_000_000)
        contexts.append(context)
        # Reset is harness setup and deliberately excluded from the measured
        # alteration interval. Refresh after reset keeps the next repetition
        # on the same generation and prevents stale-source false positives.
        target.write_text(original, encoding="utf-8")
        if refresh and snapshot is not None:
            build_snapshot(root, snapshot)
    return {
        "repetitions": repetitions,
        "wall_ms": {
            "median": statistics.median(durations),
            "p95": sorted(durations)[max(0, math.ceil(repetitions * 0.95) - 1)],
            "p99": sorted(durations)[max(0, math.ceil(repetitions * 0.99) - 1)],
            "samples": durations,
        },
        "estimated_input_tokens": sum(estimate_tokens(context) for context in contexts),
        "context_bytes": sum(len(context.encode("utf-8")) for context in contexts),
        "token_measurement": "whitespace-v1-estimate",
        "operation": "locate+edit" + ("+py_compile" if target.suffix == ".py" else "") + ("+refresh" if refresh else ""),
    }


def direct_edit(root: Path, term: str) -> str:
    context = direct_context(root, term)
    apply_deterministic_change(direct_target(root, term))
    return context


def fast_edit(root: Path, snapshot: Path, term: str, *, refresh: bool) -> str:
    with Snapshot(snapshot) as opened:
        spans = opened.context(root, term, max_results=1, max_bytes=64_000)
        if not spans:
            raise LookupError(f"Fast target not found: {term}")
        context = spans[0].content
        target = root / spans[0].file
    apply_deterministic_change(target)
    if refresh:
        build_snapshot(root, snapshot)
    return context


def delivery_scenarios(
    root: Path, snapshot: Path, term: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = direct_target(root, term)
    original = target.read_bytes()
    source_lines = original.decode("utf-8").splitlines()
    return_line = next(
        index
        for index, line in enumerate(source_lines, start=1)
        if "return value" in line
    )
    changeset = {
        "schema": "simplicio.fast.changeset/v2",
        "changes": [
            {
                "path": target.name,
                "expected_sha256": hashlib.sha256(original).hexdigest(),
                "replacements": [
                    {
                        "start_line": return_line,
                        "end_line": return_line,
                        "content": source_lines[return_line - 1].replace(
                            "return value", "return value + 1"
                        ),
                    }
                ],
            }
        ],
    }
    selection = select_engine("python").receipt()
    engine = DeliveryEngine(root, snapshot)
    full = engine.deliver(
        changeset,
        profile="full",
        engine_receipt=selection,
        write=True,
        idempotency_key="benchmark-full",
    )
    loop = engine.deliver(
        changeset,
        profile="loop-standalone",
        engine_receipt=selection,
        write=True,
        idempotency_key="benchmark-loop",
    )
    full["operation"] = "full-runtime-delivery"
    loop["operation"] = "simplicio-loop-delivery"
    return full, loop


def rust_context(root: Path, snapshot: Path, term: str, executable: Path) -> str:
    completed = subprocess.run(
        [
            str(executable),
            "--context",
            str(snapshot),
            str(root),
            term,
            "--limit",
            "10",
            "--max-bytes",
            "64_000",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Rust context failed ({completed.returncode}): {detail}")
    payload = json.loads(completed.stdout)
    return "\n".join(span["content"] for span in payload.get("spans", []))


def resident_rust_context(
    session: RustCoreSession, root: Path, snapshot: Path, term: str
) -> str:
    payload = session.call(
        "context",
        {
            "snapshot": str(snapshot),
            "root": str(root),
            "term": term,
            "limit": 10,
            "max_lines": 120,
            "max_bytes": 64_000,
            "max_tokens": 8_000,
        },
    )
    return "\n".join(span["content"] for span in payload.get("spans", []))


def timed(call: Callable[[], str], repetitions: int) -> dict[str, Any]:
    durations: list[float] = []
    bytes_seen = 0
    tokens = 0
    for _ in range(repetitions):
        start = time.perf_counter_ns()
        context = call()
        durations.append((time.perf_counter_ns() - start) / 1_000_000)
        bytes_seen += len(context.encode("utf-8"))
        tokens += estimate_tokens(context)
    return {
        "repetitions": repetitions,
        "wall_ms": {
            "median": statistics.median(durations),
            "p95": sorted(durations)[max(0, math.ceil(repetitions * 0.95) - 1)],
            "p99": sorted(durations)[max(0, math.ceil(repetitions * 0.99) - 1)],
            "samples": durations,
        },
        "context_bytes": bytes_seen,
        "estimated_input_tokens": tokens,
        "token_measurement": "whitespace-v1-estimate",
    }


def run(
    *,
    files: int,
    functions: int,
    repetitions: int,
    rust_executable: Path | None = None,
    resident_executable: Path | None = None,
    compact_symbols: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-bench-") as directory:
        root = Path(directory)
        make_workload(
            root,
            files=files,
            functions=functions,
            compact_symbols=compact_symbols,
        )
        term = f"task_{min(7, functions - 1)}"
        corpus_digest = corpus_sha256(root)
        source_commit, source_commit_reason = source_commit_receipt()
        repetition_order = list(range(1, repetitions + 1))
        random.Random(163).shuffle(repetition_order)
        source_bytes = sum(path.stat().st_size for path in _source_paths(root))
        baseline_scan = timed(lambda: direct_context(root, term), repetitions)
        baseline_ast = timed(lambda: ast_context(root, term), repetitions)

        snapshot = root / "project.sfast"
        build_start = time.perf_counter_ns()
        build = build_snapshot(root, snapshot)
        build_wall_ms = (time.perf_counter_ns() - build_start) / 1_000_000
        with Snapshot(snapshot) as opened:
            fast = timed(
                lambda: "\n".join(
                    span.content
                    for span in opened.context(
                        root, term, max_results=files, max_bytes=64_000
                    )
                ),
                repetitions,
            )

        alteration_without_fast = timed_edit(
            lambda: direct_edit(root, term),
            root,
            term,
            None,
            repetitions,
            refresh=False,
        )
        alteration_fast = timed_edit(
            lambda: fast_edit(root, snapshot, term, refresh=False),
            root,
            term,
            snapshot,
            repetitions,
            refresh=False,
        )
        alteration_fast_refresh = timed_edit(
            lambda: fast_edit(root, snapshot, term, refresh=True),
            root,
            term,
            snapshot,
            repetitions,
            refresh=True,
        )
        if rust_executable is not None and rust_executable.is_file():
            rust_standalone = timed(
                lambda: rust_context(root, snapshot, term, rust_executable), repetitions
            )
            rust_standalone["status"] = "complete"
            rust_standalone["operation"] = "rust-standalone-subprocess-context"
        else:
            rust_standalone = {
                "status": "blocked",
                "reason": "rust_executable_missing",
                "repetitions": repetitions,
                "operation": "rust-standalone-subprocess-context",
            }
        if resident_executable is not None and resident_executable.is_file():
            try:
                with RustCoreSession(resident_executable) as session:
                    session.call("stats", {"snapshot": str(snapshot)})
                    resident_rust = timed(
                        lambda: resident_rust_context(session, root, snapshot, term),
                        repetitions,
                    )
                    resident_rust["status"] = "complete"
                    resident_rust["operation"] = "rust-resident-session-context"
                    resident_rust["session_metrics"] = session.metrics()
            except (RustSessionError, OSError) as error:
                resident_rust = {
                    "status": "blocked",
                    "reason": type(error).__name__,
                    "operation": "rust-resident-session-context",
                }
        else:
            resident_rust = {
                "status": "blocked",
                "reason": "resident_executable_missing",
                "repetitions": repetitions,
                "operation": "rust-resident-session-context",
            }
        full_standalone, loop_standalone = delivery_scenarios(root, snapshot, term)

        baseline_scan_total = sum(baseline_scan["wall_ms"]["samples"])
        baseline_ast_total = sum(baseline_ast["wall_ms"]["samples"])
        fast_total = build_wall_ms + sum(fast["wall_ms"]["samples"])
        token_saved = (
            baseline_ast["estimated_input_tokens"] - fast["estimated_input_tokens"]
        )
        return {
            "schema": SCHEMA,
            "status": "partial"
            if any(
                item.get("status") == "blocked"
                for item in (
                    rust_standalone,
                    resident_rust,
                    full_standalone,
                    loop_standalone,
                )
            )
            else "complete",
            "workload": {
                "files": files,
                "functions_per_file": functions,
                "term": term,
                "compact_symbols": compact_symbols,
            },
            "environment": environment_receipt(),
            "provenance": {
                "source_commit": source_commit,
                "source_commit_reason": source_commit_reason,
                "corpus_sha256": corpus_digest,
                "repetition_order": repetition_order,
                "warmup_repetitions": 0,
            },
            "source_bytes": source_bytes,
            "build": {"wall_ms": build_wall_ms, "metrics": asdict(build)},
            "scenarios": {
                "without_fast_scan": baseline_scan,
                "without_fast_ast_reparse": baseline_ast,
                "fast_python": fast,
                "without_fast_alteration": alteration_without_fast,
                "fast_python_alteration": alteration_fast,
                "fast_python_alteration_refresh": alteration_fast_refresh,
                "fast_rust_standalone": rust_standalone,
                "fast_rust_resident": resident_rust,
                "full_standalone": full_standalone,
                "loop_standalone": loop_standalone,
            },
            "totals": {
                "without_fast_scan_wall_ms": baseline_scan_total,
                "without_fast_ast_reparse_wall_ms": baseline_ast_total,
                "fast_python_wall_ms": fast_total,
                "speedup_vs_scan": baseline_scan_total / fast_total
                if fast_total
                else None,
                "speedup_vs_ast_reparse": baseline_ast_total / fast_total
                if fast_total
                else None,
                "estimated_tokens_without_fast": baseline_ast["estimated_input_tokens"],
                "estimated_tokens_fast": fast["estimated_input_tokens"],
                "estimated_tokens_saved": token_saved,
                "estimated_token_savings_percent": (
                    token_saved / baseline_ast["estimated_input_tokens"] * 100
                    if baseline_ast["estimated_input_tokens"]
                    else None
                ),
                "without_fast_alteration_wall_ms": sum(
                    alteration_without_fast["wall_ms"]["samples"]
                ),
                "fast_python_alteration_wall_ms": sum(
                    alteration_fast["wall_ms"]["samples"]
                ),
                "fast_python_alteration_refresh_wall_ms": sum(
                    alteration_fast_refresh["wall_ms"]["samples"]
                ),
                "alteration_speedup_hot": (
                    sum(alteration_without_fast["wall_ms"]["samples"])
                    / sum(alteration_fast["wall_ms"]["samples"])
                    if sum(alteration_fast["wall_ms"]["samples"])
                    else None
                ),
                "alteration_speedup_with_refresh": (
                    sum(alteration_without_fast["wall_ms"]["samples"])
                    / sum(alteration_fast_refresh["wall_ms"]["samples"])
                    if sum(alteration_fast_refresh["wall_ms"]["samples"])
                    else None
                ),
                "alteration_estimated_tokens_without_fast": alteration_without_fast[
                    "estimated_input_tokens"
                ],
                "alteration_estimated_tokens_fast": alteration_fast[
                    "estimated_input_tokens"
                ],
                "rust_standalone_wall_ms": (
                    sum(rust_standalone["wall_ms"]["samples"])
                    if rust_standalone.get("status") == "complete"
                    else None
                ),
                "rust_standalone_speedup_vs_python": (
                    fast_total / sum(rust_standalone["wall_ms"]["samples"])
                    if rust_standalone.get("status") == "complete"
                    and sum(rust_standalone["wall_ms"]["samples"])
                    else None
                ),
                "rust_resident_wall_ms": (
                    sum(resident_rust["wall_ms"]["samples"])
                    if resident_rust.get("status") == "complete"
                    else None
                ),
                "rust_resident_speedup_vs_python": (
                    fast_total / sum(resident_rust["wall_ms"]["samples"])
                    if resident_rust.get("status") == "complete"
                    and sum(resident_rust["wall_ms"]["samples"])
                    else None
                ),
            },
            "limitations": [
                "Rust standalone measures the real subprocess/IPC context path over a Python-built snapshot; it does not measure Rust snapshot construction.",
                "Full delivery is measured fail-closed until Runtime authorization; Loop standalone uses the real Dev CLI adapter.",
                "Token counts use whitespace-v1 estimates, not provider billing telemetry.",
            ],
        }


def markdown_report(result: dict[str, Any]) -> str:
    totals = result["totals"]
    return "\n".join(
        [
            "# Fast versus baseline benchmark",
            "",
            f"- Workload: {result['workload']['files']} files × {result['workload']['functions_per_file']} functions",
            f"- Repetitions: {result['scenarios']['without_fast_scan']['repetitions']}",
            f"- Build wall time: {result['build']['wall_ms']:.3f} ms",
            f"- Baseline scan total wall time: {totals['without_fast_scan_wall_ms']:.3f} ms",
            f"- Baseline AST-reparse total wall time: {totals['without_fast_ast_reparse_wall_ms']:.3f} ms",
            f"- Fast Python total wall time: {totals['fast_python_wall_ms']:.3f} ms",
            f"- Speedup versus scan: {totals['speedup_vs_scan']:.3f}x",
            f"- Speedup versus AST reparse: {totals['speedup_vs_ast_reparse']:.3f}x",
            f"- Estimated input tokens without Fast: {totals['estimated_tokens_without_fast']}",
            f"- Estimated input tokens with Fast: {totals['estimated_tokens_fast']}",
            f"- Estimated tokens saved: {totals['estimated_tokens_saved']} ({totals['estimated_token_savings_percent']:.2f}%)",
            f"- Baseline alteration total wall time: {totals['without_fast_alteration_wall_ms']:.3f} ms",
            f"- Fast hot alteration total wall time: {totals['fast_python_alteration_wall_ms']:.3f} ms",
            f"- Fast alteration + refresh total wall time: {totals['fast_python_alteration_refresh_wall_ms']:.3f} ms",
            f"- Alteration speedup (hot): {totals['alteration_speedup_hot']:.3f}x",
            f"- Alteration speedup (with refresh): {totals['alteration_speedup_with_refresh']:.3f}x",
            f"- Alteration estimated tokens without Fast: {totals['alteration_estimated_tokens_without_fast']}",
            f"- Alteration estimated tokens with Fast: {totals['alteration_estimated_tokens_fast']}",
            f"- Rust standalone status: {result['scenarios']['fast_rust_standalone']['status']}",
            f"- Rust standalone total wall time: {totals['rust_standalone_wall_ms'] if totals['rust_standalone_wall_ms'] is not None else 'n/a'} ms",
            f"- Rust standalone speedup versus Python Fast: {totals['rust_standalone_speedup_vs_python'] if totals['rust_standalone_speedup_vs_python'] is not None else 'n/a'}x",
            f"- Full standalone status: {result['scenarios']['full_standalone']['status']} ({', '.join(result['scenarios']['full_standalone'].get('reason_codes', [])) or 'none'})",
            f"- Full delivery wall time: {result['scenarios']['full_standalone'].get('timings', {}).get('delivery_wall_ms', 'n/a')} ms",
            f"- Loop standalone status: {result['scenarios']['loop_standalone']['status']} ({', '.join(result['scenarios']['loop_standalone'].get('reason_codes', [])) or 'none'})",
            f"- Loop delivery wall time: {result['scenarios']['loop_standalone'].get('timings', {}).get('delivery_wall_ms', 'n/a')} ms",
            "",
            "Token values use `whitespace-v1-estimate`; they are not provider billing telemetry.",
            "Rust standalone is a real subprocess/IPC read over a Python-built snapshot; it is not an end-to-end Rust build measurement.",
            "Full delivery is measured fail-closed without Runtime authorization; Loop standalone is a real local delivery through the Dev CLI adapter.",
            "Alteration is a deterministic local fixture (locate + edit + py_compile), not an LLM/provider delivery run.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=50)
    parser.add_argument("--functions", type=int, default=20)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--json-out")
    parser.add_argument("--markdown-out")
    parser.add_argument("--rust-executable", type=Path)
    args = parser.parse_args()
    if min(args.files, args.functions, args.repetitions) < 1:
        parser.error("files, functions and repetitions must be positive")
    result = run(
        files=args.files,
        functions=args.functions,
        repetitions=args.repetitions,
        rust_executable=args.rust_executable,
    )
    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.json_out:
        Path(args.json_out).write_text(payload + "\n", encoding="utf-8")
    if args.markdown_out:
        Path(args.markdown_out).write_text(markdown_report(result), encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
