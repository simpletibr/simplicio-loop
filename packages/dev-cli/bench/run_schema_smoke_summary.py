"""Summarize schema-smoke JSON artifacts for issue #46.

This is an incremental report. It normalizes existing and future smoke outputs
without downloading models or claiming that the full GGUF quant curve is done.
"""

from __future__ import annotations

import argparse
import glob
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RESULTS_JSON = ROOT / "bench" / "results_v14_schema_smoke_summary.json"
RESULTS_MD = ROOT / "bench" / "results_v14_schema_smoke_summary.md"
REQUIRED_QUANT_SMOKES = ("Q8_0", "Q6_K", "Q4_K_M")
QWEN15B_QUANT_CURVE_ARTIFACTS = (
    ROOT / "bench" / "results_v14_qwen15b_quant_curve.json",
    ROOT / "bench" / "results_v14_qwen15b_quant_curve.md",
    ROOT / "bench" / "results_v14_qwen15b_quant_curve.pdf",
)


def summarize_smokes(inputs: list[Path]) -> dict[str, Any]:
    rows = []
    for path in sorted({item.resolve() for item in inputs if item.is_file()}):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(_normalize(path, payload))
    qwen15b_rows = [
        row
        for row in rows
        if "qwen" in row["model"].lower()
        and ("1.5" in row["model"].lower() or "15b" in row["source"].lower())
    ]
    required_quant_smokes_present = {
        quant: any(row["quant"] == quant for row in qwen15b_rows)
        for quant in REQUIRED_QUANT_SMOKES
    }
    required_quant_smokes_passed = {
        quant: any(
            row["quant"] == quant and row["go_no_go_pass"] is True
            for row in qwen15b_rows
        )
        for quant in REQUIRED_QUANT_SMOKES
    }
    missing_quant_smokes = [
        quant for quant, present in required_quant_smokes_present.items() if not present
    ]
    failed_required_quant_smokes = [
        quant
        for quant, present in required_quant_smokes_present.items()
        if present and not required_quant_smokes_passed[quant]
    ]
    qwen15b_quant_curve_complete = not missing_quant_smokes and all(
        path.exists() for path in QWEN15B_QUANT_CURVE_ARTIFACTS
    )
    return {
        "benchmark": "schema-smoke-summary",
        "issue": 46,
        "scope": (
            "incremental schema-smoke artifact summary; this does not replace "
            "the required Qwen2.5-Coder-1.5B GGUF quant curve"
        ),
        "date": time.strftime("%Y-%m-%d"),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "rows": rows,
        "summary": {
            "input_files": len(rows),
            "go_no_go_passes": sum(1 for row in rows if row["go_no_go_pass"] is True),
            "go_no_go_failures": sum(1 for row in rows if row["go_no_go_pass"] is False),
            "qwen15b_smokes": len(qwen15b_rows),
            "required_quant_smokes_present": required_quant_smokes_present,
            "required_quant_smokes_passed": required_quant_smokes_passed,
            "missing_quant_smokes": missing_quant_smokes,
            "failed_required_quant_smokes": failed_required_quant_smokes,
            "qwen15b_quant_curve_complete": qwen15b_quant_curve_complete,
            "release_ready": False,
            "missing_release_evidence": _missing_release_evidence(
                missing_quant_smokes
            ),
        },
    }


def _missing_release_evidence(missing_quant_smokes: list[str]) -> list[str]:
    missing = []
    if missing_quant_smokes:
        missing.append(
            "Q8_0/Q6_K/Q4_K_M schema-v1 smoke JSONs for the named GGUF model"
        )
    if not all(path.exists() for path in QWEN15B_QUANT_CURVE_ARTIFACTS):
        missing.append("bench/results_v14_qwen15b_quant_curve.{md,json,pdf}")
    return missing


