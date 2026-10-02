#!/usr/bin/env python3
"""simplicio-tasks — Azure DevOps source_adapter (az boards / az repos / az pipelines).

A concrete binding of the `source_adapter` extension point for repos that use Azure DevOps
instead of GitHub. The orchestrator's discovery (Step 2) resolves the source adapter FIRST and
never assumes GitHub; where the source is Azure Boards, it drives these verbs — the same uniform
contract every adapter exposes, plus the Repos/Pipelines verbs delivery (Step 6) needs:

  Boards (work-items):
    list_ready       metadata-only list of ready/open work-items (WIQL query)
    get_details      full work-item: fields + comments (for Step 2b deep intake)
    claim            atomic-ish cross-session claim: assign-to-self + an in-progress tag
    update_status    move a work-item to a new State
    attach_evidence  append a PR link / verification note to the work-item discussion
    close            resolve/close the work-item
  Repos + Pipelines (deliver):
    open_pr          create a PR linked to the work-item (az repos pr create --work-items)
    pr_status        poll PR status / merge state (Step 6b feedback loop)
    run_pipeline     trigger CI for a branch (az pipelines run)
    pipeline_status  gate on a pipeline run's result (az pipelines runs show)

It shells to the Azure CLI (`az`, with the `azure-devops` extension), resolved on PATH via
shutil.which (finds `az.cmd` on Windows) and invoked WITHOUT a shell — so a work-item title or
note containing shell metacharacters can never be interpreted. Output is JSON on stdout so the
orchestrator parses facts deterministically — never the LLM. `--dry-run` prints the resolved `az`
argv without executing, so the contract is testable offline (no org/auth needed).

Auth + scope (resolve once, override per call):
    az login  &&  az devops configure --defaults organization=<url> project=<name>
    or env:  AZURE_DEVOPS_ORG=https://dev.azure.com/<org>  AZURE_DEVOPS_PROJECT=<project>
    or flags: --org <url> --project <name>   (CI: AZURE_DEVOPS_EXT_PAT for the PAT)

Usage:
    python3 scripts/az_boards_adapter.py list_ready [--state "New,Active"] [--area PATH]
    python3 scripts/az_boards_adapter.py get_details --id 1234
    python3 scripts/az_boards_adapter.py claim --id 1234 --me me@org.com
    python3 scripts/az_boards_adapter.py update_status --id 1234 --state Active
    python3 scripts/az_boards_adapter.py attach_evidence --id 1234 --note "PR !57 merged; tests green"
    python3 scripts/az_boards_adapter.py close --id 1234 [--state Closed]
    python3 scripts/az_boards_adapter.py open_pr --repo Web --source feat/x --id 1234 --title "..."
    python3 scripts/az_boards_adapter.py pr_status --pr 57
    python3 scripts/az_boards_adapter.py run_pipeline --pipeline CI --branch feat/x
    python3 scripts/az_boards_adapter.py pipeline_status --run 99
    # add --dry-run to any verb to print the az command without running it
"""
import json
import os
import shutil
import subprocess
import sys

try:  # Windows consoles default to cp1252 and choke on non-ASCII — force UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg):
    print("  " + msg, file=sys.stderr)


def _exe(name):
    """Resolve an executable on PATH (finds az.cmd/npx.cmd on Windows); fall back to the name."""
    return shutil.which(name) or name


def _org(opts):
    """Just the --organization flag (az devops invoke rejects --project)."""
    org = opts.get("org") or os.environ.get("AZURE_DEVOPS_ORG")
    return ["--organization", org] if org else []


def _common(opts):
    """org + project flags from --flag, else env, appended to most az calls."""
    out = list(_org(opts))
    project = opts.get("project") or os.environ.get("AZURE_DEVOPS_PROJECT")
    if project:
        out += ["--project", project]
    return out


