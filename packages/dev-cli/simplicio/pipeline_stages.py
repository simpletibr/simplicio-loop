"""Narrow pipeline stages extracted from :mod:`simplicio.pipeline`."""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .adaptive import get_validation_mode
from .runtime_env import prepare_project_command, project_subprocess_env
from .transaction import VerificationReceipt, begin_transaction

IMPACT_RESULT_PASSED = "passed"
IMPACT_RESULT_FAILED = "failed"
IMPACT_RESULT_UNVERIFIED = "unverified"
IMPACT_RESULT_NOT_NEEDED = "no_impact_tests"

_TEST_COMMAND_PLACEHOLDERS = {
    "",
    "echo 'configure SIMPLICIO_TEST_CMD'",
    'echo "configure SIMPLICIO_TEST_CMD"',
}


@dataclass
class ValidationResult:
    ok: bool
    reason: str
    hints: list[str]


@dataclass
class PatchCandidate:
    patch: str
    strategy: str
    reason: str = ""


@dataclass
class FailureClassification:
    kind: str
    guidance: str


@dataclass
class ApplyStageResult:
    ok: bool
    log: str
    verify_receipt: dict[str, Any] | None
    patch_receipt: dict[str, Any] | None
    tx: Any | None = None
    receipt: VerificationReceipt | None = None
    changed_files: list[str] | None = None


def _infer_test_command(root: str | Path | None = None) -> str | None:
    """Resolve a real project test command from the repository layout."""
    repo = Path(root) if root is not None else Path.cwd()
    if not repo.is_dir():
        return None
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        if "[tool.pytest" in text or "pytest" in text:
            return "pytest -q"
    if (repo / "pytest.ini").is_file() or (repo / "conftest.py").is_file():
        return "pytest -q"
    tests_dir = repo / "tests"
    if tests_dir.is_dir() and any(tests_dir.rglob("test_*.py")):
        return "pytest -q"
    package_json = repo / "package.json"
    if package_json.is_file():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        scripts = payload.get("scripts") if isinstance(payload, dict) else None
        if isinstance(scripts, dict) and str(scripts.get("test") or "").strip():
            return "npm test"
    if list(repo.glob("*Tests*.csproj")) or list(repo.glob("**/*Tests*.csproj")):
        return "dotnet test"
    if list(repo.glob("*_test.go")) or list(repo.glob("**/*_test.go")):
        return "go test ./..."
    if (repo / "Cargo.toml").is_file():
        return "cargo test"
    return None


def _configured_test_command(root: str | Path | None = None) -> tuple[str | None, str | None]:
    raw = os.environ.get("SIMPLICIO_TEST_CMD", "").strip()
    if raw not in _TEST_COMMAND_PLACEHOLDERS:
        return raw, None
    inferred = _infer_test_command(root)
    if inferred:
        return inferred, None
    return None, (
        "verification command missing: configure SIMPLICIO_TEST_CMD with a real "
        "project test command before execution"
    )


# issue #1331: an unbounded default verify command is how one `edit --apply`
# left a `pytest -q` running for 22+ CPU-minutes as an orphan. 120s is a
# generous bound for the SCOPED command this module now runs by default
# (never the whole suite); an explicit opt-out (0/off/none/unlimited) still
# means unlimited, and an unparsable override falls back to the bounded
# default rather than silently going unbounded.
DEFAULT_VERIFICATION_TIMEOUT_S = 120


def _verification_timeout_seconds() -> int | None:
    raw = os.environ.get("SIMPLICIO_TEST_TIMEOUT_S", "").strip()
    if not raw:
        return DEFAULT_VERIFICATION_TIMEOUT_S
    if raw.lower() in {"0", "off", "none", "unlimited"}:
        return None
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_VERIFICATION_TIMEOUT_S
    return value if value > 0 else DEFAULT_VERIFICATION_TIMEOUT_S


