"""pr_template (pr): the PR body is the repo's own PR template, filled with the run's evidence.

The template is found by `pr_evidence.find_pr_template` (any case; `.github/`, the root or `docs/`) and
filled by `pr_evidence.fill_template`: kept verbatim, with the plan summary, `Closes #N` and the verify
result under it. A section whose heading asks for a secret is dropped, never filled.
No template in the clone -> ok, with `template_found` and `pr_body` None.
"""
import re
from pathlib import Path

from ... import pr_evidence
from .registry import PointContext, PointResult, register

NAME = "pr_template"

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
# A heading that asks the author for a credential. Matched on the heading only: a checklist item
# like "no secrets committed" in a body is a rule, not a request.
_SECRET = re.compile(r"\b(secrets?|passwords?|passwd|tokens?|api[ _-]?keys?|credentials?|private[ _-]?keys?)\b", re.I)


def drop_secret_sections(template: str) -> tuple[str, list[str]]:
    """The template without the sections whose heading asks for a secret, and those headings.

    A section runs from its heading to the next heading of the same or a higher level.
    """
    kept: list[str] = []
    dropped: list[str] = []
    skip_level = 0  # level of the heading being dropped; 0 = not dropping
    for line in template.splitlines():
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            if skip_level and level <= skip_level:
                skip_level = 0
            if not skip_level and _SECRET.search(heading.group(2)):
                skip_level = level
                dropped.append(heading.group(2))
        if not skip_level:
            kept.append(line)
    return "\n".join(kept), dropped


def _blocks(ctx: PointContext) -> list[str]:
    """Our part of the body: plan summary (the issue title when the plan is not text), Closes #N, verify."""
    issue = ctx.issue or {}
    summary = ctx.plan if isinstance(ctx.plan, str) and ctx.plan.strip() else issue.get("title")
    blocks: list[str] = []
    if summary:
        blocks += ["### Summary", str(summary).strip(), ""]
    if issue.get("number"):
        blocks += [f"Parte de #{issue['number']}", ""]
    if ctx.verify:
        blocks += ["### How to verify", ctx.verify.strip(), ""]
    return blocks


async def fill_pr_template(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")
    found = pr_evidence.find_pr_template(str(ctx.clone))
    if found is None:
        return PointResult(NAME, "ok", {"template_found": None, "pr_body": None})
    template = (Path(ctx.clone) / found).read_text(encoding="utf-8", errors="replace")
    template, dropped = drop_secret_sections(template)
    body = pr_evidence.fill_template(template, _blocks(ctx))
    return PointResult(NAME, "ok", {"template_found": found, "pr_body": body, "dropped_sections": dropped})


register(NAME, "pr", fill_pr_template)