def _az(argv, opts):
    """Run an az command (or print it on --dry-run). No shell → no metacharacter injection."""
    cmd = [_exe("az")] + argv
    if opts.get("dry-run"):
        print("az " + " ".join(_quote(a) for a in argv))
        return {}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except FileNotFoundError:
        log("az not found on PATH — install the Azure CLI + `az extension add --name azure-devops`")
        sys.exit(3)
    if r.returncode != 0:
        log("az failed (%d): %s" % (r.returncode, (r.stderr or "").strip()[:400]))
        sys.exit(r.returncode or 1)
    out = (r.stdout or "").strip()
    return json.loads(out) if out else {}


def _quote(a):
    """Faithful shell-quoting for the --dry-run preview (escapes embedded double quotes)."""
    if any(c in a for c in ' \t"\''):
        return '"%s"' % a.replace('"', '\\"')
    return a


def _wiql_lit(s):
    """Escape a string literal for WIQL (single quotes are doubled)."""
    return s.replace("'", "''")


# WIQL: ready work-items = requested states, optional area path, newest first.
WIQL = ("SELECT [System.Id], [System.Title], [System.State], [System.WorkItemType], "
        "[System.Tags] FROM workitems WHERE {state_clause}{area_clause} "
        "ORDER BY [System.ChangedDate] DESC")


def list_ready(opts):
    states = [s.strip() for s in opts.get("state", "New,Active").split(",") if s.strip()]
    state_clause = "(" + " OR ".join(
        "[System.State] = '%s'" % _wiql_lit(s) for s in states) + ")"
    area_clause = ""
    if opts.get("area"):
        area_clause = " AND [System.AreaPath] UNDER '%s'" % _wiql_lit(opts["area"])
    wiql = WIQL.format(state_clause=state_clause, area_clause=area_clause)
    # `az boards query` returns metadata fields only — the cheap, list-by-metadata call (Step 2)
    res = _az(["boards", "query", "--wiql", wiql, "--output", "json"] + _common(opts), opts)
    if opts.get("dry-run"):
        return
    rows = [{"id": w.get("id") or w.get("fields", {}).get("System.Id"),
             "title": w.get("fields", {}).get("System.Title"),
             "state": w.get("fields", {}).get("System.State"),
             "type": w.get("fields", {}).get("System.WorkItemType"),
             "tags": w.get("fields", {}).get("System.Tags", "")} for w in (res or [])]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def _show(opts):
    return _az(["boards", "work-item", "show", "--id", opts["id"], "--output", "json"]
               + _common(opts), opts)


def get_details(opts):
    _require(opts, "id")
    item = _show(opts)
    comments_argv = ["devops", "invoke", "--area", "wit", "--resource", "comments",
                     "--route-parameters", "workItemId=%s" % opts["id"],
                     "--api-version", "7.1-preview", "--output", "json"] + _org(opts)
    if opts.get("dry-run"):
        _az(comments_argv, opts)  # show how comments are fetched (REST via az devops invoke)
        return
    f = item.get("fields", {})
    comments = _az(comments_argv, opts)
    print(json.dumps({
        "id": item.get("id"),
        "title": f.get("System.Title"),
        "state": f.get("System.State"),
        "type": f.get("System.WorkItemType"),
        "body": f.get("System.Description", ""),
        "acceptance_criteria": f.get("Microsoft.VSTS.Common.AcceptanceCriteria", ""),
        "assigned_to": (f.get("System.AssignedTo") or {}).get("uniqueName", ""),
        "tags": f.get("System.Tags", ""),
        "comments": [c.get("text", "") for c in (comments.get("comments", []) if comments else [])],
    }, ensure_ascii=False, indent=2))


def claim(opts):
    """Claim = assign-to-self + add an in-progress tag, PRESERVING existing tags.

    az boards has no append for Tags (a write replaces the whole field) and no compare-and-swap,
    so claim does read-modify-write: read current tags, append `in-progress` if absent, write
    back. Then a re-read confirms the win (Step 3b idempotency backs off on a lost race).
    """
    _require(opts, "id", "me")
    if opts.get("dry-run"):
        _show(opts)  # the read half
        _az(["boards", "work-item", "update", "--id", opts["id"], "--assigned-to", opts["me"],
             "--fields", "System.Tags=<existing>; in-progress", "--output", "json"]
            + _common(opts), opts)
        return
    cur = _show(opts)
    tags = (cur.get("fields", {}) or {}).get("System.Tags", "") or ""
    parts = [t.strip() for t in tags.split(";") if t.strip()]
    if "in-progress" not in [p.lower() for p in parts]:
        parts.append("in-progress")
    merged = "; ".join(parts)
    _az(["boards", "work-item", "update", "--id", opts["id"], "--assigned-to", opts["me"],
         "--fields", "System.Tags=%s" % merged, "--output", "json"] + _common(opts), opts)
    print(json.dumps({"id": opts["id"], "claimed_by": opts["me"], "tags": merged}))