def run_bounded_subprocess(
    cmd: Any,
    *,
    shell: bool,
    cwd: str,
    env: dict[str, str],
    timeout: int | float | None,
    stdin: int = subprocess.DEVNULL,
) -> tuple[int, str, str, bool]:
    """Run ``cmd`` and, on timeout, kill its WHOLE process group.

    issue #1331: a plain ``subprocess.run(..., timeout=...)`` only kills the
    direct child; a shell-invoked test command (``pytest -q``, ``npm test``,
    ...) spawns grandchildren that survive as orphans once the parent is
    reaped -- the exact failure mode measured in docs/evidence/1327-wave.md
    and docs/evidence/1328-wave.md (a 22+ CPU-minute orphaned `pytest`).
    Returns ``(returncode, stdout, stderr, timed_out)``; a timeout reports
    ``returncode == 124`` (the conventional shell timeout exit code).
    """
    popen_kwargs: dict[str, Any] = dict(
        shell=shell,
        cwd=cwd,
        env=env,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout or "", stderr or "", False
    except subprocess.TimeoutExpired:
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return 124, stdout or "", stderr or "", True


_TEST_NAME_GUESSES = ("test_{stem}.py", "{stem}_test.py")


def _scoped_verification_command(root: str | Path, changed_files: list[str] | None) -> str | None:
    """Best-effort scoped ``pytest`` command limited to tests that reference
    the changed files -- never the whole suite (issue #1331).

    Looks only at conventional locations (same directory, a sibling
    ``tests/`` directory, and ``tests/`` mirroring the changed file's own
    directory). A changed file that IS itself a test file is included
    directly. Returns ``None`` when nothing is found; the caller then skips
    verification rather than falling back to a full-suite run.
    """
    if not changed_files:
        return None
    repo = Path(root)
    found: list[str] = []
    seen: set[str] = set()

    def _add(rel: Path) -> None:
        key = rel.as_posix()
        if key in seen:
            return
        if (repo / rel).is_file():
            seen.add(key)
            found.append(key)

    for raw in changed_files:
        rel_path = PurePosixPath(str(raw).replace("\\", "/"))
        name = rel_path.name
        if name.startswith("test_") and name.endswith(".py") or name.endswith("_test.py"):
            _add(Path(str(rel_path)))
            continue
        stem = Path(name).stem
        if not stem:
            continue
        parent = Path(str(rel_path.parent)) if str(rel_path.parent) != "." else Path()
        for guess_template in _TEST_NAME_GUESSES:
            guess_name = guess_template.format(stem=stem)
            _add(parent / guess_name)
            _add(Path("tests") / guess_name)
            if parent != Path():
                _add(Path("tests") / parent / guess_name)
    if not found:
        return None
    return "pytest -q " + " ".join(sorted(found))


def _patch_receipt(candidate: PatchCandidate | None, files: list[str] | None = None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    requested_model = os.environ.get("SIMPLICIO_MODEL", "")
    requested_effort = os.environ.get(
        "SIMPLICIO_CODEX_EFFORT",
        os.environ.get("SIMPLICIO_REASONING_EFFORT", ""),
    )
    requested_tier = os.environ.get("SIMPLICIO_MODEL_TIER", "")
    return {
        "schema": "simplicio.dev-cli.patch-receipt/v1",
        "parser_strategy": candidate.strategy,
        "fingerprint": hashlib.sha256(candidate.patch.encode("utf-8")).hexdigest(),
        "files": list(files or []),
        "capability": {
            "requested": {
                "model": requested_model,
                "effort": requested_effort,
                "tier": requested_tier,
            },
            "effective": {
                "model": os.environ.get("SIMPLICIO_EFFECTIVE_MODEL", requested_model),
                "effort": os.environ.get("SIMPLICIO_EFFECTIVE_EFFORT", requested_effort),
                "tier": os.environ.get("SIMPLICIO_EFFECTIVE_TIER", requested_tier),
            },
        },
    }


def run_impact_tests(
    root: str | Path,
    files_changed: list[str],
    *,
    test_cmd: str | None = None,
    map_ask_fn,
    prepare_project_command_fn=prepare_project_command,
) -> dict[str, Any]:
    if not files_changed:
        return {
            "status": "no_changed_files",
            "callers": [],
            "tests_run": [],
            "result": IMPACT_RESULT_NOT_NEEDED,
        }

    root_str = str(Path(root).resolve())
    callers_seen: set[str] = set()
    test_files_seen: set[str] = set()
    mapper_responded = False

    for filepath in files_changed:
        impact = map_ask_fn(root_str, "impact", filepath)
        if impact is None:
            continue
        mapper_responded = True
        if not impact:
            continue
        for entry in impact:
            if not isinstance(entry, dict):
                continue
            caller = entry.get("caller") or entry.get("path") or ""
            if caller:
                callers_seen.add(caller)

    if not callers_seen:
        return {
            "status": "no_callers_found" if mapper_responded else "mapper_unavailable",
            "callers": [],
            "tests_run": [],
            "result": IMPACT_RESULT_NOT_NEEDED if mapper_responded else IMPACT_RESULT_UNVERIFIED,
        }

    for caller in callers_seen:
        tests = map_ask_fn(root_str, "tests-for", caller)
        if not tests:
            continue
        for item in tests:
            if not isinstance(item, dict):
                continue
            test_path = item.get("test_path") or item.get("path") or item.get("file") or ""
            if test_path:
                test_files_seen.add(test_path)

    if not test_files_seen:
        return {
            "status": "no_tests_found",
            "callers": sorted(callers_seen),
            "tests_run": [],
            "result": IMPACT_RESULT_UNVERIFIED,
        }

    test_files = sorted(test_files_seen)
    cmd_raw = (test_cmd or os.environ.get("SIMPLICIO_TEST_CMD", "")).strip()
    if cmd_raw in _TEST_COMMAND_PLACEHOLDERS:
        return {
            "status": "missing_test_command",
            "callers": sorted(callers_seen),
            "tests_run": test_files,
            "result": IMPACT_RESULT_UNVERIFIED,
            "error": "verification command missing",
        }
    cmd, use_shell = prepare_project_command_fn(root_str, cmd_raw, test_files)

    try:
        proc = subprocess.run(
            cmd,
            shell=use_shell,
            cwd=root_str,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_verification_timeout_seconds(),
            env=project_subprocess_env(root_str),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "error",
            "callers": sorted(callers_seen),
            "tests_run": test_files,
            "result": IMPACT_RESULT_UNVERIFIED,
            "error": str(exc),
        }

    passed = proc.returncode == 0
    return {
        "status": "ok" if passed else "failed",
        "callers": sorted(callers_seen),
        "tests_run": test_files,
        "result": IMPACT_RESULT_PASSED if passed else IMPACT_RESULT_FAILED,
        "command": cmd_raw,
        "returncode": proc.returncode,
        "receipt": {
            "kind": "impact",
            "command": cmd_raw,
            "exit_code": proc.returncode,
            "output_tail": (proc.stdout + proc.stderr)[-2000:],
        },
        "output_tail": (proc.stdout + proc.stderr)[-2000:] if not passed else "",
    }


def extract_changed_files(output: str | None) -> list[str]:
    text = output or ""
    files = []
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", text, flags=re.M):
        files.append(match.group(2).strip())
    for match in re.finditer(r"^\+\+\+ b/(.+?)$", text, flags=re.M):
        files.append(match.group(1).strip())
    return list(dict.fromkeys(f for f in files if f and f != "/dev/null"))


def _matches_bound(path: str, patterns) -> bool:
    normalized = path.replace(os.sep, "/").lstrip("./")
    for raw in patterns or []:
        pattern = str(raw).replace(os.sep, "/").lstrip("./")
        if fnmatch.fnmatch(normalized, pattern):
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                return True
    return False


def _bound_path_warnings(files: list[str], bound_paths) -> list[str]:
    if not bound_paths:
        return []
    outside = [path for path in files if not _matches_bound(path, bound_paths)]
    if not outside:
        return []
    return [
        "diff touches path outside bound paths: "
        + ", ".join(outside)
        + f" (allowed: {', '.join(bound_paths)})"
    ]


def _bound_path_files(root: str, bound_paths) -> list[Path]:
    """Resolve concrete (non-glob) ``bound_paths`` entries to absolute paths.

    Glob-style bound patterns (containing ``*``/``?``/``[``) are skipped —
    there is nothing on disk to snapshot for a pattern until a concrete diff
    names an actual file, and that is already covered by
    :func:`_bound_path_warnings` acting on the generated diff.
    """
    files = []
    for raw in bound_paths or []:
        normalized = str(raw).replace(os.sep, "/").lstrip("./")
        if any(ch in normalized for ch in "*?["):
            continue
        files.append(Path(root) / normalized.replace("/", os.sep))
    return files


def snapshot_bound_paths(root: str, bound_paths) -> dict[str, tuple[bool, int, int]]:
    """Record identity (exists, size, mtime_ns) for each concrete bound path.

    Issue #210 AC6: bound-path enforcement must be checked *before* and
    *after* generation, not only against the returned diff. The generated
    diff is validated by :func:`_bound_path_warnings`/`validate_generated_
    output` (the "after" half); this snapshot plus :func:`bound_path_drift`
    is the "before" half — it detects an out-of-band mutation of a bound
    file that happened while the provider subprocess was running, even if
    the returned diff never mentions that path.
    """
    snapshot: dict[str, tuple[bool, int, int]] = {}
    for path in _bound_path_files(root, bound_paths):
        try:
            stat = path.stat()
            snapshot[str(path)] = (True, stat.st_size, stat.st_mtime_ns)
        except OSError:
            snapshot[str(path)] = (False, 0, 0)
    return snapshot


def bound_path_drift(root: str, bound_paths, baseline: dict[str, tuple[bool, int, int]]) -> list[str]:
    """Compare the current on-disk state of bound paths against *baseline*.

    Returns a list of human-readable warnings (empty when nothing drifted).
    Only reports paths that were snapshotted (i.e. present in *baseline*) —
    this is a targeted "did something touch a file we were told not to
    touch" check, not a general worktree diff.
    """
    warnings: list[str] = []
    for path in _bound_path_files(root, bound_paths):
        key = str(path)
        if key not in baseline:
            continue
        was_present, was_size, was_mtime = baseline[key]
        try:
            stat = path.stat()
            now_present, now_size, now_mtime = True, stat.st_size, stat.st_mtime_ns
        except OSError:
            now_present, now_size, now_mtime = False, 0, 0
        if (was_present, was_size, was_mtime) == (now_present, now_size, now_mtime):
            continue
        if was_present and not now_present:
            warnings.append(f"bound path deleted out-of-band during generation: {path}")
        elif not was_present and now_present:
            warnings.append(f"bound path created out-of-band during generation: {path}")
        else:
            warnings.append(f"bound path mutated out-of-band during generation: {path}")
    return warnings


def extract_patch(output: str | None) -> str:
    text = output or ""
    fenced = re.search(r"```(?:diff|patch)?\s*\n(.*?)(?:\n```|$)", text, flags=re.S)
    if fenced and ("diff --git " in fenced.group(1) or "--- " in fenced.group(1)):
        return fenced.group(1).strip() + "\n"
    match = re.search(r"(?m)^(diff --git .+|--- .+)$", text)
    if not match:
        return ""
    patch = text[match.start() :]
    test_marker = re.search(r"(?m)^TEST:\s*$", patch)
    if test_marker:
        patch = patch[: test_marker.start()]
    fence = patch.find("\n```")
    if fence != -1:
        patch = patch[:fence]
    return patch.strip() + "\n"


def _single_bound_path(bound_paths) -> str | None:
    normalized = [str(path).replace(os.sep, "/").lstrip("./") for path in (bound_paths or [])]
    concrete = [path for path in normalized if path and not any(ch in path for ch in "*?[")]
    return concrete[0] if len(concrete) == 1 else None


def _extract_full_file_artifact(output: str, target: str) -> str:
    text = output or ""
    fence_pattern = re.compile(
        r"```[^\n`]*(?:file|path|filename)?[^\n`]*\n(.*?)(?:\n```|$)",
        re.S | re.I,
    )
    fenced_blocks = [match.group(1) for match in fence_pattern.finditer(text)]
    for block in fenced_blocks:
        if "diff --git " not in block and not re.search(r"(?m)^--- .+\n\+\+\+ ", block):
            return block.strip("\n") + "\n"

    labelled = re.search(
        rf"(?ims)^(?:FILE|TARGET|PATH):\s*{re.escape(target)}\s*$\n(.*?)(?:^TEST:\s*$|\Z)",
        text,
    )
    if labelled:
        return labelled.group(1).strip("\n") + "\n"
    return ""


def _diff_for_full_file(root: str, target: str, content: str) -> str:
    target_path = Path(root) / target.replace("/", os.sep)
    try:
        old = target_path.read_text(encoding="utf-8")
    except OSError:
        old = ""
    if old == content:
        return ""
    old_lines = old.splitlines(keepends=True)
    new_lines = content.splitlines(keepends=True)
    body = "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{target}",
            tofile=f"b/{target}",
            lineterm="\n",
        )
    )
    if not body.endswith("\n"):
        body += "\n"
    return f"diff --git a/{target} b/{target}\n{body}"


