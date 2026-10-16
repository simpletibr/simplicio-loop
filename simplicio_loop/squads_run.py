"""`simplicio-loop squads run` (#1829): execute a wave that `squads plan --json` already planned.

Input: the plan JSON (`squads.SquadPlan.to_dict()`), and optionally the issues file, whose titles and bodies are the task text.

Per squad, in plan order (a squad whose state already says ready, blocked or merged is not run again):
  1. a git worktree on a new branch `squads/<run>/<squad>`, from `--base`; the run folder is `<repo>/.simplicio/squads-run/<run>`;
  2. ONE execution-role worker (model and effort from the plan) through the injected launcher. Its prompt carries the task
     text, the owned paths, the shared-file rules and the contracts it must honor;
  3. after every launch, the changed files (against the base, untracked ones included) must be owned by the squad and must
     not be shared files. A violation stops that squad, names the paths, and nothing from it is merged;
  4. a launch that returns `budget_exhausted` writes a handoff note (`.simplicio/handoff.md` in the worktree) and launches a
     continuation, at most `max_continuations` times, then the squad is BLOCKED;
  5. a squad whose ownership check passed is committed on its branch, and its tests run there (ready when they pass).

Merge (only with `--execute` and at least one `--approver`): the ready squads in merge order. Each branch is pushed (never
forced), gets a PR, and merges only when `squads.squad_gate` finds an authorized approval on the PR's head. Without an approver
the run stops after step 5: nothing is pushed or merged. `batch` merges one PR at a time and verifies main after each merge.
`lockfree` hands the PRs to `merge_lockfree.merge_pass`. A red main stops the run; no revert is opened here.

A dry run (no `--execute`) prints the preview and the exact commands, and spawns nothing.

Injected seams (tests use fakes; the defaults are the real commands):
  * `Deps.launcher(LaunchRequest) -> WorkerOutcome`: the default runs the template of SIMPLICIO_SQUADS_WORKER_CMD (default
    `claude -p --model {model}`) in the worktree, with the prompt on stdin. Exit 0 = done, 75 = budget_exhausted, else failed.
  * `Deps.tester(worktree) -> (ok, output)`: default SIMPLICIO_SQUADS_TEST_CMD (default `python3 -m pytest -q`).
  * `Deps.hosting`: push / open_pr / gate / merge. The default uses git and gh (REST).
  * `Deps.verify(sha) -> (ok, output)`: the tests on main at a merged commit.
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import merge_lockfree, next_step, squads

RUN_SCHEMA = "simplicio.squad-run/v1"
WORKER_CMD_ENV = "SIMPLICIO_SQUADS_WORKER_CMD"
TEST_CMD_ENV = "SIMPLICIO_SQUADS_TEST_CMD"
MAX_CONTINUATIONS_ENV = "SIMPLICIO_SQUADS_MAX_CONTINUATIONS"
DEFAULT_WORKER_CMD = "claude -p --model {model}"
DEFAULT_TEST_CMD = "python3 -m pytest -q"
DEFAULT_MAX_CONTINUATIONS = 3
DEFAULT_BASE = "main"
REMOTE = "origin"
BUDGET_EXIT_CODE = 75  # the default launcher's typed budget_exhausted signal (EX_TEMPFAIL)
WORKER_TIMEOUT_S = 3600
TEST_TIMEOUT_S = 1800
SCRATCH = ".simplicio"  # bookkeeping folder inside a worktree: never committed, never counted as a change
HANDOFF_NAME = "handoff.md"
PROGRESS_NAME = "progress.md"
STATUS_DONE = "done"
STATUS_BUDGET = "budget_exhausted"
STATUS_FAILED = "failed"
WORKER_STATUSES = (STATUS_DONE, STATUS_BUDGET, STATUS_FAILED)
STATE_PENDING, STATE_READY, STATE_BLOCKED, STATE_MERGED = "pending", "ready", "blocked", "merged"
MERGE_STOP_APPROVAL = "approval"


class RunError(RuntimeError):
    """The run cannot start or cannot record its state (bad plan, unusable repository, another plan's run folder)."""


@dataclass(frozen=True)
class WorkerOutcome:
    """What a launch returned. `status` is one of done, budget_exhausted, failed (the typed launcher contract)."""

    status: str
    detail: str = ""
    report: str = ""  # the worker's own progress note, carried into the handoff note

    def __post_init__(self) -> None:
        if self.status not in WORKER_STATUSES:
            raise ValueError("worker status must be one of %s, got %r" % (", ".join(WORKER_STATUSES), self.status))


@dataclass(frozen=True)
class LaunchRequest:
    squad: str
    worktree: Path
    model: str
    effort: str
    owned: Tuple[str, ...]
    prompt: str
    attempt: int  # 1 = the first run; n = the (n-1)th continuation


@dataclass
class Deps:
    launcher: Callable[[LaunchRequest], WorkerOutcome]
    tester: Callable[[Path], Tuple[bool, str]]
    hosting: Any  # push(worktree, branch) / open_pr(branch, title, body) / gate(pr, approvers) / merge(pr, head)
    verify: Callable[[str], Tuple[bool, str]]


@dataclass(frozen=True)
class _Squad:
    id: str
    name: str
    wave: int
    issues: Tuple[int, ...]
    owned: Tuple[str, ...]
    blocked_by: Tuple[str, ...]
    model: str
    effort: str


# ---------------------------------------------------------------------------------------------- plan


def plan_id(plan: Mapping[str, Any]) -> str:
    """A stable id of one plan (12 hex of its canonical JSON): the run folder and the branch names carry it."""
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _parse_plan(plan: Any) -> Tuple[List[_Squad], List[Tuple[int, str]], Tuple[str, ...], List[Mapping[str, Any]]]:
    if not isinstance(plan, Mapping) or plan.get("schema") != squads.PLAN_SCHEMA:
        raise RunError("--plan is not a squads plan (schema %s): pass the output of `simplicio-loop squads plan --json`"
                       % squads.PLAN_SCHEMA)
    raw_squads = plan.get("squads") or []
    if not raw_squads:
        raise RunError("the plan has no squads")
    out: List[_Squad] = []
    for raw in raw_squads:
        workers = raw.get("workers") or []
        if not workers:
            raise RunError("squad %s has no worker in the plan" % raw.get("id"))
        worker = workers[0]  # one execution worker per squad (the squad's worker takes all its issues)
        out.append(_Squad(
            id=str(raw["id"]), name=str(raw.get("name") or raw["id"]), wave=int(raw.get("wave") or 1),
            issues=tuple(int(n) for n in raw.get("issues") or ()), owned=tuple(sorted(str(p) for p in raw.get("owned_paths") or ())),
            blocked_by=tuple(str(s) for s in raw.get("blocked_by") or ()), model=str(worker.get("model") or ""),
            effort=str(worker.get("effort") or ""),
        ))
    ids = [s.id for s in out]
    if len(set(ids)) != len(ids):
        raise RunError("the plan has two squads with the same id")
    merge_order = [(int(step["issue"]), str(step["squad"])) for step in plan.get("merge_order") or []]
    shared = tuple(str(p) for p in (plan.get("shared_files") or squads.SHARED_FILE_PATTERNS))
    return out, merge_order, shared, list(plan.get("contracts") or [])


def _launch_order(items: Sequence[_Squad], merge_order: Sequence[Tuple[int, str]]) -> List[_Squad]:
    position = {}
    for _issue, sid in merge_order:
        position.setdefault(sid, len(position))
    return sorted(items, key=lambda s: (s.wave, position.get(s.id, len(position)), s.id))


def _merge_sequence(items: Sequence[_Squad], merge_order: Sequence[Tuple[int, str]]) -> List[_Squad]:
    by_id = {s.id: s for s in items}
    seen: List[_Squad] = []
    for _issue, sid in merge_order:
        if sid in by_id and by_id[sid] not in seen:
            seen.append(by_id[sid])
    return seen + [s for s in items if s not in seen]


def _tail(text: Optional[str], limit: int = 600) -> str:
    cleaned = (text or "").strip()
    return cleaned[-limit:] if len(cleaned) > limit else cleaned


def _render(template: str, values: Mapping[str, str]) -> List[str]:
    """The argv of a command template: shell-split first, then each placeholder replaced inside its own token."""
    argv = []
    for token in shlex.split(template):
        for key, value in values.items():
            token = token.replace("{%s}" % key, value)
        argv.append(token)
    return argv


def _issue_text(squad: _Squad, tasks: Mapping[int, Mapping[str, Any]]) -> str:
    lines = []
    for number in squad.issues:
        issue = tasks.get(number) or {}
        lines.append("### #%d: %s" % (number, issue.get("title") or "(no title: pass --issues)"))
        body = str(issue.get("body") or "").strip()
        if body:
            lines.append(body)
    return "\n".join(lines) or "(no task text: pass --issues with the issue objects)"


def _worker_prompt(squad: _Squad, worktree: Path, tasks: Mapping[int, Mapping[str, Any]], shared: Sequence[str],
                   contracts: Sequence[Mapping[str, Any]]) -> str:
    owned = "\n".join("- %s" % p for p in squad.owned) or "- (none: any change stops this squad)"
    lines = [
        "You are the execution worker of squad %s (%s) in a `simplicio-loop squads run`." % (squad.id, squad.name),
        "Work only in this worktree: %s" % worktree,
        "",
        "## Task",
        _issue_text(squad, tasks),
        "",
        "## File ownership (hard rule)",
        "Edit only these paths:",
        owned,
        "Shared files are never yours (only the general coordinator edits them): %s." % ", ".join(shared[:12]),
        "A change outside the list stops your squad, and nothing from it is merged.",
        "",
        "## Interfaces you must honor",
    ]
    mine = [c for c in contracts if squad.id in (c.get("producer"), c.get("consumer"))]
    lines += ["- %s -> %s: %s" % (c.get("producer"), c.get("consumer"), c.get("signature") or c.get("function") or "")
              for c in mine] or ["- none"]
    lines += [
        "",
        "## Rules",
        "- Do not commit, push, merge or open a pull request: the coordinator does that.",
        "- Keep a progress note in .simplicio/%s with the sections \"## Done\" and \"## Remaining\"; update it before you stop."
        % PROGRESS_NAME,
        "- If you run out of context or turn budget, stop: the coordinator writes a handoff note and continues you.",
    ]
    return "\n".join(lines) + "\n"


def _continuation_prompt(prompt: str, handoff: str) -> str:
    return (prompt + "\n## Handoff from the previous attempt\n" + handoff +
            "\nContinue from the remaining items only. Do not redo what is done.\n")


def _handoff_note(squad: _Squad, outcome: WorkerOutcome, attempt: int, changed: Sequence[str]) -> str:
    report = outcome.report.strip() or "(no %s/%s was written; launcher detail: %s)" % (SCRATCH, PROGRESS_NAME, outcome.detail or "none")
    files = "\n".join("- %s" % p for p in changed) or "- (none yet)"
    owned = "\n".join("- %s" % p for p in squad.owned) or "- (none)"
    return ("# Handoff: squad %s (%s)\n\n"
            "Attempt %d stopped at its context or turn budget (budget_exhausted).\n\n"
            "## Done and remaining (worker report)\n%s\n\n"
            "## Files touched\n%s\n\n"
            "## Owned paths\n%s\n") % (squad.id, squad.name, attempt, report, files, owned)


# ---------------------------------------------------------------------------------------------- git and files


def _git(cwd: Path, *args: str, timeout: float = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False,
                          encoding="utf-8", errors="replace")


def _is_scratch(path: str) -> bool:
    return path == SCRATCH or path.startswith(SCRATCH + "/")


def changed_files(worktree: Path, base_sha: str) -> List[str]:
    """Every path that differs from the base (tracked and untracked), minus the run's own scratch folder."""
    tracked = _git(worktree, "diff", "--name-only", base_sha)
    untracked = _git(worktree, "ls-files", "--others", "--exclude-standard")
    if tracked.returncode or untracked.returncode:
        raise RunError("git could not list the changed files of %s: %s" % (worktree, _tail(tracked.stderr or untracked.stderr)))
    paths = {line.strip().replace("\\", "/") for line in (tracked.stdout + "\n" + untracked.stdout).splitlines()}
    return sorted(p for p in paths if p and not _is_scratch(p))


def violations(paths: Sequence[str], owned: Sequence[str], shared: Sequence[str]) -> List[str]:
    """The changed paths that the squad does not own, plus every shared file (a shared file is never a worker's, glob or not)."""
    bad = []
    for path in paths:
        is_shared = any(fnmatch.fnmatchcase(path, pattern) for pattern in shared)
        is_owned = any(fnmatch.fnmatchcase(path, pattern) for pattern in owned)
        if is_shared or not is_owned:
            bad.append(path)
    return bad


def _resolve_base(repo: Path, base: str) -> str:
    found = _git(repo, "rev-parse", "--verify", "--quiet", "%s^{commit}" % base)
    if found.returncode or not found.stdout.strip():
        raise RunError("base %r is not a commit of %s" % (base, repo))
    return found.stdout.strip()


def _write_handoff(worktree: Path, note: str) -> None:
    folder = worktree / SCRATCH
    folder.mkdir(parents=True, exist_ok=True)
    (folder / HANDOFF_NAME).write_text(note, encoding="utf-8")


def _read_progress(worktree: Path) -> str:
    try:
        return (worktree / SCRATCH / PROGRESS_NAME).read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------------------------------------- default seams


def command_launcher(template: str) -> Callable[[LaunchRequest], WorkerOutcome]:
    """The default launcher: the template's argv runs in the worktree with the prompt on stdin."""

    def launch(request: LaunchRequest) -> WorkerOutcome:
        argv = _render(template, {"model": request.model, "effort": request.effort, "squad": request.squad,
                                  "worktree": str(request.worktree)})
        if not argv:
            raise RunError("the worker command is empty (%s)" % WORKER_CMD_ENV)
        try:
            done = subprocess.run(argv, input=request.prompt, cwd=str(request.worktree), capture_output=True, text=True,
                                  timeout=WORKER_TIMEOUT_S, check=False, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return WorkerOutcome(STATUS_FAILED, detail="worker command not found: %s" % argv[0])
        except subprocess.TimeoutExpired:
            return WorkerOutcome(STATUS_FAILED, detail="worker timed out after %d s" % WORKER_TIMEOUT_S)
        report = _read_progress(request.worktree)
        if done.returncode == 0:
            return WorkerOutcome(STATUS_DONE, report=report)
        if done.returncode == BUDGET_EXIT_CODE:
            return WorkerOutcome(STATUS_BUDGET, detail=_tail(done.stderr or done.stdout, 300), report=report)
        return WorkerOutcome(STATUS_FAILED, detail="exit %d: %s" % (done.returncode, _tail(done.stderr or done.stdout, 300)),
                             report=report)

    return launch


def command_tester(template: str) -> Callable[[Path], Tuple[bool, str]]:
    def test(worktree: Path) -> Tuple[bool, str]:
        argv = shlex.split(template)
        try:
            done = subprocess.run(argv, cwd=str(worktree), capture_output=True, text=True, timeout=TEST_TIMEOUT_S, check=False,
                                  encoding="utf-8", errors="replace")
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return False, "the test command could not finish: %s" % exc
        return done.returncode == 0, _tail(done.stdout + "\n" + done.stderr)

    return test


class GitHubHosting:
    """push, PR, gate and merge through git and gh (REST). Nothing here forces a push or a merge."""

    def __init__(self, repo: Path, base: str) -> None:
        self.repo = repo
        self.base = base
        self._slug: Optional[str] = None

    def _gh(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["gh", *args], cwd=str(self.repo), capture_output=True, text=True, timeout=120, check=False,
                              encoding="utf-8", errors="replace")

    def slug(self) -> str:
        if self._slug is None:
            found = self._gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
            if found.returncode or not found.stdout.strip():
                raise RunError("gh could not name the repository: %s" % _tail(found.stderr))
            self._slug = found.stdout.strip()
        return self._slug

    def push(self, worktree: Path, branch: str) -> None:
        pushed = subprocess.run(["git", "push", "-u", REMOTE, branch], cwd=str(worktree), capture_output=True, text=True,
                                timeout=180, check=False, encoding="utf-8", errors="replace")
        if pushed.returncode:
            raise RunError("push of %s was refused (nothing was forced): %s" % (branch, _tail(pushed.stderr)))

    def open_pr(self, branch: str, title: str, body: str) -> int:
        opened = self._gh("api", "-X", "POST", "repos/%s/pulls" % self.slug(), "-f", "title=%s" % title, "-f", "head=%s" % branch,
                          "-f", "base=%s" % self.base, "-f", "body=%s" % body, "--jq", ".number")
        if opened.returncode or not opened.stdout.strip().isdigit():
            raise RunError("the pull request for %s was not opened: %s" % (branch, _tail(opened.stderr or opened.stdout)))
        return int(opened.stdout.strip())

    def gate(self, pr: int, approvers: Sequence[str]) -> Dict[str, Any]:
        try:
            return asyncio.run(squads.squad_gate_for_pr(self.slug(), pr, approvers=approvers))
        except squads.SquadGateError as exc:  # fails closed: an unreadable PR is not an approved one
            return {"approved": False, "reason": "gate_error: %s" % exc}

    def merge(self, pr: int, head: str) -> Optional[str]:
        merged = self._gh("api", "-X", "PUT", "repos/%s/pulls/%d/merge" % (self.slug(), pr), "-f", "merge_method=squash",
                          "-f", "sha=%s" % head, "--jq", ".sha")
        sha = merged.stdout.strip() if merged.returncode == 0 else ""
        return sha or None


def make_verify(repo: Path, run_dir: Path, tester: Callable[[Path], Tuple[bool, str]]) -> Callable[[str], Tuple[bool, str]]:
    """The tests on main at a merged commit, in a detached worktree of the run folder (removed afterwards)."""

    def verify(sha: str) -> Tuple[bool, str]:
        if _git(repo, "fetch", "--quiet", REMOTE, "main").returncode:
            return False, "fetch of origin/main failed"
        path = run_dir / "verify" / sha[:12]
        if _git(repo, "worktree", "add", "--detach", str(path), sha).returncode:
            return False, "worktree of the merged commit %s could not be added" % sha[:12]
        try:
            return tester(path)
        finally:
            if _git(repo, "worktree", "remove", str(path)).returncode:
                shutil.rmtree(path, ignore_errors=True)
                _git(repo, "worktree", "prune")

    return verify


def default_deps(repo: Path, run_dir: Path, base: str, *, worker_cmd: str, test_cmd: str) -> Deps:
    tester = command_tester(test_cmd)
    return Deps(launcher=command_launcher(worker_cmd), tester=tester, hosting=GitHubHosting(repo, base),
                verify=make_verify(repo, run_dir, tester))


# ---------------------------------------------------------------------------------------------- preview


def build_preview(items: Sequence[_Squad], merge_order: Sequence[Tuple[int, str]], shared: Sequence[str], contracts: Sequence[Mapping[str, Any]],
                  *, repo: Path, run_dir: Path, run_id: str, base: str, mode: str, approvers: Sequence[str],
                  worker_cmd: str, test_cmd: str, max_continuations: int) -> Dict[str, Any]:
    rows = []
    for squad in _launch_order(items, merge_order):
        worktree = run_dir / "worktrees" / squad.id
        branch = "squads/%s/%s" % (run_id, squad.id)
        worker = _render(worker_cmd, {"model": squad.model, "effort": squad.effort, "squad": squad.id, "worktree": str(worktree)})
        commands = [
            "git -C %s worktree add -b %s %s %s" % (shlex.quote(str(repo)), branch, shlex.quote(str(worktree)), base),
            "%s   # cwd %s; stdin = the worker prompt" % (shlex.join(worker), worktree),
            "%s   # cwd %s; committed on %s when it passes" % (test_cmd, worktree, branch),
        ]
        if approvers:
            commands += [
                "git -C %s push -u %s %s" % (worktree, REMOTE, branch),
                "gh api -X POST repos/{owner}/{repo}/pulls -f head=%s -f base=%s   # then the gate of each PR" % (branch, base),
                "gh api -X PUT repos/{owner}/{repo}/pulls/<pr>/merge -f merge_method=squash -f sha=<head>   # only after the gate",
            ]
        rows.append({
            "squad": squad.id, "name": squad.name, "wave": squad.wave, "role": "execution", "model": squad.model,
            "effort": squad.effort, "issues": list(squad.issues), "owned_paths": list(squad.owned),
            "blocked_by": list(squad.blocked_by), "branch": branch, "worktree": str(worktree),
            "worker_command": shlex.join(worker), "commands": commands,
            "contracts": [c for c in contracts if squad.id in (c.get("producer"), c.get("consumer"))],
        })
    return {
        "schema": RUN_SCHEMA, "run": run_id, "base": base, "mode": mode, "run_dir": str(run_dir),
        "max_continuations": max_continuations, "squads": rows, "shared_files": list(shared),
        "merge_order": [{"issue": n, "squad": sid} for n, sid in merge_order],
        "merge": ("gated: pushed and merged only with an authorized approval of %s" % ", ".join(approvers))
        if approvers else "none: add --approver LOGIN to push, open the PRs and merge behind the approval gate",
    }


def format_preview(preview: Mapping[str, Any]) -> str:
    lines = [
        "squads run preview: plan %s, base %s, mode %s" % (preview["run"], preview["base"], preview["mode"]),
        "  run folder: %s   continuations per worker: at most %d" % (preview["run_dir"], preview["max_continuations"]),
        "",
        "Squads (one execution worker each):",
    ]
    for row in preview["squads"]:
        lines += [
            "  %s  wave %d  %s %s effort %s  issues %s" % (row["squad"], row["wave"], row["role"], row["model"], row["effort"],
                                                        ", ".join("#%d" % n for n in row["issues"])),
            "      owns:       %s" % (", ".join(row["owned_paths"]) or "(none: any change stops this squad)"),
            "      blocked by: %s" % (", ".join(row["blocked_by"]) or "none"),
            "      branch:     %s" % row["branch"],
        ]
    lines += ["", "Shared files (only the general coordinator edits them; a worker change to one stops its squad):"]
    lines += ["  - %s" % p for p in preview["shared_files"][:12]] or ["  (none)"]
    lines += ["", "Merge order (topological, as planned):"]
    lines += ["  %d. #%d -> %s" % (i, step["issue"], step["squad"]) for i, step in enumerate(preview["merge_order"], 1)]
    lines += ["  merge: %s" % preview["merge"], "", "Commands:"]
    for row in preview["squads"]:
        lines += ["  " + command for command in row["commands"]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- state


def _fresh_state(squad: _Squad, run_dir: Path, run_id: str) -> Dict[str, Any]:
    return {"status": STATE_PENDING, "branch": "squads/%s/%s" % (run_id, squad.id),
            "worktree": str(run_dir / "worktrees" / squad.id), "launches": 0, "continuations": 0, "reason_kind": "",
            "reason": "", "offending": [], "changed": [], "head": "", "tests_green": False, "pr": None, "merge": ""}


def _load_state(run_dir: Path, run_id: str, base: str, items: Sequence[_Squad]) -> Dict[str, Any]:
    path = run_dir / "state.json"
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RunError("the run state %s cannot be read: %s" % (path, exc))
        if state.get("run") != run_id or state.get("base") != base:
            raise RunError("the run folder %s belongs to another plan or base (run %s, base %s)" % (run_dir, state.get("run"), state.get("base")))
        return state
    return {"schema": RUN_SCHEMA, "run": run_id, "base": base, "base_sha": "",
            "squads": {s.id: _fresh_state(s, run_dir, run_id) for s in items}}


def _save_state(run_dir: Path, state: Mapping[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, run_dir / "state.json")


def _block(st: Dict[str, Any], kind: str, reason: str) -> None:
    st.update(status=STATE_BLOCKED, reason_kind=kind, reason=reason)


# ---------------------------------------------------------------------------------------------- one squad


def _run_squad(sq: _Squad, st: Dict[str, Any], *, repo: Path, run_dir: Path, base_sha: str, deps: Deps, shared: Sequence[str],
               contracts: Sequence[Mapping[str, Any]], tasks: Mapping[int, Mapping[str, Any]], max_continuations: int) -> None:
    worktree = Path(st["worktree"])
    if worktree.exists():
        return _block(st, "git", "the worktree %s already exists: a run is in progress or the run folder is stale" % worktree)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    added = _git(repo, "worktree", "add", "-b", st["branch"], str(worktree), base_sha)
    if added.returncode:
        return _block(st, "git", "git worktree add failed: %s" % _tail(added.stderr or added.stdout))

    prompt = _worker_prompt(sq, worktree, tasks, shared, contracts)
    handoff = ""
    while True:
        st["launches"] += 1
        request = LaunchRequest(sq.id, worktree, sq.model, sq.effort, sq.owned,
                                _continuation_prompt(prompt, handoff) if handoff else prompt, st["launches"])
        outcome = deps.launcher(request)
        st["changed"] = changed_files(worktree, base_sha)
        bad = violations(st["changed"], sq.owned, shared)
        if bad:
            st["offending"] = bad
            return _block(st, "ownership", "%d changed path(s) outside the ownership of %s: %s" % (len(bad), sq.id, ", ".join(bad)))
        if outcome.status == STATUS_FAILED:
            return _block(st, "failed", "the worker failed: %s" % (outcome.detail or "no detail"))
        if outcome.status == STATUS_DONE:
            break
        if st["continuations"] >= max_continuations:
            return _block(st, "budget", "budget_exhausted after %d continuation(s), the maximum" % st["continuations"])
        st["continuations"] += 1
        handoff = _handoff_note(sq, outcome, st["launches"], st["changed"])
        _write_handoff(worktree, handoff)

    if not st["changed"]:
        return _block(st, "no_changes", "the worker changed no file")
    dirty = _git(worktree, "status", "--porcelain", "--", ".", ":(exclude)%s" % SCRATCH)
    if dirty.returncode:
        return _block(st, "git", "git status failed: %s" % _tail(dirty.stderr))
    if dirty.stdout.strip():
        added = _git(worktree, "add", "-A", "--", ".", ":(exclude)%s" % SCRATCH)
        committed = _git(worktree, "commit", "-q", "-m", "squad %s: %s (issues %s)" % (
            sq.id, sq.name, ", ".join("#%d" % n for n in sq.issues)))
        if added.returncode or committed.returncode:
            return _block(st, "git", "git commit failed: %s" % _tail(added.stderr or committed.stderr or committed.stdout))
    head = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    ok, output = deps.tester(worktree)
    if not ok:
        st["tests_green"] = False
        return _block(st, "tests", "tests failed on %s: %s" % (st["branch"], _tail(output, 400)))
    st.update(status=STATE_READY, head=head, tests_green=True, reason_kind="", reason="", offending=[])


# ---------------------------------------------------------------------------------------------- merge phase


def _open_prs(order: Sequence[_Squad], state: Dict[str, Any], *, deps: Deps, run_id: str) -> None:
    for sq in order:
        st = state["squads"][sq.id]
        if st["status"] != STATE_READY or st["pr"]:
            continue
        try:
            deps.hosting.push(Path(st["worktree"]), st["branch"])
            st["pr"] = deps.hosting.open_pr(st["branch"], "squads run: %s (issues %s)" % (sq.name, ", ".join("#%d" % n for n in sq.issues)),
                                            "Squad %s of the squads run %s. Owned: %s. Tests passed on the branch before this PR. "
                                            "Merges only with the approval gate (simplicio-loop squads gate)."
                                            % (sq.id, run_id, ", ".join(sq.owned)))
        except RunError as exc:
            _block(st, "push", str(exc))


def _merge_batch(order: Sequence[_Squad], state: Dict[str, Any], *, deps: Deps, approvers: Sequence[str]) -> str:
    """One PR at a time, in merge order. Stops at the first PR the gate refuses, the first failed merge, or a red main."""
    for sq in order:
        st = state["squads"][sq.id]
        if st["status"] != STATE_READY:
            continue
        waits = [d for d in sq.blocked_by if state["squads"][d]["status"] != STATE_MERGED]
        if waits:
            st.update(reason_kind="dependency", reason="waits for %s to merge" % ", ".join(waits))
            continue
        verdict = deps.hosting.gate(st["pr"], approvers)
        if not verdict.get("approved"):
            st.update(reason_kind="gate", reason="approval gate: %s" % verdict.get("reason", "not approved"))
            return "gate"
        sha = deps.hosting.merge(st["pr"], st["head"])
        if not sha:
            _block(st, "merge", "the merge of PR #%s was refused by GitHub" % st["pr"])
            return "merge"
        st.update(status=STATE_MERGED, merge=sha, reason_kind="", reason="")
        ok, output = deps.verify(sha)
        if not ok:
            st.update(reason_kind="verify", reason="main is red after the merge of PR #%s: %s" % (st["pr"], _tail(output, 300)))
            return "verify"
    return ""


def _merge_lockfree(order: Sequence[_Squad], state: Dict[str, Any], *, deps: Deps, approvers: Sequence[str]) -> str:
    """The approved PRs through `merge_lockfree.merge_pass`: no batch, a red main halts the rest of the run."""
    ready = [sq for sq in order if state["squads"][sq.id]["status"] == STATE_READY and state["squads"][sq.id]["pr"]]
    prs = []
    for sq in ready:
        st = state["squads"][sq.id]
        verdict = deps.hosting.gate(st["pr"], approvers)
        prs.append(merge_lockfree.PRState(
            pr=st["pr"], issue=sq.issues[0] if sq.issues else 0, head=st["head"], files=frozenset(st["changed"]),
            approved=bool(verdict.get("approved")), gate_reason=str(verdict.get("reason", "")),
            tests_green=bool(st["tests_green"]), squad=sq.id))
    shas: Dict[int, str] = {}
    merged_ids: set = set()
    dep_wait: Dict[int, str] = {}
    by_pr = {state["squads"][sq.id]["pr"]: sq for sq in ready}

    def merge(pr: int, head: str) -> Optional[str]:
        sq = by_pr[pr]
        waits = [d for d in sq.blocked_by if d not in merged_ids]
        if waits:  # a dependency that did not merge first: this PR does not merge either
            dep_wait[pr] = "waits for %s to merge" % ", ".join(waits)
            return None
        sha = deps.hosting.merge(pr, head)
        if sha:
            shas[pr] = sha
            merged_ids.add(sq.id)
        return sha

    def run_tests(_selected: Any, sha: str) -> Tuple[bool, Tuple[str, ...]]:
        ok, output = deps.verify(sha)
        return ok, () if ok else (_tail(output, 300) or "verify failed",)

    async def check(_pr: int, sha: str) -> merge_lockfree.PostMerge:
        return await merge_lockfree.post_merge_check(sha, impacted=lambda _sha: None, run_tests=run_tests)

    def on_red(red: merge_lockfree.Red) -> merge_lockfree.Action:
        return merge_lockfree.Action("stopped", "", "main is red after PR #%d: no lock-free merge after it in this run" % red.pr)

    report = asyncio.run(merge_lockfree.merge_pass(prs, merge=merge, check=check, on_red=on_red))
    for pr in report.merged:
        st = state["squads"][by_pr[pr].id]
        st.update(status=STATE_MERGED, merge=shas.get(pr, ""), reason_kind="", reason="")
    for pr in report.failed:
        st = state["squads"][by_pr[pr].id]
        if pr in dep_wait:
            st.update(reason_kind="dependency", reason=dep_wait[pr])
        else:
            _block(st, "merge", "the merge of PR #%d was refused by GitHub" % pr)
    for pr, reason in report.refused.items():
        st = state["squads"][by_pr[pr].id]
        st.update(reason_kind="gate" if "approval" in reason else "refused", reason=reason)
    for pr, reason in report.waited.items():
        state["squads"][by_pr[pr].id].update(reason_kind="dependency", reason=reason)
    for pr, reason in report.pending.items():
        state["squads"][by_pr[pr].id].update(reason_kind="verify", reason="post-merge verify not finished: %s" % reason)
    if report.red:
        st = state["squads"][by_pr[report.red["pr"]].id]
        st.update(reason_kind="verify", reason="main is red after the merge of PR #%d" % report.red["pr"])
        return "verify"
    if report.pending:
        return "verify"
    return ""


# ---------------------------------------------------------------------------------------------- the run


_NEXT = {
    "ownership": "squad {id} changed paths outside its ownership ({detail}); fix the worker or the plan and rerun",
    "budget": "squad {id} stopped at its budget ({detail}); split its issues (squads plan --max-workers N) or raise --max-continuations and rerun",
    "failed": "squad {id}: the worker failed ({detail}); fix the cause and rerun",
    "tests": "squad {id}: its tests failed on its branch ({detail}); fix the branch and rerun",
    "no_changes": "squad {id}: the worker changed no file; check its task and rerun",
    "git": "squad {id}: {detail}; fix the repository state and rerun",
    "push": "squad {id}: {detail}; check the branch on origin (nothing was forced) and rerun",
    "merge": "squad {id}: {detail}; nothing after it merged",
    "verify": "squad {id}: {detail}; fix main before any further merge",
    "gate": "squad {id}: {detail}; approve PR #{pr} on GitHub, then rerun",
    "dependency": "squad {id}: {detail}",
    "refused": "squad {id}: {detail}",
}


def _next_line(state: Mapping[str, Any], stop: str, rerun: str) -> Optional[str]:
    for sid, st in state["squads"].items():
        if st["status"] == STATE_BLOCKED:
            text = _NEXT.get(st["reason_kind"], "squad {id}: {detail}").format(
                id=sid, detail=st["reason"], pr=st["pr"] or "?")
            return "%s; %s" % (text, rerun)
    if stop == MERGE_STOP_APPROVAL:
        return ("nothing was pushed or merged: rerun with --approver LOGIN to open the PRs, then approve each PR and rerun; %s" % rerun)
    for sid, st in state["squads"].items():
        if st["status"] == STATE_READY:
            if st["reason_kind"] in _NEXT:
                text = _NEXT[st["reason_kind"]].format(id=sid, detail=st["reason"], pr=st["pr"] or "?")
            else:
                text = "squad %s: %s" % (sid, st["reason"] or "waiting for its PR to be approved")
            return "%s; %s" % (text, rerun)
    return None


def run_plan(plan: Any, *, repo: Path, run_dir: Path, deps: Deps, base: str = DEFAULT_BASE, execute: bool = False,
             approvers: Sequence[str] = (), mode: str = merge_lockfree.MODE_BATCH,
             max_continuations: int = DEFAULT_MAX_CONTINUATIONS, tasks: Optional[Mapping[int, Mapping[str, Any]]] = None,
             worker_cmd: str = DEFAULT_WORKER_CMD, test_cmd: str = DEFAULT_TEST_CMD,
             on_preview: Optional[Callable[[Mapping[str, Any]], None]] = None) -> Dict[str, Any]:
    """Run (or preview) the plan. The preview goes to `on_preview` BEFORE any worker is launched (AGENTS.md: mandatory preview)."""
    if mode not in merge_lockfree.MODES:
        raise RunError("mode must be one of %s, got %r" % (", ".join(merge_lockfree.MODES), mode))
    if not isinstance(max_continuations, int) or isinstance(max_continuations, bool) or max_continuations < 0:
        raise RunError("max_continuations must be an integer >= 0")
    repo, run_dir = Path(repo), Path(run_dir)
    items, merge_order, shared, contracts = _parse_plan(plan)
    run_id = plan_id(plan)
    approvers = tuple(a.strip() for a in approvers if a and a.strip())
    preview = build_preview(items, merge_order, shared, contracts, repo=repo, run_dir=run_dir, run_id=run_id, base=base, mode=mode,
                            approvers=approvers, worker_cmd=worker_cmd, test_cmd=test_cmd, max_continuations=max_continuations)
    if on_preview is not None:
        on_preview(preview)
    if not execute:
        return {"schema": RUN_SCHEMA, "status": "DRY_RUN", "run": run_id, "preview": preview, "squads": {}, "merged": [],
                "reason": "dry run: nothing spawned; add --execute to run", "next": None}

    state = _load_state(run_dir, run_id, base, items)
    if not state.get("base_sha"):
        state["base_sha"] = _resolve_base(repo, base)
    base_sha = state["base_sha"]
    _save_state(run_dir, state)
    by_id = {s.id: s for s in items}
    order = _launch_order(items, merge_order)
    for sq in order:
        st = state["squads"][sq.id]
        if st["status"] == STATE_PENDING:
            _run_squad(sq, st, repo=repo, run_dir=run_dir, base_sha=base_sha, deps=deps, shared=shared, contracts=contracts,
                       tasks=tasks or {}, max_continuations=max_continuations)
            _save_state(run_dir, state)

    merge_seq = _merge_sequence(items, merge_order)
    stop = ""
    if not any(st["status"] == STATE_READY for st in state["squads"].values()):
        stop = ""
    elif not approvers:
        stop = MERGE_STOP_APPROVAL
    else:
        _open_prs(merge_seq, state, deps=deps, run_id=run_id)
        _save_state(run_dir, state)
        if mode == merge_lockfree.MODE_LOCKFREE:
            stop = _merge_lockfree(merge_seq, state, deps=deps, approvers=approvers)
        else:
            stop = _merge_batch(merge_seq, state, deps=deps, approvers=approvers)
    _save_state(run_dir, state)

    unfinished = [sid for sid, st in state["squads"].items() if st["status"] in (STATE_BLOCKED, STATE_READY)]
    status = "DONE" if not unfinished and not stop else "BLOCKED"
    rerun = "rerun: simplicio-loop squads run --plan <plan.json> --execute%s --run-dir %s" % (
        "".join(" --approver %s" % a for a in approvers), run_dir)
    problems = ["%s: %s" % (sid, state["squads"][sid]["reason"]) for sid in unfinished if state["squads"][sid]["reason"]]
    reason = "; ".join(problems) if problems else ("merge stopped: %s" % stop if stop else "")
    if stop == MERGE_STOP_APPROVAL and not problems:
        reason = "no approver given: the squads are ready and nothing was pushed or merged"
    return {
        "schema": RUN_SCHEMA, "status": status, "run": run_id, "base": base, "base_sha": base_sha, "mode": mode,
        "run_dir": str(run_dir), "squads": state["squads"], "merged": [sid for sid in (s.id for s in merge_seq)
                                                                          if state["squads"][sid]["status"] == STATE_MERGED],
        "merge_order": [{"issue": n, "squad": sid} for n, sid in merge_order if sid in by_id], "preview": preview,
        "reason": reason, "next": _next_line(state, stop, rerun) if status == "BLOCKED" else None,
    }


# ---------------------------------------------------------------------------------------------- CLI


def _load_json(raw: str) -> Any:
    if raw == "-":
        text = sys.stdin.read()
    elif os.path.isfile(raw):
        try:
            text = Path(raw).read_text(encoding="utf-8")
        except OSError as exc:
            raise RunError("cannot read --plan %s: %s" % (raw, exc))
    else:
        text = raw
    try:
        return json.loads(text)
    except ValueError as exc:
        raise RunError("--plan is not JSON (%s): pass a file path, '-' for stdin, or the JSON itself" % exc)


def _max_continuations(raw: Optional[int]) -> int:
    if raw is not None:
        return raw
    text = os.environ.get(MAX_CONTINUATIONS_ENV, "").strip()
    if not text:
        return DEFAULT_MAX_CONTINUATIONS
    try:
        return int(text)
    except ValueError:
        raise RunError("%s must be an integer >= 0, got %r" % (MAX_CONTINUATIONS_ENV, text))


def configure_run(subparsers: argparse._SubParsersAction) -> None:
    run = subparsers.add_parser(
        "run", help="execute a planned wave: one worktree and one worker per squad, ownership check, continuation, "
                    "merge in plan order behind the approval gate (a dry run unless --execute)",
        description="Execute the output of `squads plan --json`. Without --execute it prints the preview and the exact "
                    "commands and spawns nothing. With --execute it runs the workers, checks the ownership of every change, "
                    "commits and tests each squad, and merges only with an authorized approval (--approver).")
    run.add_argument("--plan", required=True, metavar="PATH|-|JSON",
                     help="the output of `squads plan --json`: a file path, '-' for stdin, or the JSON itself")
    run.add_argument("--issues", default="", metavar="PATH|-|JSON",
                     help="the issues of the plan (as for squads plan); their titles and bodies are the worker's task text")
    run.add_argument("--execute", action="store_true",
                     help="really run the workers, commit and test each squad, and merge with the approval gate; "
                          "without it the command only prints the preview (nothing is spawned)")
    run.add_argument("--approver", action="append", default=[], metavar="LOGIN",
                     help="gh login whose approval lets a PR merge (repeatable). Without it, nothing is pushed or merged")
    run.add_argument("--mode", choices=merge_lockfree.MODES, default=merge_lockfree.MODE_BATCH,
                     help="merge path: batch (one PR at a time, main verified after each; default) or lockfree (approved "
                          "PRs merge without waiting for each other, a red main stops the run)")
    run.add_argument("--max-continuations", type=int, default=None, metavar="N",
                     help="continuations of a worker that stops at its budget before its squad is BLOCKED (default: %d, "
                          "or SIMPLICIO_SQUADS_MAX_CONTINUATIONS)" % DEFAULT_MAX_CONTINUATIONS)
    run.add_argument("--repo", default=".", help="the git repository the squads branch from (default: current directory)")
    run.add_argument("--base", default=DEFAULT_BASE, help="the ref each squad branches from and merges into (default: main)")
    run.add_argument("--run-dir", default="", metavar="DIR",
                     help="folder for the worktrees and state.json (default: <repo>/.simplicio/squads-run/<plan id>); "
                          "a rerun of the same plan resumes from it")
    run.add_argument("--json", action="store_true", help="machine-readable output: one JSON document with the preview inside")


def dispatch(args: argparse.Namespace) -> int:
    """0 = dry run or done, 2 = BLOCKED (with one `next:` line on stderr)."""
    repo = Path(args.repo).resolve()
    try:
        plan = _load_json(args.plan)
        run_id = plan_id(plan) if isinstance(plan, Mapping) else "invalid"
        run_dir = Path(args.run_dir) if args.run_dir else repo / ".simplicio" / "squads-run" / run_id
        tasks: Dict[int, Mapping[str, Any]] = {}
        if args.issues:
            for issue in squads._load_issues(args.issues):
                tasks[int(squads._number(issue.get("number")))] = issue
        worker_cmd = os.environ.get(WORKER_CMD_ENV) or DEFAULT_WORKER_CMD
        test_cmd = os.environ.get(TEST_CMD_ENV) or DEFAULT_TEST_CMD
        deps = default_deps(repo, run_dir, args.base, worker_cmd=worker_cmd, test_cmd=test_cmd)
        on_preview = None if args.json else (lambda p: print(format_preview(p)))
        result = run_plan(plan, repo=repo, run_dir=run_dir, deps=deps, base=args.base, execute=args.execute,
                          approvers=args.approver, mode=args.mode, max_continuations=_max_continuations(args.max_continuations),
                          tasks=tasks, worker_cmd=worker_cmd, test_cmd=test_cmd, on_preview=on_preview)
    except (RunError, squads.SquadPlanError, ValueError, OSError) as exc:
        payload = {"schema": RUN_SCHEMA, "status": "BLOCKED", "error": type(exc).__name__, "reason": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        next_step.emit("%s; pass --plan with the output of `simplicio-loop squads plan --json` (simplicio-loop squads run --help)"
                       % exc)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    elif result["status"] == "DRY_RUN":
        print("\nDRY RUN: nothing was spawned. Add --execute to run the workers.")
    else:
        for sid, st in result["squads"].items():
            print("%s  %s  %s" % (sid, st["status"], st["reason"]))
        print("merged: %s" % (", ".join(result["merged"]) or "none"))
    if result["status"] == "BLOCKED":
        next_step.emit(result["next"] or result["reason"])
        return 2
    return 0