def update_status(opts):
    _require(opts, "id", "state")
    _az(["boards", "work-item", "update", "--id", opts["id"],
         "--state", opts["state"], "--output", "json"] + _common(opts), opts)
    if not opts.get("dry-run"):
        print(json.dumps({"id": opts["id"], "state": opts["state"]}))


def attach_evidence(opts):
    _require(opts, "id", "note")
    _az(["boards", "work-item", "update", "--id", opts["id"],
         "--discussion", opts["note"], "--output", "json"] + _common(opts), opts)
    if not opts.get("dry-run"):
        print(json.dumps({"id": opts["id"], "evidence_appended": True}))


def close(opts):
    _require(opts, "id")
    state = opts.get("state", "Closed")
    _az(["boards", "work-item", "update", "--id", opts["id"],
         "--state", state, "--output", "json"] + _common(opts), opts)
    if not opts.get("dry-run"):
        print(json.dumps({"id": opts["id"], "state": state}))


def open_pr(opts):
    """Create a PR linked to the work-item (--work-items lets Azure auto-transition on merge)."""
    _require(opts, "repo", "source", "id")
    argv = ["repos", "pr", "create", "--repository", opts["repo"],
            "--source-branch", opts["source"], "--target-branch", opts.get("target", "main"),
            "--work-items", opts["id"], "--output", "json"]
    if opts.get("title"):
        argv += ["--title", opts["title"]]
    res = _az(argv + _common(opts), opts)
    if not opts.get("dry-run"):
        print(json.dumps({"pr": res.get("pullRequestId"), "linked_work_item": opts["id"]}))


def pr_status(opts):
    _require(opts, "pr")
    res = _az(["repos", "pr", "show", "--id", opts["pr"], "--output", "json"] + _org(opts), opts)
    if not opts.get("dry-run"):
        print(json.dumps({"pr": res.get("pullRequestId"), "status": res.get("status"),
                          "mergeStatus": res.get("mergeStatus")}))


def run_pipeline(opts):
    _require(opts, "pipeline")
    res = _az(["pipelines", "run", "--name", opts["pipeline"],
               "--branch", opts.get("branch", "main"), "--output", "json"] + _common(opts), opts)
    if not opts.get("dry-run"):
        print(json.dumps({"run": res.get("id"), "state": res.get("state")}))


def pipeline_status(opts):
    _require(opts, "run")
    res = _az(["pipelines", "runs", "show", "--id", opts["run"], "--output", "json"]
              + _common(opts), opts)
    if not opts.get("dry-run"):
        print(json.dumps({"run": res.get("id"), "state": res.get("state"),
                          "result": res.get("result")}))


def _require(opts, *keys):
    missing = [k for k in keys if k not in opts]
    if missing:
        print("missing required flag(s): %s" % ", ".join("--" + m for m in missing))
        sys.exit(2)


VERBS = {"list_ready": list_ready, "get_details": get_details, "claim": claim,
         "update_status": update_status, "attach_evidence": attach_evidence, "close": close,
         "open_pr": open_pr, "pr_status": pr_status,
         "run_pipeline": run_pipeline, "pipeline_status": pipeline_status}


def _parse(args):
    opts = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                opts[key] = args[i + 1]
                i += 2
            else:
                opts[key] = True
                i += 1
        else:
            i += 1
    return opts


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if not argv or argv[0] not in VERBS:
        print(__doc__)
        sys.exit(2)
    VERBS[argv[0]](_parse(argv[1:]))


if __name__ == "__main__":
    main()