def _extract_patch_candidate(output: str, root: str, bound_paths=None) -> PatchCandidate:
    patch = extract_patch(output)
    if patch:
        return PatchCandidate(patch=patch, strategy="unified_diff")
    target = _single_bound_path(bound_paths)
    if not target:
        return PatchCandidate(patch="", strategy="none", reason="no unified diff and no single bound target")
    content = _extract_full_file_artifact(output, target)
    if not content:
        return PatchCandidate(patch="", strategy="none", reason="no unified diff or full-file artifact found")
    patch = _diff_for_full_file(root, target, content)
    if not patch:
        return PatchCandidate(
            patch="",
            strategy="full_file_noop",
            reason="full-file artifact matches current target",
        )
    return PatchCandidate(patch=patch, strategy="full_file_artifact")


# Issue #219: flag a diff that deletes ~all of a pre-existing bound file as a
# likely destructive full-file replacement. Off below _DESTRUCTIVE_MIN_FILE_LINES
# so small legitimate full-file rewrites (see issue-129 fixtures) aren't flagged.
_DESTRUCTIVE_MIN_FILE_LINES = 5
_DESTRUCTIVE_DELETE_RATIO = 0.9
_DESTRUCTIVE_CONTEXT_RATIO = 0.1


def _diff_section_for_file(patch: str, target: str) -> str:
    """Return the slice of *patch* covering *target*'s hunks, or ``""``."""
    marker = f"diff --git a/{target} b/{target}"
    idx = patch.find(marker)
    if idx == -1:
        marker = f"+++ b/{target}"
        idx = patch.find(marker)
        if idx == -1:
            return ""
    end = patch.find("\ndiff --git ", idx + 1)
    return patch[idx:] if end == -1 else patch[idx : end + 1]