def _normalize(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("benchmark") == "schema-v1-smoke":
        calls = int(payload.get("calls") or 0)
        parse_ok = int((payload.get("summary") or {}).get("parse_ok") or 0)
        parse_failed = int((payload.get("summary") or {}).get("parse_failed") or 0)
        criterion_pass = bool((payload.get("go_no_go") or {}).get("pass"))
        return _row(
            path,
            payload,
            calls=calls,
            parse_ok=parse_ok,
            parse_failed=parse_failed,
            go_no_go_pass=criterion_pass,
            format="schema-v1-smoke",
        )

    if "parse_ok_count" in payload:
        calls = int(payload.get("N") or 0)
        parse_ok = int(payload.get("parse_ok_count") or 0)
        parse_failed = int(payload.get("parse_failed_count") or max(0, calls - parse_ok))
        return _row(
            path,
            payload,
            calls=calls,
            parse_ok=parse_ok,
            parse_failed=parse_failed,
            go_no_go_pass=_passes_smoke(parse_ok, calls),
            format="legacy-flat",
        )

    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if "parse_ok" in result:
        parse_ok = int(result.get("parse_ok") or 0)
        parse_failed = int(result.get("parse_fail") or 0)
        calls = parse_ok + parse_failed
        return _row(
            path,
            payload,
            calls=calls,
            parse_ok=parse_ok,
            parse_failed=parse_failed,
            go_no_go_pass=_passes_smoke(parse_ok, calls),
            format="legacy-escalation",
        )

    return _row(
        path,
        payload,
        calls=0,
        parse_ok=0,
        parse_failed=0,
        go_no_go_pass=False,
        format="unknown",
    )


def _row(
    path: Path,
    payload: dict[str, Any],
    *,
    calls: int,
    parse_ok: int,
    parse_failed: int,
    go_no_go_pass: bool,
    format: str,
) -> dict[str, Any]:
    return {
        "source": _relative(path),
        "format": format,
        "model": str(payload.get("model") or payload.get("model_spec") or "unknown"),
        "quant": _quant_from_payload_or_path(path, payload),
        "calls": calls,
        "parse_ok": parse_ok,
        "parse_failed": parse_failed,
        "parse_ok_rate": round(parse_ok / max(calls, 1), 4),
        "go_no_go_pass": go_no_go_pass,
    }


def _quant_from_payload_or_path(path: Path, payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("quant"),
        payload.get("model"),
        payload.get("model_spec"),
        path.name,
    ]
    for candidate in candidates:
        value = str(candidate or "").upper()
        for quant in REQUIRED_QUANT_SMOKES:
            if quant in value:
                return quant
    return "unknown"


def _passes_smoke(parse_ok: int, calls: int) -> bool:
    return parse_ok >= max(1, (calls + 1) // 2)


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def default_inputs() -> list[Path]:
    patterns = [
        ROOT / "bench" / "*smoke*_schema*.json",
        ROOT / "bench" / "*schema*_smoke*.json",
        ROOT / "bench" / "results_v14_qwen15b_*_smoke_schema_v1.json",
    ]
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(Path(item) for item in glob.glob(str(pattern)))
    output_paths = {RESULTS_JSON.resolve(), RESULTS_MD.resolve()}
    return [path for path in paths if path.resolve() not in output_paths]


def write_reports(summary: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_to_markdown(summary), encoding="utf-8")


def _to_markdown(summary: dict[str, Any]) -> str:
    meta = summary["summary"]
    lines = [
        "# Schema Smoke Summary",
        "",
        summary["scope"],
        "",
        "## Summary",
        "",
        f"- input files: {meta['input_files']}",
        f"- go/no-go passes: {meta['go_no_go_passes']}",
        f"- go/no-go failures: {meta['go_no_go_failures']}",
        f"- Qwen 1.5B smokes: {meta['qwen15b_smokes']}",
        "- required quant smokes present: "
        + ", ".join(
            f"{quant}={present}"
            for quant, present in meta["required_quant_smokes_present"].items()
        ),
        "- required quant smokes passed: "
        + ", ".join(
            f"{quant}={passed}"
            for quant, passed in meta["required_quant_smokes_passed"].items()
        ),
        f"- missing quant smokes: {', '.join(meta['missing_quant_smokes']) or 'none'}",
        "- failed required quant smokes: "
        + (", ".join(meta["failed_required_quant_smokes"]) or "none"),
        f"- Qwen 1.5B quant curve complete: {meta['qwen15b_quant_curve_complete']}",
        f"- release ready: {meta['release_ready']}",
        "",
        "## Rows",
        "",
        "| source | model | quant | parse ok | calls | go/no-go |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in summary["rows"]:
        lines.append(
            f"| `{row['source']}` | {row['model']} | {row['quant']} | "
            f"{row['parse_ok']} | {row['calls']} | {row['go_no_go_pass']} |"
        )
    lines.extend(["", "## Missing Release Evidence", ""])
    if meta["missing_release_evidence"]:
        for item in meta["missing_release_evidence"]:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="*", default=None)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--fail-missing-required-quants",
        action="store_true",
        help="Return exit code 1 if Q8_0/Q6_K/Q4_K_M Qwen 1.5B smokes are missing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inputs = args.inputs if args.inputs is not None else default_inputs()
    summary = summarize_smokes(inputs)
    write_reports(summary, args.json_output, args.md_output)
    if not args.quiet:
        print(json.dumps(summary["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
    if (
        args.fail_missing_required_quants
        and (
            summary["summary"]["missing_quant_smokes"]
            or summary["summary"]["failed_required_quant_smokes"]
        )
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
