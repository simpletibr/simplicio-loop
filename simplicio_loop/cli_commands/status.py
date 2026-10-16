"""`status`, `progress`, `preflight` and `verify`: run state and gates.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
import json
import sys

from ._base import impl

from ..json_order import stable_first

def verify(repo: str, run_id: str) -> int:
    from ..runner import verify_run
    payload = verify_run(repo, run_id)
    print(json.dumps(stable_first(payload), ensure_ascii=False, indent=2))
    return 0 if payload["state"].get("phase") == "done" else 1


def _render_status_text(payload: dict) -> str:
    """Human-readable one-screen summary of a run status payload."""
    state = payload.get("state") or {}
    lines = ["simplicio-loop run status", ""]
    run_dir = payload.get("run_dir", "")
    if run_dir:
        lines.append(f"run_dir: {run_dir}")
    completion = state.get("completion") or {}
    lines.append(f"phase: {state.get('phase', 'UNKNOWN')}")
    lines.append(f"completion_tag: {completion.get('tag', 'UNVERIFIED')}")
    coverage = completion.get("coverage")
    if coverage:
        lines.append(f"coverage: {coverage}")
    delivery = state.get("delivery") or {}
    lines.append(f"delivery_ready: {delivery.get('ready', False)}")
    route = payload.get("execution_route") or state.get("execution_route") or {}
    lines.append(f"execution_route: {route.get('route', 'UNVERIFIED')}")
    lines.append(f"route_receipt_sha: {route.get('receipt_sha', '') or 'UNVERIFIED'}")
    lines.append(f"route_backend: {route.get('backend', 'UNVERIFIED')}")
    return "\n".join(lines) + "\n"


def status(repo: str, run_id: str, as_json: bool = False, as_text: bool = False) -> int:
    try:
        payload = impl().read_status(repo, run_id)
        if (payload.get("state") or {}).get("phase") == "no_runs":
            payload.update({"schema": "simplicio.status/v1", "status": "UNVERIFIED",
                            "reason_code": "run_missing"})
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        payload = {"schema": "simplicio.status/v1", "status": "UNVERIFIED",
                   "reason_code": "run_missing", "error": str(exc)}
    # Default remains JSON (backwards-compatible). --text opts into the human summary.
    if as_text and not as_json:
        print(_render_status_text(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def preflight(repo: str, as_json: bool = False, *, strict: bool = False) -> int:
    """Verify the bound operators (mapper, dev-cli).

    Under ``--strict`` / ``SIMPLICIO_LOOP_STRICT=1`` hand-edit is reported as
    forbidden.

    Returns exit 0 when all *required* operators are present, 1 otherwise.
    """
    import os as _os

    from ..finding_router import route_finding as _route_finding
    from ..strict_mode import preflight_payload, recommended_env

    repo_path = Path(repo).resolve()
    if strict:
        _os.environ["SIMPLICIO_LOOP_STRICT"] = "1"
    from .. import version_drift

    payload = preflight_payload(str(repo_path), strict=strict)
    all_present = bool(payload.get("all_present"))
    missing = list(payload.get("missing_operators") or [])
    drift = version_drift.check(version_drift.running_version(), repo=repo_path)
    if drift is not None:
        payload["version_drift"] = drift
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("simplicio-loop preflight" + (" [STRICT]" if payload.get("strict") else ""))
        required = set(payload.get("required_operators") or [])
        for op in payload.get("operators") or []:
            name = op.get("name", "")
            present = bool(op.get("present"))
            if present:
                mark = "OK "
            elif name in required or name in {"simplicio-mapper", "simplicio-dev-cli"}:
                mark = "MISSING"
            else:
                mark = "OPTIONAL"
            ver = f" ({op['version']})" if op.get("version") else ""
            extra = ""
            if name == "simplicio-dev-cli" and op.get("resolved_as"):
                extra = f" via {op['resolved_as']}"
            print(f"  [{mark}] {name}{ver}{extra}")
        print("  all_present: true" if all_present else "  NOT ALL REQUIRED OPERATORS PRESENT")
        print(f"  execution_profile: {payload.get('execution_profile')}")
        print(f"  hand_edit_forbidden: {payload.get('hand_edit_forbidden')}")
        if payload.get("strict"):
            print("  recommended_env:")
            for key, value in (recommended_env() or {}).items():
                print(f"    {key}={value}")
        drift_line = version_drift.format_line(drift)
        if drift_line:
            print(drift_line)
    if not all_present:
        for name in missing:
            _route_finding(
                stage="preflight",
                finding_id=f"missing-operator-{name}",
                severity="high",
                source=f"preflight:{name}",
                confirmed=True,
                item_id=None,
                repo=str(repo_path),
                detail=f"bound operator {name} not present or not operational",
            )
    return 0 if all_present else 1


def progress(repo: str, run_id: str, fmt: str, once: bool, interval: float,
             no_animation: bool = False, ascii_only: bool = False) -> int:
    """Render a run's portable progress event for an LLM, terminal, or dashboard."""
    try:
        status = impl().read_status(repo, run_id)
    except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"schema": "simplicio.progress/v1", "status": "UNVERIFIED",
                          "reason_code": "run_missing", "error": str(exc)}, ensure_ascii=False))
        return 2
    if not status or not status.get("run_dir"):
        print(json.dumps({"schema": "simplicio.progress/v1", "status": "UNVERIFIED",
                          "reason_code": "run_missing"}, ensure_ascii=False))
        return 2
    if fmt != "json":
        try:
            from ..dashboard import cli as dashboard_cli
            hint = dashboard_cli.panel_hint()
            if hint is not None:
                print(hint, file=sys.stderr)
        except Exception:
            pass
    impl().stream_progress(status["run_dir"], fmt=fmt, once=once, interval=interval,
                    no_animation=no_animation, ascii_only=ascii_only)
    return 0


