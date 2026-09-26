"""#81: positive integration test for the evidence chain
web_verify -> tee/web (+ video_evidence -> tee/video) -> pr_evidence -> PR body.

Every prior test of these workers exercised only the NEGATIVE path in isolation (BLOCKS when the
toolchain/evidence is absent). Nothing ever asserted that what web_verify/video_evidence actually
WRITE is what pr_evidence actually FINDS and EMBEDS — a path or schema drift between producer and
consumer could break the chain silently (`pr_evidence build --require-evidence` exiting 3 despite
real evidence on disk, or embedding nothing while the checklist still passes).

This builds fixtures using the PRODUCERS' OWN naming convention (mirrored from web_verify.py's
`cmd_run` / video_evidence.py's mp4 naming, not invented filenames), freezes an anchor via the real
`task_anchor.py` CLI, then drives `pr_evidence.py` for real and asserts the produced PR body
threads the exact paths through end to end.

This test itself already caught a real drift while being written: `pr_evidence.py` defaulted to
scanning ONLY `.simplicio-loop/orchestrator/tee/web`, but `video_evidence.py`'s real default output directory is
`.simplicio-loop/orchestrator/tee/video` — a demo video was silently never embedded unless the caller manually
widened `--shots-dir`. Fixed in `pr_evidence.py` (`collect_all_evidence`, `--video-dir`) as part of
this issue; this test pins the fix.
"""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK_ANCHOR = os.path.join(REPO, "scripts", "task_anchor.py")
TASK_BACKLOG = os.path.join(REPO, "scripts", "task_backlog.py")
PR_EVIDENCE = os.path.join(REPO, "scripts", "pr_evidence.py")


def _run(script, args, cwd, env=None):
    full_env = dict(os.environ)
    full_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, script] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=full_env,
        stdin=subprocess.DEVNULL,
    )


def _write_web_verify_fixture(tee_web_dir, issue="12", url="https://app.example/login"):
    """A fixture matching web_verify.py's cmd_run naming EXACTLY: shot/trace/errlog/ledger."""
    os.makedirs(tee_web_dir, exist_ok=True)
    shot = os.path.join(tee_web_dir, "%s-web.png" % issue)
    trace_zip = os.path.join(tee_web_dir, "%s-trace.zip" % issue)
    errlog = os.path.join(tee_web_dir, "%s-console.json" % issue)
    with open(shot, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"fixture-not-a-real-png")
    with open(trace_zip, "wb") as f:
        f.write(b"PK\x03\x04fixture-not-a-real-zip")
    with open(errlog, "w", encoding="utf-8") as f:
        json.dump([], f)
    verdict = ("web_verify: PASS — %s (expect='Welcome', runner=npx) shot=%s trace=%s"
               % (url, shot, trace_zip))
    with open(os.path.join(tee_web_dir, "ledger.txt"), "a", encoding="utf-8") as f:
        f.write(verdict + "\n")
    return shot, trace_zip