def _full_file_replacement_hints(text: str, root: str | os.PathLike | None, bound_paths) -> list[str]:
    """Flag a diff deleting ~all of a pre-existing single bound file.

    No-op without ``root`` (no pre-image to compare) or without exactly one
    concrete bound path (nothing to call "the whole file").
    """
    if root is None or not text:
        return []
    target = _single_bound_path(bound_paths)
    if not target:
        return []
    try:
        original_lines = (Path(root) / target.replace("/", os.sep)).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    total = len(original_lines)
    if total < _DESTRUCTIVE_MIN_FILE_LINES:
        return []
    section = _diff_section_for_file(text, target)
    if not section:
        return []
    deleted = 0
    context = 0
    old_start: int | None = None
    for line in section.splitlines():
        header = re.match(r"^@@ -(\d+)(?:,\d+)? \+", line)
        if header:
            if old_start is None:
                old_start = int(header.group(1))
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            deleted += 1
        elif line.startswith(" "):
            context += 1
    if old_start not in (0, 1):
        return []
    if deleted < max(1, int(total * _DESTRUCTIVE_DELETE_RATIO)):
        return []
    if context > max(1, int(total * _DESTRUCTIVE_CONTEXT_RATIO)):
        return []
    return [
        f"diff replaces the entire pre-existing file {target} "
        f"({deleted}/{total} lines deleted, only {context} kept as context) — this looks like "
        "a destructive full-file rewrite for what was requested as a localized change; return "
        "a minimal, targeted diff instead (or confirm a full rewrite is genuinely required)"
    ]


