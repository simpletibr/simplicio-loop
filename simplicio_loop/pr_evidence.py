"""Idempotent GitHub comment publish primitives (#295, #1476).

The single implementation of `publish_comment` / `find_existing_comment`. It lives in the
package (not in `scripts/`) because the installed watcher and `github_lifecycle` need it and
`scripts/` does not ship in the wheel. `scripts/pr_evidence.py` is the CLI over it.

`publish_comment` posts through `gh api` (never `gh issue comment`, which cannot find and
update its own prior comment), tagging the body with a hidden HTML marker so a second run on
the same issue UPDATES the existing comment instead of appending a duplicate. The `gh` call is
injected as `runner` (default `subprocess.run`), so it is unit-testable without the network.
"""
import json
import os
import subprocess

PR_EVIDENCE_COMMENT_MARKER = "<!-- simplicio-loop:pr-evidence-comment -->"
# Where a maintainer keeps the PR template, in order of preference (GitHub accepts any case).
PR_TEMPLATE_DIRS = (".github", "", "docs")
PR_TEMPLATE_NAME = "pull_request_template.md"


def find_pr_template(root):
    """Repo-relative posix path of the PR template under `root`, or None.

    Matches `.github/`, the repo root and `docs/` case-insensitively, so both
    `.github/pull_request_template.md` and `PULL_REQUEST_TEMPLATE.md` are found.
    """
    for directory in PR_TEMPLATE_DIRS:
        folder = os.path.join(root, directory)
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if name.lower() == PR_TEMPLATE_NAME and os.path.isfile(os.path.join(folder, name)):
                return "/".join(part for part in (directory, name) if part)
    return None


def fill_template(tpl, blocks):
    """Append our evidence blocks to a discovered PR template (never drop the maintainer's sections).

    We do not try to surgically rewrite arbitrary templates (untrusted content); we keep the
    template verbatim and append the AC checklist + evidence under a clear divider, so the PR always
    has both the maintainer's layout AND the proof.
    """
    parts = [tpl.rstrip(), "", "---", ""]
    parts += blocks
    return "\n".join(parts).rstrip() + "\n"


class PublishError(RuntimeError):
    """Raised when the GitHub comment publish could not be completed or verified."""


def _run_gh(args, runner, timeout, input_text=None):
    # `text=True` without an explicit encoding falls back to the platform's default
    # locale encoding (cp1252 on Windows), which raises `UnicodeDecodeError` on any
    # issue title/body/comment containing non-Latin1 characters. `gh` always emits UTF-8.
    completed = runner(["gh"] + args, capture_output=True, text=True, timeout=timeout,
                       check=False, input=input_text, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise PublishError("gh %s failed: %s" % (" ".join(args), stderr or "unknown error"))
    return completed.stdout


def find_existing_comment(owner, repo, issue, marker=PR_EVIDENCE_COMMENT_MARKER,
                          runner=subprocess.run, timeout=20):
    """Return the numeric id of a prior comment on `issue` whose body carries `marker`, or None.

    Paginates through `gh api repos/{owner}/{repo}/issues/{issue}/comments` and returns the FIRST
    match (there should only ever be one, since publish always reuses it) so a re-run edits rather
    than appends.
    """
    stdout = _run_gh(
        ["api", "repos/%s/%s/issues/%s/comments" % (owner, repo, issue), "--paginate"],
        runner, timeout)
    try:
        comments = json.loads(stdout)
    except ValueError:
        raise PublishError("gh api returned non-JSON comment list")
    if not isinstance(comments, list):
        comments = []
    for c in comments:
        if marker in (c.get("body") or ""):
            return c.get("id")
    return None


def publish_comment(owner, repo, issue, body, marker=PR_EVIDENCE_COMMENT_MARKER,
                    runner=subprocess.run, timeout=20):
    """Publish `body` to `issue` idempotently. Returns {"action": "created"|"updated", "id": int}.

    Tags the body with the hidden marker (added once, not duplicated if already present), then
    either PATCHes the existing tagged comment or POSTs a new one. Raises `PublishError` on any
    `gh` failure -- callers must treat that as BLOCKED, never as a silent success (#295): a
    comment that failed to post must never be reported as posted.

    The request body is sent as a JSON payload on stdin (`gh api ... --input -`), never via
    shell interpolation of the rendered markdown, so untrusted acceptance-criteria text cannot
    reach the argument vector.
    """
    tagged_body = body if marker in body else (body.rstrip("\n") + "\n\n" + marker + "\n")
    existing_id = find_existing_comment(owner, repo, issue, marker=marker, runner=runner,
                                        timeout=timeout)
    payload = json.dumps({"body": tagged_body})
    if existing_id is not None:
        _run_gh(["api", "-X", "PATCH",
                 "repos/%s/%s/issues/comments/%s" % (owner, repo, existing_id),
                 "--input", "-"], runner, timeout, input_text=payload)
        return {"action": "updated", "id": existing_id}
    stdout = _run_gh(["api", "-X", "POST",
                      "repos/%s/%s/issues/%s/comments" % (owner, repo, issue),
                      "--input", "-"], runner, timeout, input_text=payload)
    try:
        created = json.loads(stdout)
        new_id = created.get("id")
    except ValueError:
        new_id = None
    return {"action": "created", "id": new_id}
