"""Reversible, approval-preserving Codex CLI wrapper (issue #408)."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .detect import detect

WRAPPER_MARKER = "# simplicio-codex-wrapper/v1"
HOOK_MARKER = "simplicio-codex-runtime-hook/v1"
DEFAULT_COMMAND = "codex"
DEFAULT_RUNTIME_COMMAND = "simplicio"


@dataclass(frozen=True)
class CodexIntegrationReport:
    wrapper_path: Path
    hooks_path: Path
    wrapper_installed: bool
    hooks_updated: bool
    backup_path: Path | None


def _runtime_command() -> str:
    return os.environ.get("SIMPLICIO_RUNTIME_COMMAND", DEFAULT_RUNTIME_COMMAND)


def _policy_environment(argv: list[str]) -> dict[str, str]:
    """Expose Codex policy inputs to Runtime without changing their values."""
    policy: dict[str, str] = {}
    value_flags = {
        "--sandbox": "SIMPLICIO_CODEX_SANDBOX_MODE",
        "-s": "SIMPLICIO_CODEX_SANDBOX_MODE",
        "--ask-for-approval": "SIMPLICIO_CODEX_APPROVAL_POLICY",
        "-a": "SIMPLICIO_CODEX_APPROVAL_POLICY",
        "--permission-mode": "SIMPLICIO_CODEX_PERMISSION_MODE",
    }
    for index, value in enumerate(argv[:-1]):
        key = value_flags.get(value)
        if key:
            policy[key] = argv[index + 1]
    for value in argv:
        for flag, key in value_flags.items():
            prefix = f"{flag}="
            if value.startswith(prefix):
                policy[key] = value[len(prefix) :]
    if "--dangerously-bypass-approvals-and-sandbox" in argv:
        policy["SIMPLICIO_CODEX_BYPASS_REQUESTED"] = "1"
    if policy.get("SIMPLICIO_CODEX_PERMISSION_MODE") == "bypassPermissions":
        policy["SIMPLICIO_CODEX_BYPASS_REQUESTED"] = "1"
    return policy


def _policy_payload(argv: list[str]) -> dict[str, Any]:
    values = _policy_environment(argv)
    return {
        "sandbox_mode": values.get("SIMPLICIO_CODEX_SANDBOX_MODE"),
        "approval_policy": values.get("SIMPLICIO_CODEX_APPROVAL_POLICY"),
        "permission_mode": values.get("SIMPLICIO_CODEX_PERMISSION_MODE"),
        "bypass_requested": values.get("SIMPLICIO_CODEX_BYPASS_REQUESTED") == "1",
    }


def _receipt_from_output(output: str) -> dict[str, Any] | None:
    """Accept only a successful Runtime JSON result carrying evidence identity."""
    for line in reversed([item.strip() for item in output.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        nested = value.get("result")
        result: dict[str, Any] = nested if isinstance(nested, dict) else value
        status = result.get("status")
        successful = (
            status in {"done", "passed", "completed", "completed_skeleton", "succeeded", "success", "ok"}
            or result.get("ok") is True
        )
        schema = result.get("schema")
        schema_ok = schema in {
            "simplicio.io/v1",
            "simplicio.run-result/v1",
            "simplicio.workflow-ledger/v1",
            "simplicio.run-verification/v1",
            "simplicio.evidence-summary/v1",
        }
        identified = any(
            result.get(key)
            for key in ("receipt", "receipt_id", "receipts", "run_id", "ledger_id", "evidence")
        )
        if successful and schema_ok and identified:
            return value
    return None


def _prompt_from_argv(argv: list[str]) -> str | None:
    """Return an explicit Codex prompt, excluding values belonging to flags."""
    value_flags = {
        "--model",
        "-m",
        "--profile",
        "-p",
        "--sandbox",
        "-s",
        "--ask-for-approval",
        "-a",
        "--permission-mode",
        "-C",
        "--cd",
        "--add-dir",
        "--output-schema",
        "-o",
        "--output-last-message",
        "--color",
    }
    candidates: list[str] = []
    skip_next = False
    for value in argv:
        if skip_next:
            skip_next = False
            continue
        if value in value_flags:
            skip_next = True
            continue
        if value.startswith("-"):
            continue
        if value in {"exec", "e", "review", "help", "login", "logout", "mcp"}:
            continue
        candidates.append(value)
    return candidates[-1] if candidates else None


def _should_route_prompt(prompt: str) -> bool:
    result = detect(prompt)
    return result.is_code_task or result.score >= 2


def route_through_runtime(
    prompt: str,
    argv: list[str],
    *,
    cwd: str | None = None,
    runtime_command: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a developer task through Runtime before Codex can mutate anything."""
    command = runtime_command or _runtime_command()
    if not shutil.which(command) and not Path(command).is_file():
        raise FileNotFoundError(f"Runtime command not found: {command}")
    environment = os.environ.copy()
    policy = _policy_environment(argv)
    if policy.get("SIMPLICIO_CODEX_BYPASS_REQUESTED") == "1":
        raise PermissionError("Codex approval and sandbox bypass is not allowed by the Runtime integration")
    environment.update(policy)
    environment["SIMPLICIO_CODEX_POLICY_JSON"] = json.dumps(_policy_payload(argv), sort_keys=True)
    environment["SIMPLICIO_CODEX_ARGV_JSON"] = json.dumps(argv)
    environment["SIMPLICIO_HOOK_GUARD"] = "1"
    environment["SIMPLICIO_CODEX_ROUTE"] = "runtime"
    command_path = Path(command)
    command_argv = [command]
    if os.name == "nt" and command_path.is_file():
        try:
            first_line = command_path.open("rb").readline().lower()
        except OSError:
            first_line = b""
        if first_line.startswith(b"#!") and b"python" in first_line:
            command_argv = [sys.executable, command]
    runtime_argv = [*command_argv, "run", prompt, "--repo", cwd or os.getcwd(), "--evidence", "--json"]
    return subprocess.run(
        runtime_argv,
        cwd=cwd,
        env=environment,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def _wrapper_source(python_executable: str) -> str:
    return (
        f"#!{python_executable}\n"
        f"{WRAPPER_MARKER}\n"
        "import os\n"
        "os.environ['SIMPLICIO_CODEX_ROUTE'] = 'runtime'\n"
        "from simplicio.codex_wrapper import run_wrapped\n"
        "raise SystemExit(run_wrapped())\n"
    )


def install_wrapper(path: str | Path, *, python_executable: str = sys.executable) -> Path:
    """Install only at an explicit path and refuse to overwrite another tool."""
    target = Path(path).expanduser().resolve()
    if target.exists():
        content = target.read_text(encoding="utf-8", errors="replace")
        if WRAPPER_MARKER not in content:
            raise FileExistsError(f"refusing to overwrite existing non-Simplicio wrapper: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_wrapper_source(python_executable), encoding="utf-8", newline="\n")
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def uninstall_wrapper(path: str | Path) -> bool:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        return False
    content = target.read_text(encoding="utf-8", errors="replace")
    if WRAPPER_MARKER not in content:
        raise PermissionError(f"refusing to remove non-Simplicio wrapper: {target}")
    target.unlink()
    return True


def run_wrapped(argv: list[str] | None = None, *, command: str | None = None) -> int:
    """Route explicit developer prompts through Runtime; preserve legacy forwarding otherwise."""
    forwarded = list(sys.argv[1:] if argv is None else argv)
    prompt = _prompt_from_argv(forwarded)
    should_route = False
    if os.environ.get("SIMPLICIO_CODEX_ROUTE") == "runtime" and prompt:
        try:
            should_route = _should_route_prompt(prompt)
        except Exception as exc:
            sys.stderr.write(f"{HOOK_MARKER}: task classification failed: {exc}\n")
            return 1
    if should_route and prompt:
        try:
            routed = route_through_runtime(prompt, forwarded)
        except Exception as exc:
            sys.stderr.write(f"{HOOK_MARKER}: Runtime route failed: {exc}\n")
            return 1
        if routed.returncode != 0:
            detail = (routed.stderr or routed.stdout or "Runtime rejected the task").strip()
            sys.stderr.write(f"{HOOK_MARKER}: Runtime route failed: {detail}\n")
            return routed.returncode or 1
        if _receipt_from_output(routed.stdout or "") is None:
            sys.stderr.write(f"{HOOK_MARKER}: Runtime returned no valid evidence receipt\n")
            return 1
        return routed.returncode
    codex = command or os.environ.get("SIMPLICIO_CODEX_COMMAND") or DEFAULT_COMMAND
    environment = os.environ.copy()
    # Prevent a nested Codex invocation from firing the same hook again. No
    # sandbox, approval-policy, or mutation flag is added or removed here.
    environment["SIMPLICIO_HOOK_GUARD"] = "1"
    completed = subprocess.run([codex, *forwarded], env=environment, check=False)
    return completed.returncode


def _hook_command(python_executable: str) -> str:
    command = [
        python_executable,
        "-m",
        "simplicio.codex_hooks",
        "--route",
        "runtime",
        "--marker",
        HOOK_MARKER,
    ]
    return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def _read_hooks(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"hooks": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Codex hooks file: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Codex hooks file must contain an object: {path}")
    hooks = value.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"Codex hooks field must contain an object: {path}")
    return value


def _is_runtime_hook_command(hook: Any) -> bool:
    return isinstance(hook, dict) and HOOK_MARKER in str(hook.get("command", ""))


def _is_runtime_hook(entry: Any) -> bool:
    return isinstance(entry, dict) and any(_is_runtime_hook_command(hook) for hook in entry.get("hooks", []))


def install_codex_integration(
    codex_home: str | Path,
    *,
    wrapper_path: str | Path,
    python_executable: str = sys.executable,
) -> CodexIntegrationReport:
    """Install the marked PATH shim and a UserPromptSubmit Runtime hook."""
    home = Path(codex_home).expanduser().resolve()
    hooks_path = home / "hooks.json"
    original_hooks = hooks_path.read_bytes() if hooks_path.exists() else None
    original_wrapper = Path(wrapper_path).expanduser().resolve()
    original_wrapper_bytes = original_wrapper.read_bytes() if original_wrapper.exists() else None
    original_wrapper_mode = original_wrapper.stat().st_mode if original_wrapper.exists() else None
    settings = _read_hooks(hooks_path)
    hooks = settings["hooks"]
    entries = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(entries, list):
        raise ValueError(f"Codex UserPromptSubmit hooks must be a list: {hooks_path}")
    updated = False
    if not any(_is_runtime_hook(entry) for entry in entries):
        entries.append(
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": _hook_command(python_executable), "timeout": 120}],
            }
        )
        updated = True
    backup: Path | None = None
    try:
        wrapper = install_wrapper(wrapper_path, python_executable=python_executable)
        if updated:
            home.mkdir(parents=True, exist_ok=True)
            if hooks_path.exists():
                backup = hooks_path.with_name(f"{hooks_path.name}.simplicio.bak")
                if not backup.exists():
                    shutil.copy2(hooks_path, backup)
            hooks_path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        if original_wrapper_bytes is None:
            if original_wrapper.exists():
                original_wrapper.unlink()
        else:
            original_wrapper.parent.mkdir(parents=True, exist_ok=True)
            original_wrapper.write_bytes(original_wrapper_bytes)
            if original_wrapper_mode is not None:
                original_wrapper.chmod(original_wrapper_mode)
        if original_hooks is None:
            if hooks_path.exists():
                hooks_path.unlink()
        else:
            hooks_path.parent.mkdir(parents=True, exist_ok=True)
            hooks_path.write_bytes(original_hooks)
        raise
    return CodexIntegrationReport(wrapper, hooks_path, True, updated, backup)


def uninstall_codex_integration(codex_home: str | Path, *, wrapper_path: str | Path) -> bool:
    """Remove only the marked hook and wrapper; preserve all foreign config."""
    hooks_path = Path(codex_home).expanduser().resolve() / "hooks.json"
    changed = False
    if hooks_path.exists():
        settings = _read_hooks(hooks_path)
        entries = settings["hooks"].get("UserPromptSubmit", [])
        if isinstance(entries, list):
            kept: list[Any] = []
            changed = False
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                    kept.append(entry)
                    continue
                foreign_hooks = [hook for hook in entry["hooks"] if not _is_runtime_hook_command(hook)]
                if len(foreign_hooks) != len(entry["hooks"]):
                    changed = True
                if foreign_hooks:
                    preserved = dict(entry)
                    preserved["hooks"] = foreign_hooks
                    kept.append(preserved)
                elif entry.get("hooks"):
                    changed = True
            if changed:
                settings["hooks"]["UserPromptSubmit"] = kept
                if not any(settings["hooks"].values()):
                    hooks_path.write_text(
                        json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                    )
                else:
                    hooks_path.write_text(
                        json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                    )
    wrapper_removed = uninstall_wrapper(wrapper_path)
    return changed or wrapper_removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--install", metavar="PATH")
    actions.add_argument("--install-codex", metavar="CODEX_HOME")
    actions.add_argument("--uninstall", metavar="PATH")
    actions.add_argument("--uninstall-codex", metavar="CODEX_HOME")
    actions.add_argument("--run", action="store_true")
    parser.add_argument("--python", dest="python_executable", default=sys.executable)
    parser.add_argument("--wrapper-path", default=None)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.install:
        sys.stdout.write(f"{install_wrapper(args.install, python_executable=args.python_executable)}\n")
        return 0
    if args.install_codex:
        wrapper_path = args.wrapper_path or str(Path(args.install_codex).expanduser() / "bin" / "codex")
        report = install_codex_integration(
            args.install_codex,
            wrapper_path=wrapper_path,
            python_executable=args.python_executable,
        )
        sys.stdout.write(
            json.dumps(
                {
                    "wrapper": str(report.wrapper_path),
                    "hooks": str(report.hooks_path),
                    "backup": str(report.backup_path) if report.backup_path else None,
                }
            )
            + "\n"
        )
        return 0
    if args.uninstall:
        return 0 if uninstall_wrapper(args.uninstall) else 1
    if args.uninstall_codex:
        wrapper_path = args.wrapper_path or str(Path(args.uninstall_codex).expanduser() / "bin" / "codex")
        return 0 if uninstall_codex_integration(args.uninstall_codex, wrapper_path=wrapper_path) else 1
    forwarded = args.args[1:] if args.args[:1] == ["--"] else args.args
    return run_wrapped(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