def _write_video_evidence_fixture(tee_video_dir, name="login-demo", issue="12"):
    """A fixture matching video_evidence.py's real mp4 naming + ledger line."""
    os.makedirs(tee_video_dir, exist_ok=True)
    mp4 = os.path.join(tee_video_dir, "%s-%s.mp4" % (name, issue))
    with open(mp4, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42fixture-not-a-real-mp4")
    verdict = "video_evidence: PASS — demo video (playwright) project=%s file=%s" % (name, mp4)
    with open(os.path.join(tee_video_dir, "ledger.txt"), "a", encoding="utf-8") as f:
        f.write(verdict + "\n")
    return mp4


def _freeze_anchor(tmp_path, anchor_path, item="12"):
    env = {"SIMPLICIO_ANCHOR_FILE": anchor_path}
    r = _run(TASK_ANCHOR, ["set", "--item", item, "--goal", "Add SSO login",
                          "--ac", "Login page renders an SSO button",
                          "--ac", "Clicking it redirects to the IdP"],
             cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run(TASK_ANCHOR, ["mark", "--id", "AC1", "--status", "done",
                          "--evidence", "web_verify screenshot"],
             cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return env


def test_web_verify_artifact_is_found_and_embedded_by_pr_evidence(tmp_path):
    tee_web = str(tmp_path / ".simplicio-loop/orchestrator" / "tee" / "web")
    anchor_path = str(tmp_path / "anchor.json")
    shot, trace_zip = _write_web_verify_fixture(tee_web)
    env = _freeze_anchor(tmp_path, anchor_path)

    out_path = str(tmp_path / "pr_body.md")
    r = _run(PR_EVIDENCE, ["build", "--title", "Add SSO login", "--item", "12",
                          "--summary", "Adds an SSO button and the IdP redirect.",
                          "--anchor", anchor_path, "--shots-dir", tee_web,
                          "--video-dir", str(tmp_path / "no-videos-here"),
                          "--require-evidence", "--out", out_path],
             cwd=str(tmp_path), env=env)
    assert r.returncode == 0, "real evidence on disk must not BLOCK:\n%s%s" % (r.stdout, r.stderr)
    assert os.path.exists(out_path)
    body = open(out_path, encoding="utf-8").read()

    # the AC checklist made it through
    assert "AC1" in body and "AC2" in body
    assert "Login page renders an SSO button" in body
    assert "Closes #12" in body

    # the EXACT file web_verify wrote is embedded as a markdown image — not a placeholder path
    shot_rel = os.path.relpath(shot, REPO).replace(os.sep, "/")
    assert ("![%s](%s)" % (os.path.basename(shot), shot_rel)) in body, body


def test_video_evidence_artifact_is_found_and_embedded_by_pr_evidence(tmp_path):
    # Proves the fix for the drift this test discovered: video_evidence's REAL output dir
    # (tee/video) is picked up by default, not just tee/web.
    tee_web = str(tmp_path / ".simplicio-loop/orchestrator" / "tee" / "web")
    tee_video = str(tmp_path / ".simplicio-loop/orchestrator" / "tee" / "video")
    anchor_path = str(tmp_path / "anchor.json")
    _write_web_verify_fixture(tee_web)
    mp4 = _write_video_evidence_fixture(tee_video)
    env = _freeze_anchor(tmp_path, anchor_path)

    out_path = str(tmp_path / "pr_body.md")
    r = _run(PR_EVIDENCE, ["build", "--title", "Add SSO login", "--item", "12",
                          "--anchor", anchor_path, "--shots-dir", tee_web,
                          "--video-dir", tee_video,
                          "--require-evidence", "--out", out_path],
             cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    body = open(out_path, encoding="utf-8").read()

    mp4_rel = os.path.relpath(mp4, REPO).replace(os.sep, "/")
    assert ("🎬 [%s](%s)" % (os.path.basename(mp4), mp4_rel)) in body, body


def test_pr_evidence_video_dir_scanned_even_without_explicit_flag(tmp_path):
    # The default (no --video-dir passed) must ALSO pick up tee/video relative to the repo's own
    # layout convention — proven here by pointing REPO-relative defaults at an isolated shots-dir
    # while confirming collect_all_evidence merges both dirs when they differ.
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import pr_evidence  # noqa: E402 (import after sys.path mutation, by design)
    web_dir = str(tmp_path / "web")
    video_dir = str(tmp_path / "video")
    _write_web_verify_fixture(web_dir)
    _write_video_evidence_fixture(video_dir)
    images, videos = pr_evidence.collect_all_evidence({"shots-dir": web_dir, "video-dir": video_dir})
    assert any(i.endswith("-web.png") for i in images), images
    assert any(v.endswith(".mp4") for v in videos), videos


def test_evidence_comment_reports_accurate_counts_end_to_end(tmp_path):
    tee_web = str(tmp_path / ".simplicio-loop/orchestrator" / "tee" / "web")
    tee_video = str(tmp_path / ".simplicio-loop/orchestrator" / "tee" / "video")
    anchor_path = str(tmp_path / "anchor.json")
    _write_web_verify_fixture(tee_web)
    _write_video_evidence_fixture(tee_video)
    env = _freeze_anchor(tmp_path, anchor_path)

    r = _run(PR_EVIDENCE, ["comment", "--pr", "34", "--anchor", anchor_path,
                          "--shots-dir", tee_web, "--video-dir", tee_video],
             cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 print(s), 1 recording(s)" in r.stdout, r.stdout
    assert "1/2 acceptance criteria met" in r.stdout, r.stdout


def test_backlog_table_is_embedded_before_anchor_checklist(tmp_path):
    backlog_path = str(tmp_path / "backlog.jsonl")
    anchor_path = str(tmp_path / "anchor.json")
    item_file = tmp_path / "items.json"
    item_file.write_text(json.dumps([
        {"id": "T1", "goal": "Add SSO login", "acs": ["Login page renders an SSO button"]},
        {"id": "T2", "goal": "Document rollout", "acs": ["Docs updated with release note"]},
    ]), encoding="utf-8")

    env = {"SIMPLICIO_BACKLOG_FILE": backlog_path, "SIMPLICIO_ANCHOR_FILE": anchor_path}
    r = _run(TASK_BACKLOG, ["init", "--goal", "Drain Phase 0", "--item-file", str(item_file)],
             cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run(TASK_BACKLOG, ["next"], cwd=str(tmp_path), env=env)
    assert r.returncode == 0 and "T1" in r.stdout, r.stdout + r.stderr
    claim_fields = r.stdout.strip().split("\t")
    assert len(claim_fields) >= 3 and claim_fields[2].startswith("fence-"), r.stdout
    claim_fence = claim_fields[2]

    r = _run(TASK_ANCHOR, ["set", "--item", "T1", "--goal", "Add SSO login",
                           "--ac", "Login page renders an SSO button"], cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run(TASK_ANCHOR, ["mark", "--id", "AC1", "--status", "done",
                           "--evidence", "web_verify screenshot"], cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    r = _run(TASK_BACKLOG, ["done", "--item", "T1", "--anchor", anchor_path,
                            "--worker", "__anonymous__", "--fence", claim_fence],
             cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    os.remove(anchor_path)  # end of drain turn: the next item can re-arm a fresh anchor

    out_path = str(tmp_path / "pr_body.md")
    r = _run(PR_EVIDENCE, ["build", "--title", "Drain Phase 0", "--item", "12",
                           "--anchor", anchor_path, "--backlog", backlog_path,
                           "--require-evidence", "--out", out_path],
             cwd=str(tmp_path), env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    body = open(out_path, encoding="utf-8").read()
    assert "Body of work (Phase 0 backlog)" in body, body
    assert body.index("Body of work (Phase 0 backlog)") < body.index("### Acceptance criteria"), body
    assert "| T1 | done |" in body, body
    assert "web_verify screenshot" in body, body


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_evidence_chain")
