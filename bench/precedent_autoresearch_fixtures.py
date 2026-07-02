"""precedent_autoresearch_fixtures.py — shared fixture builders for the #90 autoresearch run.

Two fixed case sets, deliberately using only the TWO code paths of
`build_precedent_block()` that are reachable with zero heavy ML dependency
(no `sentence-transformers`/torch needed in this sandbox):

  1. the structured "indexed" branch (a `.simplicio/precedent-index.json` is present —
     this is the real production path once `simplicio-mapper` has run `precedent-index`)
  2. the "unknown stack" fallback branch (no scanner for the given stack -> static message)

The third path (regex-grep + embedding re-rank when no index file exists) needs
`sentence-transformers`/torch, unavailable here — intentionally excluded from both
SCORE_CASES and HOLDOUT_CASES, not silently mutated.

SCORE_CASES drives the autoresearch loop's score (the eval-cmd average). HOLDOUT_CASES is
a DIFFERENT, fixed set used only once, after the run, to check the token reduction
generalizes instead of being an artifact of the loop having "seen" (via score feedback)
the exact wording of the score-case fixtures — the anti-overfit check the issue asks for.
"""
import json
import os
import shutil
import tempfile
from contextlib import contextmanager

SCORE_CASES = [
    {
        "id": "score-indexed-react-login",
        "stack": "react",
        "goal": "fix login permission",
        "index": {
            "items": [
                {
                    "path": "src/ui/Login.tsx",
                    "line": 12,
                    "change_type": "feature",
                    "summary": "Login guard checks permission before render",
                    "tags": ["react", "login", "permission"],
                    "snippet": "return can('login') && <Login />",
                },
                {
                    "path": "src/payments.ts",
                    "line": 3,
                    "summary": "Payment helper",
                    "tags": ["billing"],
                    "snippet": "export const pay = () => null",
                },
            ]
        },
        "k": 1,
    },
    {
        "id": "score-indexed-dotnet-authorize",
        "stack": "dotnet",
        "goal": "restrict controller action to admins",
        "index": {
            "items": [
                {
                    "path": "src/Controllers/AdminController.cs",
                    "line": 21,
                    "change_type": "feature",
                    "summary": "Existing admin-only action uses [Authorize(Roles=\"Admin\")]",
                    "tags": ["dotnet", "authorize", "admin"],
                    "snippet": "[Authorize(Roles=\"Admin\")]\npublic IActionResult Delete(int id) { ... }",
                }
            ]
        },
        "k": 1,
    },
    {
        "id": "score-unknown-stack-fastapi",
        "stack": "Python + FastAPI",
        "goal": "add a FastAPI route",
        "index": None,
        "k": 1,
    },
]

HOLDOUT_CASES = [
    {
        "id": "holdout-indexed-angular-hidden",
        "stack": "angular",
        "goal": "hide delete button for non-admin",
        "index": {
            "items": [
                {
                    "path": "src/app/screen/screen.component.html",
                    "line": 8,
                    "change_type": "feature",
                    "summary": "Existing template hides action via *ngIf=\"isAdmin\"",
                    "tags": ["angular", "permission", "template"],
                    "snippet": '<button *ngIf="isAdmin" (click)="delete()">Delete</button>',
                }
            ]
        },
        "k": 1,
    },
    {
        "id": "holdout-unknown-stack-cobol",
        "stack": "COBOL mainframe batch job",
        "goal": "add a new report field",
        "index": None,
        "k": 1,
    },
]


@contextmanager
def _tmp_root():
    d = tempfile.mkdtemp(prefix="precedent_ar_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def render_case(case):
    """Build an isolated tmp root for one case and return the rendered precedent block."""
    from simplicio.precedent import build_precedent_block

    with _tmp_root() as root:
        if case["index"] is not None:
            idx_dir = os.path.join(root, ".simplicio")
            os.makedirs(idx_dir, exist_ok=True)
            with open(os.path.join(idx_dir, "precedent-index.json"), "w", encoding="utf-8") as f:
                json.dump(case["index"], f)
        return build_precedent_block(root, case["stack"], case["goal"], k=case["k"])


def required_markers(case):
    """Literal substrings that MUST survive any mutation (anti-Goodhart content check)."""
    if case["index"] is None:
        return ["[PRECEDENT]"]
    top = case["index"]["items"][0]
    return ["[PRECEDENT]", "{}:{}".format(top["path"], top["line"])]
