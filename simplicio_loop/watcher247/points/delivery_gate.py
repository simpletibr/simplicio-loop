"""delivery_gate (pr, blocking): the one DoD gate before the PR opens.

It combines what the earlier stages already decided, and runs none of it again:
* verify green: the label ``verify.decide`` gave (``ctx.verify``). No label, a failed one or an unknown one blocks;
  ``UNVERIFIED|no_test_command`` is what decide lets through (the repo has no tests), and is flagged in the evidence;
* judge ACCEPT and a clean secret scan: the verdict ``judge`` saved in ``<run_dir>/judge.json``;
* a non-empty ``Closes #N``: the closing line the PR body carries, which needs the issue number.
Every failure is listed; the first is the reason_code.
An empty diff (judge saved NO_DIFF) is skipped: the tick ends it as done_no_diff and opens no PR.
"""
import json

from .. import verify
from .judge import ACCEPT, NO_DIFF, VERDICT_FILE
from .registry import PointContext, PointResult, register

NAME = "delivery_gate"
_PASSED, _FAILED = "MEASURED|verify_passed", "MEASURED|verify_failed"


def _verdict(ctx: PointContext) -> dict | None:
    if ctx.run_dir is None:
        return None
    try:
        saved = json.loads((ctx.run_dir / VERDICT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return saved if isinstance(saved, dict) else None


def _closes(ctx: PointContext) -> str | None:
    number = str((ctx.issue or {}).get("number") or "").strip()
    return f"Closes #{number}" if number.isdigit() and int(number) > 0 else None


async def gate(ctx: PointContext) -> PointResult:
    saved = _verdict(ctx)
    if saved is not None and saved.get("verdict") == NO_DIFF:  # done_no_diff: no PR is opened, nothing to gate
        return PointResult(NAME, "skipped", {}, "no_diff")
    evidence: dict = {}
    failures: list[str] = []
    label = (ctx.verify or "").strip()
    if label.startswith(_PASSED):
        evidence["verify"] = "passed"
    elif label.startswith(verify.UNVERIFIED):
        evidence["verify"] = "unverified"
    else:
        evidence["verify"] = label[:80] or None
        failures.append("verify_failed" if label.startswith(_FAILED) or label else "verify_missing")
    if saved is None:
        failures.append("judge_missing")
    else:
        evidence["judge"] = saved.get("verdict")
        if saved.get("verdict") != ACCEPT:
            failures.append("judge_rejected")
        secrets = saved.get("secret_files")
        if not isinstance(secrets, list):
            failures.append("secret_scan_missing")
        elif secrets:
            evidence["secret_files"] = secrets
            failures.append("secret_detected")
        else:
            evidence["secret_scan"] = "clean"
    closes = _closes(ctx)
    evidence["closes"] = closes
    if closes is None:
        failures.append("closes_missing")
    if failures:
        return PointResult(NAME, "blocked", {**evidence, "failures": failures}, failures[0])
    return PointResult(NAME, "ok", evidence)


register(NAME, "pr", gate, blocking=True)
