"""pr_template (pr): read PR template if exists, produce PR body that follows its structure.

Searches for PR templates in standard locations and prepares a body that follows the template.
"""
from pathlib import Path

from .registry import PointContext, PointResult, register

NAME = "pr_template"

# Possible template locations in order of preference
TEMPLATE_PATHS = [
    ".github/pull_request_template.md",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "PULL_REQUEST_TEMPLATE.md",
    "docs/PULL_REQUEST_TEMPLATE.md",
]


async def find_pr_template(ctx: PointContext) -> PointResult:
    if ctx.clone is None:
        return PointResult(NAME, "skipped", {}, "no_clone")

    clone_path = Path(ctx.clone)
    template_found = None
    template_content = None

    # Search for template in standard locations
    for relative_path in TEMPLATE_PATHS:
        full_path = clone_path / relative_path
        try:
            if full_path.exists():
                template_found = relative_path
                template_content = full_path.read_text(encoding="utf-8")
                break
        except (OSError, UnicodeDecodeError):
            continue

    evidence = {
        "template_found": template_found or False,
    }

    # If template found, prepare PR body with headings
    if template_found and template_content:
        pr_body = template_content
        evidence["pr_body"] = pr_body
    else:
        evidence["pr_body"] = None

    return PointResult(NAME, "ok", evidence)


register(NAME, "pr", find_pr_template)