def _path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def authorized_path_warnings(
    files: list[str],
    *,
    root: str | os.PathLike[str],
    repo_root: str | os.PathLike[str] | None = None,
    scope_root: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Reject every changed path outside the declared mutation roots."""
    mutation_root = Path(root).resolve()
    authorized_repo = Path(repo_root if repo_root is not None else mutation_root).resolve()
    raw_scope = Path(scope_root if scope_root is not None else authorized_repo)
    authorized_scope = (
        (authorized_repo / raw_scope).resolve() if not raw_scope.is_absolute() else raw_scope.resolve()
    )
    if authorized_repo != mutation_root:
        return ["REPO_ROOT_MISMATCH: authorized repo_root must equal the actual mutation root"]
    if not _path_is_inside(authorized_scope, authorized_repo):
        return ["ROOT_SCOPE_MISMATCH: authorized scope_root must be inside repo_root"]

    warnings: list[str] = []
    for raw_path in files:
        normalized = str(raw_path).replace("\\", "/")
        posix_path = PurePosixPath(normalized)
        windows_path = PureWindowsPath(str(raw_path))
        if (
            not normalized
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in posix_path.parts
        ):
            warnings.append(f"PATCH_PATH_OUTSIDE_REPO: {raw_path}")
            continue
        resolved = (authorized_repo / Path(*posix_path.parts)).resolve()
        if not _path_is_inside(resolved, authorized_repo):
            warnings.append(f"PATCH_PATH_OUTSIDE_REPO: {raw_path}")
        elif not _path_is_inside(resolved, authorized_scope):
            warnings.append(f"PATCH_PATH_OUTSIDE_SCOPE: {raw_path}")
    return warnings


def validate_generated_output(
    output,
    bound_paths=None,
    mode=None,
    root=None,
    repo_root=None,
    scope_root=None,
) -> ValidationResult:
    text = output or ""
    if mode is None:
        mode = get_validation_mode()
    hints = []
    has_diff = bool(re.search(r"^diff --git |^--- .+\n\+\+\+ ", text, flags=re.M))
    has_test = "TEST:" in text or re.search(r"(^|\n)(test|it|def test_|describe)\b", text)
    external_test_cmd = os.environ.get("SIMPLICIO_TEST_CMD", "").strip()
    has_external_test = bool(external_test_cmd and external_test_cmd != "echo 'configure SIMPLICIO_TEST_CMD'")
    if not has_diff and _single_bound_path(bound_paths):
        has_diff = bool(_extract_full_file_artifact(text, _single_bound_path(bound_paths) or ""))
    if not has_diff:
        hints.append("include a unified diff with exact target files")
    if mode == "strict" and not has_test and not has_external_test:
        hints.append("include a TEST block or concrete test code")
    if not has_external_test and re.search(r"(?i)\b(pseudocode|placeholder|todo: implement)\b", text):
        hints.append("replace placeholders with executable code")
    changed_files = extract_changed_files(output)
    hints.extend(_bound_path_warnings(changed_files, bound_paths))
    if root is not None:
        hints.extend(
            authorized_path_warnings(
                changed_files,
                root=root,
                repo_root=repo_root,
                scope_root=scope_root,
            )
        )
    # Issue #219: unconditional (not mode-gated) — a destructive rewrite is a safety concern.
    hints.extend(_full_file_replacement_hints(text, root, bound_paths))
    return ValidationResult(
        ok=not hints,
        reason="ok" if not hints else "; ".join(hints),
        hints=hints,
    )


def classify_failure(log: str | None) -> FailureClassification:
    text = (log or "").lower()
    if "syntaxerror" in text or "unexpected token" in text or "parse error" in text:
        return FailureClassification(
            "syntax", "Fix syntax first; keep the patch minimal and rerun the same test."
        )
    if "assertionerror" in text or "expected" in text and "actual" in text:
        return FailureClassification(
            "assertion",
            "The test ran but behavior is wrong; inspect the asserted contract and adjust logic.",
        )
    if "modulenotfound" in text or "no module named" in text or "cannot find module" in text:
        return FailureClassification(
            "dependency",
            "Use existing project dependencies or correct imports; do not invent packages.",
        )
    if "timeout" in text or "timed out" in text:
        return FailureClassification(
            "timeout",
            "Reduce scope, avoid long-running work, and make the verification deterministic.",
        )
    if "traceback" in text or "exception" in text or "typeerror" in text or "referenceerror" in text:
        return FailureClassification("runtime", "Fix the runtime exception at the reported callsite.")
    return FailureClassification(
        "unknown",
        "Re-read the mapper context and produce a smaller, directly testable diff.",
    )


def build_retry_feedback(attempt, validation=None, test_log="") -> str:
    classification = classify_failure(test_log)
    lines = [
        f"Retry feedback for attempt {attempt}:",
        f"failure_class={classification.kind}",
        classification.guidance,
    ]
    if validation and not validation.ok:
        lines.append(f"pre-apply validation failed: {validation.reason}")
    if test_log:
        lines.append("test/runtime tail:")
        lines.append(test_log[-1600:])
    lines.append("Return the full corrected DIFF + TEST block only.")
    return "\n".join(lines)


def _git_apply_patch(root: str, patch: str, *, subprocess_run=subprocess.run) -> tuple[bool, str]:
    patch = patch.replace("\r\n", "\n").replace("\r", "\n")
    paths = re.findall(r"^diff --git a/(\S+) b/\S+$", patch, flags=re.M)
    if paths:
        candidate = Path(root) / paths[0].replace("/", os.sep)
        try:
            data = candidate.read_bytes()
        except OSError:
            data = b""
        if data and data.count(b"\r\n") == data.count(b"\n"):
            patch = patch.replace("\n", "\r\n")
    attempts = [
        ([], "git apply"),
        (["--recount"], "git apply --recount"),
        (["--recount", "--3way"], "git apply --recount --3way"),
    ]
    errors = []
    for extra_args, label in attempts:
        check = subprocess_run(
            ["git", "apply", "--check", *extra_args, "-"],
            input=patch.encode("utf-8"),
            cwd=root,
            capture_output=True,
        )
        if check.returncode != 0:
            detail = (check.stderr or check.stdout).decode("utf-8", errors="replace")
            errors.append(f"{label} --check failed:\n{detail[-1600:]}")
            continue
        apply = subprocess_run(
            ["git", "apply", *extra_args, "-"],
            input=patch.encode("utf-8"),
            cwd=root,
            capture_output=True,
        )
        if apply.returncode == 0:
            return True, ""
        detail = (apply.stderr or apply.stdout).decode("utf-8", errors="replace")
        errors.append(f"{label} failed:\n{detail[-1600:]}")
    return False, "\n".join(errors)


def _copy_transaction_workspace(root: str, candidate: Path) -> None:
    src_root = Path(root)
    for item in src_root.iterdir():
        if item.name in {".git", ".simplicio-loop", "__pycache__"}:
            continue
        destination = candidate / item.name
        if item.is_dir():
            shutil.copytree(
                item,
                destination,
                ignore=shutil.ignore_patterns(".git", ".simplicio-loop", "__pycache__", "*.pyc"),
                dirs_exist_ok=True,
            )
        elif item.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def _apply_patch_to_transaction(
    root,
    output,
    bound_paths,
    candidate,
    patch,
    changed_files,
    patch_receipt,
    git_apply_patch_fn,
    begin_transaction_fn,
    simplicio_dir,
):
    tx = begin_transaction_fn(root, dirty_policy="preserve")
    _copy_transaction_workspace(root, tx.candidate)
    applied, apply_log = git_apply_patch_fn(str(tx.candidate), patch)
    if not applied and candidate.strategy == "unified_diff":
        target = _single_bound_path(bound_paths)
        content = _extract_full_file_artifact(output or "", target or "") if target else ""
        fallback_patch = _diff_for_full_file(str(tx.candidate), target, content) if target and content else ""
        if fallback_patch:
            fallback_applied, fallback_log = git_apply_patch_fn(str(tx.candidate), fallback_patch)
            if fallback_applied:
                candidate = PatchCandidate(fallback_patch, "full_file_after_patch_failure")
                patch = fallback_patch
                changed_files = extract_changed_files(patch)
                patch_receipt = _patch_receipt(candidate, changed_files)
                applied = True
                apply_log = ""
                (simplicio_dir / "last_patch.diff").write_text(patch, encoding="utf-8")
                (simplicio_dir / "last_patch_strategy.txt").write_text(
                    candidate.strategy + "\n", encoding="utf-8"
                )
            else:
                apply_log = apply_log + "\nfull-file fallback failed:\n" + fallback_log
    return tx, candidate, patch, changed_files, patch_receipt, applied, apply_log


def _verify_apply_transaction(
    tx,
    cmd,
    prepare_project_command_fn,
    changed_files,
    patch_receipt,
    promote_on_success,
):
    assert cmd is not None
    prepared, use_shell = prepare_project_command_fn(str(tx.candidate), cmd)
    verify_cmd = " ".join(prepared) if isinstance(prepared, list) else str(prepared)
    try:
        proc = subprocess.run(
            prepared,
            shell=use_shell,
            cwd=str(tx.candidate),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=_verification_timeout_seconds(),
            env=project_subprocess_env(str(tx.candidate)),
        )
        output_tail = (proc.stdout + proc.stderr)[-2000:]
        receipt = tx.receipt(
            changed_files,
            commands=[verify_cmd],
            exit_codes=[proc.returncode],
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.output
            if isinstance(exc.output, str)
            else (exc.output or b"").decode("utf-8", errors="replace")
        )
        stderr = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else (exc.stderr or b"").decode("utf-8", errors="replace")
        )
        receipt = tx.receipt(
            changed_files,
            commands=[verify_cmd],
            exit_codes=[124],
            stdout=stdout,
            stderr=stderr or f"timed out after {exc.timeout}s",
        )
        return ApplyStageResult(
            False,
            f"verification timed out after {exc.timeout}s",
            receipt.to_dict(),
            patch_receipt,
            tx=tx,
            receipt=receipt,
            changed_files=changed_files,
        )

    if proc.returncode != 0:
        return ApplyStageResult(
            False,
            output_tail,
            receipt.to_dict(),
            patch_receipt,
            tx=tx,
            receipt=receipt,
            changed_files=changed_files,
        )

    if promote_on_success:
        tx.promote(receipt)
    return ApplyStageResult(
        True,
        output_tail,
        receipt.to_dict(),
        patch_receipt,
        tx=tx,
        receipt=receipt,
        changed_files=changed_files,
    )


def run_apply_stage(
    output,
    root,
    *,
    bound_paths=None,
    git_apply_patch_fn=_git_apply_patch,
    prepare_project_command_fn=prepare_project_command,
    begin_transaction_fn=begin_transaction,
    promote_on_success=True,
    repo_root=None,
    scope_root=None,
) -> ApplyStageResult:
    cmd, command_error = _configured_test_command(root)
    if command_error:
        return ApplyStageResult(False, command_error, None, None)

    root_path = Path(root)
    validation = validate_generated_output(
        output,
        bound_paths,
        root=root,
        repo_root=repo_root,
        scope_root=scope_root,
    )
    if not validation.ok:
        return ApplyStageResult(False, f"pre-apply validation failed: {validation.reason}", None, None)

    preview_changed_files = extract_changed_files(output or "")
    preview_warnings = authorized_path_warnings(
        preview_changed_files,
        root=root,
        repo_root=repo_root,
        scope_root=scope_root,
    )
    if preview_warnings:
        return ApplyStageResult(
            False,
            "pre-apply validation failed: " + "; ".join(preview_warnings),
            None,
            None,
            changed_files=preview_changed_files,
        )

    candidate = _extract_patch_candidate(output or "", root, bound_paths)
    patch = candidate.patch
    changed_files = extract_changed_files(patch)
    patch_receipt = _patch_receipt(candidate, changed_files)
    if not patch:
        reason = candidate.reason or "no unified diff found"
        return ApplyStageResult(False, f"pre-apply validation failed: {reason}", None, patch_receipt)

    path_warnings = authorized_path_warnings(
        changed_files,
        root=root,
        repo_root=repo_root,
        scope_root=scope_root,
    )
    if path_warnings:
        return ApplyStageResult(
            False,
            "pre-apply validation failed: " + "; ".join(path_warnings),
            None,
            patch_receipt,
            changed_files=changed_files,
        )

    simplicio_dir = root_path / ".simplicio-loop"
    simplicio_dir.mkdir(parents=True, exist_ok=True)
    (simplicio_dir / "last_output.txt").write_text(output or "", encoding="utf-8")
    (simplicio_dir / "last_patch.diff").write_text(patch, encoding="utf-8")
    (simplicio_dir / "last_patch_strategy.txt").write_text(candidate.strategy + "\n", encoding="utf-8")

    (
        tx,
        candidate,
        patch,
        changed_files,
        patch_receipt,
        applied,
        apply_log,
    ) = _apply_patch_to_transaction(
        root,
        output,
        bound_paths,
        candidate,
        patch,
        changed_files,
        patch_receipt,
        git_apply_patch_fn,
        begin_transaction_fn,
        simplicio_dir,
    )
    if not applied:
        receipt = tx.receipt(
            changed_files,
            commands=[f"git apply ({candidate.strategy})"],
            exit_codes=[2],
            stdout="",
            stderr=apply_log,
        )
        return ApplyStageResult(
            False,
            apply_log,
            receipt.to_dict(),
            patch_receipt,
            tx=tx,
            receipt=receipt,
            changed_files=changed_files,
        )

    return _verify_apply_transaction(
        tx,
        cmd,
        prepare_project_command_fn,
        changed_files,
        patch_receipt,
        promote_on_success,
    )
