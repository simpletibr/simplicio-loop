"""Progressive verification executor: parse→format→targeted→impact→module→full (#368)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simplicio.plan_compiler.execution_contracts import BoundVerificationPlan, VerificationCommand

_LEVEL_ORDER = ("parse", "format", "targeted", "impact", "module", "full")


class ProgressiveVerifyError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


def _redact(text: str) -> str:
    lowered = text
    for secret in ("AKIA", "ghp_", "gho_", "xoxb-", "password=", "token="):
        if secret.lower() in lowered.lower():
            return "[REDACTED]"
    return text


@dataclass(frozen=True)
class CommandResult:
    command_id: str
    level: str
    argv: list[str]
    exit_code: int
    duration_ms: float
    stdout: str
    stderr: str
    timed_out: bool
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "level": self.level,
            "argv": self.argv,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout": _redact(self.stdout),
            "stderr": _redact(self.stderr),
            "timed_out": self.timed_out,
            "version": self.version,
        }


class ProgressiveVerifier:
    def __init__(
        self,
        root: str | Path,
        *,
        cache: dict[str, dict[str, Any]] | None = None,
        default_timeout_s: float | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.cache = cache if cache is not None else {}
        self.default_timeout_s = default_timeout_s

    def _cache_key(self, command: VerificationCommand, source_hashes: Mapping[str, str]) -> str:
        payload = {
            "argv": command.argv,
            "level": command.level,
            "hashes": dict(sorted(source_hashes.items())),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def run_command(
        self,
        command: VerificationCommand,
        *,
        source_hashes: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> CommandResult:
        hashes = dict(source_hashes or {})
        if not hashes:
            raise ProgressiveVerifyError("CACHE_HASHES_REQUIRED")
        key = self._cache_key(command, hashes)
        if key in self.cache:
            cached = self.cache[key]
            if cached.get("source_hashes") != hashes:
                raise ProgressiveVerifyError("CACHE_STALE")
            return CommandResult(**cached["result"])

        if not command.argv:
            raise ProgressiveVerifyError("EMPTY_ARGV", command.command_id)
        # Resolve executable presence without shell.
        executable = command.argv[0]
        if os.path.sep in executable or (os.path.altsep and os.path.altsep in executable):
            if not (self.root / executable).exists() and not Path(executable).exists():
                raise ProgressiveVerifyError("COMMAND_MISSING", executable)
        else:
            from shutil import which

            if which(executable) is None:
                raise ProgressiveVerifyError("COMMAND_MISSING", executable)

        started = time.perf_counter()
        timed_out = False
        try:
            completed = subprocess.run(
                list(command.argv),
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s if timeout_s is not None else self.default_timeout_s,
                check=False,
                shell=False,
            )
            exit_code = int(completed.returncode)
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else "timeout"
        duration_ms = (time.perf_counter() - started) * 1000.0
        result = CommandResult(
            command_id=command.command_id,
            level=command.level,
            argv=list(command.argv),
            exit_code=exit_code,
            duration_ms=round(duration_ms, 3),
            stdout=stdout[:8000],
            stderr=stderr[:8000],
            timed_out=timed_out,
        )
        self.cache[key] = {"source_hashes": hashes, "result": result.to_dict()}
        return result

    def execute_plan(
        self,
        plan: BoundVerificationPlan,
        *,
        source_hashes: Mapping[str, str],
        require_full: bool = False,
    ) -> dict[str, Any]:
        plan.validate()
        by_level: dict[str, list[VerificationCommand]] = {level: [] for level in _LEVEL_ORDER}
        for command in plan.commands:
            by_level.setdefault(command.level, []).append(command)
        results: list[dict[str, Any]] = []
        failed = False
        for level in _LEVEL_ORDER:
            commands = by_level.get(level, [])
            if require_full and level == "full" and not commands:
                raise ProgressiveVerifyError("FULL_REQUIRED")
            for command in commands:
                outcome = self.run_command(command, source_hashes=source_hashes)
                results.append(outcome.to_dict())
                if outcome.timed_out or outcome.exit_code != 0:
                    failed = True
                    break
            if failed:
                break
        receipt = {
            "schema": "simplicio.progressive-verification-receipt/v1",
            "plan_hash": plan.canonical_hash() if hasattr(plan, "canonical_hash") else None,
            "status": "failed" if failed else "passed",
            "results": results,
            "short_circuited": failed,
        }
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        receipt["receipt_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return receipt
