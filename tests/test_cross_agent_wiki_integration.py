import json
import io
import os
from contextlib import redirect_stdout
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import cross_agent_wiki as wiki  # noqa: E402


def _seed_loop(root):
    loop = os.path.join(root, ".simplicio-loop/orchestrator", "loop")
    os.makedirs(loop, exist_ok=True)
    with open(os.path.join(loop, "scratchpad.md"), "w", encoding="utf-8") as f:
        f.write("---\niteration: 2\nmax_iterations: 5\n---\nShip the smallest verified fix.\n")
    with open(os.path.join(loop, "phase.json"), "w", encoding="utf-8") as f:
        json.dump({
            "phase": "debug",
            "strategy": "Prove the failure before fixing it",
            "tactical_guard": "Do not refactor unrelated code",
            "iteration": 2,
        }, f)
    with open(os.path.join(loop, "journal.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "iteration": 1,
            "action": "add regression test",
            "gate": "fail",
            "fingerprint": "abc123deadbe",
            "blocked_reason": "failing fingerprint unresolved",
            "next_action": "compare dead-end attempts before retrying",
        }) + "\n")
        f.write(json.dumps({
            "iteration": 2,
            "action": "tighten watcher gate",
            "gate": "pass",
            "fingerprint": "",
        }) + "\n")
    with open(os.path.join(loop, "watcher_state.json"), "w", encoding="utf-8") as f:
        json.dump({
            "match": True,
            "status": "MEASURED",
            "checked_at": "2026-07-01T00:00:00Z",
        }, f)



def test_capture_summary_and_handoff_materialize_cross_agent_artifacts(tmp_path):
    root = str(tmp_path)
    _seed_loop(root)
    origin = wiki.REPO
    prior_env = os.environ.get("SIMPLICIO_AGENT_PROFILE")
    try:
        wiki._set_repo(root)
        os.environ["SIMPLICIO_AGENT_PROFILE"] = "test-agent"
        wiki.cmd_capture()
        wiki.cmd_summary()
        wiki.cmd_handoff()

        wiki_summary = os.path.join(root, ".simplicio-loop/orchestrator", "wiki", "SUMMARY.md")
        handoff_file = os.path.join(root, ".simplicio-loop/orchestrator", "loop", "HANDOFF.md")
        journal_dir = os.path.join(root, ".simplicio-loop/orchestrator", "wiki", "journal")
        assert os.path.exists(wiki_summary)
        assert os.listdir(journal_dir)

        summary_body = open(wiki_summary, encoding="utf-8").read()
        handoff_body = open(handoff_file, encoding="utf-8").read()
        assert "Current phase" in summary_body
        assert "Watcher verification" in summary_body
        assert "Watcher state:** verified" in summary_body
        assert "debug" in summary_body
        assert "Open questions / blockers" in summary_body
        assert "Suggested next actions" in summary_body
        assert "failing fingerprint unresolved" in summary_body
        assert "compare dead-end attempts before retrying" in handoff_body
        assert "tighten watcher gate" in handoff_body
        assert "Resume instructions for the next agent" in handoff_body
    finally:
        wiki._set_repo(origin)
        if prior_env is None:
            os.environ.pop("SIMPLICIO_AGENT_PROFILE", None)
        else:
            os.environ["SIMPLICIO_AGENT_PROFILE"] = prior_env


def test_legacy_hermes_profile_env_var_still_resolves(tmp_path):
    """N-1/N compat (#262): SIMPLICIO_AGENT_PROFILE is canonical; HERMES_PROFILE still works
    as a fallback during the rebrand's compat window."""
    root = str(tmp_path)
    _seed_loop(root)
    origin = wiki.REPO
    prior_agent_env = os.environ.get("SIMPLICIO_AGENT_PROFILE")
    prior_legacy_env = os.environ.get("HERMES_PROFILE")
    try:
        wiki._set_repo(root)
        os.environ.pop("SIMPLICIO_AGENT_PROFILE", None)
        os.environ["HERMES_PROFILE"] = "legacy-agent"
        wiki.cmd_capture()
        journal_dir = os.path.join(root, ".simplicio-loop/orchestrator", "wiki", "journal")
        assert os.listdir(journal_dir)
    finally:
        wiki._set_repo(origin)
        if prior_agent_env is None:
            os.environ.pop("SIMPLICIO_AGENT_PROFILE", None)
        else:
            os.environ["SIMPLICIO_AGENT_PROFILE"] = prior_agent_env
        if prior_legacy_env is None:
            os.environ.pop("HERMES_PROFILE", None)
        else:
            os.environ["HERMES_PROFILE"] = prior_legacy_env


def test_status_surfaces_watcher_receipt(tmp_path):
    root = str(tmp_path)
    _seed_loop(root)
    origin = wiki.REPO
    try:
        wiki._set_repo(root)
        buf = io.StringIO()
        with redirect_stdout(buf):
            wiki.cmd_status()
        out = buf.getvalue()
        assert "MEASURED|watcher: verified match" in out
        assert "status=MEASURED" in out
        assert "checked_at=2026-07-01T00:00:00Z" in out
    finally:
        wiki._set_repo(origin)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_cross_agent_wiki")
