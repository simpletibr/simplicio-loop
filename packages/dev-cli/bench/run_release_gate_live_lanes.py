"""Preflight and optional tiny probes for #114/#121 live release lanes.

This harness does not pretend the full release gate is green. It inventories
the live lanes that complement the deterministic PLANES corpus and classifies
each lane as measured / ready / blocked with concrete evidence:

* shell-out lanes (`codex-cli/...`, `claude-cli/...`) can be probed with a
  one-line read-only prompt that should return `OK` when the lane is usable;
* API lanes are marked ready only when the required credential env var exists;
* the GPT-5.4 medium Codex lane is always listed explicitly because the
  deterministic corpus names it as missing release evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

RESULTS_JSON = ROOT / "bench" / "results_release_gate_live_lanes.json"
RESULTS_MD = ROOT / "bench" / "results_release_gate_live_lanes.md"
PLANES_CASE_ID = "planes-ordering"


@dataclass(frozen=True)
class LaneSpec:
    lane_id: str
    route: str
    provider: str
    model: str
    kind: str
    env_key: str | None = None
    binary: str | None = None
    issue_refs: tuple[str, ...] = ("#114", "#121")


LANES: tuple[LaneSpec, ...] = (
    LaneSpec(
        lane_id="codex-gpt-5.4-medium",
        route="codex-cli/gpt-5.4-medium",
        provider="codex-cli",
        model="gpt-5.4-medium",
        kind="shell-out",
        binary="codex",
    ),
    LaneSpec(
        lane_id="codex-default",
        route="codex-cli/default",
        provider="codex-cli",
        model="default",
        kind="shell-out",
        binary="codex",
    ),
    LaneSpec(
        lane_id="claude-default",
        route="claude-cli/default",
        provider="claude-cli",
        model="default",
        kind="shell-out",
        binary="claude",
    ),
    LaneSpec(
        lane_id="openai-gpt-5.4",
        route="openai/gpt-5.4",
        provider="openai",
        model="gpt-5.4",
        kind="api",
        env_key="OPENAI_API_KEY",
    ),
    LaneSpec(
        lane_id="anthropic-claude-opus-4.7",
        route="anthropic/claude-opus-4-7",
        provider="anthropic",
        model="claude-opus-4-7",
        kind="api",
        env_key="ANTHROPIC_API_KEY",
    ),
    LaneSpec(
        lane_id="deepseek-v3.1",
        route="deepseek-hf/deepseek-ai/DeepSeek-V3.1",
        provider="deepseek-hf",
        model="deepseek-ai/DeepSeek-V3.1",
        kind="api",
        env_key="HF_TOKEN",
    ),
)


def run_lane_report(
    *,
    probe_shell_outs: bool = False,
    shell_out_timeout_seconds: int = 45,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    rows = [
        _inspect_lane(
            lane,
            probe_shell_outs=probe_shell_outs,
            shell_out_timeout_seconds=shell_out_timeout_seconds,
            runner=runner,
        )
        for lane in LANES
    ]
    summary = _summarize(rows)
    return {
        "benchmark": "release-gate-live-lanes",
        "schema": "simplicio.dev-cli.release-gate-live-lanes/v1",
        "date": time.strftime("%Y-%m-%d"),
        "proof_kind": "preflight-plus-tiny-probes",
        "scope": (
            "live-lane readiness companion to the deterministic PLANES release "
            "gate for #114/#121; does not claim release readiness by itself"
        ),
        "planes_case_id": PLANES_CASE_ID,
        "probe_shell_outs": probe_shell_outs,
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "lanes": rows,
        "summary": summary,
    }


def _inspect_lane(
    lane: LaneSpec,
    *,
    probe_shell_outs: bool,
    shell_out_timeout_seconds: int,
    runner: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "lane_id": lane.lane_id,
        "route": lane.route,
        "provider": lane.provider,
        "model": lane.model,
        "kind": lane.kind,
        "issue_refs": list(lane.issue_refs),
        "planes_case_id": PLANES_CASE_ID,
        "status": "blocked",
        "evidence_class": "blocked",
        "available": False,
        "credential_present": None,
        "binary_on_path": None,
        "measured": False,
        "command": None,
        "notes": [],
    }
    if lane.kind == "api":
        present = bool(lane.env_key and os.environ.get(lane.env_key))
        row["credential_present"] = present
        row["status"] = "ready" if present else "blocked"
        row["evidence_class"] = "ready" if present else "blocked"
        row["available"] = present
        row["notes"].append(
            f"{lane.env_key} {'present' if present else 'missing'}"
        )
        return row

    binary_path = shutil.which(str(lane.binary))
    row["binary_on_path"] = binary_path
    row["available"] = binary_path is not None
    if binary_path is None:
        row["status"] = "blocked"
        row["evidence_class"] = "blocked"
        row["notes"].append(f"{lane.binary} not found on PATH")
        return row
    if not probe_shell_outs:
        row["status"] = "ready"
        row["evidence_class"] = "ready"
        row["notes"].append("binary found; shell-out probe not requested")
        return row

    probe = _probe_shell_out_lane(
        lane,
        executable=binary_path,
        timeout_seconds=shell_out_timeout_seconds,
        runner=runner,
    )
    row.update(probe)
    return row


def _probe_shell_out_lane(
    lane: LaneSpec,
    *,
    executable: str,
    timeout_seconds: int,
    runner: Any,
) -> dict[str, Any]:
    if lane.provider == "codex-cli":
        cmd = [
            executable,
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "-C",
            str(ROOT),
        ]
        if lane.model != "default":
            cmd.extend(["--model", lane.model])
        cmd.append("Reply with exactly OK.")
    elif lane.provider == "claude-cli":
        cmd = [executable, "-p", "Reply with exactly OK.", "--output-format", "json"]
        if lane.model != "default":
            cmd.extend(["--model", lane.model])
    else:
        raise ValueError(f"unsupported shell-out provider: {lane.provider}")

    use_shell = os.name == "nt" and executable.lower().endswith((".cmd", ".bat"))
    command: list[str] | str
    if use_shell:
        command = subprocess.list2cmdline(cmd)
    else:
        command = cmd

    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=ROOT,
            shell=use_shell,
        )
    except OSError as exc:
        return {
            "status": "blocked",
            "evidence_class": "blocked",
            "available": False,
            "measured": True,
            "command": command,
            "probe_returncode": None,
            "probe_stdout_tail": "",
            "probe_stderr_tail": "",
            "notes": [f"probe launcher error: {exc}"],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "blocked",
            "evidence_class": "blocked",
            "measured": True,
            "command": command,
            "probe_returncode": None,
            "probe_stdout_tail": _tail_text(exc.stdout),
            "probe_stderr_tail": _tail_text(exc.stderr),
            "notes": [f"probe timed out after {timeout_seconds}s"],
        }

    stdout_tail = _tail_text(completed.stdout)
    stderr_tail = _tail_text(completed.stderr)
    ok = completed.returncode == 0 and "OK" in (completed.stdout or "")
    notes = []
    if ok:
        status = "measured"
        evidence_class = "measured"
        available = True
        notes.append("tiny read-only probe returned OK")
    else:
        status = "blocked"
        evidence_class = "blocked"
        available = False
        notes.append("tiny read-only probe did not return OK")
    return {
        "status": status,
        "evidence_class": evidence_class,
        "available": available,
        "measured": True,
        "command": command,
        "probe_returncode": completed.returncode,
        "probe_stdout_tail": stdout_tail,
        "probe_stderr_tail": stderr_tail,
        "notes": notes,
    }


def _tail_text(text: Any, *, limit: int = 1200) -> str:
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    data = str(text)
    return data[-limit:]


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "measured": sum(1 for row in rows if row["status"] == "measured"),
        "ready": sum(1 for row in rows if row["status"] == "ready"),
        "blocked": sum(1 for row in rows if row["status"] == "blocked"),
    }
    gpt54 = next(row for row in rows if row["lane_id"] == "codex-gpt-5.4-medium")
    return {
        "lane_count": len(rows),
        "measured_count": counts["measured"],
        "ready_count": counts["ready"],
        "blocked_count": counts["blocked"],
        "gpt_5_4_medium": {
            "status": gpt54["status"],
            "available": gpt54["available"],
            "measured": gpt54["measured"],
        },
        "release_ready": False,
        "missing_release_evidence": [
            "full live PLANES execution receipts across the allowed provider matrix",
            "runtime+loop+dev-cli cross-repo receipts",
            "Windows/Linux live matrix",
        ],
    }


def write_reports(result: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        "# Release Gate Live Lanes",
        "",
        result["scope"],
        "",
        f"- PLANES case: `{result['planes_case_id']}`",
        f"- probe shell-outs: `{result['probe_shell_outs']}`",
        f"- measured lanes: {result['summary']['measured_count']}",
        f"- ready lanes: {result['summary']['ready_count']}",
        f"- blocked lanes: {result['summary']['blocked_count']}",
        "",
        "| lane | route | kind | status | available | measured |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in result["lanes"]:
        lines.append(
            f"| {row['lane_id']} | `{row['route']}` | {row['kind']} | "
            f"{row['status']} | {row['available']} | {row['measured']} |"
        )
    lines.extend(["", "## Missing Release Evidence", ""])
    for item in result["summary"]["missing_release_evidence"]:
        lines.append(f"- {item}")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-shell-outs", action="store_true")
    parser.add_argument("--shell-out-timeout-seconds", type=int, default=45)
    parser.add_argument("--json-output", type=Path, default=RESULTS_JSON)
    parser.add_argument("--md-output", type=Path, default=RESULTS_MD)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_lane_report(
        probe_shell_outs=args.probe_shell_outs,
        shell_out_timeout_seconds=args.shell_out_timeout_seconds,
    )
    write_reports(result, args.json_output, args.md_output)
    if not args.quiet:
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        print(f"wrote {args.json_output}")
        print(f"wrote {args.md_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
