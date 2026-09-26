"""Tests for delivery/evidence-stage progress instrumentation (issue #301, EPIC #296).

Covers scripts/pr_evidence.py (progress section in the PR body, the `progress-comment` verb —
idempotent/rate-limited/fail-open), scripts/loop_progress.py's `run_state` derivation, and the
web_verify.py/video_evidence.py `evidence` emit hooks (via in-process opts calls, never touching
the real repo's .simplicio-loop/orchestrator/tee/*).
"""
import importlib.util
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PR_EVIDENCE = os.path.join(REPO, "scripts", "pr_evidence.py")
PROGRESS = os.path.join(REPO, "scripts", "loop_progress.py")
WEB_VERIFY = os.path.join(REPO, "scripts", "web_verify.py")
VIDEO_EVIDENCE = os.path.join(REPO, "scripts", "video_evidence.py")

_pspec = importlib.util.spec_from_file_location("loop_progress_delivery_test", PROGRESS)
loop_progress = importlib.util.module_from_spec(_pspec)
_pspec.loader.exec_module(loop_progress)

_evspec = importlib.util.spec_from_file_location("pr_evidence_delivery_test", PR_EVIDENCE)
pr_evidence = importlib.util.module_from_spec(_evspec)
_evspec.loader.exec_module(pr_evidence)

_wvspec = importlib.util.spec_from_file_location("web_verify_delivery_test", WEB_VERIFY)
web_verify = importlib.util.module_from_spec(_wvspec)
_wvspec.loader.exec_module(web_verify)

_vespec = importlib.util.spec_from_file_location("video_evidence_delivery_test", VIDEO_EVIDENCE)
video_evidence = importlib.util.module_from_spec(_vespec)
_vespec.loader.exec_module(video_evidence)


def _env(tmp_path):
    return {
        "SIMPLICIO_PROGRESS_DIR": str(tmp_path),
        "SIMPLICIO_ANCHOR_FILE": str(tmp_path / "anchor.json"),
        "SIMPLICIO_BACKLOG_FILE": str(tmp_path / "backlog.jsonl"),
    }