def add_status(sub):
    p_status = sub.add_parser("status", help="show the latest run state or a specific run")
    p_status.add_argument("--repo", default=".", help="repository root")
    p_status.add_argument("--run-id", default="", help="run id to inspect")
    p_status.add_argument("--json", action="store_true",
                          help="emit machine-readable JSON (this is also the default)")
    p_status.add_argument("--text", dest="as_text", action="store_true",
                          help="emit human-readable text instead of JSON")


def add_preflight(sub):
    p_preflight = sub.add_parser(
        "preflight", help="verify bound operators (mapper/dev-cli) are installed")
    p_preflight.add_argument("--repo", default=".", help="repository root")
    p_preflight.add_argument("--json", action="store_true",
                             help="emit machine-readable JSON (default: human-readable text)")
    p_preflight.add_argument(
        "--strict",
        action="store_true",
        help="arm SIMPLICIO_LOOP_STRICT: forbid hand-edit, lock evidence/mutation authority",
    )


def add_verify(sub):
    p_verify = sub.add_parser("verify", help="run the independent watcher and delivery gates")
    p_verify.add_argument("--repo", default=".", help="repository root")
    p_verify.add_argument("run_id", help="run id to verify")


def add_progress(sub):
    p_progress = sub.add_parser("progress", help="render visual progress for a run")
    p_progress.add_argument("--repo", default=".", help="repository root")
    p_progress.add_argument("run_id", nargs="?", help="run id to render (legacy positional form)")
    p_progress.add_argument("--run", dest="run_flag", default="",
                            help="run id to render (explicit form)")
    p_progress.add_argument("--format", choices=("text", "json", "markdown", "ansi"),
                            default="text", dest="fmt", help="output format")
    p_progress.add_argument("--once", action="store_true", help="render one snapshot")
    p_progress.add_argument("--no-animation", action="store_true",
                            help="emit one static snapshot without spinner/ANSI control codes")
    p_progress.add_argument("--ascii", action="store_true", dest="ascii_only",
                            help="use ASCII icons/bar for terminals without Unicode support")
    p_progress.add_argument("--interval", type=float, default=0.25,
                            help="animation polling interval in seconds")
