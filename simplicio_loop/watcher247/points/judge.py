"""judge (verify, blocking): an ACCEPT/REJECT verdict on the applied diff; a REJECT blocks the PR.

Deterministic checks only, first and cheap: the diff is empty, it touches files outside the plan, it removes or
skips tests, it carries a secret (``secret_scan.scan_diff``, the scan that already guards the push). The reasons
become ``review_panel`` findings and the verdict words are the panel's (``pass`` is ACCEPT, ``fix-required`` is
REJECT). The verdict is saved to ``<run_dir>/judge.json`` for ``delivery_gate``, which does not re-run the scan.
"""
import json
import re

from ... import review_panel
from .. import proc, secret_scan, state
from . import _plan
from .registry import PointContext, PointResult, register

NAME = "judge"
VERDICT_FILE = "judge.json"
ACCEPT, REJECT = "ACCEPT", "REJECT"
ROLE = "blast_radius_reviewer"
_VERDICT = {review_panel.VERDICT_PASS: ACCEPT, review_panel.VERDICT_FIX_REQUIRED: REJECT}
_STATE_DIRS = (".simplicio-loop/", ".simplicio/")  # the loop's own files are never part of the change
_UNTRACKED_CAP = 200_000
_FILE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*$|_test\.[^/]+$|\.(test|spec)\.[^/]+$")
_TEST_DEF = re.compile(
    r"^[+-]\s*(?:async\s+def\s+(test\w*)|def\s+(test\w*)|func\s+(Test\w*)"
    r"|(?:it|test|describe)\(\s*['\"`](.+?)['\"`])", re.MULTILINE)
_SKIP = re.compile(
    r"^\+.*(?:@pytest\.mark\.(?:skip\b|xfail)|\bpytest\.(?:skip|xfail)\(|@unittest\.(?:skip|expectedFailure)"
    r"|\b(?:it|test|describe)\.skip\(|\bx(?:it|describe)\(|#\[ignore\]|\bt\.Skip\()", re.MULTILINE)


def _segments(diff: str) -> dict[str, str]:
    """The diff split per file (keyed by the new path)."""
    marks = list(_FILE.finditer(diff))
    return {mark.group(2): diff[mark.start():(marks[i + 1].start() if i + 1 < len(marks) else len(diff))]
            for i, mark in enumerate(marks) if not mark.group(2).startswith(_STATE_DIRS)}


def _defs(text: str, sign: str) -> set[str]:
    return {next(g for g in m.groups() if g) for m in _TEST_DEF.finditer(text) if m.group(0).startswith(sign)}


def _changes(status: str) -> tuple[list[str], list[str], list[str]]:
    """(changed, deleted, untracked) paths of `git status --porcelain`, read as the tick's `dirty` reads it."""
    changed, deleted, untracked = [], [], []
    for line in status.splitlines():
        code, path = line[:2], line[3:].split(" -> ")[-1].strip('"')
        if not path or path.startswith(_STATE_DIRS) or path == ".gitignore":
            continue
        changed.append(path)
        if "D" in code:
            deleted.append(path)
        if code == "??":
            untracked.append(path)
    return changed, deleted, untracked


def _untracked(ctx: PointContext, untracked: list[str]) -> str:
    """New files as a diff of added lines, so they get the same checks (read-only: nothing is staged)."""
    parts = []
    for rel in untracked:
        try:
            text = (ctx.clone / rel).read_text(encoding="utf-8", errors="replace")[:_UNTRACKED_CAP]
        except OSError:
            continue
        body = "".join(f"+{line}\n" for line in text.splitlines())
        parts.append(f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n{body}")
    return "".join(parts)


def _review(files: list[str], deleted: list[str], segments: dict[str, str], planned: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {
        "outside_plan": [path for path in files if planned and path not in planned],
        "test_removed": [path for path in deleted if _TEST_PATH.search(path)],
        "test_skipped": []}
    for path, text in segments.items():
        if not _TEST_PATH.search(path) or path in deleted:
            continue
        found["test_removed"] += [f"{path}:{name}" for name in sorted(_defs(text, "-") - _defs(text, "+"))]
        if _SKIP.search(text):
            found["test_skipped"].append(path)
    return found


_CLASS = {"empty_diff": "correctness", "outside_plan": "blast_radius", "test_removed": "correctness",
          "test_skipped": "correctness", "secret_detected": "security"}


def _findings(items: dict[str, list[str]]) -> list[dict]:
    findings = [review_panel.make_finding(role_id=ROLE, file=item.split(":")[0] or "(diff)", line=0, claim=reason,
                                          finding_class=_CLASS[reason], confidence="high")
                for reason, values in items.items() for item in (values or ["(diff)"])]
    return review_panel.dedup_findings(findings)


async def judge(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    status = await proc.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ctx.clone)
    tracked = await proc.run(["git", "diff", "HEAD", "--unified=0", "--no-color"], cwd=ctx.clone)
    for done in (status, tracked):  # a diff that cannot be read is not an empty diff: fail closed
        if done.returncode != 0:
            return PointResult(NAME, "error", {"error": (done.stderr or "")[-300:]}, "git_failed")
    files, deleted, untracked = _changes(status.stdout)
    segments = _segments(tracked.stdout + _untracked(ctx, untracked))
    found = _review(files, deleted, segments, _plan.plan_paths(ctx.plan, ctx.turbo_json))
    secrets = secret_scan.scan_diff("".join(segments.values())) if segments else []
    found = {"empty_diff": [] if files else ["(diff)"], **found, "secret_detected": secrets}
    found = {reason: values for reason, values in found.items() if values}
    reasons = list(found)
    verdict = _VERDICT[review_panel.VERDICT_FIX_REQUIRED if reasons else review_panel.VERDICT_PASS]
    files = sorted(files)
    saved = {"verdict": verdict, "reasons": reasons, "files": files, "secret_files": secrets}
    _save(ctx, saved)
    evidence = {**saved, **{k: v for k, v in found.items() if k not in ("empty_diff", "secret_detected")},
                "findings": _findings(found)}
    if reasons:
        return PointResult(NAME, "blocked", evidence, reasons[0])
    return PointResult(NAME, "ok", evidence)


def _save(ctx: PointContext, verdict: dict) -> None:
    """Best effort: when this fails delivery_gate finds no verdict and blocks (it fails closed)."""
    if ctx.run_dir is None:
        return
    try:
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        (ctx.run_dir / VERDICT_FILE).write_text(json.dumps(verdict), encoding="utf-8")
    except OSError as exc:
        state.log(f"judge verdict not saved: {exc}")


register(NAME, "verify", judge, blocking=True)