class _env_ctx:
    """Set env vars for the duration of the block, restore after — avoids the `monkeypatch`
    fixture so these tests stay runnable under the bare-python3 fallback."""

    def __init__(self, mapping):
        self.mapping = mapping
        self._orig = {}

    def __enter__(self):
        for k, v in self.mapping.items():
            self._orig[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def _events(tmp_path):
    path = tmp_path / "progress.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_run_state_running_by_default():
    assert loop_progress._run_state({}) == "running"
    assert loop_progress._run_state({"step": "operate", "status": "end"}) == "running"


def test_run_state_done_on_promise_verified():
    last = {"step": "refeed_exit", "outcome": "pass", "detail": "promise verificada"}
    assert loop_progress._run_state(last) == "done"


def test_run_state_capped_on_cap_reached():
    last = {"step": "refeed_exit", "outcome": "blocked", "detail": "cap atingido: max_iterations"}
    assert loop_progress._run_state(last) == "capped"


def test_run_state_handoff_and_stopped():
    handoff = {"step": "refeed_exit", "outcome": "blocked", "detail": "handoff latched"}
    assert loop_progress._run_state(handoff) == "handoff"
    stopped = {"step": "refeed_exit", "outcome": "blocked", "detail": "STOP: manual STOP signal"}
    assert loop_progress._run_state(stopped) == "stopped"


def test_progress_section_shows_no_fabricated_pct_without_sources(tmp_path):
    with _env_ctx(_env(tmp_path)):
        section = pr_evidence.render_progress_section()
    assert "Progresso do run" in section
    assert "UNVERIFIED|pct=?" in section


def test_progress_section_shows_drain_pct_with_backlog_and_anchor(tmp_path):
    env = _env(tmp_path)
    with _env_ctx(env):
        (tmp_path / "anchor.json").write_text(json.dumps({
            "item": "T1", "criteria": [{"id": "AC1", "status": "done"}]}), encoding="utf-8")
        (tmp_path / "backlog.jsonl").write_text(
            json.dumps({"kind": "master", "goal": "g"}) + "\n" +
            json.dumps({"kind": "item", "id": "T1", "status": "running"}) + "\n",
            encoding="utf-8")
        section = pr_evidence.render_progress_section()
    assert "MEASURED|" in section
    assert "fase F" in section


def test_progress_comment_body_has_marker_and_header(tmp_path):
    with _env_ctx(_env(tmp_path)):
        body = pr_evidence.build_progress_comment_body()
    assert pr_evidence.PROGRESS_COMMENT_MARKER in body
    assert "simplicio-loop progress" in body


def test_rate_limit_blocks_within_window_and_clears_after(tmp_path):
    state_path = str(tmp_path / "state.json")
    assert pr_evidence._rate_limited(60, now=1000.0, state_path=state_path) is False
    pr_evidence._record_post(now=1000.0, state_path=state_path)
    assert pr_evidence._rate_limited(60, now=1030.0, state_path=state_path) is True
    assert pr_evidence._rate_limited(60, now=1061.0, state_path=state_path) is False


def test_find_existing_progress_comment_matches_marker(tmp_path):
    comments = [
        {"id": 1, "body": "unrelated comment"},
        {"id": 2, "body": pr_evidence.PROGRESS_COMMENT_MARKER + "\nold progress"},
    ]

    class _FakeResult:
        returncode = 0
        stdout = json.dumps(comments)

    def fake_runner(cmd, timeout=30):
        return _FakeResult()

    found = pr_evidence.find_existing_progress_comment("42", runner=fake_runner)
    assert found == 2


def test_find_existing_progress_comment_none_when_gh_fails():
    def failing_runner(cmd, timeout=30):
        return None

    assert pr_evidence.find_existing_progress_comment("42", runner=failing_runner) is None


def test_progress_comment_fail_open_without_gh_on_path(tmp_path):
    """AC5 — no gh on PATH -> exit 0, no crash, nothing posted."""
    r = subprocess.run([sys.executable, PR_EVIDENCE, "progress-comment", "--issue", "42"],
                       capture_output=True, text=True, cwd=str(tmp_path),
                       env={**os.environ, "PATH": ""}, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skip" in r.stdout


def test_progress_comment_requires_issue_and_fails_open():
    r = subprocess.run([sys.executable, PR_EVIDENCE, "progress-comment"],
                       capture_output=True, text=True, cwd=REPO, stdin=subprocess.DEVNULL)
    assert r.returncode == 0
    assert "blocked" in r.stdout


def test_pr_build_includes_progress_section_and_still_gates_on_evidence(tmp_path):
    env = _env(tmp_path)
    full_env = dict(os.environ)
    full_env.update(env)
    r = subprocess.run([sys.executable, PR_EVIDENCE, "build", "--title", "T", "--require-evidence"],
                       capture_output=True, text=True, cwd=str(tmp_path), env=full_env,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 3, r.stdout + r.stderr  # unchanged fail-closed semantics (AC3)


def test_web_verify_blocked_path_emits_blocked_outcome(tmp_path):
    """Exercises `_blocked()` directly — the actual toolchain-absent path — rather than driving
    the full `cmd_run` (which would shell out to a real npx/Playwright)."""
    env = _env(tmp_path)
    with _env_ctx(env):
        out_dir = str(tmp_path / "web-out")
        try:
            web_verify._blocked(out_dir, "npx not found on PATH — install Node.js 22+")
        except SystemExit as exc:
            assert exc.code == 3
        events = _events(tmp_path)
    blocked = [e for e in events if e["step"] == "evidence" and e["status"] == "blocked"]
    assert blocked, events
    assert blocked[-1]["outcome"] == "blocked"


def test_video_evidence_blocked_path_emits_blocked_outcome(tmp_path):
    env = _env(tmp_path)
    with _env_ctx(env):
        out_dir = str(tmp_path / "video-out")
        try:
            video_evidence.cmd_record({"out": out_dir})  # no --url -> blocked
        except SystemExit:
            pass
        events = _events(tmp_path)
    blocked = [e for e in events if e["step"] == "evidence" and e["status"] == "blocked"]
    assert blocked, events


def test_existing_pr_evidence_selftest_stays_green():
    r = subprocess.run([sys.executable, PR_EVIDENCE, "selftest"], capture_output=True, text=True,
                       cwd=REPO, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_delivery_progress")
