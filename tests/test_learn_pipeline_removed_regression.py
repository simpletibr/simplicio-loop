"""#69: the write-only learn pipeline (`hooks/learn_stop.py` enqueuing
`.simplicio-loop/orchestrator/learn/pending.jsonl`) had no consumer anywhere in the repo — markers went in,
nothing ever came out. Chosen fix: remove the producer everywhere (Option B from the issue) rather
than build a consumer for a queue nothing reads. This pins that removal so the hook, and its
wiring, cannot silently reappear half-wired.
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_learn_stop_hook_removed_everywhere():
    for rel in (
        "hooks/learn_stop.py",
        "plugin/hooks/learn_stop.py",
        "simplicio_loop/_bundle/hooks/learn_stop.py",
    ):
        assert not os.path.exists(os.path.join(REPO, rel)), \
            "%s should have been removed with the write-only learn pipeline (#69)" % rel


def test_learn_stop_not_wired_in_any_hooks_manifest():
    for rel in (
        "hooks/hooks.json",
        "hooks/hooks.claude.json",
        "simplicio_loop/_bundle/hooks/hooks.json",
        "simplicio_loop/_bundle/hooks/hooks.claude.json",
    ):
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert "learn_stop" not in text, "%s still wires learn_stop.py (#69)" % rel
        json.loads(text)  # still valid JSON after the edit


def test_learn_stop_not_wired_by_installer():
    path = os.path.join(REPO, "scripts", "install_lib.py")
    with open(path, encoding="utf-8") as f:
        assert "learn_stop" not in f.read(), "installer still wires learn_stop.py (#69)"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _selfrun import run_module
    run_module(globals(), "test_learn_pipeline_removed")
