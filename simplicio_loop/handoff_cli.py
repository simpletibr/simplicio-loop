"""``simplicio-loop handoff write|read|check`` (#1608, part B).

* ``write``: read a ``simplicio.agent-handoff/v1`` document (``--file``, default stdin), mask secrets in its free text,
  validate it and store it as ``<repo>/.simplicio-loop/orchestrator/handoff/<run_id>/<continuation>.json``. The file is
  0600 and the directories are 0700. No symbolic link may stand on the path, and an existing handoff is never replaced.
* ``read``: print one stored handoff (``--n``, default the highest number) after validating it again.
* ``check``: say ``ok``, ``handoff`` or ``over`` for the PROJECTED total prompt of the NEXT request. Give the three
  counters of the last request (``--input-tokens``, ``--cache-read``, ``--cache-write``; MEASURED) and, optionally, the
  text that will be added (``--added-file``). A host that reports no usage gives ``--prompt-file`` instead (ESTIMATED).

The ceiling comes from the DEFAULT BRANCH, never from the working tree: the ``agent_input_token_ceiling`` key of
``.simplicio-loop/loop.toml`` as ``origin/HEAD`` has it (as of the last fetch). An agent that edits its own clone cannot
raise it. The environment variable ``SIMPLICIO_AGENT_INPUT_TOKEN_CEILING`` still wins and then no git is needed.
A repository without ``origin/HEAD`` and without the variable fails loud: there is no silent default.

Exit codes: 0 ok, 3 handoff (write one before the next request), 4 over (do not send), 2 error.
An error prints ``{"status": "error", "reason_code": ..., "error": ...}`` on stderr and nothing on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from .agent_handoff import HandoffError, handoff_path, redact_handoff, validate_handoff
from .input_ceiling import (
    DEFAULT_CEILING, ENV_NAME, MAX_CEILING, TOML_KEY, CeilingConfigError, PromptUsage, Projection, _check_ceiling,
    check_budget)

CONFIG_PATH = ".simplicio-loop/loop.toml"
# A handoff is at most 6000 estimated tokens (about 24 KB of JSON). A file far above that is not one.
MAX_FILE_BYTES = 256 * 1024
EXIT_STATUS = {"ok": 0, "handoff": 3, "over": 4}
EXIT_ERROR = 2
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CONTINUATION_FILE = re.compile(r"[1-9][0-9]*\.json")


# --- the ceiling ---------------------------------------------------------------------------------------------------------

def ceiling_from(config: Mapping[str, Any], environ: Mapping[str, str]) -> int:
    """Pure. The environment variable wins over the config key; neither set means 98,000. A bad value raises."""
    if ENV_NAME in environ:
        raw = environ[ENV_NAME]
        if not re.fullmatch(r"[0-9]{1,7}", raw):
            raise CeilingConfigError("%s: %r is not an integer from 1 to %d" % (ENV_NAME, raw, MAX_CEILING))
        return _check_ceiling(int(raw), ENV_NAME)
    if TOML_KEY in config:
        return _check_ceiling(config[TOML_KEY], "default branch %s key %s" % (CONFIG_PATH, TOML_KEY))
    return DEFAULT_CEILING


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HandoffError("default_branch_unresolved", "git failed in %s: %s" % (repo, exc)) from exc


def default_branch_config(repo: Path) -> dict[str, Any]:
    """The parsed ``.simplicio-loop/loop.toml`` of ``origin/HEAD`` (empty when that branch has no such file)."""
    head = _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD")
    if head.returncode != 0:
        raise HandoffError("default_branch_unresolved",
                           "%s has no origin/HEAD, so the default branch is unknown. Run `git remote set-head origin "
                           "--auto` or set %s" % (repo, ENV_NAME))
    ref = head.stdout.decode("utf-8", "replace").strip()
    listed = _git(repo, "ls-tree", "--name-only", ref, "--", CONFIG_PATH)
    if listed.returncode != 0:
        raise HandoffError("default_branch_unresolved", "cannot list %s: %s" % (ref, listed.stderr.decode("utf-8", "replace").strip()))
    if not listed.stdout.strip():
        return {}
    blob = _git(repo, "show", "%s:%s" % (ref, CONFIG_PATH))
    if blob.returncode != 0:
        raise HandoffError("default_branch_unresolved", "cannot read %s:%s" % (ref, CONFIG_PATH))
    try:
        return tomllib.loads(blob.stdout.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise CeilingConfigError("%s:%s: %s" % (ref, CONFIG_PATH, exc)) from exc


def _ceiling(repo: Path) -> int:
    return ceiling_from({} if ENV_NAME in os.environ else default_branch_config(repo), os.environ)


# --- input and output ----------------------------------------------------------------------------------------------------

def _read_text(source: str) -> str:
    try:
        return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HandoffError("handoff_input_invalid", "cannot read %s: %s" % ("stdin" if source == "-" else source, exc)) from exc


def _parse_object(text: str, where: str) -> dict:
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise HandoffError("handoff_input_invalid", "%s is not JSON: %s" % (where, exc)) from exc
    if not isinstance(doc, dict):
        raise HandoffError("handoff_schema_invalid", "%s is not a JSON object" % where)
    return doc


def _root(repo: str) -> Path:
    root = Path(repo)
    if not root.is_dir():
        raise HandoffError("handoff_input_invalid", "%s is not a directory" % repo)
    return root.resolve()


def _walk(root: Path, parts: Sequence[str], create: bool) -> Path:
    """Follow ``parts`` below ``root``. A link or a plain file on the way is an error. ``create`` makes missing
    directories 0700; ``handoff`` and the run directory are always set to 0700."""
    here = root
    for depth, part in enumerate(parts):
        here = here / part
        try:
            mode = os.lstat(here).st_mode
        except FileNotFoundError:
            if not create:
                raise HandoffError("handoff_not_found", "%s does not exist" % here) from None
            os.mkdir(here, 0o700)
            mode = stat.S_IFDIR
        if stat.S_ISLNK(mode):
            raise HandoffError("handoff_symlink", "%s is a symbolic link" % here)
        if not stat.S_ISDIR(mode):
            raise HandoffError("handoff_input_invalid", "%s is not a directory" % here)
        if create and depth >= 2:
            os.chmod(here, 0o700)
    return here


def _parts(run_id: str) -> tuple[str, ...]:
    return (".simplicio-loop", "orchestrator", "handoff", run_id)


def _publish(path: Path, text: str) -> None:
    """Write ``text`` to a private temporary file and link it to ``path``. The link fails when ``path`` exists, so a
    stored handoff is never replaced and a reader never sees half a file."""
    tmp = path.with_name(".%s.tmp" % uuid.uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise HandoffError("handoff_exists", "%s exists; a handoff is never replaced" % path) from None
    finally:
        os.unlink(tmp)


def _read_stored(path: Path) -> str:
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        raise HandoffError("handoff_not_found", "%s does not exist" % path) from None
    if stat.S_ISLNK(mode):
        raise HandoffError("handoff_symlink", "%s is a symbolic link" % path)
    if not stat.S_ISREG(mode):
        raise HandoffError("handoff_input_invalid", "%s is not a regular file" % path)
    with os.fdopen(os.open(path, os.O_RDONLY | _NOFOLLOW), "rb") as fh:
        data = fh.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HandoffError("handoff_too_large", "%s is more than %d bytes" % (path, MAX_FILE_BYTES))
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HandoffError("handoff_input_invalid", "%s is not UTF-8: %s" % (path, exc)) from exc


def _highest(run_dir: Path) -> int:
    numbers = [int(entry.name[:-5]) for entry in os.scandir(run_dir)
               if _CONTINUATION_FILE.fullmatch(entry.name) and not entry.is_dir(follow_symlinks=False)]
    if not numbers:
        raise HandoffError("handoff_not_found", "%s holds no handoff" % run_dir)
    return max(numbers)


# --- commands ------------------------------------------------------------------------------------------------------------

def _write(args: argparse.Namespace) -> dict:
    root = _root(args.repo)
    clean, redacted = redact_handoff(_parse_object(_read_text(args.file), "the input"))
    validate_handoff(clean)  # after the mask: a mask can be longer than what it hides
    path = handoff_path(root, clean["run_id"], clean["continuation"])
    _walk(root, _parts(clean["run_id"]), create=True)
    _publish(path, json.dumps(clean, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return {"path": path.relative_to(root).as_posix(), "continuation": clean["continuation"], "redacted": redacted}


def _read(args: argparse.Namespace) -> dict:
    root = _root(args.repo)
    handoff_path(root, args.run, 1 if args.n is None else args.n)  # checks the run id and the number
    run_dir = _walk(root, _parts(args.run), create=False)
    n = _highest(run_dir) if args.n is None else args.n
    path = handoff_path(root, args.run, n)
    doc = _parse_object(_read_stored(path), str(path))
    validate_handoff(doc)
    if doc["run_id"] != args.run or doc["continuation"] != n:
        raise HandoffError("handoff_location_mismatch", "%s holds run %r continuation %r" % (path, doc["run_id"], doc["continuation"]))
    return doc


def _projection(args: argparse.Namespace) -> Projection:
    counters = (args.input_tokens, args.cache_read, args.cache_write)
    if all(c is None for c in counters):
        if args.prompt_file is None:
            raise HandoffError("usage_invalid", "give --input-tokens, --cache-read and --cache-write, or --prompt-file for an estimate")
        if args.added_file is not None:
            raise HandoffError("usage_invalid", "--added-file goes with the measured counters, not with --prompt-file")
        return Projection.estimated(_read_text(args.prompt_file))
    if any(c is None for c in counters):
        raise HandoffError("usage_invalid", "give all three of --input-tokens, --cache-read and --cache-write")
    if args.prompt_file is not None:
        raise HandoffError("usage_invalid", "a measured count and --prompt-file never mix")
    try:
        usage = PromptUsage(*counters)
    except ValueError as exc:
        raise HandoffError("usage_invalid", str(exc)) from exc
    return Projection.measured(usage, "" if args.added_file is None else _read_text(args.added_file))


def _check(args: argparse.Namespace) -> dict:
    projection = _projection(args)
    verdict = check_budget(projection, _ceiling(_root(args.repo)))
    return {"status": verdict.status, "basis": verdict.basis, "tokens": verdict.tokens, "ceiling": verdict.ceiling,
            "soft_limit": verdict.soft_limit, "headroom": verdict.headroom, "ratio": round(verdict.ratio, 4),
            "measured_base": projection.measured_base, "estimated_tokens": projection.estimated_tokens,
            "estimator": projection.estimator}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simplicio-loop handoff", description="Write, read and check agent handoffs (simplicio.agent-handoff/v1).",
        epilog="check exits 0 for ok, 3 for handoff, 4 for over; every command exits 2 on an error.")
    sub = parser.add_subparsers(dest="handoff_command", required=True)
    write = sub.add_parser("write", help="mask secrets, validate and store a handoff")
    write.add_argument("--repo", default=".")
    write.add_argument("--file", default="-", help="the handoff JSON (default: stdin)")
    read = sub.add_parser("read", help="print a stored handoff")
    read.add_argument("--repo", default=".")
    read.add_argument("--run", required=True, help="run id")
    read.add_argument("--n", type=int, default=None, help="continuation number (default: the highest)")
    check = sub.add_parser("check", help="ok, handoff or over for the next request")
    check.add_argument("--repo", default=".")
    check.add_argument("--input-tokens", type=int, default=None, help="new input tokens of the last request")
    check.add_argument("--cache-read", type=int, default=None, help="cache read tokens of the last request")
    check.add_argument("--cache-write", type=int, default=None, help="cache write tokens of the last request")
    check.add_argument("--added-file", default=None, help="text that the next request adds (path or -)")
    check.add_argument("--prompt-file", default=None, help="whole prompt when no usage is known: ESTIMATED (path or -)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.handoff_command == "read":
            result = _read(args)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0
        result = _write(args) if args.handoff_command == "write" else _check(args)
    except (HandoffError, CeilingConfigError) as exc:
        print(json.dumps({"status": "error", "reason_code": exc.reason_code, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(json.dumps({"status": "error", "reason_code": "handoff_io_error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return EXIT_STATUS.get(result.get("status"), 0)
